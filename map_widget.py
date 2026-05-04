from __future__ import annotations
import json
import os
import pickle

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGraphicsView, QGraphicsScene, QGraphicsEllipseItem,
    QGraphicsItem, QScrollArea, QSizePolicy, QToolTip,
    QDockWidget, QDoubleSpinBox, QSpinBox, QFormLayout, QFrame,
)
from PyQt6.QtGui import QBrush, QColor, QPen, QWheelEvent, QPainter
from PyQt6.QtCore import Qt, QRectF, QTimer

from workers import MapWorker


# ── Palette ──────────────────────────────────────────────────
_CLUSTER_COLORS = [
    "#5488C8", "#4CB87A", "#E07B4A", "#A86EC9", "#D95A5A",
    "#4BBEC2", "#D4A82A", "#B05070", "#6DA87C", "#8888CC",
    "#CC8844", "#44AACC", "#AA4488", "#88CC44", "#CC4444",
]
_NOISE_COLOR = "#888888"
_SELECT_COLOR = "#FFFFFF"
_POINT_RADIUS = 1
_HOVER_RADIUS = 0.5

# ── Config ───────────────────────────────────────────────────
_CONFIG_KEY = "map_params"
_CONFIG_FILE = "config.json"
_MAP_CACHE_FILE = "map_cache.pkl"
_DEFAULTS = {
    "umap_n_neighbors":    15,
    "umap_min_dist":       0.1,
    "hdbscan_min_cluster": 15,
}


# ═════════════════════════════════════════════════════════════
#  Config helpers
# ═════════════════════════════════════════════════════════════

def _load_map_params() -> dict:
    if os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f).get(_CONFIG_KEY, {})
            return {
                "umap_n_neighbors":    int(saved.get("umap_n_neighbors",    _DEFAULTS["umap_n_neighbors"])),
                "umap_min_dist":       float(saved.get("umap_min_dist",     _DEFAULTS["umap_min_dist"])),
                "hdbscan_min_cluster": int(saved.get("hdbscan_min_cluster", _DEFAULTS["hdbscan_min_cluster"])),
            }
        except Exception:
            pass
    return dict(_DEFAULTS)


def _save_map_params(params: dict):
    cfg = {}
    if os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
    cfg[_CONFIG_KEY] = params
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# ═════════════════════════════════════════════════════════════
#  Nœud interactif
# ═════════════════════════════════════════════════════════════

class _MapNode(QGraphicsEllipseItem):
    def __init__(self, img_name: str, cluster: int,
                 color: QColor, callback_select):
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
        r = _HOVER_RADIUS
        self.setRect(-r, -r, 2 * r, 2 * r)
        self.setPen(QPen(QColor(_SELECT_COLOR), 2))
        self.setZValue(10)
        QToolTip.showText(event.screenPos(), self.img_name)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        r = _POINT_RADIUS
        self.setRect(-r, -r, 2 * r, 2 * r)
        self.setPen(
            QPen(QColor(_SELECT_COLOR), 2) if self.isSelected()
            else QPen(Qt.GlobalColor.transparent)
        )
        self.setZValue(5 if self.isSelected() else 1)
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._cb_sel(self.img_name)
        super().mousePressEvent(event)

    def mark_selected(self, selected: bool):
        r = _POINT_RADIUS
        self.setRect(-r, -r, 2 * r, 2 * r)
        self.setPen(
            QPen(QColor(_SELECT_COLOR), 2) if selected
            else QPen(Qt.GlobalColor.transparent)
        )
        self.setZValue(5 if selected else 1)


# ═════════════════════════════════════════════════════════════
#  Vue zoomable
# ═════════════════════════════════════════════════════════════

