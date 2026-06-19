"""Module de gestion des tâches asynchrones de l'application (workers Qt).

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
import random
from collections import defaultdict

import numpy as np
from PIL import Image as PILImage
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

from services.box_search_strategies import pil_to_bytes
from services.ollama_wrapper import OllamaWrapper
from services.sam3_service import Sam3Service
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

    def __init__(self, img_name: str, cache: ThumbnailCache) -> None:
        """Initialise une tâche de génération de miniature.

        Configure une tâche exécutable dans un pool de threads pour charger ou générer
        une miniature à partir d'un fichier image, avec accès au cache partagé.

        Args:
            img_name (str): Nom du fichier image à traiter.
            cache (ThumbnailCache): Cache de miniatures utilisé pour la récupération ou la génération.

        """
        super().__init__()
        self.img_name = img_name
        self.cache = cache
        self.signals = TaskSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
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

    def __init__(self, cache: ThumbnailCache) -> None:
        """Initialise le planificateur de génération de miniatures.

        Configure un pool de threads et un système de synchronisation pour gérer
        la création asynchrone de miniatures avec mise en cache et évitement des doublons.

        Args:
            cache (ThumbnailCache): Cache utilisé pour stocker et récupérer les miniatures.

        """
        super().__init__()
        self.cache = cache
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(self.POOL_THREADS)
        self._mutex = QMutex()
        self._pending: set[str] = set()

    def set_cache(self, cache: ThumbnailCache) -> None:
        """Remplace le cache de miniatures.

        Args:
            cache (ThumbnailCache): Cache de miniatures

        """
        self.cache = cache
        with QMutexLocker(self._mutex):
            self._pending.clear()

    def submit(self, img_name: str) -> None:
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

    def flush_pending(self) -> None:
        """Vide les images en attente de miniatures."""
        with QMutexLocker(self._mutex):
            self._pending.clear()

    def wait_all(self) -> None:
        """Attend que toutes les miniatures soient créées."""
        self._pool.waitForDone()

    def on_signal_done(self, img_name: str, pixmap: QPixmap) -> None:
        """Finaliser la génération d'une miniature et notifier les abonnés.

        Retire l'image de la liste des traitements en attente et émet le signal
        indiquant que la miniature est prête.

        Args:
            img_name (str): Nom de l'image.
            pixmap (QPixmap): Miniature générée.

        """
        with QMutexLocker(self._mutex):
            self._pending.discard(img_name)
        self.signal_thumbnail_ready.emit(img_name, pixmap)

    def on_signal_error(self, img_name: str) -> None:
        """Gérer une erreur survenue lors de la génération d'une miniature.

        Retire l'image concernée de la liste des tâches en attente afin d'éviter
        qu'elle bloque le traitement global.

        Args:
        img_name (str): Nom de l'image en erreur.

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

    def __init__(self, image_path: str, client: OllamaWrapper) -> None:
        """Initialise le worker pour auto completer.

        Args:
            image_path (str): Chemin vers l'image
            client (OllamaWrapper): Client Ollama.

        """
        super().__init__()
        self.image_path = image_path
        self.client = client

    def run(self) -> None:
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

    def __init__(self, folder: str, images: list[str], client: OllamaWrapper) -> None:
        """Initialise le worker pour tout auto compléter.

        Args:
            folder (str): Dossier contenant les images
            images (list[str]): Liste des noms des images
            client (OllamaWrapper): Client Ollama.

        """
        super().__init__()
        self.folder = folder
        self.images = images
        self.client = client
        self._cancelled = False

    def cancel(self) -> None:
        """Annule le traitement."""
        self._cancelled = True

    def run(self) -> None:
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

    def __init__(self, image_name: str, folder: str, desc: str, keywords: list[str], client: OllamaWrapper) -> None:
        """Initialise le worker pour save les metadata d'une image.(id, path, descirption, keywords, embbeding).

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

    def run(self) -> None:
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
    ) -> None:
        """Initialise le worker de génération de carte de clusters.

        Configure les paramètres nécessaires au calcul de projection (UMAP) et de clustering
        (HDBSCAN) à partir des embeddings de l'index.

        Args:
            index (dict): Index des images contenant notamment les embeddings.
            client (OllamaWrapper): Client utilisé pour les traitements sémantiques.
            umap_n_neighbors (int, optional): Nombre de voisins pour UMAP. Defaults to 15.
            umap_min_dist (float, optional): Distance minimale pour UMAP. Defaults to 0.1.
            hdbscan_min_cluster (int, optional): Taille minimale d'un cluster pour HDBSCAN.

        """
        super().__init__()
        self.index = index
        self.client = client
        self.umap_n_neighbors = umap_n_neighbors
        self.umap_min_dist = umap_min_dist
        self.hdbscan_min_cluster = hdbscan_min_cluster
        self.cluster_names: dict[int, str] = {}

    def run(self) -> None:
        """Lance le calcul."""
        try:
            self.compute()
        except Exception as exc:
            self.signal_error.emit(str(exc))

    def compute(self) -> None:
        """Fait le Calcule les embeddings et les clusters."""
        # ── 1. Embeddings ─────────────────────────────────────
        self.signal_progress.emit("Extraction des embeddings…")
        names, vectors = [], []
        for name, data in self.index.items():
            emb = data.get("embedding")
            if emb:
                names.append(name)
                vectors.append(emb)
        min_vecors_size = 2
        if len(vectors) < min_vecors_size:
            self.signal_error.emit(f"Pas assez d'embeddings ({len(vectors)} / min 2).")
            return

        X = np.array(vectors, dtype=np.float32)

        # ── 2. UMAP ───────────────────────────────────────────
        self.signal_progress.emit(f"UMAP sur {len(names)} images…")
        import umap  # noqa: PLC0415

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
            import hdbscan  # noqa: PLC0415

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

    def name_clusters_async(self, names: list[str], labels: list[int]) -> None:
        """Nomme les clusters en fonction des descriptions et mots clés des images.

        Args:
            names (list[str]): Les noms des images.
            labels (list[int]): Les labels des clusters.

        """
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

    def __init__(self, service: Sam3Service) -> None:
        """Initialise le worker pour load.

        Args:
            service (Sam3Service): instance du service SAM3.

        """
        super().__init__()
        self._service = service

    def run(self) -> None:
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

    def __init__(self, service: Sam3Service, pil_image: PILImage) -> None:
        """Initialise le worker pour l'encodage.

        Args:
            service (Sam3Service): instance du service SAM3.
            pil_image (PILImage): PIL.Image RGB à encoder.

        """
        super().__init__()
        self._service = service
        self._image = pil_image

    def run(self) -> None:
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

    def __init__(self, service: Sam3Service, state: dict, prompt_fn) -> None:  # noqa ANN001
        """Initialise le worker de segmentation.

        Args:
            service (Sam3Service): instance du service SAM3.
            state (dict): état SAM3 courant.
            prompt_fn (function): new_state appliquant le prompt.

        """
        super().__init__()
        self._service = service
        self._state = state
        self._prompt_fn = prompt_fn

    def run(self) -> None:
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

    def __init__(self, service: Sam3Service, state: dict) -> None:
        """Initialise le worker pour reset.

        Args:
            service (Sam3Service): instance du service SAM3.
            state (dict): état SAM3 courant.

        """
        super().__init__()
        self._service = service
        self._state = state

    def run(self) -> None:
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
    """Parcourt toutes les images du dossier et détecte celles où l'objet texte est trouvé avec un score >= threshold.

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
        images: list,
        service: Sam3Service,
        text: str,
        threshold: float = 0.75,
    ) -> None:
        """Initialise le worker de recherche d'objet sur toutes les images.

        Configure les paramètres nécessaires pour parcourir l'ensemble du dossier et
        détecter la présence d'un objet décrit par un texte via Sam3Service, en filtrant
        les résultats selon un seuil de confiance.

        Args:
        folder (str): Chemin du dossier contenant les images.
        images (list): Liste des noms de fichiers à analyser.
        service (Sam3Service): Service SAM3 déjà chargé utilisé pour la détection.
        text (str): Description textuelle de l'objet à rechercher.
        threshold (float, optional): Seuil minimal de confiance pour retenir une image.

        """
        super().__init__()
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
        """Exécuter la recherche SAM3 sur l'ensemble des images.

        Parcourt toutes les images du dataset, applique le modèle SAM3 sur chacune d'elles
        avec un prompt textuel, calcule le score maximal obtenu et conserve les images
        dont le score dépasse le seuil défini. Émet des signaux de progression, de match,
        de fin de traitement ou d'erreur.
        """
        try:
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


