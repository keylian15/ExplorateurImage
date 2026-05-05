"""
Deux niveaux de cache pour les thumbnails :
  - Niveau 1 : LRU en mémoire (OrderedDict, taille configurable)
  - Niveau 2 : Fichiers JPEG dans .thumbnails/ au côté des images

Usage :
    cache = ThumbnailCache(folder, thumb_size=192, max_memory=500)
    pixmap = cache.get(img_name)   # None si absent des deux niveaux
    cache.put(img_name, pixmap)    # écrit les deux niveaux
    cache.clear_memory()           # vide uniquement le LRU mémoire
"""

import hashlib
import os
from collections import OrderedDict

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap

THUMB_QUALITY = 85  # qualité JPEG du cache disque
THUMB_FOLDER = ".thumbnails"


class ThumbnailCache:
    def __init__(self, folder: str, thumb_size: int = 192, max_memory: int = 500) -> None:
        """
        Deux niveaux de cache pour les thumbnails :
        - Niveau 1 : LRU en mémoire (OrderedDict, taille configurable)
        - Niveau 2 : Fichiers JPEG dans .thumbnails/ au côté des images

        Args:
            folder (str): Le dossier courant.
            thumb_size (int, optional): La taille du thumbnail. Defaults to 192.
            max_memory (int, optional): La mémoire maximum allouée. Defaults to 500.
        """

        self.thumb_size = thumb_size
        self.max_memory = max_memory
        self._memory: OrderedDict[str, QPixmap] = OrderedDict()
        self.set_folder(folder)

    # ──────────────────────────────────────────────
    # Dossier courant
    # ──────────────────────────────────────────────

    def set_folder(self, folder: str) -> None:
        """Définit le dossier source des images et met à jour le dossier de cache des thumbnails. Réinitialise le cache mémoire.

        Args:
            folder (str): Chemin du dossier contenant les images.
        """

        self.folder = folder
        self.thumb_folder = os.path.join(folder, THUMB_FOLDER)
        self._memory.clear()

    def _ensure_thumb_dir(self):
        """Crée le dossier de stockage des thumbnails s'il n'existe pas déjà."""
        os.makedirs(self.thumb_folder, exist_ok=True)

    # ──────────────────────────────────────────────
    # Clé disque
    # ──────────────────────────────────────────────

    def _disk_key(self, img_name: str) -> str:
        """Génère un chemin de fichier unique et stable pour le thumbnail associé à une image.

        Args:
            img_name (str): Nom de l'image.
        Returns:
            str: Chemin du fichier thumbnail sur disque.
        """

        h = hashlib.md5(img_name.encode()).hexdigest()
        return os.path.join(self.thumb_folder, f"{h}_{self.thumb_size}.jpg")

    # ──────────────────────────────────────────────
    # Fonctions Publiques
    # ──────────────────────────────────────────────

    def get(self, img_name: str) -> QPixmap | None:
        """
        Retourne le QPixmap mis en cache, ou None s'il est absent.
        Promotionne automatiquement depuis le disque vers la mémoire.

        Args:
            img_name (str): Nom de l'image.

        Returns:
            QPixmap | None: Le thumbnail en mémoire ou None s'il n'existe pas.
        """
        # Niveau 1 : mémoire
        if img_name in self._memory:
            self._memory.move_to_end(img_name)
            return self._memory[img_name]

        # Niveau 2 : disque
        disk_path = self._disk_key(img_name)
        if os.path.exists(disk_path):
            pixmap = QPixmap(disk_path)
            if not pixmap.isNull():
                self._store_memory(img_name, pixmap)
                return pixmap

        return None

    def put(self, img_name: str, pixmap: QPixmap):
        """Stocke le thumbnail dans les deux niveaux.

        Args:
            img_name (str): Nom de l'image.
            pixmap (QPixmap): Le thumbnail à stocker.
        """
        if pixmap.isNull():
            return
        self._store_memory(img_name, pixmap)
        self._store_disk(img_name, pixmap)

    def invalidate(self, img_name: str):
        """Supprime une entrée des deux niveaux (ex : après renommage).

        Args:
            img_name (str): Nom de l'image.
        """
        self._memory.pop(img_name, None)
        disk_path = self._disk_key(img_name)
        if os.path.exists(disk_path):
            try:
                os.remove(disk_path)
            except OSError:
                pass

    def clear_memory(self):
        """Vide uniquement le LRU mémoire (libère RAM sans toucher au disque)."""
        self._memory.clear()

    def resize(self, new_size: int):
        """
        Change la taille des thumbnails. Vide la mémoire.
        Le cache disque de l'ancienne taille reste intact (autre nom de fichier).

        Args:
            new_size (int): Nouvelle taille des thumbnails.
        """
        self.thumb_size = new_size
        self._memory.clear()

    # ──────────────────────────────────────────────
    # Helpers privés
    # ──────────────────────────────────────────────

    def _store_memory(self, img_name: str, pixmap: QPixmap):
        """Stocke le thumbnail en mémoire et applique l'éviction LRU si nécessaire.

        Args:
            img_name (str): Nom de l'image.
            pixmap (QPixmap): Thumbnail.
        """
        self._memory[img_name] = pixmap
        self._memory.move_to_end(img_name)
        # Éviction LRU si dépassement
        while len(self._memory) > self.max_memory:
            self._memory.popitem(last=False)

    def _store_disk(self, img_name: str, pixmap: QPixmap):
        """Stocke le thumbnail sur le disque.

        Args:
            img_name (str): Nom de l'image.
            pixmap (QPixmap): Thumbnail.
        """

        self._ensure_thumb_dir()
        disk_path = self._disk_key(img_name)
        if not os.path.exists(disk_path):
            pixmap.save(disk_path, "JPEG", THUMB_QUALITY)

    # ──────────────────────────────────────────────
    # Utilitaires
    # ──────────────────────────────────────────────

    def make_thumbnail(self, img_name: str) -> QPixmap | None:
        """
        Charge l'image source, la redimensionne et la met en cache.
        Retourne le QPixmap ou None si le fichier est illisible.
        Pensé pour être appelé depuis un thread secondaire.

        Args:
            img_name (str): Nom de l'image.
        """
        src_path = os.path.join(self.folder, img_name)
        image = QImage(src_path)
        if image.isNull():
            return None

        image = image.scaled(
            self.thumb_size,
            self.thumb_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pixmap = QPixmap.fromImage(image)
        self.put(img_name, pixmap)
        return pixmap
