"""
Module de gestion des tâches asynchrones de l'application (workers Qt).

Ce module centralise l'exécution des traitements lourds en arrière-plan afin de
préserver la réactivité de l'interface utilisateur. Il regroupe les opérations
liées aux thumbnails, à l'IA, à la sauvegarde des métadonnées et au clustering.

Contenu :
 - Chargement asynchrone des thumbnails (QRunnable + pool de threads)
 - Orchestration de la génération de thumbnails (scheduler)
 - Auto-complétion d'images via IA (single et batch)
 - Sauvegarde des métadonnées et embeddings
 - Calcul de projection 2D (UMAP) et clustering (HDBSCAN)

Responsabilités :
 1. Exécuter les tâches lourdes en arrière-plan sans bloquer l'UI
 2. Gérer la génération et le chargement des thumbnails de manière concurrente
 3. Fournir des workers IA pour l'analyse et l'enrichissement des images
 4. Sauvegarder les métadonnées et embeddings dans un index persistant
 5. Calculer et structurer la projection 2D des images (UMAP)
 6. Regrouper et nommer automatiquement les clusters d'images
"""

from __future__ import annotations

import json
import os

from PyQt6.QtCore import (
    QMutex,
    QMutexLocker,
    QObject,
    QRunnable,
    QThread,
    QThreadPool,
    pyqtSignal,
)
from PyQt6.QtGui import QPixmap

from services.ollama_wrapper import OllamaWrapper
from services.thumbnail_cache import ThumbnailCache

MODEL_EMBED = "nomic-embed-text:v1.5"


# ═══════════════════════════════════════════════════════════
#  THUMBNAIL LOADER
# ═══════════════════════════════════════════════════════════


class TaskSignals(QObject):
    """Défini deux signaux. Un pour les erreurs, un pour les résultats."""

    signal_done = pyqtSignal(str, QPixmap)
    signal_error = pyqtSignal(str)


class ThumbnailTask(QRunnable):
    """Charge une miniature à partir d'un fichier image."""

    def __init__(self, img_name: str, cache: ThumbnailCache):
        """

        Args:
            img_name (str): Nom du fichier image
            cache (ThumbnailCache): Cache de miniatures
        """
        super().__init__()
        self.img_name = img_name
        self.cache = cache
        self.signals = TaskSignals()
        self.setAutoDelete(True)

    def run(self):
        """Lance le chargement de la miniature."""
        pixmap = self.cache.make_thumbnail(self.img_name)
        if pixmap and not pixmap.isNull():
            self.signals.signal_done.emit(self.img_name, pixmap)
        else:
            self.signals.signal_error.emit(self.img_name)


class ThumbnailScheduler(QObject):
    """Class qui gère la création de miniatures."""

    signal_thumbnail_ready = pyqtSignal(str, QPixmap)
    POOL_THREADS = 4

    def __init__(self, cache: ThumbnailCache, parent=None):
        """

        Args:
            cache (ThumbnailCache): Cache de miniatures
            parent (Any, optional): Parent QObject. Defaults to None.
        """
        super().__init__(parent)
        self.cache = cache
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(self.POOL_THREADS)
        self._mutex = QMutex()
        self._pending: set[str] = set()

    def set_cache(self, cache: ThumbnailCache):
        """Remplace le cache de miniatures.

        Args:
            cache (ThumbnailCache): Cache de miniatures
        """
        self.cache = cache
        with QMutexLocker(self._mutex):
            self._pending.clear()

    def submit(self, img_name: str):
        """Soumet une image à la création de miniatures.

        Args:
            img_name (str): Nom de l'image
        """
        if self.cache.get(img_name) is not None:
            return
        with QMutexLocker(self._mutex):
            if img_name in self._pending:
                return
            self._pending.add(img_name)
        task = ThumbnailTask(img_name, self.cache)
        task.signals.signal_done.connect(self.on_signal_done)
        task.signals.signal_error.connect(self.on_signal_error)
        self._pool.start(task)

    def flush_pending(self):
        """Vide les images en attente de miniatures."""
        with QMutexLocker(self._mutex):
            self._pending.clear()

    def wait_all(self):
        """Attend que toutes les miniatures soient créées."""
        self._pool.waitForDone()

    def on_signal_done(self, img_name: str, pixmap: QPixmap):
        """Callback appelé quand une miniature est créée.

        Args:
            img_name (str): Nom de l'image
            pixmap (QPixmap): Miniature
        """
        with QMutexLocker(self._mutex):
            self._pending.discard(img_name)
        self.signal_thumbnail_ready.emit(img_name, pixmap)

    def on_signal_error(self, img_name: str):
        """Callback appelé quand une erreur se produit lors de la création d'une miniature.

        Args:
            img_name (str): Nom de l'image
        """
        with QMutexLocker(self._mutex):
            self._pending.discard(img_name)


