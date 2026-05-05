"""
viewmodels/detail_vm.py

Logique du panneau de détail :
  - affichage des métadonnées de l'image sélectionnée
  - sauvegarde (description + keywords + embedding)
  - calcul et affichage des voisins cosinus
  - auto-complétion unitaire
  - renommage de fichier
"""
from __future__ import annotations
import os

from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap

from models import index_repository, config_repository
from services.ollama_wrapper import OllamaWrapper
from services.workers import AutoCompleteWorker, SaveMetadataWorker

MODEL_EMBED = "nomic-embed-text:v1.5"


class DetailViewModel(QObject):
    # ── Signaux vers la View ──────────────────────────────────────────────────
    metadata_loaded    = pyqtSignal(str, str, list)        # (img_name, desc, keywords)
    preview_ready      = pyqtSignal(QPixmap, str)          # (pixmap, img_name)
    neighbors_ready    = pyqtSignal(dict)                  # {name: score}
    save_started       = pyqtSignal()
    save_finished      = pyqtSignal()
    save_error         = pyqtSignal(str)
    autocomplete_started  = pyqtSignal()
    autocomplete_finished = pyqtSignal(str, list)          # (desc, keywords)
    autocomplete_error    = pyqtSignal(str)
    rename_done        = pyqtSignal(str)                   # nouveau nom
    rename_error       = pyqtSignal(str)
    index_updated      = pyqtSignal(set)                   # noms indexés

    def __init__(self, client: OllamaWrapper, config: dict,
                 gallery_vm,  # GalleryViewModel (évite import circulaire)
                 parent=None):
        super().__init__(parent)
        self._client     = client
        self._config     = config
        self._gallery_vm = gallery_vm

        self.selected_image: str | None = None
        self._worker:      AutoCompleteWorker | None = None
        self._save_worker: SaveMetadataWorker | None = None

        # Debounce sauvegarde
        self._save_timer = QTimer()
        self._save_timer.setInterval(2000)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._do_save)

        self._pending_desc:     str       = ""
        self._pending_keywords: list[str] = []

    # ── Propriétés ────────────────────────────────────────────────────────────

    @property
    def k_neighbors(self) -> int:
        return self._config.get("k_neighbors", 5)

    @k_neighbors.setter
    def k_neighbors(self, value: int):
        self._config["k_neighbors"] = value
        config_repository.save(self._config)

    @property
    def _index(self) -> dict:
        return self._gallery_vm.index

    @property
    def _folder(self) -> str | None:
        return self._gallery_vm.current_folder

    # ── Sélection ─────────────────────────────────────────────────────────────

    def on_image_selected(self, img_name: str):
        self.selected_image = img_name

        # Pixmap
        if self._folder:
            path = os.path.join(self._folder, img_name)
            pixmap = QPixmap(path)
            self.preview_ready.emit(pixmap, img_name)

        # Métadonnées
        data = self._index.get(img_name)
        desc     = data.get("description", "") if data else ""
        keywords = data.get("keywords", [])    if data else []
        self.metadata_loaded.emit(img_name, desc, keywords)

        # Voisins
        self._compute_neighbors(img_name)

    # ── Sauvegarde ────────────────────────────────────────────────────────────

    def schedule_save(self, desc: str, keywords: list[str]):
        if not self.selected_image:
            return
        self._pending_desc     = desc
        self._pending_keywords = keywords
        self._save_timer.start()

    def _do_save(self):
        if not self.selected_image or not self._folder:
            return
        if self._save_worker and self._save_worker.isRunning():
            return

        self.save_started.emit()
        self._save_worker = SaveMetadataWorker(
            self.selected_image, self._folder,
            self._pending_desc, self._pending_keywords, self._client,
        )
        self._save_worker.finished.connect(self._on_save_done)
        self._save_worker.error.connect(self.save_error)
        self._save_worker.start()

    def _on_save_done(self):
        self._gallery_vm.reload_index()
        self.save_finished.emit()
        self.index_updated.emit(set(self._index.keys()))

    # ── Auto-complétion ───────────────────────────────────────────────────────

    def auto_complete(self):
        if not self.selected_image or not self._folder:
            return
        if self._worker and self._worker.isRunning():
            return

        path = os.path.join(self._folder, self.selected_image)
        self.autocomplete_started.emit()
        self._worker = AutoCompleteWorker(path, self._client)
        self._worker.finished.connect(self._on_autocomplete_done)
        self._worker.error.connect(self.autocomplete_error)
        self._worker.start()

    def _on_autocomplete_done(self, result: dict):
        desc     = result["description"]
        keywords = result["keywords"]
        self.autocomplete_finished.emit(desc, keywords)

    # ── Voisins ───────────────────────────────────────────────────────────────

    def _compute_neighbors(self, img_name: str):
        if img_name not in self._index:
            self.neighbors_ready.emit({})
            return
        entry = self._index[img_name]
        if "embedding" not in entry:
            self.neighbors_ready.emit({})
            return

        scores = {}
        for key, data in self._index.items():
            if key == img_name or "embedding" not in data:
                continue
            scores[key] = self._client.similarite_cosinus(
                entry["embedding"], data["embedding"]
            )
        top = dict(sorted(scores.items(), key=lambda x: x[1], reverse=True)[:self.k_neighbors])
        self.neighbors_ready.emit(top)

    def refresh_neighbors(self):
        if self.selected_image:
            self._compute_neighbors(self.selected_image)

    # ── Renommage ─────────────────────────────────────────────────────────────

    def rename(self, new_name: str):
        if not self.selected_image or not self._folder:
            return
        if not new_name or new_name == self.selected_image:
            return

        old_ext = os.path.splitext(self.selected_image)[1]
        if not os.path.splitext(new_name)[1]:
            new_name += old_ext

        old_path = os.path.join(self._folder, self.selected_image)
        new_path = os.path.join(self._folder, new_name)

        if os.path.exists(new_path):
            self.rename_error.emit("Un fichier avec ce nom existe déjà.")
            return

        try:
            os.rename(old_path, new_path)
        except OSError as e:
            self.rename_error.emit(str(e))
            return

        self._gallery_vm.cache.invalidate(self.selected_image)
        index_repository.rename_entry(self._folder, self.selected_image, new_name, new_path)
        self._gallery_vm.reload_index()

        old = self.selected_image
        self.selected_image = new_name
        self.rename_done.emit(new_name)
        self.index_updated.emit(set(self._index.keys()))
