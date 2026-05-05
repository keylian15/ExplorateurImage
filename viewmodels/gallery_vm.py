"""
viewmodels/gallery_vm.py

Logique de présentation de la galerie :
  - chargement du dossier
  - filtrage / recherche sémantique
  - gestion du zoom (taille des cellules)

Émet des signaux Qt que la View connecte ; ne touche jamais aux widgets.
"""
from __future__ import annotations
import os

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from models.image_model import ImageListModel, ImageGridDelegate
from models import index_repository, config_repository
from services.thumbnail_cache import ThumbnailCache
from services.workers import ThumbnailScheduler
from services.ollama_wrapper import OllamaWrapper
from styles import THUMB

EXTENSIONS    = (".png", ".jpg", ".jpeg", ".bmp")
MODEL_EMBED   = "nomic-embed-text:v1.5"


class GalleryViewModel(QObject):
    # ── Signaux émis vers la View ─────────────────────────────────────────────
    images_changed    = pyqtSignal(list)          # nouvelle liste de noms
    cell_size_changed = pyqtSignal(int)           # zoom modifié
    folder_changed    = pyqtSignal(str)           # dossier courant
    index_changed     = pyqtSignal(set)           # ensemble des noms indexés
    image_selected    = pyqtSignal(str)           # image cliquée

    def __init__(self, client: OllamaWrapper, config: dict, parent=None):
        super().__init__(parent)
        self._client = client
        self._config = config

        self.current_folder: str | None = None
        self.index: dict = {}

        # Cache + scheduler
        _dummy = os.path.expanduser("~")
        self.cache     = ThumbnailCache(_dummy, THUMB["default_size"], THUMB["lru_max_memory"])
        self.scheduler = ThumbnailScheduler(self.cache)

        # Modèle + delegate
        self.model    = ImageListModel()
        self.delegate = ImageGridDelegate(self.cache, self.scheduler, THUMB["default_size"])
        self.delegate.repaint_requested.connect(self._on_repaint_requested)

        # Taille cellule
        self._size_index = THUMB["size_index_default"]
        self._cell_size  = THUMB["size_levels"][self._size_index]

        # Timer recherche (debounce)
        self._search_timer = QTimer()
        self._search_timer.setInterval(200)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._do_search)
        self._search_text = ""

    # ── Propriétés ────────────────────────────────────────────────────────────

    @property
    def cell_size(self) -> int:
        return self._cell_size

    # ── Dossier ───────────────────────────────────────────────────────────────

    def open_folder(self, folder: str):
        self.current_folder = folder
        self._config["default_folder"] = folder
        config_repository.save(self._config)

        self.cache.set_folder(folder)
        self.cache.resize(self._cell_size)
        self.scheduler.set_cache(self.cache)

        self._load_index()
        self._refresh(None)
        self.folder_changed.emit(folder)

    def _load_index(self):
        self.index = index_repository.load(self.current_folder)
        self.model.set_indexed(set(self.index.keys()))
        self.index_changed.emit(set(self.index.keys()))

    def reload_index(self):
        """Appelé après une sauvegarde externe (save_worker)."""
        self._load_index()

    # ── Images ────────────────────────────────────────────────────────────────

    def _refresh(self, images: list[str] | None):
        if images is None:
            try:
                images = [
                    f for f in os.listdir(self.current_folder)
                    if f.lower().endswith(EXTENSIONS)
                ]
            except (FileNotFoundError, TypeError):
                images = []
        self.model.set_images(images)
        self.images_changed.emit(images)

    def all_images(self) -> list[str]:
        try:
            return [
                f for f in os.listdir(self.current_folder)
                if f.lower().endswith(EXTENSIONS)
            ]
        except (FileNotFoundError, TypeError):
            return []

    def unindexed_images(self) -> list[str]:
        return [f for f in self.all_images() if f not in self.index]

    # ── Recherche ─────────────────────────────────────────────────────────────

    def schedule_search(self, text: str):
        self._search_text = text
        self._search_timer.start()

    def _do_search(self):
        text = self._search_text.strip()
        if text:
            self._refresh(self._filtered_images(text))
        else:
            self._refresh(None)

    def _filtered_images(self, filter_text: str) -> list[str]:
        ft = filter_text.lower().strip()
        query_emb = self._client.embed(model=MODEL_EMBED, text=ft)
        scores = {}
        for key, data in self.index.items():
            sim = self._client.similarite_cosinus(query_emb, data["embedding"])
            text_match = (
                ft in data.get("description", "").lower()
                or ft in " ".join(data.get("keywords", [])).lower()
            )
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
        self.model.set_selected(img_name)
        self.image_selected.emit(img_name)

    # ── Zoom ──────────────────────────────────────────────────────────────────

    def zoom_in(self):
        levels = THUMB["size_levels"]
        if self._size_index < len(levels) - 1:
            self._size_index += 1
            self._apply_zoom()

    def zoom_out(self):
        if self._size_index > 0:
            self._size_index -= 1
            self._apply_zoom()

    def _apply_zoom(self):
        self._cell_size = THUMB["size_levels"][self._size_index]
        self.cache.resize(self._cell_size)
        self.scheduler.flush_pending()
        self.delegate.set_cell_size(self._cell_size)
        self.cell_size_changed.emit(self._cell_size)

    # ── Repaint ───────────────────────────────────────────────────────────────

    def _on_repaint_requested(self, img_name: str):
        self.model.notify_image_updated(img_name)
