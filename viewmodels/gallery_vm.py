"""
ViewModel de la galerie d'images.

Ce composant pilote la logique principale d'affichage et d'interaction avec un dossier
d'images. Il gère le chargement des fichiers, la synchronisation avec l'index, le cache
de thumbnails, le zoom de la grille et la recherche sémantique basée sur embeddings.

Il agit comme un point de coordination entre les modèles (liste, index), les services
(IA, cache, workers) et la vue via des signaux Qt, tout en restant indépendant de toute
logique d'interface graphique.

Contenu :
 - Gestion du dossier courant et chargement des images
 - Synchronisation avec l'index persistant
 - Filtrage et recherche sémantique par embeddings
 - Gestion du zoom et de la taille des cellules
 - Sélection d'images et propagation des événements UI
 - Interaction avec le cache de thumbnails et le scheduler

Responsabilités :
 1. Charger et maintenir la liste des images d'un dossier
 2. Synchroniser les images avec l'index persistant
 3. Fournir les listes d'images (toutes, indexées, non indexées)
 4. Gérer la recherche sémantique et le classement des résultats
 5. Piloter le zoom et la taille des cellules de la grille
 6. Maintenir le cache de thumbnails et son cycle de vie
 7. Propager les événements de sélection et de mise à jour vers la vue
 8. Assurer le lien entre modèles, services et interface via signaux Qt
"""

from __future__ import annotations

import os

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from models import config_repository, index_repository
from models.image_model import ImageGridDelegate, ImageListModel
from services.ollama_wrapper import OllamaWrapper
from services.thumbnail_cache import ThumbnailCache
from services.workers import ThumbnailScheduler
from styles import THUMB

EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp")
MODEL_EMBED = "nomic-embed-text:v1.5"


