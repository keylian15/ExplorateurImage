"""
Onglet de visualisation de la carte 2D sémantique.

Ce widget représente l'interface graphique de la projection 2D des images après réduction
dimensionnelle (UMAP) et clustering (HDBSCAN). Il permet de visualiser les images sous forme
de points colorés regroupés par clusters, d'interagir avec la scène (sélection, zoom, filtrage)
et d'explorer les regroupements sémantiques.

Toute la logique de calcul, de clustering et de transformation des données est entièrement
déléguée au MapViewModel. Ce composant se limite à l'affichage graphique et à la gestion
des interactions utilisateur.

Contenu :
 - Zone de contrôle (lancement du calcul, paramètres, reset filtre, statut)
 - Vue graphique interactive (QGraphicsView) représentant les points 2D
 - Légende dynamique des clusters avec noms et effectifs
 - Dock de paramètres (UMAP / HDBSCAN)
 - Dock de recherche avec barre, arbre d'historique, bouton sauvegarde et affinage
 - Interaction directe avec les points (hover, sélection, centrage)
 - Filtrage visuel des clusters et zoom contextuel
 - Mise à jour dynamique des noms de clusters

Responsabilités :
 1. Afficher la projection 2D des images sous forme de points interactifs
 2. Représenter visuellement les clusters avec une palette de couleurs dédiée
 3. Permettre la sélection et la mise en surbrillance d'une image
 4. Gérer les interactions utilisateur (zoom, clic, hover, filtrage)
 5. Afficher et mettre à jour la légende des clusters dynamiquement
 6. Permettre l'isolation visuelle d'un cluster avec zoom automatique
 7. Relayer les actions utilisateur vers le ViewModel sans logique métier
 8. Synchroniser l'affichage avec les résultats du calcul du ViewModel
 9. Filtrer les noeuds visibles selon une requête sémantique
 10. Gérer l'arbre d'historique des recherches avec affinage
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QAction, QBrush, QColor, QKeySequence, QPainter, QPen, QWheelEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from styles import dot_color_style, dot_label_style, legend_label_style, no_border_style
from viewmodels.map_vm import MapViewModel
from views.tree_widget import TreeViewWidget

# ── Palette ───────────────────────────────────────────────────────────────────
_CLUSTER_COLORS = [
    "#5488C8",
    "#4CB87A",
    "#E07B4A",
    "#A86EC9",
    "#D95A5A",
    "#4BBEC2",
    "#D4A82A",
    "#B05070",
    "#6DA87C",
    "#8888CC",
    "#CC8844",
    "#44AACC",
    "#AA4488",
    "#88CC44",
    "#CC4444",
]
_NOISE_COLOR = "#888888"
_SELECT_COLOR = "#FFFFFF"
_POINT_RADIUS = 1
_HOVER_RADIUS = 0.5


# ═════════════════════════════════════════════════════════════════════════════
#  Nœud interactif
# ═════════════════════════════════════════════════════════════════════════════


class MapNode(QGraphicsEllipseItem):
    def __init__(self, img_name: str, cluster: int, color: QColor, callback_select):
        """
        Args:
            img_name (str): Nom de l'image
            cluster (int): Numéro du cluster
            color (QColor): Couleur du cluster
            callback_select (function): Fonction de sélection
        """
        r = _POINT_RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r)
        self.img_name = img_name
        self.cluster = cluster
        self.setBrush(QBrush(color))
        self.setPen(QPen(Qt.GlobalColor.transparent))
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(img_name)
        self.setZValue(1)
        self._cb_sel = callback_select

    def hoverEnterEvent(self, event):
        """Surcharge l'évènement de survol

        Args:
            event (QGraphicsSceneHoverEvent): Evènement de survol
        """
        r = _HOVER_RADIUS
        self.setRect(-r, -r, 2 * r, 2 * r)
        self.setPen(QPen(QColor(_SELECT_COLOR), 2))
        self.setZValue(10)
        QToolTip.showText(event.screenPos(), self.img_name)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        """Surcharge l'évènement de survol

        Args:
            event (QGraphicsSceneHoverEvent): Evènement de survol
        """
        r = _POINT_RADIUS
        self.setRect(-r, -r, 2 * r, 2 * r)
        self.setPen(QPen(QColor(_SELECT_COLOR), 2) if self.isSelected() else QPen(Qt.GlobalColor.transparent))
        self.setZValue(5 if self.isSelected() else 1)
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        """Surcharge l'évènement de clic

        Args:
            event (QGraphicsSceneMouseEvent): Evènement de clic
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self._cb_sel(self.img_name)
        super().mousePressEvent(event)

    def mark_selected(self, selected: bool):
        """Marque selectionné le noeud.

        Args:
            selected (bool): True si le noeud est sélectionné"""
        r = _POINT_RADIUS
        self.setRect(-r, -r, 2 * r, 2 * r)
        self.setPen(QPen(QColor(_SELECT_COLOR), 2) if selected else QPen(Qt.GlobalColor.transparent))
        self.setZValue(5 if selected else 1)


