"""
views/map_widget.py

Onglet carte 2D sémantique.
Toute la logique de calcul est dans MapViewModel.
Ce fichier ne contient que les widgets Qt et leur câblage.
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QWheelEvent
from PyQt6.QtWidgets import (
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
        self._vm.compute_started.connect(self.on_compute_started)
        self._vm.compute_progress.connect(self._lbl_status.setText)
        self._vm.compute_finished.connect(self.on_finished)
        self._vm.cluster_named.connect(self.on_cluster_named)
        self._vm.compute_error.connect(self.on_error)
        self._vm.params_changed.connect(self._settings_dock.set_params)

        QTimer.singleShot(500, self._vm.autoload)

    # ── UI ────────────────────────────────────────────────────────────────────

    def build_ui(self):
        """Construit le widget."""
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        bar = QHBoxLayout()

        self._btn_compute = QPushButton("Calculer la carte")
        self._btn_compute.clicked.connect(self._vm.compute)
        bar.addWidget(self._btn_compute)

        self._btn_settings = QPushButton("⚙ Paramètres")
        self._btn_settings.setCheckable(True)
        self._btn_settings.clicked.connect(lambda checked: self._settings_dock.setVisible(checked))
        bar.addWidget(self._btn_settings)

        self._btn_reset_filter = QPushButton("Réinitialiser le filtre")
        self._btn_reset_filter.clicked.connect(self.reset_opacity)
        self._btn_reset_filter.setEnabled(False)
        bar.addWidget(self._btn_reset_filter)

        self._lbl_status = QLabel("Chargement en cours…")
        self._lbl_status.setStyleSheet("color: gray; font-size: 12px;")
        bar.addWidget(self._lbl_status, stretch=1)

        root.addLayout(bar)

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

    # ── Slots ─────────────────────────────────────────────────────────────────

    def on_compute_started(self):
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

    def on_cluster_named(self, cid: int, name: str):
        """Callback lors du nommage.

        Args:
            cid (int): Identifiant du cluster
            name (str): Nom du cluster"""
        self._cluster_names[cid] = name
        self.refresh_legend_names()

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
        for node in self._nodes.values():
            node.setOpacity(1.0 if node.cluster == cluster_id else 0.12)
        if cluster_id in self._cluster_rects:
            self._view.zoom_to_rect(self._cluster_rects[cluster_id])
        self._btn_reset_filter.setEnabled(True)

    def reset_opacity(self):
        """Reset l'opacité des nodes."""
        for node in self._nodes.values():
            node.setOpacity(1.0)
        self._view.fitInView(QRectF(0, 0, 800, 800), Qt.AspectRatioMode.KeepAspectRatio)

    # ── API externe ───────────────────────────────────────────────────────────

    def on_image_selected(self, img_name: str):
        """Highlight un node.

        Args:
            img_name (str): Nom de l'image."""
        if self._nodes:
            self.highlight(img_name)
