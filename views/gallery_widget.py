"""
Widget principal de la galerie d'images.

Ce composant constitue la vue centrale de navigation des images. Il affiche une grille
d'images en mode icônes avec recherche, zoom dynamique, préchargement des thumbnails
et gestion du batch d'auto-complétion.

Toute la logique métier est externalisée dans les ViewModels : ce widget se limite
à la gestion de l'interface utilisateur et à la propagation des interactions.

Contenu :
 - Barre de recherche et actions globales (ouvrir dossier, batch IA, annulation)
 - Affichage des images en grille via QListView en mode icônes
 - Barre de progression pour les traitements batch
 - Support du zoom dynamique (Ctrl + molette)
 - Préchargement intelligent des thumbnails (prefetch)
 - Ouverture d'images en plein écran

Responsabilités :
 1. Afficher la grille d'images du dossier courant
 2. Permettre la recherche et le filtrage via le ViewModel
 3. Gérer le zoom de la grille (taille des cellules)
 4. Lancer et suivre les traitements batch d'auto-complétion
 5. Précharger les thumbnails visibles pour fluidifier l'affichage
 6. Ouvrir les images en plein écran sur interaction utilisateur
 7. Relayer les événements UI vers les ViewModels sans logique métier
"""

from __future__ import annotations

from PyQt6.QtCore import QModelIndex, QPoint, QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from models.image_model import IMG_NAME_ROLE
from styles import THUMB
from viewmodels.autocomplete_vm import AutocompleteViewModel
from viewmodels.gallery_vm import GalleryViewModel
from views.components.fullscreen_dialog import FullscreenDialog
from views.tree_widget import TreeViewWidget

PREFETCH_ROWS = THUMB["prefetch_rows"]