# ═════════════════════════════════════════════════════════════════════════════
#  Vue zoomable
# ═════════════════════════════════════════════════════════════════════════════


class MapView(QGraphicsView):
    ZOOM_FACTOR = 1.15

    def __init__(self, scene: QGraphicsScene, parent=None):
        """
        Args:
            scene (QGraphicsScene): Scene à afficher.
            parent (QWidget, optional): Parent. Defaults to None.
        """
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def wheelEvent(self, event: QWheelEvent):
        """Gere l'évènement de roulette de souris.

        Args:
            event (QWheelEvent): Evènement de roulette de souris.
        """
        factor = self.ZOOM_FACTOR if event.angleDelta().y() > 0 else 1 / self.ZOOM_FACTOR
        self.scale(factor, factor)

    def zoom_to_rect(self, rect: QRectF, margin: float = 60.0):
        """Zoom à une zone.

        Args:
            rect (QRectF): Zone à zoomer.
            margin (float, optional): Marge. Defaults to 60.0.
        """
        padded = rect.adjusted(-margin, -margin, margin, margin)
        self.fitInView(padded, Qt.AspectRatioMode.KeepAspectRatio)

    def reset_zoom(self):
        """Réinitialise le zoom."""
        self.resetTransform()


# ═════════════════════════════════════════════════════════════════════════════
#  Dock paramètres (View pure)
# ═════════════════════════════════════════════════════════════════════════════


class SettingsDock(QDockWidget):
    def __init__(self, params: dict[str, int], on_apply, parent=None):
        """
        Args:
            params (dict[str, int]): Paramètres de la carte.
            on_apply (function): Fonction à appeler lors de l'application des paramètres.
            parent (QWidget, optional): Parent. Defaults to None.
        """

        super().__init__("Paramètres de la carte", parent)
        self.on_apply = on_apply
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.BottomDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable | QDockWidget.DockWidgetFeature.DockWidgetClosable)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(8)

        self._spin_neighbors = QSpinBox()
        self._spin_neighbors.setRange(2, 200)
        self._spin_neighbors.setValue(params["umap_n_neighbors"])
        self._spin_neighbors.setToolTip("Petit → détail local. Grand → vue globale.")
        form.addRow("UMAP n_neighbors", self._spin_neighbors)

        self._spin_min_dist = QDoubleSpinBox()
        self._spin_min_dist.setRange(0.0, 1.0)
        self._spin_min_dist.setSingleStep(0.05)
        self._spin_min_dist.setDecimals(2)
        self._spin_min_dist.setValue(params["umap_min_dist"])
        self._spin_min_dist.setToolTip("0.0 → clusters serrés. 1.0 → carte diffuse.")
        form.addRow("UMAP min_dist", self._spin_min_dist)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)

        self._spin_hdbscan = QSpinBox()
        self._spin_hdbscan.setRange(2, 500)
        self._spin_hdbscan.setValue(params["hdbscan_min_cluster"])
        self._spin_hdbscan.setToolTip("Petit → beaucoup de clusters. Grand → clusters stables.")
        form.addRow("HDBSCAN min_cluster", self._spin_hdbscan)

        layout.addLayout(form)
        layout.addWidget(sep)

        btn = QPushButton("Appliquer et recalculer")
        btn.clicked.connect(self.apply)
        layout.addWidget(btn)
        layout.addStretch()

        self.setWidget(content)
        self.setMinimumWidth(240)

    def apply(self):
        """Applique les paramètres."""
        self.on_apply(self.current_params())

    def current_params(self) -> dict[str, int]:
        """Renvoi les parametres actuels.

        Returns:
            dict[str, int]: Les parametres actuels."""
        return {
            "umap_n_neighbors": self._spin_neighbors.value(),
            "umap_min_dist": self._spin_min_dist.value(),
            "hdbscan_min_cluster": self._spin_hdbscan.value(),
        }

    def set_params(self, params: dict[str, int]):
        """Change les parametres.

        Args:
            params (dict[str, int]): Les parametres."""
        self._spin_neighbors.setValue(params["umap_n_neighbors"])
        self._spin_min_dist.setValue(params["umap_min_dist"])
        self._spin_hdbscan.setValue(params["hdbscan_min_cluster"])


