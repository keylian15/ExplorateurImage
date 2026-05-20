"""
Widget représentant un espace de travail complet.

Chaque workspace est autonome : il possède ses propres instances de ViewModels
(GalleryViewModel, DetailViewModel, AutocompleteViewModel, MapViewModel) et ses
propres vues (GalleryWidget, DetailWidget, MapTab, StyleTab).

Chaque workspace stocke également ses propres paramètres (k_neighbors, map_params,
pinned_images, history_search).

La communication avec la fenêtre principale se fait uniquement via des signaux :
- folder_changed : quand l'utilisateur ouvre un dossier
- name_changed   : quand l'utilisateur renomme l'espace de travail (géré par MainWindow)

Responsabilités :
 1. Instancier les ViewModels dans le bon ordre de dépendance
 2. Transmettre les données du workspace (k_neighbors, map_params, pinned_images) aux ViewModels
 3. Assembler les 3 onglets (Galerie, Carte 2D, Thème)
 4. Gérer le dock de détail en interne
 5. Ouvrir automatiquement le dossier restauré depuis la config
 6. Exposer les métadonnées du workspace (id, nom, dossier courant, paramètres, épingles, arbres)
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

from models import workspace_repository as ws_repo
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

    signal_folder_changed = pyqtSignal(str, str)  # (ws_id, folder_path)
    signal_closed = pyqtSignal(str)  # ws_id

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
            ws_data (dict | None): Données complètes du workspace (k_neighbors, map_params, pinned_images…).
            parent: Parent Qt.
        """
        super().__init__(parent)
        self.ws_id = ws_id
        self.ws_name = name
        self._main_window = main_window

        # Données du workspace (avec valeurs par défaut si absent)
        _ws_data = ws_data or ws_repo.make_workspace(name=name, folder=folder)

        # ── ViewModels ────────────────────────────────────────────────────────
        # GalleryViewModel reçoit ws_id et ws_data pour gérer les épingles et l'arbre
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

        # ── Dock détail (rattaché à la fenêtre principale) ────────────────────
        self._dock = QDockWidget(f"Détails — {name}", main_window)
        self._dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self._dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self._dock.setWidget(self._detail_widget)
        self._dock.setMinimumWidth(280)
        self._dock.setVisible(False)
        main_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._dock)

        # ── Dock recherche galerie (rattaché à la fenêtre principale) ─────────
        self._search_dock = self._gallery_widget.build_search_dock(main_window)
        self._search_dock.setVisible(False)
        main_window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._search_dock)

        # ── Dock recherche carte (rattaché à la fenêtre principale) ──────────
        self._map_search_dock = self._map_tab.build_search_dock(main_window)
        self._map_search_dock.setVisible(False)
        main_window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._map_search_dock)

        # ── Connexions inter-VM ───────────────────────────────────────────────
        self.gallery_vm.signal_image_selected.connect(self._on_image_selected)
        self.gallery_vm.signal_image_selected.connect(self._map_tab.on_image_selected)
        self.gallery_vm.signal_folder_changed.connect(self._on_folder_changed)

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
        """Liste des images épinglées du workspace.

        Returns:
            list[str]: Noms des images épinglées dans leur ordre d'épinglage.
        """
        return self.gallery_vm.pinned_images

    @property
    def current_search_trees(self) -> dict:
        """Sérialisation des arbres de recherche (galerie + carte) du workspace.

        Returns:
            dict: {"gallery": {...}, "map": {...}} prêt à être stocké dans config.json.
        """
        return {
            "gallery": self.gallery_vm.search_tree.to_dict(),
            "map": self.map_vm.search_tree.to_dict(),
        }

    # ── Slots internes ────────────────────────────────────────────────────────

    def _on_image_selected(self, img_name: str):
        """Affiche le dock de détail et notifie le DetailViewModel."""
        if not self._dock.isVisible():
            self._dock.setVisible(True)
        self.detail_vm.on_image_selected(img_name)

    def _on_folder_changed(self, folder: str):
        """Propage le changement de dossier vers MainWindow pour persistance."""
        self.signal_folder_changed.emit(self.ws_id, folder)

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
        """Masque le dock de détail, le dock de recherche galerie et le dock de recherche carte."""
        self._dock.setVisible(False)
        self._search_dock.setVisible(False)
        self._map_search_dock.setVisible(False)

    def rename(self, new_name: str):
        """Met à jour le nom interne et le titre du dock.

        Args:
            new_name (str): Nouveau nom de l'espace de travail.
        """
        self.ws_name = new_name
        self._dock.setWindowTitle(f"Détails — {new_name}")