# ═══════════════════════════════════════════════════════════
#  AUTO-COMPLETE (une image)
# ═══════════════════════════════════════════════════════════


class AutoCompleteWorker(QThread):
    """Class pour effectuer une recherche d'auto-complétion sur une image."""

    signal_finished = pyqtSignal(dict)
    signal_error = pyqtSignal(str)

    def __init__(self, image_path: str, client: OllamaWrapper):
        """
        Args:
            image_path (str): Chemin vers l'image
            client (OllamaWrapper): Client Ollama
        """
        super().__init__()
        self.image_path = image_path
        self.client = client

    def run(self):
        """Lance l'auto-complétion sur l'image."""
        try:
            result = self.client.get_description_and_keywords_from_image(self.image_path)
            self.signal_finished.emit(result)
        except Exception as e:
            self.signal_error.emit(str(e))


# ═══════════════════════════════════════════════════════════
#  AUTO-COMPLETE BATCH
# ═══════════════════════════════════════════════════════════


class AutoCompleteAllWorker(QThread):
    """Class pour effectuer une recherche d'auto-complétion sur toutes les images d'un dossier."""

    signal_image_done = pyqtSignal(int, str, dict)
    signal_image_error = pyqtSignal(int, str, str)
    signal_all_done = pyqtSignal()

    def __init__(self, folder: str, images: list[str], client: OllamaWrapper):
        """

        Args:
            folder (str): Dossier contenant les images
            images (list[str]): Liste des noms des images
            client (OllamaWrapper): Client Ollama
        """
        super().__init__()
        self.folder = folder
        self.images = images
        self.client = client
        self._cancelled = False

    def cancel(self):
        """Annule le traitement."""
        self._cancelled = True

    def run(self):
        """Lance l'auto-complétion."""
        for i, img_name in enumerate(self.images):
            if self._cancelled:
                break
            path = os.path.join(self.folder, img_name)
            try:
                result = self.client.get_description_and_keywords_from_image(path)
                self.signal_image_done.emit(i, img_name, result)
            except Exception as e:
                self.signal_image_error.emit(i, img_name, str(e))
        self.signal_all_done.emit()


# ═══════════════════════════════════════════════════════════
#  SAVE METADATA
# ═══════════════════════════════════════════════════════════