# ═════════════════════════════════════════════════════════════════════════════
#  Onglet carte 2D
# ═════════════════════════════════════════════════════════════════════════════


class MapTab(QWidget):
    def __init__(self, map_vm: MapViewModel, main_window, parent=None):
        """
        Args:
            map_vm (MapViewModel): Le view model de la carte.
            main_window (MainWindow): La fenetre principale.
            parent (QWidget, optional): Le parent. Defaults to None.
        """

        super().__init__(parent)
        self._vm = map_vm
        self._main_window = main_window
        self._nodes: dict[str, MapNode] = {}
        self._current_selected: str | None = None
        self._cluster_rects: dict[int, QRectF] = {}
        self._legend_labels: dict[int, QLabel] = {}
        self._cluster_names: dict[int, str] = {}
        # État du filtre actif : "cluster" | "search" | None
        self._active_filter: str | None = None
        # Dock recherche (construit depuis workspace_widget)
        self._search_dock: QDockWidget | None = None

        self.build_ui()

        # Dock paramètres
        self._settings_dock = SettingsDock(
            self._vm.params,
            on_apply=self._vm.apply_params,
            parent=main_window,
        )
        main_window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._settings_dock)
        self._settings_dock.setVisible(False)
        self._settings_dock.visibilityChanged.connect(lambda v: self._btn_settings.setChecked(v))

        # Câblage ViewModel → View
        self._vm.signal_compute_started.connect(self.on_signal_compute_started)
        self._vm.signal_compute_progress.connect(self._lbl_status.setText)
        self._vm.signal_compute_finished.connect(self.on_finished)
        self._vm.signal_cluster_named.connect(self.on_cluster_named)
        self._vm.signal_compute_error.connect(self.on_error)
        self._vm.signal_params_changed.connect(self._settings_dock.set_params)
        self._vm.signal_search_results_changed.connect(self.on_search_results)

        QTimer.singleShot(500, self._vm.autoload)

    # ── UI ────────────────────────────────────────────────────────────────────

    def build_ui(self):
        """Construit le widget."""
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Barre de contrôle ─────────────────────────────────────────────────
        bar = QHBoxLayout()

        self._btn_compute = QPushButton("Calculer la carte")
        self._btn_compute.clicked.connect(self._vm.compute)
        bar.addWidget(self._btn_compute)

        self._btn_settings = QPushButton("⚙ Paramètres")
        self._btn_settings.setCheckable(True)
        self._btn_settings.clicked.connect(lambda checked: self._settings_dock.setVisible(checked))
        bar.addWidget(self._btn_settings)

        self._btn_reset_filter = QPushButton("Réinitialiser le filtre")
        self._btn_reset_filter.clicked.connect(self.reset_all_filters)
        self._btn_reset_filter.setEnabled(False)
        bar.addWidget(self._btn_reset_filter)

        # Bouton pour afficher/masquer le dock de recherche
        self._btn_search_dock = QPushButton("🔍 Recherche")
        self._btn_search_dock.setCheckable(True)
        self._btn_search_dock.setToolTip("Afficher / masquer le panneau de recherche")
        bar.addWidget(self._btn_search_dock)

        bar.addStretch()

        self._lbl_status = QLabel("Chargement en cours…")
        self._lbl_status.setStyleSheet("color: gray; font-size: 12px;")
        bar.addWidget(self._lbl_status)

        root.addLayout(bar)

        # ── Zone carte + légende ──────────────────────────────────────────────
        h = QHBoxLayout()
        h.setSpacing(8)

        self._scene = QGraphicsScene(self)
        self._view = MapView(self._scene, self)
        self._view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        h.addWidget(self._view, stretch=5)

        legend_container = QWidget()
        legend_container.setFixedWidth(180)
        self._legend_layout = QVBoxLayout(legend_container)
        self._legend_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._legend_layout.setSpacing(4)
        self._legend_layout.setContentsMargins(4, 4, 4, 4)

        lbl_leg = QLabel("Clusters")
        lbl_leg.setStyleSheet(legend_label_style())
        self._legend_layout.addWidget(lbl_leg)

        legend_scroll = QScrollArea()
        legend_scroll.setWidget(legend_container)
        legend_scroll.setWidgetResizable(True)
        legend_scroll.setFixedWidth(195)
        legend_scroll.setStyleSheet(no_border_style())
        h.addWidget(legend_scroll)

        root.addLayout(h)

    def build_search_dock(self, main_window) -> QDockWidget:
        """Construit et retourne le dock de recherche de la carte.

        Doit être appelé depuis WorkspaceWidget après construction,
        une fois que main_window est disponible.

        Args:
            main_window: La QMainWindow à laquelle rattacher le dock.

        Returns:
            QDockWidget: Le dock de recherche.
        """
        dock = QDockWidget("Recherche sur la Carte", main_window)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        dock.setMinimumWidth(220)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # ── Barre de recherche ────────────────────────────────────────────────
        self.dock_search_bar = QLineEdit()
        self.dock_search_bar.setObjectName("search_bar")
        self.dock_search_bar.setPlaceholderText("Rechercher…")
        self.dock_search_bar.setClearButtonEnabled(True)
        layout.addWidget(self.dock_search_bar)

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
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #1f2937;")
        layout.addWidget(sep)

        # ── Arbre de recherche ────────────────────────────────────────────────
        self.tree_widget = TreeViewWidget(self._vm.search_tree)
        self.tree_widget.signal_node_clicked.connect(self.on_signal_tree_node_clicked)
        layout.addWidget(self.tree_widget)

        layout.addStretch()
        dock.setWidget(content)

        # Raccourci Ctrl+F → focus dock_search_bar quand dock visible
        action_focus = QAction("MapSearch", self)
        action_focus.setShortcut(QKeySequence("Ctrl+F"))
        action_focus.triggered.connect(lambda: (dock.setVisible(True), self.dock_search_bar.setFocus()))
        self.addAction(action_focus)

        # Sync bouton ↔ visibilité dock
        dock.visibilityChanged.connect(self._btn_search_dock.setChecked)
        self._btn_search_dock.clicked.connect(dock.setVisible)

        # Connexions vers le ViewModel
        self.dock_search_bar.textChanged.connect(self._on_dock_search_text_changed)
        self.btn_save_search.clicked.connect(self._vm.save_search)
        self.checkbox_affinage.toggled.connect(self._vm.set_affinage)

        # Signal sauvegarde → refresh arbre
        self._vm.signal_saved_search.connect(self.on_signal_search_saved)

        self._search_dock = dock
        return dock

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
        node = self._vm.search_tree.get_node(node_id)
        if node is None:
            return
        self._vm.search_tree.set_current(node_id)
        if hasattr(node, "query") and hasattr(self, "dock_search_bar"):
            self.dock_search_bar.blockSignals(True)
            self.dock_search_bar.setText(node.query)
            self.dock_search_bar.blockSignals(False)
            self._vm.schedule_search(node.query)
        if hasattr(self, "tree_widget"):
            self.tree_widget.refresh()

    def _on_dock_search_text_changed(self, text: str):
        """Relaie le texte du dock au ViewModel.

        Args:
            text (str): Texte saisi dans le dock.
        """
        if not text.strip():
            self._vm.clear_search()
        else:
            self._vm.schedule_search(text)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def on_signal_compute_started(self):
        """Callback pour tout nettoyer"""
        self._btn_compute.setEnabled(False)
        self._scene.clear()
        self._nodes.clear()
        self._cluster_rects.clear()
        self._btn_reset_filter.setEnabled(False)

    def on_error(self, msg: str):
        """Callback pour afficher un message d'erreur

        Args:
            msg (str): Message d'erreur"""
        self._lbl_status.setText(f"❌ {msg}")
        self._btn_compute.setEnabled(True)

    def on_finished(self, points: list[tuple[float, float]], labels: list[int], names: list[str], cluster_names: dict[int, str]):
        """Callback pour afficher les clusters

        Args:
            points (list[tuple[float, float]]): Coordonnées des points
            labels (list[int]): Labels des clusters
            names (list[str]): Noms des images
            cluster_names (dict[int, str]): Noms des clusters
        """
        self.build_scene(points, labels, names, cluster_names)
        n_clusters = len({label for label in labels if label >= 0})
        n_noise = labels.count(-1)
        self._lbl_status.setText(f"{len(names)} images — {n_clusters} clusters" + (f" — {n_noise} bruit" if n_noise else ""))
        self._btn_compute.setEnabled(True)
        self._btn_reset_filter.setEnabled(True)
        if self._current_selected:
            self.highlight(self._current_selected)
        # Rejoue la recherche en cours si elle existait avant le recalcul
        if hasattr(self, "dock_search_bar") and self.dock_search_bar.text().strip():
            self._vm.schedule_search(self.dock_search_bar.text())

    def on_cluster_named(self, cid: int, name: str):
        """Callback lors du nommage.

        Args:
            cid (int): Identifiant du cluster
            name (str): Nom du cluster"""
        self._cluster_names[cid] = name
        self.refresh_legend_names()

    def on_search_results(self, matching_names: list[str]):
        """Applique le filtre de recherche sur les noeuds.

        Args:
            matching_names (list[str]): Noms des images correspondant à la requête.
                                        Liste vide = afficher tout.
        """
        if not self._nodes:
            return

        if not matching_names:
            # Requête vide : réafficher tout (sauf si un filtre cluster est actif)
            if self._active_filter == "search":
                self._active_filter = None
                self._btn_reset_filter.setEnabled(bool(self._nodes))
                for node in self._nodes.values():
                    node.setOpacity(1.0)
                self._view.fitInView(QRectF(0, 0, 800, 800), Qt.AspectRatioMode.KeepAspectRatio)
            return

        # Filtre actif : mettre en valeur les résultats
        self._active_filter = "search"
        matching_set = set(matching_names)
        count = 0
        for name, node in self._nodes.items():
            if name in matching_set:
                node.setOpacity(1.0)
                node.setZValue(2)
                count += 1
            else:
                node.setOpacity(0.08)
                node.setZValue(0)

        self._btn_reset_filter.setEnabled(True)

        # Zoom automatique sur la bounding box des résultats trouvés
        if count > 0:
            matching_nodes = [self._nodes[n] for n in matching_names if n in self._nodes]
            xs = [node.pos().x() for node in matching_nodes]
            ys = [node.pos().y() for node in matching_nodes]
            if xs and ys:
                rect = QRectF(min(xs), min(ys), max(xs) - min(xs) or 1, max(ys) - min(ys) or 1)
                self._view.zoom_to_rect(rect, margin=80.0)

    # ── Scène ─────────────────────────────────────────────────────────────────

    def build_scene(self, points: list[tuple[float, float]], labels: list[int], names: list[str], cluster_names: dict[int, str]):
        """Construit la scène.

        Args:
            points (list[tuple[float, float]]): Points
            labels (list[int]): Labels
            names (list[str]): Noms des images
            cluster_names (dict[int, str]): Noms des clusters
        """
        self._scene.clear()
        self._nodes.clear()
        self._cluster_rects.clear()
        self.clear_legend()
        self._cluster_names = dict(cluster_names)
        self._active_filter = None

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        rx = (max(xs) - min(xs)) or 1
        ry = (max(ys) - min(ys)) or 1
        W = H = 800.0

        def sp(px, py):
            """Renvoi les coordonnées de la scène."""
            return (px - min(xs)) / rx * W, (py - min(ys)) / ry * H

        unique = sorted(set(labels))
        color_map: dict[int, QColor] = {}
        pi = 0
        for c in unique:
            color_map[c] = QColor(_NOISE_COLOR) if c == -1 else QColor(_CLUSTER_COLORS[pi % len(_CLUSTER_COLORS)])
            if c != -1:
                pi += 1

        cluster_points: dict[int, list] = {}
        for name, (px, py), label in zip(names, points, labels, strict=False):
            sx, sy = sp(px, py)
            node = MapNode(name, label, color_map[label], callback_select=self.on_node_clicked)
            node.setPos(sx, sy)
            self._scene.addItem(node)
            self._nodes[name] = node
            cluster_points.setdefault(label, []).append((sx, sy))

        for cid, pts in cluster_points.items():
            xs2 = [p[0] for p in pts]
            ys2 = [p[1] for p in pts]
            self._cluster_rects[cid] = QRectF(
                min(xs2),
                min(ys2),
                max(xs2) - min(xs2) or 1,
                max(ys2) - min(ys2) or 1,
            )

        self._view.setScene(self._scene)
        self._view.reset_zoom()
        self._view.scale(0.9, 0.9)
        self._view.fitInView(
            QRectF(0, 0, W, H).adjusted(-50, -50, 50, 50),
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        self.build_legend(color_map, labels, cluster_names)

    # ── Légende ───────────────────────────────────────────────────────────────

    def clear_legend(self):
        """Nettoie la légende."""
        self._legend_labels.clear()
        while self._legend_layout.count() > 1:
            item = self._legend_layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()

    def build_legend(self, color_map: dict[int, QColor], labels: list[int], cluster_names: dict[int, str]):
        """Construit la légende.

        Args:
            color_map (dict[int, QColor]): Carte des couleurs.
            labels (list[int]): Labels des clusters.
            cluster_names (dict[int, str]): Nom des clusters.
        """
        from collections import Counter

        counts = Counter(labels)
        for cid in sorted(color_map.keys()):
            label_text = cluster_names.get(cid, f"Cluster {cid}")
            display = f"{label_text} ({counts.get(cid, 0)})"

            row = QHBoxLayout()
            dot = QLabel()
            dot.setFixedSize(12, 12)
            dot.setStyleSheet(dot_color_style(color_map[cid]))
            row.addWidget(dot)

            lbl = QLabel(display)
            lbl.setStyleSheet(dot_label_style())
            lbl.setWordWrap(True)
            lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            lbl.setToolTip("Clic : isoler et zoomer sur ce cluster")
            lbl.mousePressEvent = lambda _e, c=cid: self.filter_and_zoom_cluster(c)
            row.addWidget(lbl, stretch=1)
            self._legend_labels[cid] = lbl

            container = QWidget()
            container.setLayout(row)
            self._legend_layout.addWidget(container)

    def refresh_legend_names(self):
        """Rafraichi la légende."""
        for cid, lbl in self._legend_labels.items():
            base = self._cluster_names.get(cid, f"Cluster {cid}")
            text = lbl.text()
            if "(" in text:
                count_part = text.split("(")[-1]
                lbl.setText(f"{base} ({count_part}")

    # ── Interactions ──────────────────────────────────────────────────────────

    def on_node_clicked(self, img_name: str):
        """Highlight le node lorsqu'on clique dessus.

        Args:
            img_name (str): Nom de l'image."""
        self.highlight(img_name)
        self._vm._gallery_vm.select_image(img_name)

    def highlight(self, img_name: str):
        """Highlight un node.

        Args:
            img_name (str): Nom de l'image."""
        if self._current_selected and self._current_selected in self._nodes:
            self._nodes[self._current_selected].mark_selected(False)
        self._current_selected = img_name
        if img_name in self._nodes:
            node = self._nodes[img_name]
            node.mark_selected(True)
            self._view.centerOn(node)

    def filter_and_zoom_cluster(self, cluster_id: int):
        """Filtre et zoom sur un cluster.

        Args:
            cluster_id (int): ID du cluster.
        """
        # Vider la recherche du dock si elle était active
        if hasattr(self, "dock_search_bar"):
            self.dock_search_bar.blockSignals(True)
            self.dock_search_bar.clear()
            self.dock_search_bar.blockSignals(False)

        self._active_filter = "cluster"
        for node in self._nodes.values():
            node.setOpacity(1.0 if node.cluster == cluster_id else 0.12)
            node.setZValue(2 if node.cluster == cluster_id else 0)
        if cluster_id in self._cluster_rects:
            self._view.zoom_to_rect(self._cluster_rects[cluster_id])
        self._btn_reset_filter.setEnabled(True)

    def reset_all_filters(self):
        """Réinitialise tous les filtres (recherche + cluster)."""
        if hasattr(self, "dock_search_bar"):
            self.dock_search_bar.blockSignals(True)
            self.dock_search_bar.clear()
            self.dock_search_bar.blockSignals(False)

        self._vm.clear_search()

        self._active_filter = None
        self._btn_reset_filter.setEnabled(bool(self._nodes))

        for node in self._nodes.values():
            node.setOpacity(1.0)
            node.setZValue(1)
        self._view.fitInView(QRectF(0, 0, 800, 800), Qt.AspectRatioMode.KeepAspectRatio)

    # ── API externe ───────────────────────────────────────────────────────────

    def on_image_selected(self, img_name: str):
        """Highlight un node.

        Args:
            img_name (str): Nom de l'image."""
        if self._nodes:
            self.highlight(img_name)

    def hide_search_dock(self):
        """Masque le dock de recherche de la carte."""
        if self._search_dock:
            self._search_dock.setVisible(False)
