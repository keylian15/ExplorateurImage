"""
ViewModel gérant le processus d'auto-complétion en batch des images non indexées.

Il orchestre l'exécution asynchrone de la génération de descriptions, mots-clés
et embeddings pour chaque image via un worker dédié, puis met à jour l'index
persistant au fur et à mesure du traitement.

Ce composant fait le lien entre les services (IA, index) et la vue en exposant
des signaux de progression, d'erreur et de fin, permettant un suivi en temps réel
et une éventuelle annulation du processus.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from models import index_repository
from services.ollama_wrapper import OllamaWrapper
from services.workers import AutoCompleteAllWorker

MODEL_EMBED = "nomic-embed-text:v1.5"


class AutocompleteViewModel(QObject):
    """Class pour la vue d'auto-complétion."""

    # ── Signaux vers la View ──────────────────────────────────────────────────
    started = pyqtSignal(int)  # total d'images à traiter
    image_done = pyqtSignal(int, str)  # (idx, img_name)
    image_error = pyqtSignal(int, str, str)  # (idx, img_name, msg)
    finished = pyqtSignal(bool)  # cancelled=True/False
    progress = pyqtSignal(int, int, str)  # (done, total, label)

    def __init__(
        self,
        client: OllamaWrapper,
        gallery_vm,  # GalleryViewModel
        parent=None,
    ):
        """
        Args:
            client (OllamaWrapper): Instance de OllamaWrapper
            gallery_vm (GalleryViewModel): Instance de GalleryViewModel
        """
        super().__init__(parent)
        self._client = client
        self._gallery_vm = gallery_vm
        self._worker: AutoCompleteAllWorker | None = None

    def start(self):
        """Lancement de l'auto-complétion."""
        if self._worker and self._worker.isRunning():
            return

        images = self._gallery_vm.unindexed_images()
        if not images:
            return

        self.started.emit(len(images))
        self._worker = AutoCompleteAllWorker(self._gallery_vm.current_folder, images, self._client)
        self._worker.image_done.connect(self.on_image_done)
        self._worker.image_error.connect(self.on_image_error)
        self._worker.all_done.connect(self.on_all_done)
        self._worker.start()

    def cancel(self):
        """Annulation de l'auto-complétion."""
        if self._worker and self._worker.isRunning():
            self._worker.cancel()

    def is_running(self) -> bool:
        """Test si l'auto-complétion est en cours."""
        return bool(self._worker and self._worker.isRunning())

    def on_image_done(self, idx: int, img_name: str, result: dict):
        """Callback quand une image est traitée.

        Args:
            idx (int): Index de l'image.
            img_name (str): Nom de l'image.
            result (dict): Résultat de l'auto-complétion.
        """
        folder = self._gallery_vm.current_folder
        desc = result["description"]
        keywords = result["keywords"]

        embedding = self._client.embed(
            model=MODEL_EMBED,
            text=self._client.build_embedding(desc, keywords),
        )
        entry = index_repository.build_entry(img_name, folder, desc, keywords, embedding)
        index_repository.upsert_entry(folder, img_name, entry)
        self._gallery_vm.reload_index()

        total = self._worker.images.__len__()
        self.image_done.emit(idx, img_name)
        self.progress.emit(idx + 1, total, img_name)

    def on_image_error(self, idx: int, img_name: str, msg: str):
        """Callback quand une image ne peut pas être traitée.

        Args:
            idx (int): Index de l'image.
            img_name (str): Nom de l'image.
            msg (str): Message d'erreur.
        """

        total = self._worker.images.__len__()
        self.image_error.emit(idx, img_name, msg)
        self.progress.emit(idx + 1, total, img_name)

    def on_all_done(self):
        """Callback quand toutes les images ont été traitées."""
        cancelled = self._worker._cancelled
        self.finished.emit(cancelled)
