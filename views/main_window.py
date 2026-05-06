"""
views/main_window.py

QMainWindow : assemble les widgets, gère le dock détail et les onglets.
Ne contient aucune logique métier.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QTabWidget,
)

from viewmodels.autocomplete_vm import AutocompleteViewModel
from viewmodels.detail_vm import DetailViewModel
from viewmodels.gallery_vm import GalleryViewModel
from viewmodels.map_vm import MapViewModel
from views.detail_widget import DetailWidget
from views.gallery_widget import GalleryWidget
from views.map_widget import MapTab
from views.style_tab import StyleTab


class MainWindow(QMainWindow):
    def __init__(
        self,
        gallery_vm: GalleryViewModel,
        detail_vm: DetailViewModel,
        autocomplete_vm: AutocompleteViewModel,
        map_vm: MapViewModel,
    ):
        """
        Args:
            gallery_vm (GalleryViewModel): ViewModel de la vue d'exploration
            detail_vm (DetailViewModel): ViewModel de la vue de détail
            autocomplete_vm (AutocompleteViewModel): ViewModel de la vue d'autocomplétion
            map_vm (MapViewModel): ViewModel de la vue de carte"""

        super().__init__()
        self._gvm = gallery_vm
        self._dvm = detail_vm
        self._avm = autocomplete_vm
        self._mvm = map_vm

        self.setWindowTitle("Explorateur d'images")
        screen = QApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen)

        self.build_ui()
        self.connect_vms()

    # ── Construction ──────────────────────────────────────────────────────────

    def build_ui(self):
        """Construit l'interface utilisateur de la fenêtre principale"""

        # ── Widgets principaux ────────────────────────────────────────────────
        self._gallery_widget = GalleryWidget(self._gvm, self._avm, self)
        self._detail_widget = DetailWidget(self._dvm, self)
        self._map_tab = MapTab(self._mvm, self, self)
        self._style_tab = StyleTab(self)

        # Bouton "Ouvrir" dans la galerie → dialog ici car besoin de la fenêtre
        self._gallery_widget.btn_open.clicked.connect(self.open_folder_dialog)

        # ── Onglets ───────────────────────────────────────────────────────────
        tabs = QTabWidget()
        tabs.addTab(self._gallery_widget, "Galerie")
        tabs.addTab(self._map_tab, "Carte 2D")
        tabs.addTab(self._style_tab, "🎨 Thème")
        self.setCentralWidget(tabs)

        # ── Dock détail ───────────────────────────────────────────────────────
        self._dock = QDockWidget("Détails de l'image", self)
        self._dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self._dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self._dock.setWidget(self._detail_widget)
        self._dock.setMinimumWidth(280)
        self._dock.setVisible(False)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._dock)

    def connect_vms(self):
        """Connecter les VMs entre elles"""
        # Sélection dans la galerie → détail + carte
        self._gvm.image_selected.connect(self.on_image_selected)
        # Sélection via carte → galerie
        self._gvm.image_selected.connect(self._map_tab.on_image_selected)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def open_folder_dialog(self):
        """Ouvre une boîte de dialogue pour choisir un dossier"""
        folder = QFileDialog.getExistingDirectory(self, "Choisir un dossier")
        if folder:
            self._gvm.open_folder(folder)

    def on_image_selected(self, img_name: str):
        """Selectionne l'image.

        Args:
            img_name (str): Nom de l'image
        """
        if not self._dock.isVisible():
            self._dock.setVisible(True)
        self._dvm.on_image_selected(img_name)
