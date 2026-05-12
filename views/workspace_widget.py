"""
Widget représentant un espace de travail complet.

Chaque workspace est autonome : il possède ses propres instances de ViewModels
(GalleryViewModel, DetailViewModel, AutocompleteViewModel, MapViewModel) et ses
propres vues (GalleryWidget, DetailWidget, MapTab, StyleTab).

Chaque workspace stocke également ses propres paramètres (k_neighbors, map_params,
pinned_images) ainsi que son historique d'actions (history, history_current_id).

La communication avec la fenêtre principale se fait uniquement via des signaux :
- folder_changed : quand l'utilisateur ouvre un dossier
- name_changed   : quand l'utilisateur renomme l'espace de travail (géré par MainWindow)

Responsabilités :
 1. Instancier les ViewModels dans le bon ordre de dépendance
 2. Transmettre les données du workspace (k_neighbors, map_params, pinned_images) aux ViewModels
 3. Assembler les 3 onglets (Galerie, Carte 2D, Thème)
 4. Gérer le dock de détail en interne
 5. Ouvrir automatiquement le dossier restauré depuis la config
 6. Exposer les métadonnées du workspace (id, nom, dossier courant, paramètres, épingles)
 7. Sauvegarder l'historique dans config.json après chaque action
 8. Restaurer l'historique depuis config.json au démarrage
"""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QTabWidget,
    QWidget,
)

from models import config_repository
from models import workspace_repository as ws_repo
from services.history.history_node import HistoryNode
from services.history.history_tree import HistoryTree
from services.history.history_types import HistoryActionType
from services.ollama_wrapper import OllamaWrapper
from viewmodels.autocomplete_vm import AutocompleteViewModel
from viewmodels.detail_vm import DetailViewModel
from viewmodels.gallery_vm import GalleryViewModel
from viewmodels.map_vm import MapViewModel
from views.detail_widget import DetailWidget
from views.gallery_widget import GalleryWidget
from views.map_widget import MapTab
from views.style_tab import StyleTab