class SaveMetadataWorker(QThread):
    """Class pour sauvegarder les métadonnées des images."""

    signal_finished = pyqtSignal()
    signal_error = pyqtSignal(str)

    def __init__(self, image_name: str, folder: str, desc: str, keywords: list[str], client: OllamaWrapper):
        """
        Args:
            image_name (str): Nom de l'image.
            folder (str): Dossier de l'image.
            desc (str): Description de l'image.
            keywords (list[str]): Mots-clés de l'image.
            client (OllamaWrapper): Client Ollama.
        """
        super().__init__()
        self.image_name = image_name
        self.folder = folder
        self.desc = desc
        self.keywords = keywords
        self.client = client

    def run(self):
        """Lance la sauvegarde des métadonnées."""
        try:
            embedding = self.client.embed(
                model=MODEL_EMBED,
                text=self.client.build_embedding(self.desc, self.keywords),
            )
            index_path = os.path.join(self.folder, "index.json")
            index = {}
            if os.path.exists(index_path):
                with open(index_path, encoding="utf-8") as f:
                    index = json.load(f)

            index[self.image_name] = {
                "id": self.image_name,
                "path": os.path.join(self.folder, self.image_name),
                "description": self.desc,
                "keywords": self.keywords,
                "embedding": embedding,
            }
            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(index, f, indent=2, ensure_ascii=False)

            self.signal_finished.emit()
        except Exception as e:
            self.signal_error.emit(str(e))


# ═══════════════════════════════════════════════════════════
#  MAP WORKER  (UMAP + HDBSCAN)
# ═══════════════════════════════════════════════════════════


class MapWorker(QThread):
    """Class pour générer une carte UMAP + HDBSCAN."""

    signal_finished = pyqtSignal(list, list, list, dict)
    signal_cluster_named = pyqtSignal(int, str)
    signal_progress = pyqtSignal(str)
    signal_error = pyqtSignal(str)

    def __init__(
        self,
        index: dict,
        client: OllamaWrapper,
        umap_n_neighbors: int = 15,
        umap_min_dist: float = 0.1,
        hdbscan_min_cluster: int = 15,
    ):
        """
        Args:
            index (dict): Index des images.
            client (OllamaWrapper): Client Ollama.
            umap_n_neighbors (int, optional): Nombre de voisins pour UMAP. Defaults to 15.
            umap_min_dist (float, optional): Distance minimale pour UMAP. Defaults to 0.1.
        """

        super().__init__()
        self.index = index
        self.client = client
        self.umap_n_neighbors = umap_n_neighbors
        self.umap_min_dist = umap_min_dist
        self.hdbscan_min_cluster = hdbscan_min_cluster
        self.cluster_names: dict[int, str] = {}

    def run(self):
        """Lance le calcul."""
        try:
            self.compute()
        except Exception as exc:
            self.signal_error.emit(str(exc))

    def compute(self):
        """Calcule les embeddings et les clusters."""
        import numpy as np

        # ── 1. Embeddings ─────────────────────────────────────
        self.signal_progress.emit("Extraction des embeddings…")
        names, vectors = [], []
        for name, data in self.index.items():
            emb = data.get("embedding")
            if emb:
                names.append(name)
                vectors.append(emb)

        if len(vectors) < 2:
            self.signal_error.emit(f"Pas assez d'embeddings ({len(vectors)} / min 2).")
            return

        X = np.array(vectors, dtype=np.float32)

        # ── 2. UMAP ───────────────────────────────────────────
        self.signal_progress.emit(f"UMAP sur {len(names)} images…")
        import umap  # type: ignore

        embedding_2d = umap.UMAP(
            n_neighbors=min(self.umap_n_neighbors, len(names) - 1),
            min_dist=self.umap_min_dist,
            metric="cosine",
            random_state=42,
            n_components=2,
            verbose=False,
        ).fit_transform(X)

        # ── 3. HDBSCAN ────────────────────────────────────────
        self.signal_progress.emit("Clustering HDBSCAN…")
        try:
            import hdbscan  # type: ignore

            labels: list[int] = (
                hdbscan.HDBSCAN(
                    min_cluster_size=max(2, self.hdbscan_min_cluster),
                    metric="euclidean",
                )
                .fit_predict(embedding_2d)
                .tolist()
            )
        except ImportError:
            self.signal_progress.emit("hdbscan absent → pas de clustering")
            labels = [0] * len(names)

        # ── 4. Affichage Non Bloquant ────────────────────────────────────────
        points = [(float(x), float(y)) for x, y in embedding_2d]
        self.signal_progress.emit("Carte prête.")
        self.signal_finished.emit(points, labels, names, self.cluster_names)

        # ── 5. Nommer les clusters en fond ────────────────────────────────────────
        self.cluster_names.clear()
        self.name_clusters_async(names, labels)
        self.signal_progress.emit("Nommage des clusters terminé, carte prête.")
        self.signal_finished.emit(points, labels, names, self.cluster_names)

    def name_clusters_async(self, names: list[str], labels: list[int]):
        """Nomme les clusters en fonction des descriptions et mots clés des images.

        Args:
            names (list[str]): Les noms des images.
            labels (list[int]): Les labels des clusters."""
        import random
        from collections import defaultdict

        # Tri des labels par ordre croissant
        unique = sorted(c for c in set(labels) if c >= 0)
        if not unique:
            return

        cluster_members: dict[int, list[str]] = defaultdict(list)
        for name, label in zip(names, labels, strict=False):
            if label >= 0:
                cluster_members[label].append(name)

        # Pour chaque cluster
        for i, cid in enumerate(unique):
            self.signal_progress.emit(f"Nommage cluster {i + 1}/{len(unique)}…")
            members = cluster_members[cid]
            # Nombre aléatoire pour eviter de prendre trop d'images
            sample = random.sample(members, min(8, len(members)))

            descriptions = []
            for name in sample:
                data = self.index.get(name, {})
                desc = data.get("description", "")
                kws = data.get("keywords", [])
                if desc:
                    descriptions.append(desc)
                elif kws:
                    descriptions.append(", ".join(kws))

            if not descriptions:
                self.signal_cluster_named.emit(cid, f"Cluster {cid}")
                continue

            # Prompt
            prompt = (
                "Voici des descriptions d'images appartenant au même groupe :\n"
                + "\n".join(f"- {d}" for d in descriptions)
                + "\n\nDonne un nom de groupe court (2-3 mots max, français). Ne met pas de guillemets."
            )
            try:
                result = self.client.generate_text(
                    model="qwen2.5vl:7b",
                    prompt=prompt,
                    options={"temperature": 0.3},
                )
                name = result.response.strip().splitlines()[0][:40]
            except Exception:
                name = f"Cluster {cid}"
            self.signal_cluster_named.emit(cid, name)
            self.cluster_names[cid] = name