class GalleryWidget(QWidget):
    def __init__(self, gallery_vm: GalleryViewModel, autocomplete_vm: AutocompleteViewModel, parent=None):
        """
        Args:
            gallery_vm (GalleryViewModel): ViewModel de la galerie.
            autocomplete_vm (AutocompleteViewModel): ViewModel de l'autocomplétion."""
        super().__init__(parent)
        self._gvm = gallery_vm
        self._avm = autocomplete_vm
        self._search_dock: QDockWidget | None = None

        self.build_ui()
        self.connect_vm()

    # ── Construction ─────────────────────────────────────────────────────────

    def build_ui(self):
        """Construit le widget."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 4)
        layout.setSpacing(6)

        # ── Barre du haut ─────────────────────────────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(8)

        self.btn_open = QPushButton("Ouvrir un dossier")
        top.addWidget(self.btn_open)

        self.btn_batch = QPushButton("Tout auto-compléter")
        top.addWidget(self.btn_batch)

        self.btn_cancel = QPushButton("Annuler")
        self.btn_cancel.setVisible(False)
        top.addWidget(self.btn_cancel)

        # Bouton pour afficher/masquer le dock de recherche
        self.btn_search_dock = QPushButton("🔍 Recherche")
        self.btn_search_dock.setCheckable(True)
        self.btn_search_dock.setToolTip("Afficher / masquer le panneau de recherche")
        top.addWidget(self.btn_search_dock)

        top.addStretch()

        layout.addLayout(top)

        # ── Vue ───────────────────────────────────────────────────────────────
        size = self._gvm.cell_size
        self.list_view = QListView()
        self.list_view.setModel(self._gvm.model)
        self.list_view.setItemDelegate(self._gvm.delegate)
        self.list_view.setViewMode(QListView.ViewMode.IconMode)
        self.list_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.list_view.setMovement(QListView.Movement.Static)
        self.list_view.setUniformItemSizes(True)
        self.list_view.setGridSize(QSize(size + 8, size + 8))
        self.list_view.setSpacing(THUMB["spacing"])
        self.list_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_view.setToolTip("Clic gauche : sélectionner | Clic droit : voir en plein écran")
        layout.addWidget(self.list_view)

        # ── Progression batch ─────────────────────────────────────────────────
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("")
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)

        # ── Prefetch timer ────────────────────────────────────────────────────
        self._prefetch_timer = QTimer()
        self._prefetch_timer.setInterval(100)
        self._prefetch_timer.setSingleShot(True)
        self._prefetch_timer.timeout.connect(self.prefetch_visible)

    def build_search_dock(self, main_window) -> QDockWidget:
        """Construit et retourne le dock de recherche.

        Doit être appelé depuis WorkspaceWidget après construction,
        une fois que main_window est disponible.

        Args:
            main_window: La QMainWindow à laquelle rattacher le dock.

        Returns:
            QDockWidget: Le dock de recherche.
        """
        dock = QDockWidget("Recherche dans la Galerie", main_window)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        dock.setMinimumWidth(220)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # ── Barre de recherche ────────────────────────────────────────────────
        self.search_bar = QLineEdit()
        self.search_bar.setObjectName("search_bar")
        self.search_bar.setPlaceholderText("Rechercher…")
        self.search_bar.setClearButtonEnabled(True)
        layout.addWidget(self.search_bar)

        # ── Actions sous la barre ─────────────────────────────────────────────
        actions_row = QHBoxLayout()
        actions_row.setSpacing(6)

        self.btn_save_search = QPushButton("💾 Sauvegarder")
        self.btn_save_search.setToolTip("Enregistrer la recherche dans l'historique")
        actions_row.addWidget(self.btn_save_search)

        self.checkbox_affinage = QCheckBox("Affinage")
        self.checkbox_affinage.setToolTip("Si activé, les recherches suivantes seront affinées à partir des résultats actuels")
        actions_row.addWidget(self.checkbox_affinage)

        layout.addLayout(actions_row)

        # ── Séparateur ────────────────────────────────────────────────────────
        from PyQt6.QtWidgets import QFrame

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #1f2937;")
        layout.addWidget(sep)

        # ── Arbre de recherche ────────────────────────────────────────────────
        self.tree_widget = TreeViewWidget(self._gvm.search_tree)
        self.tree_widget.signal_node_clicked.connect(self.on_signal_tree_node_clicked)
        layout.addWidget(self.tree_widget)

        layout.addStretch()
        dock.setWidget(content)

        # Raccourci Ctrl+F → focus barre de recherche
        action_search = QAction("Search", self)
        action_search.setShortcut(QKeySequence("Ctrl+F"))
        action_search.triggered.connect(lambda: (dock.setVisible(True), self.search_bar.setFocus()))
        self.addAction(action_search)

        action_zoom_in = QAction("Zoom In", self)
        action_zoom_in.setShortcut(QKeySequence("Ctrl+="))
        action_zoom_in.triggered.connect(self._gvm.zoom_in)

        action_zoom_out = QAction("Zoom Out", self)
        action_zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        action_zoom_out.triggered.connect(self._gvm.zoom_out)

        # Sync bouton ↔ visibilité dock
        dock.visibilityChanged.connect(self.btn_search_dock.setChecked)
        self.btn_search_dock.clicked.connect(dock.setVisible)

        # Connecter les signaux de la barre de recherche galerie
        self.search_bar.textChanged.connect(self._gvm.schedule_search)
        self.btn_save_search.clicked.connect(self._gvm.save_search)
        self.checkbox_affinage.toggled.connect(self._gvm.set_affinage)

        self._search_dock = dock
        return dock

    def connect_vm(self):
        """Connect la view au viewmodel."""
        # View → ViewModel
        self.btn_batch.clicked.connect(self._avm.start)
        self.btn_cancel.clicked.connect(self.on_cancel)
        self.list_view.clicked.connect(self.on_item_clicked)
        self.list_view.customContextMenuRequested.connect(self.on_right_click)
        self.list_view.verticalScrollBar().valueChanged.connect(lambda: self._prefetch_timer.start())

        # ViewModel → View
        self._gvm.signal_cell_size_changed.connect(self.on_signal_cell_size_changed)
        self._gvm.signal_saved_search.connect(self.on_signal_search_saved)

        self._avm.signal_started.connect(self.on_batch_started)
        self._avm.signal_progress.connect(self.on_batch_progress)
        self._avm.signal_finished.connect(self.on_batch_finished)

    # ── Slots internes ─────────────────────────────────────────────────────

    def on_signal_search_saved(self):
        """Rafraîchit l'arbre après sauvegarde d'une recherche."""
        if hasattr(self, "tree_widget"):
            self.tree_widget.refresh()

    def on_signal_tree_node_clicked(self, node_id: str):
        """Navigue vers le noeud cliqué dans l'arbre.

        Args:
            node_id (str): Identifiant du noeud.
        """
        node = self._gvm.search_tree.get_node(node_id)
        if node is None:
            return
        self._gvm.search_tree.set_current(node_id)
        if hasattr(node, "query") and hasattr(self, "search_bar"):
            self.search_bar.setText(node.query)
        self.tree_widget.refresh()

    # ── Slots View → ViewModel ─────────────────────────────────────────────

    def on_item_clicked(self, index: QModelIndex):
        """Selectionne l'image.

        Args:
            index (QModelIndex): Index de l'image."""
        img_name = index.data(IMG_NAME_ROLE)
        if img_name:
            self._gvm.select_image(img_name)

    def on_right_click(self, pos: QPoint):
        """Affiche l'image en plein ecran.

        Args:
            pos (QPoint): Position du clic."""
        index = self.list_view.indexAt(pos)
        if not index.isValid():
            return
        img_name = index.data(IMG_NAME_ROLE)
        if not img_name or not self._gvm.current_folder:
            return
        import os

        pixmap = QPixmap(os.path.join(self._gvm.current_folder, img_name))
        if not pixmap.isNull():
            dlg = FullscreenDialog(pixmap, img_name, self)
            dlg.exec()

    def on_cancel(self):
        """Annule le batch."""
        self._avm.cancel()
        self.btn_cancel.setEnabled(False)
        self.progress_label.setText("⛔ Annulation…")

    # ── Slots ViewModel → View ─────────────────────────────────────────────

    def on_signal_cell_size_changed(self, size: int):
        """Redimensionne la gallery.

        Args:
            size (int): Nouvelle taille des cellules."""
        self.list_view.setGridSize(QSize(size + 8, size + 8))
        self.list_view.doItemsLayout()
        QTimer.singleShot(50, self.prefetch_visible)

    def on_batch_started(self, total: int):
        """Démarre le batch.

        Args:
            total (int): Nombre d'images à traiter."""

        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.progress_label.setText(f"0 / {total} — en attente…")
        self.progress_label.setVisible(True)
        self.btn_batch.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(True)

    def on_batch_progress(self, done: int, total: int, label: str):
        """Callback pour la progression du batch.

        Args:
            done (int): Nombre d'images traitées.
            total (int): Nombre d'images à traiter.
            label (str): Label à afficher."""
        self.progress_bar.setValue(done)
        self.progress_label.setText(f"{done} / {total} — {label}")

    def on_batch_finished(self, cancelled: bool):
        """Callback pour la fin du batch.

        Args:
            cancelled (bool): True si le batch a été annulé, False sinon.
        """
        total = self.progress_bar.maximum()
        self.progress_label.setText("⛔ Annulé" if cancelled else f"✅ Terminé — {total} images traitées")
        self.btn_batch.setEnabled(True)
        self.btn_cancel.setVisible(False)
        QTimer.singleShot(
            4000,
            lambda: (
                self.progress_bar.setVisible(False),
                self.progress_label.setVisible(False),
            ),
        )

    # ── Prefetch ──────────────────────────────────────────────────────────────

    def prefetch_visible(self):
        """Précharge les images visibles."""
        vp = self.list_view.viewport()
        rect = vp.rect()
        size = self._gvm.cell_size
        extra = PREFETCH_ROWS * (size + 8)
        rect.setHeight(rect.height() + extra)

        total = self._gvm.model.rowCount()
        if total == 0:
            return

        first = self.list_view.indexAt(vp.rect().topLeft())
        start = max(0, first.row() if first.isValid() else 0)

        for row in range(start, total):
            mi = self._gvm.model.index(row)
            if self.list_view.visualRect(mi).top() > rect.bottom():
                break
            self._gvm.scheduler.submit(self._gvm.model.image_at(row))
