"""
Tous les QThread / QRunnable de l'application.

  ThumbnailTask         QRunnable - charge UN thumbnail (pool)
  ThumbnailScheduler    QObject   - gère la file de priorité + QThreadPool
  AutoCompleteWorker    QThread   - décrit une image via OllamaWrapper
  AutoCompleteAllWorker QThread   - batch auto-complétion
  SaveMetadataWorker    QThread   - embedding + écriture index.json
"""

import os
import json

from PyQt6.QtCore import (QObject, QRunnable, QThreadPool, QMutex, QMutexLocker,
    pyqtSignal, QThread
)
from PyQt6.QtGui import QPixmap

from ollama_wrapper_iut import OllamaWrapper
from thumbnail_cache import ThumbnailCache


# ═══════════════════════════════════════════════════════════
#  THUMBNAIL LOADER  (QRunnable + scheduler)
# ═══════════════════════════════════════════════════════════

class _TaskSignals(QObject):
    """Signaux séparés car QRunnable n'hérite pas de QObject."""
    done = pyqtSignal(str, QPixmap)   # (img_name, pixmap)
    error = pyqtSignal(str)            # img_name


class ThumbnailTask(QRunnable):
    """Charge et met en cache UN thumbnail. Conçu pour QThreadPool."""

    def __init__(self, img_name: str, cache: ThumbnailCache):
        """Constructeur, stocke les arguments et prépare les signaux.

        Args:
            img_name (str): Le nom de l'image à traiter.
            cache (ThumbnailCache): Le cache des thumbnails.
        """
        
        super().__init__()
        self.img_name = img_name
        self.cache = cache
        self.signals = _TaskSignals()
        self.setAutoDelete(True)

    def run(self):
        """Charge le thumbnail et émet un signal."""
        
        pixmap = self.cache.make_thumbnail(self.img_name)
        if pixmap and not pixmap.isNull():
            self.signals.done.emit(self.img_name, pixmap)
        else:
            self.signals.error.emit(self.img_name)

class ThumbnailScheduler(QObject):
    """
    Gère la file de priorité des thumbnails à charger.

    - submit(img_name)  : demande le chargement d'un thumbnail.
      Les appels redondants (déjà en cache ou déjà en cours) sont ignorés.
    - flush_pending()   : annule les tâches en attente qui ne sont plus
      dans le viewport (appelé avant chaque nouvelle vague de submit).
    - thumbnail_ready   : signal émis quand un pixmap est disponible.
    """

    thumbnail_ready = pyqtSignal(str, QPixmap)   # (img_name, pixmap)

    POOL_THREADS = 4

    def __init__(self, cache: ThumbnailCache, parent=None):
        """Initialise le pool de threads et les structures de suivi.

        Args:
            cache (ThumbnailCache): Le cache des thumbnails.
            parent (_type_, optional): Le parent QObject. Defaults to None.
        """
        
        super().__init__(parent)
        self.cache = cache
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(self.POOL_THREADS)
        self._mutex = QMutex()
        # tâches soumises, pas encore terminées
        self._pending: set[str] = set()

    def set_cache(self, cache: ThumbnailCache):
        """Change le cache des thumbnails.

        Args:
            cache (ThumbnailCache): Le nouveau cache.
        """
        
        self.cache = cache
        with QMutexLocker(self._mutex):
            self._pending.clear()
        # On ne peut pas annuler les tâches déjà lancées dans le pool,
        # mais elles écriront dans un cache obsolète -> ignorées via signal check.

    def submit(self, img_name: str):
        """Soumet un thumbnail à charger si nécessaire.
        
        Args:
            img_name (str): Le nom de l'image.
        """
        
        # Déjà en mémoire -> rien à faire
        if self.cache.get(img_name) is not None:
            return

        with QMutexLocker(self._mutex):
            if img_name in self._pending:
                return
            self._pending.add(img_name)

        task = ThumbnailTask(img_name, self.cache)
        task.signals.done.connect(self._on_done)
        task.signals.error.connect(self._on_error)
        self._pool.start(task)

    def flush_pending(self):
        """Vide la liste de suivi (ne stoppe pas les tâches en cours dans le pool)."""
        
        with QMutexLocker(self._mutex):
            self._pending.clear()

    def wait_all(self):
        """Attend que toutes les tâches en cours soient terminées."""
        self._pool.waitForDone()
    
    # ──────────────────────────────────────────────
    # Fonctions privées 
    # ──────────────────────────────────────────────

    def _on_done(self, img_name: str, pixmap: QPixmap):
        with QMutexLocker(self._mutex):
            self._pending.discard(img_name)
        self.thumbnail_ready.emit(img_name, pixmap)

    def _on_error(self, img_name: str):
        with QMutexLocker(self._mutex):
            self._pending.discard(img_name)