# ═══════════════════════════════════════════════════════════
#  SAM3 WORKERS
# ═══════════════════════════════════════════════════════════


class Sam3LoadWorker(QThread):
    """Charge le modèle SAM3 en arrière-plan."""

    signal_finished = pyqtSignal()
    signal_error = pyqtSignal(str)

    def __init__(self, service, parent=None):
        """
        Args:
            service (Sam3Service): instance du service SAM3.
        """
        super().__init__(parent)
        self._service = service

    def run(self):
        """Lance le chargement du modèle."""
        try:
            self._service.load_model()
            self.signal_finished.emit()
        except Exception as exc:
            self.signal_error.emit(str(exc))


class Sam3EncodeWorker(QThread):
    """Encode une image PIL dans l'état SAM3."""

    signal_finished = pyqtSignal(object)  # state dict
    signal_error = pyqtSignal(str)

    def __init__(self, service, pil_image, parent=None):
        """
        Args:
            service (Sam3Service): instance du service SAM3.
            pil_image: PIL.Image RGB à encoder.
        """
        super().__init__(parent)
        self._service = service
        self._image = pil_image

    def run(self):
        """Lance l'encodage de l'image."""
        try:
            state = self._service.set_image(self._image)
            self.signal_finished.emit(state)
        except Exception as exc:
            self.signal_error.emit(str(exc))