# ═══════════════════════════════════════════════════════════
#  BOX SEARCH WORKERS  (recherche à partir d'une region box)
# ═══════════════════════════════════════════════════════════


class EmbeddingBoxSearchWorker(QThread):
    """Worker pour la stratégie Embedding (rapide).

    Workflow :
     1. Appel VLM sur le crop PIL pour obtenir une description en Français.
     2. Embedding via nomic-embed-text.
     3. Similarité cosinus sur tout l'index.
     4. Émet signal_match pour chaque image au-dessus du seuil.

    Args:
        crop: PIL.Image recadrée sur la région d'intérêt.
        folder: Chemin du dossier des images (pour signal_progress).
        images: Liste des noms de fichiers (pour signal_progress total).
        index: Index des métadonnées {img_name: {embedding: [...], ...}}.
        client: Instance OllamaWrapper.
        threshold: Score cosinus minimum pour retenir une image.
        max_results: Nombre maximum de résultats (0 = illimité).

    """

    signal_progress = pyqtSignal(int, int, str)
    signal_match = pyqtSignal(str, float)
    signal_finished = pyqtSignal(list)
    signal_error = pyqtSignal(str)

    def __init__(self, crop: PILImage, folder: str, images: list, index: dict, client: OllamaWrapper, threshold: float = 0.3, max_results: int = 0) -> None:
        """Initialise le worker de recherche basé sur les embeddings (rapide).

        Configure les paramètres nécessaires à une recherche par similarité cosinus :
        description VLM, génération d'embedding et comparaison sur l'ensemble de l'index.

        Args:
        crop (PILImage): Image recadrée représentant la région d'intérêt.
        folder (str): Chemin du dossier contenant les images.
        images (list): Liste des images à analyser pour la progression.
        index (dict): Index contenant les embeddings des images.
        client (OllamaWrapper): Client utilisé pour la génération VLM et embeddings.
        threshold (float, optional): Seuil minimal de similarité cosinus.
        max_results (int, optional): Nombre maximum de résultats (0 = illimité).

        """
        super().__init__()
        self._crop = crop
        self._folder = folder
        self._images = images
        self._index = index
        self._client = client
        self._threshold = threshold
        self._max_results = max_results
        self._cancelled = False

    def cancel(self) -> None:
        """Demande l'arrêt propre du worker."""
        self._cancelled = True

    def run(self) -> None:
        """Exécute la recherche par embedding."""
        try:
            MODEL_VLM = "qwen2.5vl:7b"
            MODEL_EMBED_LOCAL = "nomic-embed-text:v1.5"
            PROMPT_FR = (
                "Décris précisément l'objet principal de l'image en Français. Donne des hypernymes et concepts associés, retourne une liste des termes uniquement séparés par une virgule sans phrase."
            )

            # 1. Description VLM du crop
            result = self._client.generate_with_image(model=MODEL_VLM, prompt=PROMPT_FR, image=pil_to_bytes(self._crop))
            description = result.response.strip()

            if self._cancelled:
                self.signal_finished.emit([])
                return

            # 2. Embedding de la description
            query_emb = self._client.embed(model=MODEL_EMBED_LOCAL, text=description)

            # 3. Similarité cosinus sur l'index
            scores: list[tuple[str, float]] = []
            total = len(self._index)

            for i, (img_name, data) in enumerate(self._index.items()):
                if self._cancelled:
                    self.signal_finished.emit([m for m, _ in scores])
                    return
                self.signal_progress.emit(i, total, img_name)
                emb = data.get("embedding")
                if not emb:
                    continue
                score = self._client.similarite_cosinus(query_emb, emb)
                if score >= self._threshold:
                    scores.append((img_name, float(score)))

            scores.sort(key=lambda x: x[1], reverse=True)
            if self._max_results > 0:
                scores = scores[: self._max_results]

            matched = []
            for img_name, score in scores:
                self.signal_match.emit(img_name, score)
                matched.append(img_name)

            self.signal_progress.emit(total, total, "")
            self.signal_finished.emit(matched)

        except Exception as exc:
            self.signal_error.emit(str(exc))


