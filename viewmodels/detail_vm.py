"""
ViewModel du panneau de détail d'une image.

Ce composant gère toute la logique liée à l'inspection et à la modification
d'une image sélectionnée : affichage des métadonnées, sauvegarde, auto-complétion,
calcul des voisins, renommage du fichier et épinglage.

Il agit comme intermédiaire entre les services (IA, index, cache) et la vue,
en exposant des signaux Qt pour piloter l'interface de manière réactive.

Contenu :
 - Gestion de l'image sélectionnée et de ses métadonnées
 - Calcul des voisins basés sur la similarité cosinus
 - Sauvegarde des métadonnées avec embeddings
 - Auto-complétion via modèle IA
 - Renommage de fichiers et mise à jour de l'index
 - Épinglage/désépinglage via le GalleryViewModel

Responsabilités :
 1. Charger et exposer les métadonnées de l'image sélectionnée
 2. Générer et afficher un aperçu de l'image
 3. Calculer les images voisines via similarité des embeddings
 4. Orchestrer la sauvegarde des métadonnées (description, keywords, embedding)
 5. Déclencher l'auto-complétion d'une image
 6. Gérer le renommage et la cohérence de l'index et du cache
 7. Notifier la vue des changements (metadata, save, autocomplete, rename, pin)
 8. Déléguer l'épinglage au GalleryViewModel pour centraliser la logique
"""

from __future__ import annotations

import os

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap

from models import index_repository
from models import workspace_repository as ws_repo
from services.ollama_wrapper import OllamaWrapper
from services.workers import AutoCompleteWorker, SaveMetadataWorker

MODEL_EMBED = "nomic-embed-text:v1.5"