class _MapView(QGraphicsView):
    ZOOM_FACTOR = 1.15

    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("background: transparent; border: none;")

    def wheelEvent(self, event: QWheelEvent):
        factor = self.ZOOM_FACTOR if event.angleDelta().y() > 0 else 1 / \
            self.ZOOM_FACTOR
        self.scale(factor, factor)
    
    def zoom_to_rect(self, rect: QRectF, margin: float = 60.0):
        """Zoome et centre la vue sur un QRectF de la scène avec une marge."""
        padded = rect.adjusted(-margin, -margin, margin, margin)
        self.fitInView(padded, Qt.AspectRatioMode.KeepAspectRatio)

    def reset_zoom(self):
        self.resetTransform()

# ═════════════════════════════════════════════════════════════
#  Dock paramètres
# ═════════════════════════════════════════════════════════════

class _SettingsDock(QDockWidget):
    def __init__(self, params: dict, on_apply, parent=None):
        super().__init__("Paramètres de la carte", parent)
        self.on_apply = on_apply
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea |
            Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(8)

        self._spin_neighbors = QSpinBox()
        self._spin_neighbors.setRange(2, 200)
        self._spin_neighbors.setValue(params["umap_n_neighbors"])
        self._spin_neighbors.setToolTip(
            "Nombre de voisins UMAP.\nPetit -> détail local.\nGrand -> vue globale.")
        form.addRow("UMAP n_neighbors", self._spin_neighbors)

        self._spin_min_dist = QDoubleSpinBox()
        self._spin_min_dist.setRange(0.0, 1.0)
        self._spin_min_dist.setSingleStep(0.05)
        self._spin_min_dist.setDecimals(2)
        self._spin_min_dist.setValue(params["umap_min_dist"])
        self._spin_min_dist.setToolTip(
            "Espacement minimal UMAP.\n0.0 -> clusters serrés.\n1.0 -> carte diffuse.")
        form.addRow("UMAP min_dist", self._spin_min_dist)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)

        self._spin_hdbscan = QSpinBox()
        self._spin_hdbscan.setRange(2, 500)
        self._spin_hdbscan.setValue(params["hdbscan_min_cluster"])
        self._spin_hdbscan.setToolTip(
            "Taille min d'un cluster HDBSCAN.\nPetit -> beaucoup de clusters.\nGrand -> clusters stables.")
        form.addRow("HDBSCAN min_cluster", self._spin_hdbscan)

        layout.addLayout(form)
        layout.addWidget(sep)

        btn = QPushButton("Appliquer et recalculer")
        btn.clicked.connect(self._apply)
        layout.addWidget(btn)
        layout.addStretch()

        self.setWidget(content)
        self.setMinimumWidth(240)

    def _apply(self):
        params = self.current_params()
        _save_map_params(params)
        self.on_apply(params)

    def current_params(self) -> dict:
        return {
            "umap_n_neighbors":    self._spin_neighbors.value(),
            "umap_min_dist":       self._spin_min_dist.value(),
            "hdbscan_min_cluster": self._spin_hdbscan.value(),
        }

    def set_params(self, params: dict):
        self._spin_neighbors.setValue(params["umap_n_neighbors"])
        self._spin_min_dist.setValue(params["umap_min_dist"])
        self._spin_hdbscan.setValue(params["hdbscan_min_cluster"])


# ═════════════════════════════════════════════════════════════
#  Onglet carte 2D
# ═════════════════════════════════════════════════════════════