class Sam3BoxSearchWorker(QThread):
    """Worker pour la stratégie SAM3 (précis).

    Workflow :
     1. Appel VLM sur le crop pour nommer l'objet en anglais (1-2 mots).
     2. Parcours de toutes les images du dossier avec SAM3.
     3. Émet signal_match pour chaque image où le score SAM3 >= seuil.

    Args:
        crop: PIL.Image recadrée sur la région d'intérêt.
        folder: Chemin du dossier des images.
        images: Liste des noms de fichiers à analyser.
        index: Index des métadonnées (utilisé pour le total dans progress).
        client: Instance OllamaWrapper.
        service: Instance Sam3Service déjà chargé.
        threshold: Score SAM3 minimum pour retenir une image.
        max_results: Nombre maximum de résultats (0 = illimité).

    """

    signal_progress = pyqtSignal(int, int, str)
    signal_match = pyqtSignal(str, float)
    signal_finished = pyqtSignal(list)
    signal_error = pyqtSignal(str)

    def __init__(self, crop: PILImage, folder: str, images: list, index: dict, client: OllamaWrapper, service: Sam3Service, threshold: float = 0.75, max_results: int = 0) -> None:
        """Initialise le worker de recherche SAM3 (précision élevée).

        Configure les paramètres nécessaires à la recherche basée uniquement sur SAM3 :
        nomination de l'objet via VLM, puis segmentation et scoring sur l'ensemble du dataset.

        Args:
        crop (PILImage): Image recadrée représentant la région d'intérêt.
        folder (str): Chemin du dossier contenant les images.
        images (list): Liste des images à analyser.
        index (dict): Index des métadonnées utilisé pour le suivi de progression.
        client (OllamaWrapper): Client utilisé pour l'analyse VLM.
        service (Sam3Service): Service SAM3 déjà initialisé.
        threshold (float, optional): Seuil minimal du score SAM3 pour conserver une image.
        max_results (int, optional): Nombre maximum de résultats (0 = illimité).

        """
        super().__init__()
        self._crop = crop
        self._folder = folder
        self._images = images
        self._index = index
        self._client = client
        self._service = service
        self._threshold = threshold
        self._max_results = max_results
        self._cancelled = False

    def cancel(self) -> None:
        """Demande l'arrêt propre du worker."""
        self._cancelled = True

    def run(self) -> None:
        """Exécute la recherche SAM3."""
        try:
            MODEL_VLM = "qwen2.5vl:7b"
            PROMPT_EN = "In one or two English words, name the main object in this image. Return only the object name, nothing else."

            # 1. Nom de l'objet en anglais
            result = self._client.generate_with_image(model=MODEL_VLM, prompt=PROMPT_EN, image=pil_to_bytes(self._crop))
            object_name = result.response.strip().splitlines()[0].strip()[:50]

            if self._cancelled:
                self.signal_finished.emit([])
                return

            # 2. SAM3 sur tout le dossier
            matched: list[str] = []
            total = len(self._images)
            result_scores: list[tuple[str, float]] = []

            for i, img_name in enumerate(self._images):
                if self._cancelled:
                    self.signal_finished.emit(matched)
                    return
                self.signal_progress.emit(i, total, img_name)

                img_path = os.path.join(self._folder, img_name)
                try:
                    pil = PILImage.open(img_path).convert("RGB")
                    state = self._service.set_image(pil)
                    state = self._service.apply_text_prompt(object_name, state)
                    seg_result = self._service.extract_result(state)
                except Exception as e:
                    print(f"[SAM3]   {img_name} → erreur : {e}")
                    continue

                if not seg_result.scores:
                    continue

                best = max(seg_result.scores)
                if best >= self._threshold:
                    result_scores.append((img_name, float(best)))
                    # Émission immédiate pour affichage au fil de l'eau
                    self.signal_match.emit(img_name, float(best))
                    matched.append(img_name)

            result_scores.sort(key=lambda x: x[1], reverse=True)
            if self._max_results > 0:
                result_scores = result_scores[: self._max_results]

            self.signal_progress.emit(total, total, "")
            # signal_finished avec liste triée (pour wait_mode)
            self.signal_finished.emit([n for n, _ in result_scores])

        except Exception as exc:
            self.signal_error.emit(str(exc))