class DetailViewModel(QObject):
    # ── Signaux vers la View ──────────────────────────────────────────────────
    # (img_name, desc, keywords)
    metadata_loaded = pyqtSignal(str, str, list)
    preview_ready = pyqtSignal(QPixmap, str)  # (pixmap, img_name)
    neighbors_ready = pyqtSignal(dict)  # {name: score}
    save_started = pyqtSignal()
    save_finished = pyqtSignal()
    save_error = pyqtSignal(str)
    autocomplete_started = pyqtSignal()
    autocomplete_finished = pyqtSignal(str, list)  # (desc, keywords)
    autocomplete_error = pyqtSignal(str)
    rename_done = pyqtSignal(str)  # nouveau nom
    rename_error = pyqtSignal(str)
    index_updated = pyqtSignal(set)
    pin_changed = pyqtSignal(str, bool)
    # Nouveau : demande de persistance à WorkspaceWidget
    persist_requested = pyqtSignal()

    def __init__(
        self,
        client: OllamaWrapper,
        config: dict,
        gallery_vm,  # GalleryViewModel
        ws_id: str,
        ws_data: dict,
        parent=None,
    ):
        """
        Args:
            client (OllamaWrapper): client Ollama
            config (dict): config globale
            gallery_vm (GalleryViewModel): gallery viewmodel
            ws_id (str): identifiant du workspace
            ws_data (dict): données du workspace (contient k_neighbors)
        """

        super().__init__(parent)
        self._client = client
        self._gallery_vm = gallery_vm
        self._ws_id = ws_id
        self._k_neighbors = ws_repo.get_k_neighbors(ws_data)

        self.selected_image: str | None = None
        self._worker: AutoCompleteWorker | None = None
        self._save_worker: SaveMetadataWorker | None = None

        # Debounce sauvegarde
        self._save_timer = QTimer()
        self._save_timer.setInterval(2000)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.do_save)

        self._pending_desc: str = ""
        self._pending_keywords: list[str] = []

        # Relayer le signal pin du gallery_vm vers la vue
        self._gallery_vm.pin_changed.connect(self.pin_changed)

    # ── Propriétés ────────────────────────────────────────────────────────────

    @property
    def k_neighbors(self) -> int:
        """Donne le nombre de voisins.

        Returns:
            int: nombre de voisins"""
        return self._k_neighbors

    @k_neighbors.setter
    def k_neighbors(self, value: int):
        """Remplace le nombre de voisins et persiste dans le workspace.

        Args:
            value (int): nombre de voisins.
        """
        self._k_neighbors = value
        self.persist_requested.emit()

    @property
    def _index(self) -> dict:
        """Renvoie l'index de l'application.

        Returns:
            dict: index de l'application
        """
        return self._gallery_vm.index

    @property
    def _folder(self) -> str | None:
        """Renvoie le dossier courant.

        Returns:
            str | None: dossier courant
        """
        return self._gallery_vm.current_folder

    # ── Sélection ─────────────────────────────────────────────────────────────

    def on_image_selected(self, img_name: str):
        """Callback quand une image est sélectionnée.

        Args:
            img_name (str): nom de l'image
        """
        self.selected_image = img_name

        # Pixmap
        if self._folder:
            path = os.path.join(self._folder, img_name)
            pixmap = QPixmap(path)
            self.preview_ready.emit(pixmap, img_name)

        # Métadonnées
        data = self._index.get(img_name)
        desc = data.get("description", "") if data else ""
        keywords = data.get("keywords", []) if data else []
        self.metadata_loaded.emit(img_name, desc, keywords)

        # Voisins
        self.compute_neighbors(img_name)

        # État épingle courant
        self.pin_changed.emit(img_name, self._gallery_vm.is_pinned(img_name))

    # ── Épinglage ─────────────────────────────────────────────────────────────

    def toggle_pin(self):
        """Bascule l'état épinglé de l'image sélectionnée."""
        if self.selected_image:
            self._gallery_vm.toggle_pin(self.selected_image)

    def is_pinned(self) -> bool:
        """Indique si l'image sélectionnée est épinglée.

        Returns:
            bool: True si épinglée.
        """
        if self.selected_image:
            return self._gallery_vm.is_pinned(self.selected_image)
        return False

    # ── Sauvegarde ────────────────────────────────────────────────────────────

    def schedule_save(self, desc: str, keywords: list[str]):
        """Planifie la sauvegarde des métadonnées.

        Args:
            desc (str): description de l'image
            keywords (list[str]): liste de mots-clés de l'image
        """
        if not self.selected_image:
            return
        self._pending_desc = desc
        self._pending_keywords = keywords
        self._save_timer.start()

    def do_save(self):
        """Sauvegarde les métadonnées de l'image sélectionnée."""
        if not self.selected_image or not self._folder:
            return
        if self._save_worker and self._save_worker.isRunning():
            return

        self.save_started.emit()
        self._save_worker = SaveMetadataWorker(
            self.selected_image,
            self._folder,
            self._pending_desc,
            self._pending_keywords,
            self._client,
        )
        self._save_worker.finished.connect(self.on_save_done)
        self._save_worker.error.connect(self.save_error)
        self._save_worker.start()

    def on_save_done(self):
        """Callback de la fin de la sauvegarde."""
        self._gallery_vm.reload_index()
        self.save_finished.emit()
        self.index_updated.emit(set(self._index.keys()))

    # ── Auto-complétion ───────────────────────────────────────────────────────

    def auto_complete(self):
        """Lance l'auto-complétion des métadonnées."""
        if not self.selected_image or not self._folder:
            return
        if self._worker and self._worker.isRunning():
            return

        path = os.path.join(self._folder, self.selected_image)
        self.autocomplete_started.emit()
        self._worker = AutoCompleteWorker(path, self._client)
        self._worker.finished.connect(self.on_autocomplete_done)
        self._worker.error.connect(self.autocomplete_error)
        self._worker.start()

    def on_autocomplete_done(self, result: dict):
        """Callback de la fin de l'auto-complétion."""
        desc = result["description"]
        keywords = result["keywords"]
        self.autocomplete_finished.emit(desc, keywords)

    # ── Voisins ───────────────────────────────────────────────────────────────

    def compute_neighbors(self, img_name: str):
        """Calcule les voisins de l'image.

        Args:
            img_name (str): Nom de l'image.
        """
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
            scores[key] = self._client.similarite_cosinus(entry["embedding"], data["embedding"])
        top = dict(sorted(scores.items(), key=lambda x: x[1], reverse=True)[: self._k_neighbors])
        self.neighbors_ready.emit(top)

    def refresh_neighbors(self):
        """Rafraichi les voisins de l'image sélectionnée."""
        if self.selected_image:
            self.compute_neighbors(self.selected_image)

    # ── Renommage ─────────────────────────────────────────────────────────────

    def rename(self, new_name: str):
        """Renomme l'image sélectionnée.

        Args:
            new_name (str): Nouveau nom de l'image."""
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

        # Mettre à jour l'épingle si l'image était épinglée
        if self._gallery_vm.is_pinned(self.selected_image):
            self._gallery_vm.unpin_image(self.selected_image)
            self._gallery_vm.pin_image(new_name)

        self._gallery_vm.cache.invalidate(self.selected_image)
        index_repository.rename_entry(self._folder, self.selected_image, new_name, new_path)
        self._gallery_vm.reload_index()

        self.selected_image = new_name
        self.rename_done.emit(new_name)
        self.index_updated.emit(set(self._index.keys()))
