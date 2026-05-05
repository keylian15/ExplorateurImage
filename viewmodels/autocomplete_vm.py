"""
viewmodels/autocomplete_vm.py

Logique du batch d'auto-complétion (toutes les images non-indexées).
Séparé de detail_vm pour garder les fichiers courts.
"""
from __future__ import annotations
import os

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from models import index_repository
from services.ollama_wrapper import OllamaWrapper
from services.workers import AutoCompleteAllWorker

MODEL_EMBED = "nomic-embed-text:v1.5"


class AutocompleteViewModel(QObject):
    # ── Signaux vers la View ──────────────────────────────────────────────────
    started = pyqtSignal(int)              # total d'images à traiter
    image_done = pyqtSignal(int, str)         # (idx, img_name)
    image_error = pyqtSignal(int, str, str)    # (idx, img_name, msg)
    finished = pyqtSignal(bool)             # cancelled=True/False
    progress = pyqtSignal(int, int, str)    # (done, total, label)

    def __init__(self, client: OllamaWrapper,
                 gallery_vm,   # GalleryViewModel
                 parent=None):
        super().__init__(parent)
        self._client = client
        self._gallery_vm = gallery_vm
        self._worker: AutoCompleteAllWorker | None = None

    # ── API publique ──────────────────────────────────────────────────────────

    def start(self):
        if self._worker and self._worker.isRunning():
            return

        images = self._gallery_vm.unindexed_images()
        if not images:
            return

        self.started.emit(len(images))
        self._worker = AutoCompleteAllWorker(
            self._gallery_vm.current_folder, images, self._client
        )
        self._worker.image_done.connect(self._on_image_done)
        self._worker.image_error.connect(self._on_image_error)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.start()

    def cancel(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()

    def is_running(self) -> bool:
        return bool(self._worker and self._worker.isRunning())

    # ── Slots privés ──────────────────────────────────────────────────────────

    def _on_image_done(self, idx: int, img_name: str, result: dict):
        folder = self._gallery_vm.current_folder
        desc = result["description"]
        keywords = result["keywords"]

        embedding = self._client.embed(
            model=MODEL_EMBED,
            text=self._client.build_embedding(desc, keywords),
        )
        entry = index_repository.build_entry(
            img_name, folder, desc, keywords, embedding)
        index_repository.upsert_entry(folder, img_name, entry)
        self._gallery_vm.reload_index()

        total = self._worker.images.__len__()
        self.image_done.emit(idx, img_name)
        self.progress.emit(idx + 1, total, img_name)

    def _on_image_error(self, idx: int, img_name: str, msg: str):
        total = self._worker.images.__len__()
        self.image_error.emit(idx, img_name, msg)
        self.progress.emit(idx + 1, total, img_name)

    def _on_all_done(self):
        cancelled = self._worker._cancelled
        self.finished.emit(cancelled)