class HybridBoxSearchWorker(QThread):
    """Worker pour la stratégie Hybride (très précis, lent).

    Workflow :
     1. Appel VLM pour obtenir un nom anglais + concepts (format NAME:/CONCEPTS:).
     2. Embedding des concepts → présélection des candidats au-dessus d'un seuil bas.
     3. SAM3 sur les candidats uniquement.
     4. Score final = score_embedding x score_sam3 (ou score_sam3 dégradé si SAM3 = 0).
     5. Émet signal_match pour chaque résultat retenu.

    Args:
        crop: PIL.Image recadrée sur la région d'intérêt.
        folder: Chemin du dossier des images.
        images: Liste des noms de fichiers à analyser.
        index: Index des métadonnées {img_name: {embedding: [...], ...}}.
        client: Instance OllamaWrapper.
        service: Instance Sam3Service déjà chargé.
        embed_threshold: Seuil cosinus pour la présélection embedding (défaut 0.3).
        sam3_threshold: Seuil SAM3 pour le score brut (défaut 0.5, appliqué au score final).
        max_results: Nombre maximum de résultats finaux (0 = illimité).

    """

    signal_progress = pyqtSignal(int, int, str)
    signal_match = pyqtSignal(str, float)
    signal_finished = pyqtSignal(list)
    signal_error = pyqtSignal(str)

    def __init__(
        self, crop: PILImage, folder: str, images: list, index: dict, client: OllamaWrapper, service: Sam3Service, embed_threshold: float = 0.3, sam3_threshold: float = 0.5, max_results: int = 0
    ) -> None:
        """Initialise le worker de recherche hybride (embedding + SAM3).

        Configure les paramètres nécessaires au pipeline hybride de recherche :
        analyse VLM, présélection par embeddings, raffinement via SAM3 et scoring final
        combiné.

        Args:
        crop (PILImage): Image recadrée représentant la région d'intérêt.
        folder (str): Chemin du dossier contenant les images.
        images (list): Liste des images à analyser.
        index (dict): Index des métadonnées et embeddings des images.
        client (OllamaWrapper): Client utilisé pour les embeddings et VLM.
        service (Sam3Service): Service SAM3 déjà initialisé.
        embed_threshold (float, optional): Seuil de présélection basé sur les embeddings.
        sam3_threshold (float, optional): Seuil appliqué au score SAM3 final.
        max_results (int, optional): Nombre maximum de résultats retournés (0 = illimité).

        """
        super().__init__()
        self._crop = crop
        self._folder = folder
        self._images = images
        self._index = index
        self._client = client
        self._service = service
        self._embed_threshold = embed_threshold
        self._sam3_threshold = sam3_threshold
        self._max_results = max_results
        self._cancelled = False

    def cancel(self) -> None:
        """Demande l'arrêt propre du worker."""
        self._cancelled = True

    def run(self) -> None:
        """Exécute la recherche hybride."""
        try:
            MODEL_VLM = "qwen2.5vl:7b"
            MODEL_EMBED_LOCAL = "nomic-embed-text:v1.5"

            # Deux prompts distincts :
            # - FR pour l'embedding (l'index est indexé en français)
            # - EN pour SAM3 (le modèle prend de l'anglais)
            PROMPT_HYBRID_EN = "In one or two English words, name the main object in this image. Return only the object name, nothing else."
            PROMPT_HYBRID_FR = (
                "Décris précisément l'objet principal de l'image en Français. Donne des hypernymes et concepts associés, retourne une liste des termes uniquement séparés par une virgule sans phrase."
            )

            # 1a. Nom anglais pour SAM3
            result_en = self._client.generate_with_image(model=MODEL_VLM, prompt=PROMPT_HYBRID_EN, image=pil_to_bytes(self._crop))
            object_name = result_en.response.strip().splitlines()[0].strip()[:50]

            if self._cancelled:
                self.signal_finished.emit([])
                return

            # 1b. Description française pour l'embedding
            result_fr = self._client.generate_with_image(model=MODEL_VLM, prompt=PROMPT_HYBRID_FR, image=pil_to_bytes(self._crop))
            description_fr = result_fr.response.strip()

            if self._cancelled:
                self.signal_finished.emit([])
                return

            # 2. Embedding de la description française → présélection
            query_emb = self._client.embed(model=MODEL_EMBED_LOCAL, text=description_fr)

            embed_candidates: list[tuple[str, float]] = []
            for img_name, data in self._index.items():
                emb = data.get("embedding")
                if not emb:
                    continue
                score = self._client.similarite_cosinus(query_emb, emb)
                kept = score >= self._embed_threshold
                if kept:
                    embed_candidates.append((img_name, float(score)))

            embed_score_map = dict(embed_candidates)
            candidate_names = list(embed_score_map.keys())

            if self._cancelled:
                self.signal_finished.emit([])
                return

            # 3. SAM3 sur les candidats — émission immédiate au fil de l'eau
            matched: list[str] = []
            total = len(candidate_names)

            for i, img_name in enumerate(candidate_names):
                if self._cancelled:
                    self.signal_finished.emit(matched)
                    return
                self.signal_progress.emit(i, total, img_name)

                img_path = os.path.join(self._folder, img_name)
                e_score = embed_score_map[img_name]

                try:
                    pil = PILImage.open(img_path).convert("RGB")
                    state = self._service.set_image(pil)
                    state = self._service.apply_text_prompt(object_name, state)
                    seg_result = self._service.extract_result(state)
                except Exception:
                    combined = e_score * 0.5
                else:
                    if seg_result.scores:
                        sam3_score = max(seg_result.scores)
                        combined = e_score * sam3_score if sam3_score > 0 else e_score * 0.3
                    else:
                        combined = e_score * 0.3

                # Filtrage par seuil — seuls les scores suffisamment bons sont émis
                if combined >= self._sam3_threshold:
                    # Émission immédiate — le tri est géré côté UI par _wait_mode
                    self.signal_match.emit(img_name, float(combined))
                    matched.append(img_name)

                # Arrêt anticipé si max_results atteint
                if self._max_results > 0 and len(matched) >= self._max_results:
                    break

            self.signal_progress.emit(total, total, "")
            self.signal_finished.emit(matched)

        except Exception as exc:
            self.signal_error.emit(str(exc))