class Sam3SegmentWorker(QThread):
    """Applique un prompt (texte ou boîte) et émet le résultat."""

    signal_finished = pyqtSignal(object, object)  # (new_state, SegmentationResult)
    signal_error = pyqtSignal(str)

    def __init__(self, service, state: dict, prompt_fn, parent=None):
        """
        Args:
            service (Sam3Service): instance du service SAM3.
            state (dict): état SAM3 courant.
            prompt_fn: callable(state) -> new_state appliquant le prompt.
        """
        super().__init__(parent)
        self._service = service
        self._state = state
        self._prompt_fn = prompt_fn

    def run(self):
        """Applique le prompt et extrait le résultat."""
        try:
            new_state = self._prompt_fn(self._state)
            result = self._service.extract_result(new_state)
            self.signal_finished.emit(new_state, result)
        except Exception as exc:
            self.signal_error.emit(str(exc))


class Sam3ResetWorker(QThread):
    """Réinitialise les prompts SAM3 en arrière-plan."""

    signal_finished = pyqtSignal(object)  # new_state
    signal_error = pyqtSignal(str)

    def __init__(self, service, state: dict, parent=None):
        """
        Args:
            service (Sam3Service): instance du service SAM3.
            state (dict): état SAM3 courant.
        """
        super().__init__(parent)
        self._service = service
        self._state = state

    def run(self):
        """Réinitialise les prompts."""
        try:
            new_state = self._service.reset_prompts(state=self._state)
            self.signal_finished.emit(new_state)
        except Exception as exc:
            self.signal_error.emit(str(exc))


# ═══════════════════════════════════════════════════════════
#  OBJECT SEARCH ALL WORKER  (SAM3 sur tout le dossier)
# ═══════════════════════════════════════════════════════════


class ObjectSearchAllWorker(QThread):
    """
    Parcourt toutes les images du dossier et détecte celles où
    l'objet texte est trouvé avec un score >= threshold.

    Travaille directement avec le Sam3Service (déjà chargé) de manière
    synchrone dans le thread secondaire — jamais dans le thread Qt principal.

    Signaux :
        signal_progress(done: int, total: int, img_name: str)
        signal_match(img_name: str, score: float)   -- émis pour chaque match
        signal_finished(matched: list[str])
        signal_error(msg: str)
    """

    signal_progress = pyqtSignal(int, int, str)
    signal_match = pyqtSignal(str, float)
    signal_finished = pyqtSignal(list)
    signal_error = pyqtSignal(str)

    def __init__(
        self,
        folder: str,
        images: list,  # list[str] — noms de fichiers
        service,  # Sam3Service déjà chargé
        text: str,
        threshold: float = 0.75,
        parent=None,
    ):
        super().__init__(parent)
        self._folder = folder
        self._images = images
        self._service = service
        self._text = text
        self._threshold = threshold
        self._cancelled = False

    def cancel(self) -> None:
        """Demande l'arrêt propre du worker."""
        self._cancelled = True

    def run(self) -> None:
        try:
            from PIL import Image as PILImage

            matched: list[str] = []
            total = len(self._images)

            for i, img_name in enumerate(self._images):
                if self._cancelled:
                    break

                self.signal_progress.emit(i, total, img_name)

                img_path = os.path.join(self._folder, img_name)
                try:
                    pil = PILImage.open(img_path).convert("RGB")
                except Exception:
                    continue

                try:
                    # Encode l'image dans l'état SAM3
                    state = self._service.set_image(pil)
                    # Applique le prompt texte
                    state = self._service.apply_text_prompt(self._text, state)
                    # Extrait le résultat
                    result = self._service.extract_result(state)
                except Exception:
                    continue

                if not result.scores:
                    continue

                best_score = max(result.scores)
                if best_score >= self._threshold:
                    matched.append(img_name)
                    self.signal_match.emit(img_name, float(best_score))

            self.signal_progress.emit(total, total, "")
            self.signal_finished.emit(matched)

        except Exception as exc:
            self.signal_error.emit(str(exc))
