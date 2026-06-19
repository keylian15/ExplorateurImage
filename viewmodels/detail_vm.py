"""ViewModel du panneau de détail d'une image.

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

from models import config_repository, index_repository
from models import workspace_repository as ws_repo
from services.i18n_manager import I18nManager
from services.ollama_wrapper import OllamaWrapper
from services.workers import AutoCompleteWorker, SaveMetadataWorker
from viewmodels.gallery_vm import GalleryViewModel

MODEL_EMBED = "nomic-embed-text:v1.5"


class DetailViewModel(QObject):
    """ViewModel qui gere l'affichage et l'interaction pour la vue de details."""

    # ── Signaux vers la View ──────────────────────────────────────────────────
    # (img_name, desc, keywords)
    signal_metadata_loaded = pyqtSignal(str, str, list)
    signal_preview_ready = pyqtSignal(QPixmap, str)  # (pixmap, img_name)
    signal_neighbors_ready = pyqtSignal(dict)  # {name: score}
    signal_save_started = pyqtSignal()
    signal_save_finished = pyqtSignal()
    signal_save_error = pyqtSignal(str)
    signal_autocomplete_started = pyqtSignal()
    signal_autocomplete_finished = pyqtSignal(str, list)  # (desc, keywords)
    signal_autocomplete_error = pyqtSignal(str)
    signal_rename_done = pyqtSignal(str)  # nouveau nom
    signal_rename_error = pyqtSignal(str)
    signal_index_updated = pyqtSignal(set)  # noms indexés
    signal_pin_changed = pyqtSignal(str, bool)  # (img_name, is_pinned)

    def __init__(
        self,
        client: OllamaWrapper,
        config: dict,
        gallery_vm: GalleryViewModel,
        ws_id: str,
        ws_data: dict,
        translator: I18nManager,
    ) -> None:
        """Initialise le widget des details de l'image.

        Args:
            client (OllamaWrapper): client Ollama
            config (dict): config globale
            gallery_vm (GalleryViewModel): gallery viewmodel
            ws_id (str): identifiant du workspace
            ws_data (dict): données du workspace (contient k_neighbors).
            translator (I18nManager): le traducteur.

        """
        super().__init__()
        self._client = client
        self._config = config
        self._gallery_vm = gallery_vm
        self._ws_id = ws_id
        self._k_neighbors = ws_repo.get_k_neighbors(ws_data)
        self.translator = translator

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
        self._gallery_vm.signal_pin_changed.connect(self.signal_pin_changed)

    # ── Propriétés ────────────────────────────────────────────────────────────

    @property
    def k_neighbors(self) -> int:
        """Donne le nombre de voisins.

        Returns:
            int: nombre de voisins

        """
        return self._k_neighbors

    @k_neighbors.setter
    def k_neighbors(self, value: int) -> None:
        """Remplace le nombre de voisins et persiste dans le workspace.

        Args:
            value (int): nombre de voisins.

        """
        self._k_neighbors = value
        self.save_k_neighbors_to_workspace(value)

    def save_k_neighbors_to_workspace(self, value: int) -> None:
        """Sauvegarde k_neighbors dans le workspace courant.

        Args:
            value (int): Valeur à sauvegarder.

        """
        workspaces = ws_repo.load(self._config)
        workspaces = ws_repo.update_workspace(workspaces, self._ws_id, k_neighbors=value)
        self._config = ws_repo.save(self._config, workspaces)
        config_repository.save(self._config)

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

    def on_image_selected(self, img_name: str) -> None:
        """Traite la sélection d'une image et met à jour les données associées.

        Charge la sélection courante, prépare et émet le preview (image), les métadonnées,
        calcule les voisins et notifie l'état d'épinglage.

        Args:
            img_name (str): Nom de l'image sélectionnée.

        """
        self.selected_image = img_name

        # Pixmap
        if self._folder:
            path = os.path.join(self._folder, img_name)
            pixmap = QPixmap(path)
            self.signal_preview_ready.emit(pixmap, img_name)

        # Métadonnées
        data = self._index.get(img_name)
        desc = data.get("description", "") if data else ""
        keywords = data.get("keywords", []) if data else []
        self.signal_metadata_loaded.emit(img_name, desc, keywords)

        # Voisins
        self.compute_neighbors(img_name)

        # État épingle courant
        self.signal_pin_changed.emit(img_name, self._gallery_vm.is_pinned(img_name))

    # ── Épinglage ─────────────────────────────────────────────────────────────

    def toggle_pin(self) -> None:
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

    def schedule_save(self, desc: str, keywords: list[str]) -> None:
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

    def do_save(self) -> None:
        """Sauvegarde les métadonnées de l'image sélectionnée."""
        if not self.selected_image or not self._folder:
            return
        if self._save_worker and self._save_worker.isRunning():
            return

        self.signal_save_started.emit()
        self._save_worker = SaveMetadataWorker(
            self.selected_image,
            self._folder,
            self._pending_desc,
            self._pending_keywords,
            self._client,
        )
        self._save_worker.signal_finished.connect(self.on_save_done)
        self._save_worker.signal_error.connect(self.signal_save_error)
        self._save_worker.start()

    def on_save_done(self) -> None:
        """ "Finalise la sauvegarde des données et met à jour les composants dépendants.

        Déclenche la mise à jour de la galerie, émet les signaux de fin de sauvegarde
        et notifie la mise à jour de l'index avec l'ensemble des clés disponibles.
        """
        self._gallery_vm.reload_index()
        self.signal_save_finished.emit()
        self.signal_index_updated.emit(set(self._index.keys()))

    # ── Auto-complétion ───────────────────────────────────────────────────────

    def auto_complete(self) -> None:
        """Lance l'auto-complétion des métadonnées."""
        if not self.selected_image or not self._folder:
            return
        if self._worker and self._worker.isRunning():
            return

        path = os.path.join(self._folder, self.selected_image)
        self.signal_autocomplete_started.emit()
        self._worker = AutoCompleteWorker(path, self._client)
        self._worker.signal_finished.connect(self.on_autocomplete_done)
        self._worker.signal_error.connect(self.signal_autocomplete_error)
        self._worker.start()

    def on_autocomplete_done(self, result: dict) -> None:
        """Traite le résultat de l'auto-complétion et émet le signal de fin.

        Args:
            result (dict): Résultat contenant la description et les mots-clés générés.

        """
        desc = result["description"]
        keywords = result["keywords"]
        self.signal_autocomplete_finished.emit(desc, keywords)

    # ── Voisins ───────────────────────────────────────────────────────────────

    def compute_neighbors(self, img_name: str) -> None:
        """Fait le Calcule des voisins les plus proches d'une image à partir des embeddings.

        Compare l'image cible avec l'ensemble de l'index en utilisant la similarité cosinus,
        puis sélectionne les k voisins les plus proches.

        Args:
            img_name (str): Nom de l'image dont on souhaite calculer les voisins.

        """
        if img_name not in self._index:
            self.signal_neighbors_ready.emit({})
            return
        entry = self._index[img_name]
        if "embedding" not in entry:
            self.signal_neighbors_ready.emit({})
            return

        scores = {}
        for key, data in self._index.items():
            if key == img_name or "embedding" not in data:
                continue
            scores[key] = self._client.similarite_cosinus(entry["embedding"], data["embedding"])
        top = dict(sorted(scores.items(), key=lambda x: x[1], reverse=True)[: self._k_neighbors])
        self.signal_neighbors_ready.emit(top)

    def refresh_neighbors(self) -> None:
        """Rafraichi les voisins de l'image sélectionnée."""
        if self.selected_image:
            self.compute_neighbors(self.selected_image)

    # ── Renommage ─────────────────────────────────────────────────────────────

    def rename(self, new_name: str) -> None:
        """Renomme l'image sélectionnée.

        Args:
            new_name (str): Nouveau nom de l'image.

        """
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
            self.signal_rename_error.emit(self.translator.tr("Un fichier avec ce nom existe déjà."))
            return

        try:
            os.rename(old_path, new_path)
        except OSError as e:
            self.signal_rename_error.emit(str(e))
            return

        # Mettre à jour l'épingle si l'image était épinglée
        if self._gallery_vm.is_pinned(self.selected_image):
            self._gallery_vm.unpin_image(self.selected_image)
            self._gallery_vm.pin_image(new_name)

        self._gallery_vm.cache.invalidate(self.selected_image)
        index_repository.rename_entry(self._folder, self.selected_image, new_name, new_path)
        self._gallery_vm.reload_index()

        self.selected_image = new_name
        self.signal_rename_done.emit(new_name)
        self.signal_index_updated.emit(set(self._index.keys()))