class EmbeddingTextSearchWorker(QThread):
    """Recherche par texte via embedding cosinus (sans SAM3).

    Workflow :
     1. Embedding du texte via nomic-embed-text.
     2. Similarité cosinus contre tous les embeddings de l'index.
     3. Émet signal_match pour chaque image au-dessus du seuil.
    """

    signal_progress = pyqtSignal(int, int, str)
    signal_match = pyqtSignal(str, float)
    signal_finished = pyqtSignal(list)
    signal_error = pyqtSignal(str)

    def __init__(self, text: str, folder: str, images: list, index: dict, client: OllamaWrapper, threshold: float = 0.3) -> None:
        """Initialise le worker de recherche de similarité.

        Configure les paramètres nécessaires à l'exécution de la recherche par texte via embedding cosinus (sans SAM3).

        Args:
        text (str): Texte de la requête de recherche.
        folder (str): Chemin du dossier contenant les images.
        images (list): Liste des images à traiter.
        index (dict): Index contenant les embeddings des images.
        client (OllamaWrapper): Client utilisé pour les embeddings et la similarité.
        threshold (float, optional): Seuil minimal de similarité. Par défaut à 0.3.

        """
        super().__init__()
        self._text = text
        self._folder = folder
        self._images = images
        self._index = index
        self._client = client
        self._threshold = threshold
        self._cancelled = False

    def cancel(self) -> None:
        """Annuler la recherche."""
        self._cancelled = True

    def run(self) -> None:
        """Exécuter la recherche de similarité sur l'ensemble des images.

        Calcule l'embedding de la requête puis compare celui-ci à tous les embeddings
        disponibles dans l'index. Émet des signaux de progression, de correspondance,
        de fin de traitement ou d'erreur. Supporte l'annulation en cours d'exécution.

        Returns:
        None

        """
        try:
            query_emb = self._client.embed(model=MODEL_EMBED, text=self._text)
            matched: list[str] = []
            total = len(self._index)

            for i, (img_name, data) in enumerate(self._index.items()):
                if self._cancelled:
                    break
                self.signal_progress.emit(i, total, img_name)
                emb = data.get("embedding")
                if not emb:
                    continue
                score = self._client.similarite_cosinus(query_emb, emb)
                if score >= self._threshold:
                    matched.append(img_name)
                    self.signal_match.emit(img_name, float(score))

            self.signal_progress.emit(total, total, "")
            self.signal_finished.emit(matched)
        except Exception as exc:
            self.signal_error.emit(str(exc))
