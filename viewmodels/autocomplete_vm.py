"""
ViewModel orchestrant l'auto-complétion en batch des images non indexées.

Ce composant pilote le processus de génération automatique de métadonnées
(descriptions, mots-clés et embeddings) pour un ensemble d'images, via un worker
asynchrone. Il assure la mise à jour progressive de l'index et la communication
avec la vue grâce à des signaux Qt.

Contenu :
 - Lancement et gestion d'un worker de traitement batch
 - Connexion aux services d'IA pour enrichissement des images
 - Mise à jour de l'index persistant au fil du traitement
 - Gestion de l'annulation et du suivi de progression

Responsabilités :
 1. Identifier les images non indexées à traiter
 2. Démarrer et superviser le worker d'auto-complétion batch
 3. Générer embeddings et métadonnées via le service IA
 4. Mettre à jour l'index persistant image par image
 5. Notifier la vue de la progression, des erreurs et de la fin du traitement
 6. Gérer l'annulation du processus en cours
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from models import index_repository
from services.ollama_wrapper import OllamaWrapper

MODEL_EMBED = "nomic-embed-text:v1.5"


class AutocompleteViewModel(QObject):
    """Class pour la vue d'auto-complétion."""

    # ── Signaux vers la View ──────────────────────────────────────────────────
    signal_started = pyqtSignal(int)  # total d'images à traiter
    signal_image_done = pyqtSignal(int, str)  # (idx, img_name)
    signal_image_error = pyqtSignal(int, str, str)  # (idx, img_name, msg)
    signal_finished = pyqtSignal(bool)  # cancelled=True/False
    signal_progress = pyqtSignal(int, int, str)  # (done, total, label)

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

        self.signal_started.emit(len(images))
        self._worker = AutoCompleteAllWorker(self._gallery_vm.current_folder, images, self._client)
        self._worker.signal_image_done.connect(self.on_signal_image_done)
        self._worker.signal_image_error.connect(self.on_image_error)
        self._worker.signal_all_done.connect(self.on_signal_all_done)
        self._worker.start()

    def cancel(self):
        """Annulation de l'auto-complétion."""
        if self._worker and self._worker.isRunning():
            self._worker.cancel()

    def is_running(self) -> bool:
        """Test si l'auto-complétion est en cours."""
        return bool(self._worker and self._worker.isRunning())

    def on_signal_image_done(self, idx: int, img_name: str, result: dict):
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
        self.signal_image_done.emit(idx, img_name)
        self.signal_progress.emit(idx + 1, total, img_name)

    def on_image_error(self, idx: int, img_name: str, msg: str):
        """Callback quand une image ne peut pas être traitée.

        Args:
            idx (int): Index de l'image.
            img_name (str): Nom de l'image.
            msg (str): Message d'erreur.
        """

        total = self._worker.images.__len__()
        self.signal_image_error.emit(idx, img_name, msg)
        self.signal_progress.emit(idx + 1, total, img_name)

    def on_signal_all_done(self):
        """Callback quand toutes les images ont été traitées."""
        cancelled = self._worker._cancelled
        self.signal_finished.emit(cancelled)
