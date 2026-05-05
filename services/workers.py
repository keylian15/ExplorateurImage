"""
Module regroupant l'ensemble des workers (QThread / QRunnable) de l'application.

Il orchestre toutes les tâches lourdes exécutées en arrière-plan afin de ne pas bloquer l'interface :

  ThumbnailTask         QRunnable - charge UN thumbnail (pool)
  ThumbnailScheduler    QObject   - gère la file de priorité + QThreadPool
  AutoCompleteWorker    QThread   - décrit une image via OllamaWrapper
  AutoCompleteAllWorker QThread   - batch auto-complétion
  SaveMetadataWorker    QThread   - embedding + écriture index.json
  MapWorker             QThread   - UMAP + HDBSCAN + nommage cluster

Ce module centralise la logique asynchrone et découple le traitement des données
(image, IA, clustering) de la couche UI Qt, garantissant une application réactive
même sur de gros volumes d'images.
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

    done = pyqtSignal(str, QPixmap)
    error = pyqtSignal(str)


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
            self.signals.done.emit(self.img_name, pixmap)
        else:
            self.signals.error.emit(self.img_name)


class ThumbnailScheduler(QObject):
    """Class qui gère la création de miniatures."""

    thumbnail_ready = pyqtSignal(str, QPixmap)
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
        task.signals.done.connect(self.on_done)
        task.signals.error.connect(self.on_error)
        self._pool.start(task)

    def flush_pending(self):
        """Vide les images en attente de miniatures."""
        with QMutexLocker(self._mutex):
            self._pending.clear()

    def wait_all(self):
        """Attend que toutes les miniatures soient créées."""
        self._pool.waitForDone()

    def on_done(self, img_name: str, pixmap: QPixmap):
        """Callback appelé quand une miniature est créée.

        Args:
            img_name (str): Nom de l'image
            pixmap (QPixmap): Miniature
        """
        with QMutexLocker(self._mutex):
            self._pending.discard(img_name)
        self.thumbnail_ready.emit(img_name, pixmap)

    def on_error(self, img_name: str):
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

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

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
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# ═══════════════════════════════════════════════════════════
#  AUTO-COMPLETE BATCH
# ═══════════════════════════════════════════════════════════


class AutoCompleteAllWorker(QThread):
    """Class pour effectuer une recherche d'auto-complétion sur toutes les images d'un dossier."""

    image_done = pyqtSignal(int, str, dict)
    image_error = pyqtSignal(int, str, str)
    all_done = pyqtSignal()

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
                self.image_done.emit(i, img_name, result)
            except Exception as e:
                self.image_error.emit(i, img_name, str(e))
        self.all_done.emit()


# ═══════════════════════════════════════════════════════════
#  SAVE METADATA
# ═══════════════════════════════════════════════════════════


class SaveMetadataWorker(QThread):
    """Class pour sauvegarder les métadonnées des images."""

    finished = pyqtSignal()
    error = pyqtSignal(str)

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

            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))


# ═══════════════════════════════════════════════════════════
#  MAP WORKER  (UMAP + HDBSCAN)
# ═══════════════════════════════════════════════════════════


class MapWorker(QThread):
    """Class pour générer une carte UMAP + HDBSCAN."""

    finished = pyqtSignal(list, list, list, dict)
    cluster_named = pyqtSignal(int, str)
    progress = pyqtSignal(str)
    error = pyqtSignal(str)

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

    def run(self):
        """Lance le calcul."""
        try:
            self.compute()
        except Exception as exc:
            self.error.emit(str(exc))

    def compute(self):
        """Calcule les embeddings et les clusters."""
        import numpy as np

        self.progress.emit("Extraction des embeddings…")
        names, vectors = [], []
        for name, data in self.index.items():
            emb = data.get("embedding")
            if emb:
                names.append(name)
                vectors.append(emb)

        if len(vectors) < 2:
            self.error.emit(f"Pas assez d'embeddings ({len(vectors)} / min 2).")
            return

        X = np.array(vectors, dtype=np.float32)

        self.progress.emit(f"UMAP sur {len(names)} images…")
        import umap

        embedding_2d = umap.UMAP(
            n_neighbors=min(self.umap_n_neighbors, len(names) - 1),
            min_dist=self.umap_min_dist,
            metric="cosine",
            random_state=42,
            n_components=2,
            verbose=False,
        ).fit_transform(X)

        self.progress.emit("Clustering HDBSCAN…")
        try:
            import hdbscan

            labels: list[int] = (
                hdbscan.HDBSCAN(
                    min_cluster_size=max(2, self.hdbscan_min_cluster),
                    metric="euclidean",
                )
                .fit_predict(embedding_2d)
                .tolist()
            )
        except ImportError:
            self.progress.emit("hdbscan absent → pas de clustering")
            labels = [0] * len(names)

        points = [(float(x), float(y)) for x, y in embedding_2d]
        self.progress.emit("Carte prête.")
        self.finished.emit(points, labels, names, {})

    def name_clusters_async(self, names: list[str], labels: list[int]):
        """Nomme les clusters en fonction des descriptions et mots clés des images.

        Args:
            names (list[str]): Les noms des images.
            labels (list[int]): Les labels des clusters."""
        import random
        from collections import defaultdict

        unique = sorted(c for c in set(labels) if c >= 0)
        if not unique:
            return

        cluster_members: dict[int, list[str]] = defaultdict(list)
        for name, label in zip(names, labels, strict=False):
            if label >= 0:
                cluster_members[label].append(name)

        for i, cid in enumerate(unique):
            self.progress.emit(f"Nommage cluster {i + 1}/{len(unique)}…")
            members = cluster_members[cid]
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
                self.cluster_named.emit(cid, f"Cluster {cid}")
                continue

            prompt = "Voici des descriptions d'images appartenant au même groupe :\n" + "\n".join(f"- {d}" for d in descriptions) + "\n\nDonne un nom de groupe court (2-3 mots max, français)."
            try:
                result = self.client.generate_text(
                    model="qwen2.5vl:7b",
                    prompt=prompt,
                    options={"temperature": 0.3},
                )
                name = result.response.strip().splitlines()[0][:40]
            except Exception:
                name = f"Cluster {cid}"
            self.cluster_named.emit(cid, name)