class GalleryViewModel(QObject):
    """Class qui gère la logique de la vue de la galerie."""

    # ── Signaux émis vers la View ─────────────────────────────────────────────
    images_changed = pyqtSignal(list)  # nouvelle liste de noms
    cell_size_changed = pyqtSignal(int)  # zoom modifié
    folder_changed = pyqtSignal(str)  # dossier courant
    index_changed = pyqtSignal(set)  # ensemble des noms indexés
    image_selected = pyqtSignal(str)  # image cliquée

    def __init__(self, client: OllamaWrapper, config: dict, parent=None):
        """
        Args:
            client (OllamaWrapper): client Ollama
            config (dict): configuration
            parent (QObject, optional): parent. Defaults to None.
        """

        super().__init__(parent)
        self._client = client
        self._config = config

        self.current_folder: str | None = None
        self.index: dict = {}

        # Cache + scheduler
        _dummy = os.path.expanduser("~")
        self.cache = ThumbnailCache(_dummy, THUMB["default_size"], THUMB["lru_max_memory"])
        self.scheduler = ThumbnailScheduler(self.cache)

        # Modèle + delegate
        self.model = ImageListModel()
        self.delegate = ImageGridDelegate(self.cache, self.scheduler, THUMB["default_size"])
        self.delegate.repaint_requested.connect(self.on_repaint_requested)

        # Taille cellule
        self._size_index = THUMB["size_index_default"]
        self._cell_size = THUMB["size_levels"][self._size_index]

        # Timer recherche (debounce)
        self._search_timer = QTimer()
        self._search_timer.setInterval(200)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self.do_search)
        self._search_text = ""

    # ── Propriétés ────────────────────────────────────────────────────────────

    @property
    def cell_size(self) -> int:
        """Renvoi la taille de la cellule en pixels.

        Returns:
            int: Taille de la cellule en pixels."""
        return self._cell_size

    # ── Dossier ───────────────────────────────────────────────────────────────

    def open_folder(self, folder: str):
        """Ouvre un dossier.

        Args:
            folder (str): Chemin du dossier.
        """
        self.current_folder = folder
        self._config["default_folder"] = folder
        config_repository.save(self._config)

        self.cache.set_folder(folder)
        self.cache.resize(self._cell_size)
        self.scheduler.set_cache(self.cache)

        self.load_index()
        self.refresh(None)
        self.folder_changed.emit(folder)

    def load_index(self):
        """Charge l'index du dossier courant."""
        self.index = index_repository.load(self.current_folder)
        self.model.set_indexed(set(self.index.keys()))
        self.index_changed.emit(set(self.index.keys()))

    def reload_index(self):
        """Recharge l'index du dossier courant."""
        self.load_index()

    # ── Images ────────────────────────────────────────────────────────────────

    def refresh(self, images: list[str] | None):
        """Rafraîchit la liste des images.

        Args:
            images (list[str] | None): Liste des images à charger.
        """
        if images is None:
            try:
                images = [f for f in os.listdir(self.current_folder) if f.lower().endswith(EXTENSIONS)]
            except (FileNotFoundError, TypeError):
                images = []
        self.model.set_images(images)
        self.images_changed.emit(images)

    def all_images(self) -> list[str]:
        """Renvoie la liste de toutes les images du dossier courant.

        Returns:
            list[str]: Liste des images.
        """
        try:
            return [f for f in os.listdir(self.current_folder) if f.lower().endswith(EXTENSIONS)]
        except (FileNotFoundError, TypeError):
            return []

    def unindexed_images(self) -> list[str]:
        """Renvoie la liste des images non indexées du dossier courant."""
        return [f for f in self.all_images() if f not in self.index]

    def indexed_images(self) -> list[str]:
        """Renvoie la liste des images indexées du dossier courant."""
        return [f for f in self.all_images() if f in self.index]

    # ── Recherche ─────────────────────────────────────────────────────────────

    def schedule_search(self, text: str):
        """Lance la recherche après un delai.

        Args:
            text (str): Mot à rechercher."""
        self._search_text = text
        self._search_timer.start()

    def do_search(self):
        """Fait la recherche."""
        text = self._search_text.strip()
        if text:
            self.refresh(self.filtered_images(text))
        else:
            self.refresh(None)

    def filtered_images(self, filter_text: str) -> list[str]:
        """Renvoi les 100 images les plus proches de la requête.

        Args:
            filter_text (str): Requête de recherche.

        Returns:
            list[str]: Liste des images.
        """
        ft = filter_text.lower().strip()
        query_emb = self._client.embed(model=MODEL_EMBED, text=ft)
        scores = {}
        for key, data in self.index.items():
            sim = self._client.similarite_cosinus(query_emb, data["embedding"])
            text_match = ft in data.get("description", "").lower() or ft in " ".join(data.get("keywords", [])).lower()
            score = sim * 1.0
            if text_match:
                score += 0.3
            if sim > 0.5 and text_match:
                score += 0.5
            scores[key] = score
        sorted_items = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [name for name, _ in sorted_items[:100]]

    # ── Sélection ─────────────────────────────────────────────────────────────

    def select_image(self, img_name: str):
        """Selectionne l'image.

        Args:
            img_name (str): Nom de l'image.
        """
        self.model.set_selected(img_name)
        self.image_selected.emit(img_name)

    # ── Zoom ──────────────────────────────────────────────────────────────────

    def zoom_in(self):
        """Zoom in sur les images."""
        levels = THUMB["size_levels"]
        if self._size_index < len(levels) - 1:
            self._size_index += 1
            self.apply_zoom()

    def zoom_out(self):
        """Zoom out sur les images."""
        if self._size_index > 0:
            self._size_index -= 1
            self.apply_zoom()

    def apply_zoom(self):
        """Applique le zoom."""
        self._cell_size = THUMB["size_levels"][self._size_index]
        self.cache.resize(self._cell_size)
        self.scheduler.flush_pending()
        self.delegate.set_cell_size(self._cell_size)
        self.cell_size_changed.emit(self._cell_size)

    # ── Repaint ───────────────────────────────────────────────────────────────

    def on_repaint_requested(self, img_name: str):
        """Notifie quand une image a été modifiée.

        Args:
            img_name (str): Nom de l'image modifiée."""
        self.model.notify_image_updated(img_name)
