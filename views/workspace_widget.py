"""Widget représentant un espace de travail complet.

Chaque workspace est autonome : il possède ses propres instances de ViewModels
(GalleryViewModel, DetailViewModel, AutocompleteViewModel, MapViewModel, Sam3ViewModel)
et ses propres vues (GalleryWidget, DetailWidget, MapTab, StyleTab).

Le Sam3ViewModel est partagé au sein du workspace : le modèle SAM3 est chargé
une seule fois en arrière-plan au démarrage. Chaque ouverture de dialog plein
écran (clic droit sur une image) réutilise le modèle déjà chargé.

Responsabilités :
 1. Instancier les ViewModels dans le bon ordre de dépendance
 2. Transmettre les données du workspace (k_neighbors, map_params, pinned_images) aux ViewModels
 3. Assembler les 3 onglets (Galerie, Carte 2D, Thème)
 4. Gérer le dock de détail en interne
 5. Ouvrir automatiquement le dossier restauré depuis la config
 6. Exposer les métadonnées du workspace (id, nom, dossier courant, paramètres, épingles, arbres)
 7. Partager le Sam3ViewModel et lancer le chargement du modèle en fond au démarrage
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
    QVBoxLayout,
    QWidget,
)

from models import workspace_repository as ws_repo
from services.i18n_manager import I18nManager
from services.ollama_wrapper import OllamaWrapper
from viewmodels.autocomplete_vm import AutocompleteViewModel
from viewmodels.detail_vm import DetailViewModel
from viewmodels.gallery_vm import GalleryViewModel
from viewmodels.map_vm import MapViewModel
from viewmodels.sam3_vm import Sam3ViewModel
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
        translator: I18nManager = None,
        sam3_service=None,
    ):
        """Args:
        ws_id (str): Identifiant unique du workspace.
        name (str): Nom affiché dans l'onglet parent.
        client (OllamaWrapper): Client Ollama partagé.
        config (dict): Configuration globale.
        main_window (QMainWindow): Fenêtre principale, nécessaire pour les docks.
        folder (str | None): Dossier à restaurer, ou None.
        ws_data (dict | None): Données complètes du workspace.
        parent: Parent Qt.

        """
        super().__init__(parent)
        self.ws_id = ws_id
        self.ws_name = name
        self._main_window = main_window
        self.translator = translator

        _ws_data = ws_data or ws_repo.make_workspace(name=name, folder=folder)

        # ── ViewModels ────────────────────────────────────────────────────────
        self.gallery_vm = GalleryViewModel(client, config, ws_id=ws_id, ws_data=_ws_data)
        self.detail_vm = DetailViewModel(client, config, self.gallery_vm, ws_id, _ws_data, translator=translator)
        self.autocomplete_vm = AutocompleteViewModel(client, self.gallery_vm)
        self.map_vm = MapViewModel(client, config, self.gallery_vm, ws_id, _ws_data, translator=translator)
        self.sam3_vm = Sam3ViewModel(client, config, self.gallery_vm, ws_id, _ws_data, sam3_service, translator=translator)

        # ── Vues ──────────────────────────────────────────────────────────────
        self._gallery_widget = GalleryWidget(self.gallery_vm, self.autocomplete_vm, self.sam3_vm, translator, parent=self)
        self._detail_widget = DetailWidget(self.detail_vm, self.sam3_vm, translator, self)
        self._map_tab = MapTab(self.map_vm, main_window, translator, self)
        self._style_tab = StyleTab(translator, self)

        self._gallery_widget.btn_open.clicked.connect(self.open_folder_dialog)

        action_open_workspace = QAction("Open Workspace", self)
        action_open_workspace.setShortcut(QKeySequence("Ctrl+O"))
        action_open_workspace.triggered.connect(lambda: self.open_folder_dialog())
        self.addAction(action_open_workspace)

        # ── Onglets internes ──────────────────────────────────────────────────
        self._tabs = QTabWidget(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tabs)

        self._tabs.addTab(self._gallery_widget, self.translator.tr("🖼 Galerie"))
        self._tabs.addTab(self._map_tab, self.translator.tr("🗺 Carte 2D"))
        self._tabs.addTab(self._style_tab, self.translator.tr("⚙️ Paramètres"))

        # ── Dock détail ───────────────────────────────────────────────────────
        self._dock = QDockWidget(self.translator.tr("Détails - {name}").format(name=name), main_window)
        self._dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self._dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self._dock.setWidget(self._detail_widget)
        self._dock.setMinimumWidth(280)
        self._dock.setVisible(False)
        main_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._dock)

        # ── Dock recherche galerie ────────────────────────────────────────────
        self._search_dock = self._gallery_widget.build_search_dock(main_window)
        self._search_dock.setVisible(False)
        main_window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._search_dock)

        # ── Dock recherche carte ──────────────────────────────────────────────
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
        return self.gallery_vm.current_folder

    @property
    def current_k_neighbors(self) -> int:
        return self.detail_vm.k_neighbors

    @property
    def current_map_params(self) -> dict:
        return self.map_vm.params

    @property
    def current_pinned_images(self) -> list[str]:
        return self.gallery_vm.pinned_images

    @property
    def current_search_trees(self) -> dict:
        return {
            "gallery": self.gallery_vm.search_tree.to_dict(),
            "map": self.map_vm.search_tree.to_dict(),
        }

    # ── Slots internes ────────────────────────────────────────────────────────

    def _on_image_selected(self, img_name: str):
        if not self._dock.isVisible():
            self._dock.setVisible(True)
        self.detail_vm.on_image_selected(img_name)

    def _on_folder_changed(self, folder: str):
        self.signal_folder_changed.emit(self.ws_id, folder)

    # ── API publique ──────────────────────────────────────────────────────────

    def open_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, "Choisir un dossier")
        if folder:
            self.gallery_vm.open_folder(folder)

    def show_dock(self, visible: bool = True):
        self._dock.setVisible(visible)

    def hide_dock(self):
        self._dock.setVisible(False)
        self._search_dock.setVisible(False)
        self._map_search_dock.setVisible(False)

    def rename(self, new_name: str):
        self.ws_name = new_name
        self._dock.setWindowTitle(self.translator.tr("Détails - {name}").format(name=new_name))