# ──────────────────────────────────────────────
#  AUTO-COMPLETE  (une image)
# ──────────────────────────────────────────────

class AutoCompleteWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, image_path: str, client: OllamaWrapper):
        """Stocke les arguments et prépare les signaux.

        Args:
            img_name (str): Le nom de l'image à traiter.
            client (OllamaWrapper): Le client.
        """
        
        super().__init__()
        self.image_path = image_path
        self.client = client

    def run(self):
        """Envoie la requête à Ollama et émet un signal avec le résultat ou l'erreur."""
        
        try:
            result = self.client.get_description_and_keywords_from_image(
                self.image_path)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# ──────────────────────────────────────────────
#  AUTO-COMPLETE BATCH
# ──────────────────────────────────────────────

class AutoCompleteAllWorker(QThread):
    image_done = pyqtSignal(int, str, dict)   # (index, img_name, résultat)
    image_error = pyqtSignal(int, str, str)    # (index, img_name, msg)
    all_done = pyqtSignal()

    def __init__(self, folder: str, images: list[str], client):
        """Stocke les arguments et prépare les signaux.
        
        Args:
            folder (str): Le chemin du dossier contenant les images.
            images (list[str]): Les noms des images à traiter.
            client (_type_): Le client.
        """
        
        super().__init__()
        self.folder = folder
        self.images = images
        self.client = client
        self._cancelled = False

    def cancel(self):
        """Demande l'annulation du batch. Les tâches en cours ne seront pas stoppées, mais les résultats ignorés."""
        self._cancelled = True

    def run(self):
        """Traite les images une par une, émettant des signaux pour chaque résultat ou erreur, et un signal final à la fin."""
        
        for i, img_name in enumerate(self.images):
            if self._cancelled:
                break
            path = os.path.join(self.folder, img_name)
            try:
                result = self.client.get_description_and_keywords_from_image(
                    path)
                self.image_done.emit(i, img_name, result)
            except Exception as e:
                self.image_error.emit(i, img_name, str(e))
        self.all_done.emit()


# ──────────────────────────────────────────────
#  SAVE METADATA  (description + keywords + embedding)
# ──────────────────────────────────────────────

class SaveMetadataWorker(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, image_name: str, folder: str,
                 desc: str, keywords: list[str], client):
        """Stocke les arguments et prépare les signaux.
        
        Args:
            image_name (str): Le nom de l'image.
            folder (str): Le dossier où se trouve l'image et où sera écrit index.json.
            desc (str): La description de l'image.
            keywords (list[str]): Les mots-clés associés à l'image.
            client (_type_): Le client pour générer l'embedding.
        """
        
        super().__init__()
        self.image_name = image_name
        self.folder = folder
        self.desc = desc
        self.keywords = keywords
        self.client = client

    def run(self):
        """Génère l'embedding, met à jour index.json, et émet un signal de fin ou d'erreur."""
        
        try:
            embedding = self.client.embed(
                model='nomic-embed-text:v1.5',
                text=self.client.build_embedding(self.desc, self.keywords)
            )

            index_path = os.path.join(self.folder, "index.json")

            if os.path.exists(index_path):
                with open(index_path, "r", encoding="utf-8") as f:
                    index = json.load(f)
            else:
                index = {}

            index[self.image_name] = {
                "id":          self.image_name,
                "path":        os.path.join(self.folder, self.image_name),
                "description": self.desc,
                "keywords":    self.keywords,
                "embedding":   embedding,
            }

            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(index, f, indent=2, ensure_ascii=False)

            self.finished.emit()

        except Exception as e:
            self.error.emit(str(e))
