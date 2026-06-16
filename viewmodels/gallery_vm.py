"""ViewModel de la galerie d'images.

Ce composant pilote la logique principale d'affichage et d'interaction avec un dossier
d'images. Il gère le chargement des fichiers, la synchronisation avec l'index, le cache
de thumbnails, le zoom de la grille, la recherche sémantique basée sur embeddings,
et la gestion des images épinglées.

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
 - Épinglage d'images (tri en tête de liste, persistance par workspace)

Responsabilités :
 1. Charger et maintenir la liste des images d'un dossier
 2. Synchroniser les images avec l'index persistant
 3. Fournir les listes d'images (toutes, indexées, non indexées)
 4. Gérer la recherche sémantique et le classement des résultats
 5. Piloter le zoom et la taille des cellules de la grille
 6. Maintenir le cache de thumbnails et son cycle de vie
 7. Propager les événements de sélection et de mise à jour vers la vue
 8. Assurer le lien entre modèles, services et interface via signaux Qt
 9. Gérer l'épinglage des images et leur positionnement en tête de liste
"""

from __future__ import annotations

import os

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from models import config_repository, index_repository
from models import workspace_repository as ws_repo
from models.image_model import ImageGridDelegate, ImageListModel
from models.tree.search_tree import SearchTree
from services.ollama_wrapper import OllamaWrapper
from services.thumbnail_cache import ThumbnailCache
from services.workers import ThumbnailScheduler
from styles import THUMB

EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp")
MODEL_EMBED = "nomic-embed-text:v1.5"