class MapTab(QWidget):
    """
    Onglet carte 2D sémantique.
    `explorer` doit exposer : .index, .current_folder, .selected_image,
                              ._select_image(), .client (OllamaWrapper),
                              .addDockWidget()
    """

    def __init__(self, explorer, parent=None):
        super().__init__(parent)
        self.explorer = explorer

        self._nodes:    dict[str, _MapNode] = {}
        self._worker:   MapWorker | None = None
        self._current_selected: str | None = None
        self._params = _load_map_params()
        self._legend_labels = {}

        # Bounding boxes par cluster pour le zoom  {cluster_id: QRectF}
        self._cluster_rects: dict[int, QRectF] = {}

        self._build_ui()

        # Dock paramètres attaché à la QMainWindow
        self._settings_dock = _SettingsDock(
            self._params,
            on_apply=self._on_params_applied,
            parent=explorer,
        )
        explorer.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea, self._settings_dock)
        self._settings_dock.setVisible(False)

        # Synchroniser le bouton ⚙ si le dock est fermé via sa croix
        self._settings_dock.visibilityChanged.connect(
            lambda v: self._btn_settings.setChecked(v)
        )

        # ── Chargement automatique au démarrage ───────────────
        # On attend que l'explorateur ait fini son init (index chargé)
        QTimer.singleShot(500, self._autoload)

    # ═════════════════════════════════════════════════════════
    #  UI
    # ═════════════════════════════════════════════════════════

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Barre du haut ─────────────────────────────────────
        bar = QHBoxLayout()

        self._btn_compute = QPushButton("Calculer la carte")
        self._btn_compute.clicked.connect(self.compute)
        bar.addWidget(self._btn_compute)

        self._btn_settings = QPushButton("⚙ Paramètres")
        self._btn_settings.setCheckable(True)
        self._btn_settings.clicked.connect(
            lambda checked: self._settings_dock.setVisible(checked))
        bar.addWidget(self._btn_settings)

        self._btn_reset_filter = QPushButton("Réinitialiser le filtre")
        self._btn_reset_filter.clicked.connect(self.reset_opacity)
        self._btn_reset_filter.setEnabled(False)
        bar.addWidget(self._btn_reset_filter)

        self._lbl_status = QLabel("Chargement en cours…")
        self._lbl_status.setStyleSheet("color: gray; font-size: 12px;")
        bar.addWidget(self._lbl_status, stretch=1)

        root.addLayout(bar)

        # ── Vue + légende ─────────────────────────────────────
        h = QHBoxLayout()
        h.setSpacing(8)

        self._scene = QGraphicsScene(self)
        self._view = _MapView(self._scene, self)
        self._view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        h.addWidget(self._view, stretch=5)

        legend_container = QWidget()
        legend_container.setFixedWidth(180)
        self._legend_layout = QVBoxLayout(legend_container)
        self._legend_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._legend_layout.setSpacing(4)
        self._legend_layout.setContentsMargins(4, 4, 4, 4)

        lbl_leg = QLabel("Clusters")
        lbl_leg.setStyleSheet("font-weight: bold; font-size: 13px;")
        self._legend_layout.addWidget(lbl_leg)

        legend_scroll = QScrollArea()
        legend_scroll.setWidget(legend_container)
        legend_scroll.setWidgetResizable(True)
        legend_scroll.setFixedWidth(195)
        legend_scroll.setStyleSheet("border: none;")
        h.addWidget(legend_scroll)

        root.addLayout(h)

    # ═════════════════════════════════════════════════════════
    #  Chargement automatique
    # ═════════════════════════════════════════════════════════

    def _autoload(self):
        """Charge cache si dispo, sinon compute."""

        cache = self._load_map_cache()

        if cache:
            self._lbl_status.setText("Chargement depuis cache…")

            self._build_scene(
                cache["points"],
                cache["labels"],
                cache["names"],
                cache["cluster_names"]
            )

            self._btn_reset_filter.setEnabled(True)
            self._btn_compute.setEnabled(True)
            self._lbl_status.setText("✅ Map chargée depuis cache")

        else:
            self._lbl_status.setText(
                "Aucun cache — calcul de la carte…")
            self.compute()

    # ═════════════════════════════════════════════════════════
    #  Calcul
    # ═════════════════════════════════════════════════════════

    def compute(self):
        if self._worker and self._worker.isRunning():
            return

        indexed = {
            k: v for k, v in self.explorer.index.items()
            if v.get("embedding") and len(v["embedding"]) > 0
        }
        if len(indexed) < 2:
            self._lbl_status.setText(
                f"⚠ Pas assez d'embeddings ({len(indexed)} / min 2).")
            return

        self._btn_compute.setEnabled(False)
        self._lbl_status.setText("Calcul en cours…")
        self._scene.clear()
        self._nodes.clear()
        self._cluster_rects.clear()
        self._btn_reset_filter.setEnabled(False)

        self._worker = MapWorker(
            indexed,
            client=self.explorer.client,
            umap_n_neighbors=self._params["umap_n_neighbors"],
            umap_min_dist=self._params["umap_min_dist"],
            hdbscan_min_cluster=self._params["hdbscan_min_cluster"],
        )
        self._worker.progress.connect(self._lbl_status.setText)
        self._worker.cluster_named.connect(self._on_cluster_named)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    # ═════════════════════════════════════════════════════════
    #  Slots worker
    # ═════════════════════════════════════════════════════════

    def _on_error(self, msg: str):
        self._lbl_status.setText(f"❌ {msg}")
        self._btn_compute.setEnabled(True)

    def _on_finished(self,
                     points: list[tuple[float, float]],
                     labels: list[int],
                     names:  list[str],
                     cluster_names: dict[int, str]):

        self._save_map_cache(points, labels, names, cluster_names)

        self._build_scene(points, labels, names, cluster_names)

        n_clusters = len({l for l in labels if l >= 0})
        n_noise = labels.count(-1)
        self._lbl_status.setText(
            f"✅ {len(names)} images — {n_clusters} clusters"
            + (f" — {n_noise} bruit" if n_noise else "")
        )
        self._btn_compute.setEnabled(True)
        self._btn_reset_filter.setEnabled(True)

        if self.explorer.selected_image:
            self.highlight(self.explorer.selected_image)

    # ═════════════════════════════════════════════════════════
    #  Construction de la scène
    # ═════════════════════════════════════════════════════════

    def _build_scene(self,
                     points: list[tuple[float, float]],
                     labels: list[int],
                     names:  list[str],
                     cluster_names: dict[int, str]):
        self._scene.clear()
        self._nodes.clear()
        self._cluster_rects.clear()
        self._clear_legend()

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        rx = (max(xs) - min(xs)) or 1
        ry = (max(ys) - min(ys)) or 1
        W = H = 800.0

        def sp(px, py):
            return (px - min(xs)) / rx * W, (py - min(ys)) / ry * H

        # Palette
        unique = sorted(set(labels))
        color_map: dict[int, QColor] = {}
        pi = 0
        for c in unique:
            color_map[c] = QColor(_NOISE_COLOR) if c == -1 else QColor(
                _CLUSTER_COLORS[pi % len(_CLUSTER_COLORS)])
            if c != -1:
                pi += 1

        # Noeuds + bounding boxes par cluster
        cluster_points: dict[int, list[tuple[float, float]]] = {}
        for name, (px, py), label in zip(names, points, labels):
            sx, sy = sp(px, py)
            node = _MapNode(name, label, color_map[label],
                            callback_select=self._on_node_clicked)
            node.setPos(sx, sy)
            self._scene.addItem(node)
            self._nodes[name] = node
            cluster_points.setdefault(label, []).append((sx, sy))

        # Calculer les bounding boxes
        for cid, pts in cluster_points.items():
            xs2 = [p[0] for p in pts]
            ys2 = [p[1] for p in pts]
            self._cluster_rects[cid] = QRectF(
                min(xs2), min(ys2),
                max(xs2) - min(xs2) or 1,
                max(ys2) - min(ys2) or 1,
            )

        self._view.setScene(self._scene)
        self._view.reset_zoom()
        self._view.scale(0.9, 0.9)
        self._view.fitInView(
            QRectF(0, 0, W, H).adjusted(-50, -50, 50, 50),
            Qt.AspectRatioMode.KeepAspectRatio
        )
        self._build_legend(color_map, labels, cluster_names)

    def _on_cluster_named(self, cid: int, name: str):
        # stocker
        if not hasattr(self, "_cluster_names"):
            self._cluster_names = {}

        self._cluster_names[cid] = name

        # rebuild léger de la légende
        self._refresh_legend_names()

    
    # ═════════════════════════════════════════════════════════
    #  Légende
    # ═════════════════════════════════════════════════════════

    def _clear_legend(self):
        while self._legend_layout.count() > 1:
            item = self._legend_layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()

    def _build_legend(self,
                      color_map: dict[int, QColor],
                      labels: list[int],
                      cluster_names: dict[int, str]):
        from collections import Counter
        counts = Counter(labels)

        for cid in sorted(color_map.keys()):
            color = color_map[cid]
            count = counts.get(cid, 0)
            label_text = cluster_names.get(cid, f"Cluster {cid}")
            display = f"{label_text} ({count})"

            row = QHBoxLayout()

            dot = QLabel()
            dot.setFixedSize(12, 12)
            dot.setStyleSheet(f"background:{color.name()}; border-radius:6px;")
            row.addWidget(dot)

            lbl = QLabel(display)
            lbl.setStyleSheet("font-size: 12px;")
            lbl.setWordWrap(True)
            lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            lbl.setToolTip("Clic : isoler et zoomer sur ce cluster")
            lbl.mousePressEvent = lambda _evt, c=cid: self._filter_and_zoom_cluster(
                c)

            row.addWidget(lbl, stretch=1)
            self._legend_labels[cid] = lbl

            container = QWidget()
            container.setLayout(row)
            self._legend_layout.addWidget(container)

    def _refresh_legend_names(self):
        for cid, lbl in getattr(self, "_legend_labels", {}).items():
            base = self._cluster_names.get(cid, f"Cluster {cid}")

            # récupérer le count depuis le texte actuel
            text = lbl.text()
            if "(" in text:
                count = text.split("(")[-1]
                lbl.setText(f"{base} ({count}")

    # ═════════════════════════════════════════════════════════
    #  Interactions
    # ═════════════════════════════════════════════════════════

    def _on_node_clicked(self, img_name: str):
        self.highlight(img_name)
        self.explorer._select_image(img_name)

    def highlight(self, img_name: str):
        if self._current_selected and self._current_selected in self._nodes:
            self._nodes[self._current_selected].mark_selected(False)
        self._current_selected = img_name
        if img_name in self._nodes:
            node = self._nodes[img_name]
            node.mark_selected(True)
            self._view.centerOn(node)

    def _filter_and_zoom_cluster(self, cluster_id: int):
        """Isole visuellement le cluster ET zoome la caméra dessus."""
        # Opacité
        for node in self._nodes.values():
            node.setOpacity(1.0 if node.cluster == cluster_id else 0.12)

        # Zoom sur la bounding box du cluster
        if cluster_id in self._cluster_rects:
            self._view.zoom_to_rect(self._cluster_rects[cluster_id])

        self._btn_reset_filter.setEnabled(True)

    def reset_opacity(self):
        """Réinitialise filtre et zoom."""
        for node in self._nodes.values():
            node.setOpacity(1.0)
        # Revenir à la vue complète
        self._view.fitInView(
            QRectF(0, 0, 800, 800),
            Qt.AspectRatioMode.KeepAspectRatio
        )

    # ═════════════════════════════════════════════════════════
    #  Paramètres
    # ═════════════════════════════════════════════════════════

    def _on_params_applied(self, params: dict):
        self._params = params
        self._settings_dock.set_params(params)
        self.compute()

    # ═════════════════════════════════════════════════════════
    #  Sync depuis l'explorateur
    # ═════════════════════════════════════════════════════════

    def on_image_selected(self, img_name: str):
        if self._nodes:
            self.highlight(img_name)

    # ──────────────────────────────────────────────
    #  Save
    # ──────────────────────────────────────────────

    def _save_map_cache(self, points, labels, names, cluster_names):
        data = {
            "points": points,
            "labels": labels,
            "names": names,
            "cluster_names": cluster_names,
        }

        with open(_MAP_CACHE_FILE, "wb") as f:
            pickle.dump(data, f)

    def _load_map_cache(self):
        if not os.path.exists(_MAP_CACHE_FILE):
            return None

        try:
            with open(_MAP_CACHE_FILE, "rb") as f:
                return pickle.load(f)
        except Exception:
            return None