class WorkspaceWidget(QWidget):
    """Espace de travail autonome : galerie + carte + thème + dock détail."""

    folder_changed = pyqtSignal(str, str)  # (ws_id, folder_path)
    closed = pyqtSignal(str)  # ws_id

    def __init__(
        self,
        ws_id: str,
        name: str,
        client: OllamaWrapper,
        config: dict,
        main_window: QMainWindow,
        folder: str | None = None,
        ws_data: dict | None = None,
        parent=None,
    ):
        """
        Args:
            ws_id (str): Identifiant unique du workspace.
            name (str): Nom affiché dans l'onglet parent.
            client (OllamaWrapper): Client Ollama partagé.
            config (dict): Configuration globale.
            main_window (QMainWindow): Fenêtre principale, nécessaire pour les docks.
            folder (str | None): Dossier à restaurer, ou None.
            ws_data (dict | None): Données complètes du workspace (k_neighbors, map_params,
                                   pinned_images, history, history_current_id…).
            parent: Parent Qt.
        """
        super().__init__(parent)
        self.ws_id = ws_id
        self.ws_name = name
        self._main_window = main_window
        self._config = config

        # Données du workspace (avec valeurs par défaut si absent)
        _ws_data = ws_data or ws_repo.make_workspace(name=name, folder=folder)

        # ── Historique ────────────────────────────────────────────────────────
        history_data, history_current_id = ws_repo.get_history(_ws_data)
        self.history_tree = HistoryTree.from_list(history_data, history_current_id)
        self._last_history_selection: str | None = None
        self._is_restoring_history = False

        action_back = QAction("Back", self)
        action_back.setShortcut(QKeySequence("Ctrl+Z"))
        action_back.triggered.connect(self.on_history_back)
        self.addAction(action_back)

        action_debug = QAction("Debug", self)
        action_debug.setShortcut(QKeySequence("Ctrl+D"))
        action_debug.triggered.connect(self.print_history_tree)
        self.addAction(action_debug)

        # ── ViewModels ────────────────────────────────────────────────────────
        # GalleryViewModel reçoit ws_id et ws_data pour gérer les épingles
        self.gallery_vm = GalleryViewModel(client, config, ws_id=ws_id, ws_data=_ws_data)
        self.detail_vm = DetailViewModel(client, config, self.gallery_vm, ws_id, _ws_data)
        self.autocomplete_vm = AutocompleteViewModel(client, self.gallery_vm)
        self.map_vm = MapViewModel(client, config, self.gallery_vm, ws_id, _ws_data)

        # ── Vues ──────────────────────────────────────────────────────────────
        self._gallery_widget = GalleryWidget(self.gallery_vm, self.autocomplete_vm, self)
        self._detail_widget = DetailWidget(self.detail_vm, self)
        self._map_tab = MapTab(self.map_vm, main_window, self)
        self._style_tab = StyleTab(self)

        # Bouton "Ouvrir" → dialog géré ici
        self._gallery_widget.btn_open.clicked.connect(self.open_folder_dialog)

        action_open_workspace = QAction("Open Workspace", self)
        action_open_workspace.setShortcut(QKeySequence("Ctrl+O"))
        action_open_workspace.triggered.connect(lambda: self.open_folder_dialog())
        self.addAction(action_open_workspace)

        # ── Onglets internes ──────────────────────────────────────────────────
        self._tabs = QTabWidget(self)

        from PyQt6.QtWidgets import QVBoxLayout

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tabs)

        self._tabs.addTab(self._gallery_widget, "🖼 Galerie")
        self._tabs.addTab(self._map_tab, "🗺 Carte 2D")
        self._tabs.addTab(self._style_tab, "🎨 Thème")

        # ── Dock détail ───────────────────────────────────────────────────────
        self._dock = QDockWidget(f"Détails — {name}", main_window)
        self._dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self._dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self._dock.setWidget(self._detail_widget)
        self._dock.setMinimumWidth(280)
        self._dock.setVisible(False)
        main_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._dock)

        # ── Connexions inter-VM ───────────────────────────────────────────────
        self.gallery_vm.image_selected.connect(self.on_image_selected)
        self.gallery_vm.image_selected.connect(self._map_tab.on_image_selected)
        self.gallery_vm.folder_changed.connect(self.on_folder_changed)
        self.gallery_vm.pin_changed.connect(self.on_pin_changed)

        # ── Restauration du dossier ───────────────────────────────────────────
        if folder and os.path.exists(folder):
            self.gallery_vm.open_folder(folder)

    # ── Propriétés ────────────────────────────────────────────────────────────

    @property
    def current_folder(self) -> str | None:
        """Dossier courant du workspace."""
        return self.gallery_vm.current_folder

    @property
    def current_k_neighbors(self) -> int:
        """k_neighbors courant du workspace."""
        return self.detail_vm.k_neighbors

    @property
    def current_map_params(self) -> dict:
        """map_params courants du workspace."""
        return self.map_vm.params

    @property
    def current_pinned_images(self) -> list[str]:
        """Liste des images épinglées du workspace."""
        return self.gallery_vm.pinned_images

    @property
    def current_history(self) -> list[dict]:
        """Historique sérialisé du workspace.

        Returns:
            list[dict]: Liste plate des noeuds d'historique.
        """
        return self.history_tree.to_list()

    @property
    def current_history_current_id(self) -> str | None:
        """ID du noeud courant de l'historique.

        Returns:
            str | None: ID du noeud courant, ou None.
        """
        return self.history_tree.current_id()

    # ── Sauvegarde de l'historique ────────────────────────────────────────────

    def _save_history(self):
        """Persiste l'historique du workspace courant dans config.json."""
        workspaces = ws_repo.load(self._config)
        workspaces = ws_repo.update_workspace(
            workspaces,
            self.ws_id,
            history=self.current_history,
            history_current_id=self.current_history_current_id,
        )
        self._config = ws_repo.save(self._config, workspaces)
        config_repository.save(self._config)

    # ── Slots internes ────────────────────────────────────────────────────────

    def on_image_selected(self, img_name: str):
        """Affiche le dock de détail, notifie le DetailViewModel et sauvegarde l'historique."""

        if self._is_restoring_history:
            return

        if img_name == self._last_history_selection:
            return

        self._last_history_selection = img_name

        if not self._dock.isVisible():
            self._dock.setVisible(True)

        self.detail_vm.on_image_selected(img_name)

        self.history_tree.push(
            action_type=HistoryActionType.SELECT,
            payload={"img_name": img_name},
            active_view="gallery",
        )
        self._save_history()

    def on_folder_changed(self, folder: str):
        """Propage le changement de dossier et le sauvegarde dans l'historique."""

        old_folder = self.current_folder

        self.history_tree.push(
            action_type=HistoryActionType.FOLDER_CHANGED,
            payload={
                "old_folder": old_folder,
                "new_folder": folder,
            },
            active_view="gallery",
        )
        self._save_history()

        self.folder_changed.emit(self.ws_id, folder)

    def on_pin_changed(self, img_name: str, is_pinned: bool):
        """Ajoute l'action de pin à l'historique et la sauvegarde."""

        if self._is_restoring_history:
            return

        self.history_tree.push(
            action_type=HistoryActionType.PIN_IMAGE,
            payload={
                "img_name": img_name,
                "is_pinned": is_pinned,
            },
            active_view="gallery",
        )
        self._save_history()

    # ── API publique ──────────────────────────────────────────────────────────

    def open_folder_dialog(self):
        """Ouvre un sélecteur de dossier."""
        folder = QFileDialog.getExistingDirectory(self, "Choisir un dossier")
        if folder:
            self.gallery_vm.open_folder(folder)

    def show_dock(self, visible: bool = True):
        """Affiche ou masque le dock de détail."""
        self._dock.setVisible(visible)

    def hide_dock(self):
        """Masque le dock de détail."""
        self._dock.setVisible(False)

    def rename(self, new_name: str):
        """Met à jour le nom interne, le titre du dock et sauvegarde dans l'historique."""

        old_name = self.ws_name
        self.ws_name = new_name
        self._dock.setWindowTitle(f"Détails — {new_name}")

        self.history_tree.push(
            action_type=HistoryActionType.RENAME_WORKSPACE,
            payload={
                "old_name": old_name,
                "new_name": new_name,
            },
            active_view="gallery",
        )
        self._save_history()

    # ── Historique ────────────────────────────────────────────────────────────

    def on_history_back(self) -> None:
        """Revient au noeud précédent et restaure son état."""

        node = self.history_tree.back()

        if not node:
            return

        self._save_history()
        self.restore_history_node(node)

    def restore_history_node(self, node: HistoryNode) -> None:
        """Restaure l'état correspondant à un noeud d'historique.

        Args:
            node (HistoryNode): Noeud à restaurer.
        """
        self._is_restoring_history = True
        try:
            if node.action_type == HistoryActionType.SELECT:
                img_name = node.payload.get("img_name")
                if img_name:
                    self.gallery_vm.select_image(img_name)
        finally:
            self._is_restoring_history = False

    def print_history_tree(self) -> None:
        """Affiche l'arbre d'historique dans la console (debug)."""

        print("\n=== HISTORY TREE ===\n")
        if self.history_tree.root:
            self._print_history_node(self.history_tree.root)
        else:
            print("(vide)")

    def _print_history_node(self, node: HistoryNode, indent: int = 0) -> None:
        """Affichage récursif des noeuds d'historique.

        Args:
            node (HistoryNode): Noeud à afficher.
            indent (int): Niveau d'indentation.
        """
        prefix = "    " * indent
        current_marker = " <== CURRENT" if node == self.history_tree.current else ""
        print(f"{prefix}- {node.action_type.name} {node.payload}{current_marker} - {node.active_view}")
        for child in node.children:
            self._print_history_node(child, indent + 1)