class GalleryViewModel(QObject):
    """Class qui gère la logique de la vue de la galerie."""

    # ── Signaux émis vers la View ─────────────────────────────────────────────
    signal_images_changed = pyqtSignal(list)  # nouvelle liste de noms
    signal_cell_size_changed = pyqtSignal(int)  # zoom modifié
    signal_folder_changed = pyqtSignal(str)  # dossier courant
    signal_index_changed = pyqtSignal(set)  # ensemble des noms indexés
    signal_image_selected = pyqtSignal(str)  # image cliquée
    signal_pin_changed = pyqtSignal(str, bool)  # (img_name, is_pinned)
    signal_saved_search = pyqtSignal()  # une recherche a été sauvegardée

    def __init__(self, client: OllamaWrapper, config: dict, ws_id: str = "", ws_data: dict | None = None, parent=None):
        """Args:
        client (OllamaWrapper): client Ollama
        config (dict): configuration
        ws_id (str): identifiant du workspace (pour la persistance des épingles)
        ws_data (dict | None): données du workspace (pour restaurer les épingles et l'arbre)
        parent (QObject, optional): parent. Defaults to None.

        """
        super().__init__(parent)
        self._client = client
        self._config = config
        self._ws_id = ws_id

        self.current_folder: str | None = None
        self.index: dict = {}
        self._result_images: list[str] = []
        self._affinage_enabled = False

        # Images épinglées (liste ordonnée pour conserver l'ordre d'épinglage)
        self._pinned: list[str] = ws_repo.get_pinned_images(ws_data) if ws_data else []

        # Cache + scheduler

        _dummy = os.path.expanduser("~")
        self.cache = ThumbnailCache(_dummy, THUMB["default_size"], THUMB["lru_max_memory"])
        self.scheduler = ThumbnailScheduler(self.cache)

        # Modèle + delegate
        self.model = ImageListModel()
        # Restauration des épingles au démarrage
        self.model.set_pinned(set(self._pinned))
        self.delegate = ImageGridDelegate(self.cache, self.scheduler, THUMB["default_size"])
        self.delegate.signal_repaint_requested.connect(self.on_signal_repaint_requested)

        # Taille cellule
        self._size_index = THUMB["size_index_default"]
        self._cell_size = THUMB["size_levels"][self._size_index]

        # Timer recherche (debounce)
        self._search_timer = QTimer()
        self._search_timer.setInterval(200)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self.do_search)
        self._search_text = ""

        # Restauration de l'arbre de recherche depuis ws_data
        search_trees = ws_repo.get_search_trees(ws_data) if ws_data else {"gallery": {}, "map": {}}
        gallery_tree_data = search_trees.get("gallery", {})
        if gallery_tree_data:
            self.search_tree = SearchTree.from_dict(gallery_tree_data)
        else:
            self.search_tree = SearchTree()
            self.search_tree.create_root(query="__root__", results=[])

    # ── Propriétés ────────────────────────────────────────────────────────────

    @property
    def cell_size(self) -> int:
        """Renvoi la taille de la cellule en pixels.

        Returns:
            int: Taille de la cellule en pixels.

        """
        return self._cell_size

    @property
    def pinned_images(self) -> list[str]:
        """Retourne la liste ordonnée des images épinglées.

        Returns:
            list[str]: Noms des images épinglées.

        """
        return list(self._pinned)

    # ── Dossier ───────────────────────────────────────────────────────────────

    def open_folder(self, folder: str):
        """Ouvre un dossier.

        Args:
            folder (str): Chemin du dossier.

        """
        self.current_folder = folder

        self.cache.set_folder(folder)
        self.cache.resize(self._cell_size)
        self.scheduler.set_cache(self.cache)

        self.load_index()
        self.refresh(None)
        self.signal_folder_changed.emit(folder)

    def load_index(self):
        """Charge l'index du dossier courant."""
        self.index = index_repository.load(self.current_folder)
        self.model.set_indexed(set(self.index.keys()))
        self.signal_index_changed.emit(set(self.index.keys()))

    def reload_index(self):
        """Recharge l'index du dossier courant."""
        self.load_index()

    # ── Images ────────────────────────────────────────────────────────────────

    def refresh(self, images: list[str] | None):
        """Rafraîchit la liste des images. Les épinglées apparaissent en premier.

        Args:
            images (list[str] | None): Liste des images à charger.

        """
        if images is None:
            try:
                images = self.all_images()
            except (FileNotFoundError, TypeError):
                images = []

        images = self.sort_with_pinned(images)
        self.model.set_images(images)
        self.signal_images_changed.emit(images)

    def sort_with_pinned(self, images: list[str]) -> list[str]:
        """Trie la liste en mettant les épinglées en premier (dans leur ordre d'épinglage).

        Args:
            images (list[str]): Liste brute d'images.

        Returns:
            list[str]: Liste triée, épinglées en tête.

        """
        image_set = set(images)
        # Épinglées présentes dans la liste, dans l'ordre d'épinglage
        pinned_first = [p for p in self._pinned if p in image_set]
        # Reste (non épinglées), dans leur ordre original
        rest = [img for img in images if img not in set(self._pinned)]
        return pinned_first + rest

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

    # ── Épinglage ─────────────────────────────────────────────────────────────

    def is_pinned(self, img_name: str) -> bool:
        """Indique si une image est épinglée.

        Args:
            img_name (str): Nom de l'image.

        Returns:
            bool: True si épinglée.

        """
        return img_name in self._pinned

    def pin_image(self, img_name: str):
        """Épingle une image (la met en tête de galerie).

        Args:
            img_name (str): Nom de l'image à épingler.

        """
        if img_name in self._pinned:
            return
        self._pinned.insert(0, img_name)
        self.model.set_pinned(set(self._pinned))
        self.save_pinned()
        self.refresh(None if not self._search_text else self.filtered_images(self._search_text))
        self.signal_pin_changed.emit(img_name, True)

    def unpin_image(self, img_name: str):
        """Désépingle une image.

        Args:
            img_name (str): Nom de l'image à désépingler.

        """
        if img_name not in self._pinned:
            return
        self._pinned.remove(img_name)
        self.model.set_pinned(set(self._pinned))
        self.save_pinned()
        self.refresh(None if not self._search_text else self.filtered_images(self._search_text))
        self.signal_pin_changed.emit(img_name, False)

    def toggle_pin(self, img_name: str):
        """Bascule l'état épinglé d'une image.

        Args:
            img_name (str): Nom de l'image.

        """
        if self.is_pinned(img_name):
            self.unpin_image(img_name)
        else:
            self.pin_image(img_name)

    def save_pinned(self):
        """Persiste la liste des épingles dans le workspace courant."""
        if not self._ws_id:
            return
        workspaces = ws_repo.load(self._config)
        workspaces = ws_repo.update_workspace(workspaces, self._ws_id, pinned_images=list(self._pinned))
        self._config = ws_repo.save(self._config, workspaces)
        config_repository.save(self._config)

    # ── Recherche ─────────────────────────────────────────────────────────────

    def schedule_search(self, text: str):
        """Lance la recherche après un delai.

        Args:
            text (str): Mot à rechercher.

        """
        self._search_text = text
        self._search_timer.start()

    def do_search(self):
        """Effectue la recherche sémantique et met à jour la liste des images."""
        text = self._search_text.strip()
        if not text:
            self.refresh(None)
            return

        context = None
        if self._affinage_enabled and self.search_tree.current:
            context = self.search_tree.current.results

        self._result_images = self.filtered_images(filter_text=text, context=context)

        # Les épinglées présentes dans le dossier restent toujours en tête
        all_imgs = set(self.all_images())
        pinned_first = [p for p in self._pinned if p in all_imgs]
        result_without_pinned = [img for img in self._result_images if img not in set(self._pinned)]
        self._result_images = pinned_first + result_without_pinned

        self.refresh(self._result_images)

    def filtered_images(self, filter_text: str, context: list[str] = None) -> list[str]:
        """Renvoi les 100 images les plus proches de la requête.
        Les images épinglées sont exclues : elles sont réinjectées en tête par do_search.

        Args:
            filter_text (str): Requête de recherche.
            context (list[str]): Liste de nom d'images servant de base. Si none ce base sur toutes les images.

        Returns:
            list[str]: Liste des images. Les épinglées sont en tête.

        """
        # Récupère les embeddings de la requête
        ft = filter_text.lower().strip()
        query_emb = self._client.embed(model=MODEL_EMBED, text=ft)

        # Récupère les embeddings des images selon le context
        if context is None or context == []:
            images = self.index
        else:
            images = {key: self.index[key] for key in context if key in self.index}

        pinned_set = set(self._pinned)
        scores = {}
        for key, data in images.items():
            # Exclut les images épinglées.
            if key in pinned_set:
                continue

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

    def save_search(self) -> None:
        """Enregistre la recherche dans l'historique."""
        text = self._search_text.strip()
        if not text:
            return

        if self._affinage_enabled is False:
            self.search_tree.return_to_root()

        self.search_tree.push_search(query=text, results=self._result_images)
        self.signal_saved_search.emit()

        print("L'arbre : \n\n", self.search_tree.to_dict())

    def set_affinage(self, enabled: bool) -> None:
        """Active ou désactive l'affinage des recherches.

        Args:
            enabled (bool): Si True, les recherches suivantes seront affinées à partir des résultats actuels.

        """
        self._affinage_enabled = enabled
        self.do_search()

    # ── Sélection ─────────────────────────────────────────────────────────────

    def select_image(self, img_name: str):
        """Selectionne l'image.

        Args:
            img_name (str): Nom de l'image.

        """
        self.model.set_selected(img_name)
        self.signal_image_selected.emit(img_name)

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
        self.signal_cell_size_changed.emit(self._cell_size)

    # ── Repaint ───────────────────────────────────────────────────────────────

    def on_signal_repaint_requested(self, img_name: str):
        """Notifie quand une image a été modifiée.

        Args:
            img_name (str): Nom de l'image modifiée.

        """
        self.model.notify_image_updated(img_name)
