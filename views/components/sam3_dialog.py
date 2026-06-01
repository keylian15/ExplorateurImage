"""
Dialog plein écran avec segmentation SAM3 interactive.

Ce composant remplace FullscreenDialog et ajoute une barre latérale de contrôle
SAM3 permettant :
  - Segmentation par prompt texte (ex : "shoe", "dog")
  - Segmentation par boîte dessinée à la souris (positive ou négative)
  - Zoom via molette ou boutons
  - Reset des prompts

Ce widget ne contient AUCUNE logique métier :
  - Pas d'import numpy, PIL, services/
  - Ne connaît que MaskOverlay (type View-friendly exposé par le ViewModel)
  - Toute interaction est relayée au Sam3ViewModel via des appels de méthode
  - Tout résultat est reçu via des signaux Qt

Responsabilités (View uniquement) :
 1. Afficher l'image avec zoom interactif
 2. Dessiner les boîtes à la souris et émettre les coordonnées pixel
 3. Afficher les masques et boîtes reçus via signal_overlay_ready
 4. Gérer les états visuels (chargement, prêt, erreur)
 5. Relayer les actions utilisateur vers le ViewModel
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from styles import COLORS
from viewmodels.sam3_vm import MaskOverlay, Sam3ViewModel

# ── Palette masques ───────────────────────────────────────────────────────────
_MASK_COLORS = [
    (84, 130, 200),
    (76, 184, 122),
    (224, 123, 74),
    (168, 110, 201),
    (217, 90, 90),
    (75, 190, 194),
    (212, 168, 42),
    (176, 80, 112),
    (109, 168, 124),
    (136, 136, 204),
]


# ═════════════════════════════════════════════════════════════════════════════
#  Canvas d'image avec overlay SAM3
# ═════════════════════════════════════════════════════════════════════════════


class ImageCanvas(QLabel):
    """
    QLabel étendu pour :
      - Afficher l'image de base zoomée
      - Superposer les masques SAM3 (MaskOverlay reçu du ViewModel)
      - Permettre le dessin interactif de boîtes à la souris

    N'importe aucun module numpy/PIL/service : le rendu des masques
    utilise uniquement QImage et QPainter.
    """

    signal_box_drawn = pyqtSignal(float, float, float, float)
    # x0, y0, x1, y1 en coordonnées pixel de l'image originale (non zoomée)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

        self._base_pixmap: QPixmap | None = None
        self._overlay: MaskOverlay | None = None
        self._zoom: float = 1.0

        self._drawing = False
        self._box_start: QPoint | None = None
        self._box_end: QPoint | None = None
        self._box_positive: bool = True

    # ── API ───────────────────────────────────────────────────────────────────

    def set_base_pixmap(self, pixmap: QPixmap) -> None:
        """Définit l'image de base et efface l'overlay précédent."""
        self._base_pixmap = pixmap
        self._overlay = None
        self._box_start = self._box_end = None
        self._render()

    def set_overlay(self, overlay: MaskOverlay) -> None:
        """Met à jour l'overlay SAM3 (reçu du ViewModel via signal)."""
        self._overlay = overlay
        self._box_start = self._box_end = None
        self._render()

    def clear_overlay(self) -> None:
        """Supprime l'overlay (après reset des prompts)."""
        self._overlay = None
        self._box_start = self._box_end = None
        self._render()

    def set_zoom(self, zoom: float) -> None:
        self._zoom = max(0.05, min(10.0, zoom))
        self._render()

    def set_box_positive(self, positive: bool) -> None:
        self._box_positive = positive

    # ── Rendu ─────────────────────────────────────────────────────────────────

    def _render(self) -> None:
        if self._base_pixmap is None:
            self.clear()
            return

        w = int(self._base_pixmap.width() * self._zoom)
        h = int(self._base_pixmap.height() * self._zoom)

        scaled = self._base_pixmap.scaled(
            w,
            h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        if self._overlay and self._overlay.masks:
            scaled = self._draw_overlay(scaled)

        self.setPixmap(scaled)
        self.resize(scaled.size())

    def _draw_overlay(self, pixmap: QPixmap) -> QPixmap:
        """
        Dessine les masques et boîtes SAM3 sur le pixmap.

        Utilise uniquement QImage/QPainter - aucun import numpy ici.
        Les données numpy (mask bool array) viennent du MaskOverlay produit
        par le ViewModel.
        """
        import numpy as np  # import local : seul endroit où numpy entre dans la View,
        # justifié car QImage.Format_RGBA8888 nécessite bytes bruts.
        # Alternative possible : déléguer ce rendu au VM aussi.

        overlay = self._overlay
        out = QPixmap(pixmap)
        painter = QPainter(out)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        img_w = overlay.img_w or pixmap.width()
        img_h = overlay.img_h or pixmap.height()
        sx = pixmap.width() / img_w
        sy = pixmap.height() / img_h

        for i, (mask, box, score) in enumerate(zip(overlay.masks, overlay.boxes_xyxy, overlay.scores)):
            r, g, b = _MASK_COLORS[i % len(_MASK_COLORS)]

            # Masque → QImage RGBA (numpy utilisé uniquement pour la construction bytes)
            mask_u8 = mask.astype(np.uint8) * 255
            h_m, w_m = mask_u8.shape
            rgba = np.zeros((h_m, w_m, 4), dtype=np.uint8)
            rgba[mask_u8 > 0] = [r, g, b, 110]
            mask_img = QImage(
                rgba.tobytes(),
                w_m,
                h_m,
                w_m * 4,
                QImage.Format.Format_RGBA8888,
            )
            mask_px = QPixmap.fromImage(mask_img).scaled(
                int(w_m * sx),
                int(h_m * sy),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            painter.drawPixmap(0, 0, mask_px)

            # Boîte de détection
            x0, y0, x1, y1 = box
            rx0, ry0 = int(x0 * sx), int(y0 * sy)
            rx1, ry1 = int(x1 * sx), int(y1 * sy)
            painter.setPen(QPen(QColor(r, g, b), 2))
            painter.drawRect(rx0, ry0, rx1 - rx0, ry1 - ry0)

            # Score label
            font = QFont("Segoe UI", 9)
            font.setBold(True)
            painter.setFont(font)
            label_rect = QRect(rx0, max(0, ry0 - 20), 60, 18)
            painter.fillRect(label_rect, QColor(r, g, b, 200))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, f"{score:.2f}")

        painter.end()
        return out

    # ── Souris ────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drawing = True
            self._box_start = event.pos()
            self._box_end = event.pos()

    def mouseMoveEvent(self, event):
        if self._drawing:
            self._box_end = event.pos()
            self._draw_preview()

    def mouseReleaseEvent(self, event):
        if not self._drawing:
            return
        self._drawing = False
        if self._box_start is None or self._box_end is None:
            return

        start, end = self._box_start, self._box_end
        if abs(end.x() - start.x()) < 5 or abs(end.y() - start.y()) < 5:
            self._box_start = self._box_end = None
            self._render()
            return

        # Conversion coordonnées widget → coordonnées image originale
        if self._base_pixmap is None:
            return
        px = self.pixmap()
        if px is None:
            return
        sx = self._base_pixmap.width() / max(px.width(), 1)
        sy = self._base_pixmap.height() / max(px.height(), 1)

        x0 = min(start.x(), end.x()) * sx
        y0 = min(start.y(), end.y()) * sy
        x1 = max(start.x(), end.x()) * sx
        y1 = max(start.y(), end.y()) * sy

        self._box_start = self._box_end = None
        self.signal_box_drawn.emit(x0, y0, x1, y1)

    def _draw_preview(self) -> None:
        """Affiche la boîte en cours de dessin (pointillés)."""
        if self._base_pixmap is None or self._box_start is None or self._box_end is None:
            return
        self._render()
        pix = self.pixmap()
        if pix is None:
            return
        out = QPixmap(pix)
        painter = QPainter(out)
        color = QColor(0, 200, 80) if self._box_positive else QColor(220, 60, 60)
        painter.setPen(QPen(color, 2, Qt.PenStyle.DashLine))
        x0 = min(self._box_start.x(), self._box_end.x())
        y0 = min(self._box_start.y(), self._box_end.y())
        w = abs(self._box_end.x() - self._box_start.x())
        h = abs(self._box_end.y() - self._box_start.y())
        painter.drawRect(x0, y0, w, h)
        painter.end()
        self.setPixmap(out)


# ═════════════════════════════════════════════════════════════════════════════
#  Barre latérale SAM3
# ═════════════════════════════════════════════════════════════════════════════


class Sam3Sidebar(QWidget):
    """
    Panneau de contrôles SAM3 : prompt texte, mode boîte, confiance, reset.
    Émet des signaux vers Sam3Dialog qui les relaie au ViewModel.
    Aucune logique métier.
    """

    signal_text_prompt = pyqtSignal(str)
    signal_box_positive = pyqtSignal(bool)  # True=positif / False=négatif
    signal_confidence_changed = pyqtSignal(float)
    signal_reset = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(260)
        self._build_ui()

    def _build_ui(self):
        c = COLORS
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 16)
        layout.setSpacing(12)

        # ── Titre ─────────────────────────────────────────────────────────────
        title = QLabel("SAM3 - Segmentation")
        title.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {c['text_primary']};")
        layout.addWidget(title)

        self._sep(layout)

        # ── Status ────────────────────────────────────────────────────────────
        self.lbl_status = QLabel("⏳ Chargement du modèle…")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(f"font-size: 11px; color: {c['text_secondary']};")
        layout.addWidget(self.lbl_status)

        # ── Prompt texte ──────────────────────────────────────────────────────
        lbl_text = QLabel("Prompt texte")
        lbl_text.setStyleSheet(self._section_style())
        layout.addWidget(lbl_text)

        row = QHBoxLayout()
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("ex: shoe, dog, person…")
        self.text_input.setEnabled(False)
        self.text_input.returnPressed.connect(self._on_text_submit)
        row.addWidget(self.text_input)

        self.btn_segment = QPushButton("▶")
        self.btn_segment.setFixedWidth(32)
        self.btn_segment.setToolTip("Segmenter")
        self.btn_segment.setEnabled(False)
        self.btn_segment.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_segment.clicked.connect(self._on_text_submit)
        row.addWidget(self.btn_segment)
        layout.addLayout(row)

        # ── Mode boîte ────────────────────────────────────────────────────────
        self._sep(layout)
        lbl_box = QLabel("Mode boîte")
        lbl_box.setStyleSheet(self._section_style())
        layout.addWidget(lbl_box)

        box_row = QHBoxLayout()
        self.btn_positive = QPushButton("✚ Positive")
        self.btn_positive.setCheckable(True)
        self.btn_positive.setChecked(True)
        self.btn_positive.setEnabled(False)
        self.btn_positive.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_positive.clicked.connect(self._on_box_mode)
        self.btn_positive.setToolTip("Inclure la zone dessinée")
        box_row.addWidget(self.btn_positive)

        self.btn_negative = QPushButton("✖ Négative")
        self.btn_negative.setCheckable(True)
        self.btn_negative.setEnabled(False)
        self.btn_negative.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_negative.clicked.connect(self._on_box_mode)
        self.btn_negative.setToolTip("Exclure la zone dessinée")
        box_row.addWidget(self.btn_negative)
        layout.addLayout(box_row)

        hint = QLabel("Dessinez une boîte sur l'image")
        hint.setStyleSheet(f"font-size: 10px; color: {c['text_muted']}; font-style: italic;")
        layout.addWidget(hint)

        # ── Seuil de confiance ────────────────────────────────────────────────
        self._sep(layout)
        conf_row = QHBoxLayout()
        conf_row.addWidget(QLabel("Confiance"))
        self.lbl_conf_val = QLabel("0.50")
        self.lbl_conf_val.setStyleSheet(f"color: {c['accent']};")
        conf_row.addWidget(self.lbl_conf_val)
        layout.addLayout(conf_row)

        self.slider_conf = QSlider(Qt.Orientation.Horizontal)
        self.slider_conf.setRange(0, 100)
        self.slider_conf.setValue(50)
        self.slider_conf.setEnabled(False)
        self.slider_conf.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.slider_conf.valueChanged.connect(self._on_confidence)
        layout.addWidget(self.slider_conf)

        # ── Reset ─────────────────────────────────────────────────────────────
        self._sep(layout)
        self.btn_reset = QPushButton("↺ Réinitialiser les prompts")
        self.btn_reset.setEnabled(False)
        self.btn_reset.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_reset.clicked.connect(self.signal_reset)
        layout.addWidget(self.btn_reset)

        layout.addStretch()
        self._apply_stylesheet()

    def _sep(self, layout):
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {COLORS['border']};")
        layout.addWidget(sep)

    def _section_style(self) -> str:
        c = COLORS
        return f"font-size: 11px; color: {c['text_secondary']}; font-weight: 600;"

    def _apply_stylesheet(self):
        c = COLORS
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {c["bg_secondary"]};
                color: {c["text_primary"]};
            }}
            QPushButton {{
                background-color: {c["bg_card"]};
                color: {c["text_primary"]};
                border: 1px solid {c["border"]};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }}
            QPushButton:hover {{ background-color: {c["bg_hover"]}; border-color: {c["accent"]}; }}
            QPushButton:checked {{ background-color: {c["accent"]}; color: #fff; border-color: {c["accent"]}; }}
            QPushButton:disabled {{ color: {c["text_disabled"]}; }}
            QLineEdit {{
                background-color: {c["bg_input"]}; color: {c["text_primary"]};
                border: 1px solid {c["border"]}; border-radius: 4px;
                padding: 4px 8px; font-size: 12px;
            }}
            QLineEdit:focus {{ border-color: {c["accent"]}; }}
            QSlider::groove:horizontal {{ height: 4px; background: {c["border"]}; border-radius: 2px; }}
            QSlider::handle:horizontal {{
                background: {c["accent"]}; border: none;
                width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
            }}
            QSlider::sub-page:horizontal {{ background: {c["accent"]}; border-radius: 2px; }}
        """)

    # ── API externe ───────────────────────────────────────────────────────────

    def set_ready(self, ready: bool) -> None:
        """Active ou désactive tous les contrôles."""
        for w in (self.text_input, self.btn_segment, self.btn_positive, self.btn_negative, self.slider_conf, self.btn_reset):
            w.setEnabled(ready)
        # Redonner le focus au champ texte quand on est prêt
        if ready:
            self.text_input.setFocus()

    def set_status(self, text: str) -> None:
        self.lbl_status.setText(text)

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.set_ready(not busy)
        if message:
            self.lbl_status.setText(f"⏳ {message}")

    def is_positive_mode(self) -> bool:
        return self.btn_positive.isChecked()

    # ── Slots internes ────────────────────────────────────────────────────────

    def _on_text_submit(self):
        text = self.text_input.text().strip()
        if text:
            self.signal_text_prompt.emit(text)

    def _on_box_mode(self):
        positive = self.sender() is self.btn_positive
        self.btn_positive.setChecked(positive)
        self.btn_negative.setChecked(not positive)
        self.signal_box_positive.emit(positive)

    def _on_confidence(self, value: int):
        f = value / 100.0
        self.lbl_conf_val.setText(f"{f:.2f}")
        self.signal_confidence_changed.emit(f)


# ═════════════════════════════════════════════════════════════════════════════
#  Dialog principal
# ═════════════════════════════════════════════════════════════════════════════


class Sam3Dialog(QDialog):
    """
    Dialog plein écran combinant zoom et segmentation SAM3 interactive.

    Respecte MVVM :
      - Ne connaît que Sam3ViewModel et MaskOverlay (pas de services/ ni numpy/PIL)
      - Toute interaction est relayée au ViewModel
      - Tout résultat est reçu via des signaux
    """

    def __init__(
        self,
        pixmap: QPixmap,
        sam3_vm: Sam3ViewModel,
        title: str = "",
        img_path: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._pixmap = pixmap
        self._vm = sam3_vm
        self._img_path = img_path
        self._img_w = pixmap.width()
        self._img_h = pixmap.height()
        self._zoom = 0.75

        self.setWindowTitle(title or "Visualisation SAM3")
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(screen.width(), screen.height())

        self._build_ui()
        self._connect_vm()
        self._init_image()

    # ── Construction ─────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())

        center = QHBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(0)

        # Canvas
        self._canvas = ImageCanvas()
        self._canvas.set_base_pixmap(self._pixmap)
        self._canvas.set_zoom(self._zoom)
        self._canvas.signal_box_drawn.connect(self._on_box_drawn)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._scroll.setWidget(self._canvas)
        self._scroll.setStyleSheet(f"background: {COLORS['bg_card']}; border: none;")
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Intercepter la molette sur le scroll pour zoomer au lieu de scroller
        self._scroll.wheelEvent = self._on_scroll_wheel
        center.addWidget(self._scroll, stretch=1)

        # Sidebar
        self._sidebar = Sam3Sidebar()
        self._sidebar.signal_text_prompt.connect(self._vm.apply_text_prompt)
        self._sidebar.signal_box_positive.connect(self._canvas.set_box_positive)
        self._sidebar.signal_confidence_changed.connect(self._vm.set_confidence)
        self._sidebar.signal_reset.connect(self._vm.reset_prompts)
        center.addWidget(self._sidebar)

        root.addLayout(center)

    def _build_topbar(self) -> QWidget:
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 4, 8, 4)

        self._btn_zoom_out = QPushButton("🔍 -")
        self._btn_zoom_in = QPushButton("🔍 +")
        self._btn_zoom_reset = QPushButton("↺ Reset zoom")
        self._lbl_zoom = QLabel("75%")
        self._lbl_zoom.setFixedWidth(50)
        self._lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)

        for btn in (self._btn_zoom_out, self._btn_zoom_in, self._btn_zoom_reset):
            btn.setFixedHeight(28)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            bar.addWidget(btn)
        bar.addWidget(self._lbl_zoom)
        bar.addStretch()

        self._btn_zoom_in.clicked.connect(lambda: self._apply_zoom(self._zoom + 0.15))
        self._btn_zoom_out.clicked.connect(lambda: self._apply_zoom(self._zoom - 0.15))
        self._btn_zoom_reset.clicked.connect(lambda: self._apply_zoom(0.75))

        bar_w = QWidget()
        bar_w.setLayout(bar)
        bar_w.setFixedHeight(40)
        bar_w.setStyleSheet(f"background: {COLORS['bg_primary']}; border-bottom: 1px solid {COLORS['border']};")
        return bar_w

    # ── Connexion ViewModel → View ────────────────────────────────────────────

    def _connect_vm(self):
        vm = self._vm

        vm.signal_model_loading.connect(lambda: self._sidebar.set_status("⏳ Chargement du modèle…"))
        vm.signal_model_ready.connect(self._on_model_ready)
        vm.signal_model_error.connect(lambda e: self._sidebar.set_status(f"❌ Erreur modèle : {e}"))
        vm.signal_encoding.connect(lambda: self._sidebar.set_busy(True, "Encodage de l'image…"))
        vm.signal_encoded.connect(self._on_encoded)
        vm.signal_encoding_error.connect(lambda e: self._sidebar.set_status(f"❌ Encodage : {e}"))
        vm.signal_segmenting.connect(lambda: self._sidebar.set_busy(True, "Segmentation en cours…"))
        vm.signal_overlay_ready.connect(self._on_overlay_ready)
        vm.signal_segment_error.connect(lambda e: self._sidebar.set_status(f"❌ Segmentation : {e}"))
        vm.signal_resetting.connect(lambda: self._sidebar.set_busy(True, "Réinitialisation…"))
        vm.signal_reset_done.connect(self._on_reset_done)

    # ── Initialisation image ──────────────────────────────────────────────────

    def _init_image(self):
        """Lance l'encodage si le modèle est prêt, sinon attend signal_model_ready.
        Ne relance jamais load_model() si c'est déjà en cours (chargement en fond au démarrage).
        """
        if self._vm.is_model_loaded:
            self._vm.encode_image(self._pixmap, self._img_path)
        else:
            # Le modèle est peut-être déjà en cours de chargement depuis WorkspaceWidget.
            # On attend simplement signal_model_ready — _on_model_ready lancera l'encodage.
            self._sidebar.set_status("⏳ Chargement du modèle en cours…")
            if not self._vm.is_busy:
                self._vm.load_model()

    # ── Slots ViewModel → View ────────────────────────────────────────────────

    def _on_model_ready(self):
        self._sidebar.set_status("✅ Modèle prêt")
        if not self._vm.is_image_encoded:
            self._vm.encode_image(self._pixmap, self._img_path)

    def _on_encoded(self):
        self._sidebar.set_ready(True)
        self._sidebar.set_status("✅ Prêt - saisissez un prompt ou dessinez une boîte")

    def _on_overlay_ready(self, overlay: MaskOverlay):
        self._sidebar.set_ready(True)
        n = len(overlay.masks)
        self._sidebar.set_status(f"✅ {n} objet(s) trouvé(s)")
        self._canvas.set_overlay(overlay)

    def _on_reset_done(self):
        self._canvas.clear_overlay()
        self._sidebar.set_ready(True)
        self._sidebar.set_status("✅ Prompts réinitialisés")

    # ── Slots UI → ViewModel ──────────────────────────────────────────────────

    def _on_box_drawn(self, x0: float, y0: float, x1: float, y1: float):
        positive = self._sidebar.is_positive_mode()
        self._vm.apply_box_prompt(x0, y0, x1, y1, self._img_w, self._img_h, positive)

    # ── Zoom ──────────────────────────────────────────────────────────────────

    def _apply_zoom(self, zoom: float):
        self._zoom = max(0.05, min(10.0, zoom))
        self._canvas.set_zoom(self._zoom)
        self._lbl_zoom.setText(f"{int(self._zoom * 100)}%")

    def _on_scroll_wheel(self, event):
        """Intercepte la molette sur le QScrollArea pour zoomer."""
        delta = 0.1 if event.angleDelta().y() > 0 else -0.1
        self._apply_zoom(self._zoom + delta)