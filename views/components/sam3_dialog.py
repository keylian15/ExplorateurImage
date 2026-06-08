"""
Dialog plein écran avec segmentation SAM3 interactive.

SAM3 permettant :
  - Segmentation par prompt texte (ex : "shoe", "dog")
  - Segmentation par boîte dessinée à la souris (positive ou négative)
  - Zoom via molette ou boutons
  - Reset des prompts
  - Recherche globale sur tout le dossier avec panneau de résultats
  - Recherche par box avec trois stratégies : Embedding, SAM3, Hybride

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
 6. Afficher les résultats de la recherche globale (miniatures + scores)
 7. Permettre la sélection de la stratégie de recherche par box
"""

from __future__ import annotations

import os

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
    QButtonGroup,
    QDockWidget,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from styles import COLORS, neighbor_thumb_style, score_label_style, section_title_style
from viewmodels.sam3_vm import MaskOverlay, Sam3ViewModel
from views.components.clickable_label import ClickableLabel

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

# ── Labels lisibles pour les stratégies ──────────────────────────────────────
_STRATEGY_LABELS = {
    "embedding": "⚡ Embedding (rapide)",
    "sam3": "🎯 SAM3 (précis)",
    "hybrid": "🔬 Hybride (très précis, lent)",
}


# ═════════════════════════════════════════════════════════════════════════════
#  Canvas d'image avec overlay SAM3
# ═════════════════════════════════════════════════════════════════════════════


class ImageCanvas(QLabel):
    """QLabel étendu : affiche l'image zoomée + overlay SAM3 + dessin de boîtes."""

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

        Utilise uniquement QImage/QPainter.
        Les données numpy (mask bool array) viennent du MaskOverlay produit
        par le ViewModel.
        """
        import numpy as np

        overlay = self._overlay
        out = QPixmap(pixmap)
        painter = QPainter(out)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        img_w = overlay.img_w or pixmap.width()
        img_h = overlay.img_h or pixmap.height()
        sx = pixmap.width() / img_w
        sy = pixmap.height() / img_h

        for i, (mask, box, score) in enumerate(zip(overlay.masks, overlay.boxes_xyxy, overlay.scores, strict=True)):
            r, g, b = _MASK_COLORS[i % len(_MASK_COLORS)]

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

            x0, y0, x1, y1 = box
            rx0, ry0 = int(x0 * sx), int(y0 * sy)
            rx1, ry1 = int(x1 * sx), int(y1 * sy)
            painter.setPen(QPen(QColor(r, g, b), 2))
            painter.drawRect(rx0, ry0, rx1 - rx0, ry1 - ry0)

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
#  Panneau de résultats de la recherche globale
# ═════════════════════════════════════════════════════════════════════════════


class SearchResultsPanel(QWidget):
    """
    Grille de miniatures des images retenues par la recherche globale.

    Les résultats s'affichent au fur et à mesure grâce à un QTimer qui
    dépile une file d'attente (_pending_results) par petits lots, laissant
    Qt traiter ses événements entre chaque lot pour éviter tout freeze.

    Structure :
      - QScrollArea fixe 220 px de hauteur
      - QGridLayout 3 colonnes, spacing 4
      - ClickableLabel pour chaque miniature
      - Score centré sous chaque miniature
      - En-tête avec compteur + barre de progression fine
    """

    signal_image_clicked = pyqtSignal(str)

    THUMB = 80
    COLS = 3
    # Nombre de cellules insérées par tick du timer de flush
    _BATCH_SIZE = 5
    # Intervalle entre deux ticks (ms)
    _FLUSH_INTERVAL_MS = 16  # ~60fps

    def __init__(self, folder: str | None, parent=None):
        super().__init__(parent)
        self._folder = folder
        self._count = 0
        # File d'attente des résultats reçus mais pas encore affichés
        self._pending_results: list[tuple[str, float]] = []
        self._wait_mode: bool = False  # si True, accumule sans afficher jusqu'à finish_search

        self._flush_timer = None  # initialisé dans _build_ui (besoin de QTimer)
        self._build_ui()

    def _build_ui(self) -> None:
        from PyQt6.QtCore import QTimer

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(4)

        # ── En-tête ───────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        self._lbl_title = QLabel("Images trouvées")
        self._lbl_title.setStyleSheet(section_title_style())
        hdr.addWidget(self._lbl_title)
        hdr.addStretch()

        self._btn_clear = QPushButton("✕")
        self._btn_clear.setFixedSize(22, 22)
        self._btn_clear.setToolTip("Effacer les résultats")
        self._btn_clear.setStyleSheet(f"background: transparent; color: {COLORS['text_muted']}; border: none; font-size: 12px; min-width: 0;")
        self._btn_clear.clicked.connect(self.clear)
        hdr.addWidget(self._btn_clear)
        root.addLayout(hdr)

        # ── Barre de progression fine ─────────────────────────────────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(3)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setVisible(False)
        self._progress_bar.setStyleSheet(
            f"QProgressBar {{ background: {COLORS['bg_card']}; border: none; border-radius: 1px; }}QProgressBar::chunk {{ background: {COLORS['accent']}; border-radius: 1px; }}"
        )
        root.addWidget(self._progress_bar)

        self._lbl_progress = QLabel("")
        self._lbl_progress.setStyleSheet(score_label_style())
        self._lbl_progress.setVisible(False)
        root.addWidget(self._lbl_progress)

        # ── Grille scrollable ─────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setFixedHeight(220)
        scroll.setWidgetResizable(True)
        self._scroll = scroll

        self._neighbors_widget = QWidget()
        self._neighbors_grid = QGridLayout()
        self._neighbors_grid.setSpacing(4)
        self._neighbors_widget.setLayout(self._neighbors_grid)
        scroll.setWidget(self._neighbors_widget)
        root.addWidget(scroll)

        # ── Timer de flush progressif ─────────────────────────────────────────
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(self._FLUSH_INTERVAL_MS)
        self._flush_timer.timeout.connect(self._flush_batch)

    # ── API ───────────────────────────────────────────────────────────────────

    def set_folder(self, folder: str | None) -> None:
        self._folder = folder

    def set_wait_mode(self, enabled: bool) -> None:
        """Active ou désactive le mode attente.

        En mode attente, les résultats s'accumulent silencieusement et
        ne s'affichent qu'au moment de finish_search(), triés par score.

        Args:
            enabled: True = attendre la fin, False = afficher au fil de l'eau.
        """
        self._wait_mode = enabled

    def start_search(self, total: int) -> None:
        """Prépare le panneau pour une nouvelle recherche."""
        self.clear(keep_header=True)
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)
        self._lbl_progress.setText(f"0 / {total}")
        self._lbl_progress.setVisible(True)
        self._lbl_title.setText("Recherche en cours…")

    def update_progress(self, done: int, total: int, img_name: str) -> None:
        self._progress_bar.setValue(done)
        label = f"{done} / {total}"
        if img_name:
            label += f"  —  {img_name}"
        self._lbl_progress.setText(label)

    def add_result(self, img_name: str, score: float) -> None:
        """Enfile un résultat.

        En mode normal : démarre le timer de flush immédiatement pour
        afficher au fil de l'eau.
        En mode attente : accumule sans déclencher le timer — l'affichage
        se fait en bloc lors de finish_search().

        Args:
            img_name: Nom du fichier image résultat.
            score: Score de similarité (0–1).
        """
        self._pending_results.append((img_name, score))
        if not self._wait_mode and self._flush_timer and not self._flush_timer.isActive():
            self._flush_timer.start(0)

    def finish_search(self, matched: list) -> None:
        """Finalise l'affichage après la fin de la recherche.

        En mode normal : laisse le timer vider la file, le titre se met
        à jour au dernier tick.
        En mode attente : trie les résultats par score décroissant et
        déclenche le flush d'un bloc.
        """
        self._progress_bar.setVisible(False)
        self._lbl_progress.setVisible(False)
        self._final_count = len(matched)
        self._search_done = True

        if self._wait_mode and self._pending_results:
            # Tri par score décroissant avant affichage
            self._pending_results.sort(key=lambda x: x[1], reverse=True)
            # Démarre le flush (même timer, mais la file est maintenant triée)
            if self._flush_timer and not self._flush_timer.isActive():
                self._flush_timer.start(0)

    def show_cancelled(self) -> None:
        self._progress_bar.setVisible(False)
        self._lbl_progress.setVisible(False)
        self._search_done = True
        self._final_count = None  # None = annulé

    def clear(self, keep_header: bool = False) -> None:
        if self._flush_timer:
            self._flush_timer.stop()
        self._pending_results.clear()
        self._search_done = False
        self._final_count = None

        for i in reversed(range(self._neighbors_grid.count())):
            w = self._neighbors_grid.itemAt(i).widget()
            if w:
                w.deleteLater()
        self._count = 0
        if not keep_header:
            self._lbl_title.setText("Images trouvées")
            self._progress_bar.setVisible(False)
            self._lbl_progress.setVisible(False)

    # ── Flush progressif ──────────────────────────────────────────────────────

    def _flush_batch(self) -> None:
        """Insère jusqu'à _BATCH_SIZE cellules dans la grille, puis rend la main à Qt.

        Appelé périodiquement par _flush_timer. S'arrête quand la file est vide.
        """
        batch = self._pending_results[: self._BATCH_SIZE]
        self._pending_results = self._pending_results[self._BATCH_SIZE :]

        for img_name, score in batch:
            self._insert_cell(img_name, score)

        if not self._pending_results:
            self._flush_timer.stop()
            # Mise à jour du titre final si la recherche est terminée
            if getattr(self, "_search_done", False):
                n = getattr(self, "_final_count", None)
                if n is None:
                    # Annulé
                    self._lbl_title.setText(f"Images trouvées ({self._count}) — annulé")
                else:
                    self._lbl_title.setText(f"Images trouvées ({n} image{'s' if n > 1 else ''} — {'aucune correspondance' if n == 0 else 'cliquez pour ouvrir'})")

    def _insert_cell(self, img_name: str, score: float) -> None:
        """Crée et insère une cellule (thumbnail + score) dans la grille.

        Args:
            img_name: Nom du fichier image.
            score: Score de similarité.
        """
        if not self._folder:
            return

        img_path = os.path.join(self._folder, img_name)
        pixmap_full = QPixmap(img_path)
        if pixmap_full.isNull():
            return

        pixmap_scaled = pixmap_full.scaled(
            self.THUMB,
            self.THUMB,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        cell = QWidget()
        cell_layout = QVBoxLayout()
        cell_layout.setContentsMargins(2, 2, 2, 2)
        cell_layout.setSpacing(2)

        thumb = ClickableLabel()
        thumb.setPixmap(pixmap_scaled)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setStyleSheet(neighbor_thumb_style())
        thumb.setCursor(Qt.CursorShape.PointingHandCursor)
        thumb.setToolTip(f"{img_name}\nScore : {score:.2f}")
        thumb.leftClicked = lambda n=img_name: self.signal_image_clicked.emit(n)

        score_lbl = QLabel(f"{score:.2f}")
        score_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        score_lbl.setStyleSheet(score_label_style())

        cell_layout.addWidget(thumb)
        cell_layout.addWidget(score_lbl)
        cell.setLayout(cell_layout)

        row, col = divmod(self._count, self.COLS)
        self._neighbors_grid.addWidget(cell, row, col)
        self._count += 1
        self._lbl_title.setText(f"Images trouvées ({self._count})")


# ═════════════════════════════════════════════════════════════════════════════
#  Barre latérale SAM3
# ═════════════════════════════════════════════════════════════════════════════


class Sam3SidebarContent(QWidget):
    """Contrôles SAM3 : prompt texte, mode boîte, confiance, reset, recherche globale et recherche par box."""

    signal_text_prompt = pyqtSignal(str)
    signal_search_requested = pyqtSignal(str, float)  # (text, threshold) — recherche texte globale
    signal_box_search_requested = pyqtSignal(float, float)  # (threshold, sam3_threshold) — recherche par box
    signal_search_cancel = pyqtSignal()
    signal_box_positive = pyqtSignal(bool)
    signal_confidence_changed = pyqtSignal(float)
    signal_reset = pyqtSignal()
    signal_wait_mode_changed = pyqtSignal(bool)  # True = attendre la fin avant d'afficher

    def __init__(self, parent=None):
        super().__init__(parent)
        # Mémorise les dernières coordonnées de box dessinée (coords image originale)
        self._last_box: tuple[float, float, float, float] | None = None
        self._build_ui()

    def set_last_box(self, x0: float, y0: float, x1: float, y1: float) -> None:
        """Mémorise les coordonnées de la dernière box dessinée.

        Args:
            x0, y0, x1, y1: Coordonnées pixel sur l'image originale.
        """
        self._last_box = (x0, y0, x1, y1)
        # Active le bouton "Rechercher dans la box" si une box est disponible
        if hasattr(self, "btn_search_box"):
            self.btn_search_box.setEnabled(self.btn_segment.isEnabled())

    def has_box(self) -> bool:
        """Indique si une box a été mémorisée."""
        return self._last_box is not None

    def get_last_box(self) -> tuple[float, float, float, float] | None:
        """Retourne les coordonnées de la dernière box, ou None."""
        return self._last_box

    def current_strategy(self) -> str:
        """Retourne le nom de la stratégie de recherche sélectionnée.

        Returns:
            "embedding", "sam3" ou "hybrid".
        """
        if self._radio_sam3.isChecked():
            return "sam3"
        if self._radio_hybrid.isChecked():
            return "hybrid"
        return "embedding"

    def _build_ui(self) -> None:
        c = COLORS
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(10)

        # ── Status ────────────────────────────────────────────────────────────
        self.lbl_status = QLabel("⏳ Chargement du modèle…")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(f"font-size: 11px; color: {c['text_secondary']};")
        layout.addWidget(self.lbl_status)

        self._sep(layout)

        # ── Prompt texte ──────────────────────────────────────────────────────
        layout.addWidget(self._section_label("Prompt texte — image courante"))

        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("ex: shoe, dog, person…")
        self.text_input.setEnabled(False)
        self.text_input.returnPressed.connect(self._on_text_submit)
        layout.addWidget(self.text_input)

        self.btn_segment = QPushButton("▶ Segmenter")
        self.btn_segment.setEnabled(False)
        self.btn_segment.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_segment.clicked.connect(self._on_text_submit)
        layout.addWidget(self.btn_segment)

        # ── Mode boîte ────────────────────────────────────────────────────────
        self._sep(layout)
        layout.addWidget(self._section_label("Mode boîte"))

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

        # ── Seuil de confiance (segmentation courante) ────────────────────────
        self._sep(layout)
        conf_row = QHBoxLayout()
        conf_row.addWidget(QLabel("Confiance (prompt)"))
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

        # ── Stratégie de recherche ────────────────────────────────────────────
        self._sep(layout)
        layout.addWidget(self._section_label("Stratégie de recherche"))

        self._radio_embedding = QRadioButton(_STRATEGY_LABELS["embedding"])
        self._radio_embedding.setChecked(True)
        self._radio_embedding.setToolTip("Description VLM → embedding → similarité cosinus sur l'index.\nRapide, ne nécessite pas SAM3.")
        layout.addWidget(self._radio_embedding)

        self._radio_sam3 = QRadioButton(_STRATEGY_LABELS["sam3"])
        self._radio_sam3.setToolTip("Description VLM → recherche SAM3 sur tout le dossier.\nPrécis visuellement, nécessite SAM3.")
        layout.addWidget(self._radio_sam3)

        self._radio_hybrid = QRadioButton(_STRATEGY_LABELS["hybrid"])
        self._radio_hybrid.setToolTip("Embedding pour présélectionner, puis SAM3 pour raffiner.\nTrès précis mais lent.")
        layout.addWidget(self._radio_hybrid)

        # Groupe exclusif
        self._strategy_group = QButtonGroup(self)
        self._strategy_group.addButton(self._radio_embedding)
        self._strategy_group.addButton(self._radio_sam3)
        self._strategy_group.addButton(self._radio_hybrid)

        # ── Seuils de recherche ───────────────────────────────────────────────
        self._sep(layout)
        layout.addWidget(self._section_label("Seuils de recherche"))

        embed_thresh_row = QHBoxLayout()
        embed_thresh_row.addWidget(QLabel("Seuil embedding"))
        self.spin_embed_threshold = QDoubleSpinBox()
        self.spin_embed_threshold.setRange(0.01, 1.0)
        self.spin_embed_threshold.setSingleStep(0.05)
        self.spin_embed_threshold.setDecimals(2)
        self.spin_embed_threshold.setValue(0.30)
        self.spin_embed_threshold.setFixedWidth(70)
        self.spin_embed_threshold.setToolTip("Score cosinus minimum (stratégies Embedding et Hybride).")
        embed_thresh_row.addStretch()
        embed_thresh_row.addWidget(self.spin_embed_threshold)
        layout.addLayout(embed_thresh_row)

        sam3_thresh_row = QHBoxLayout()
        sam3_thresh_row.addWidget(QLabel("Seuil SAM3"))
        self.spin_sam3_threshold = QDoubleSpinBox()
        self.spin_sam3_threshold.setRange(0.01, 1.0)
        self.spin_sam3_threshold.setSingleStep(0.05)
        self.spin_sam3_threshold.setDecimals(2)
        self.spin_sam3_threshold.setValue(0.75)
        self.spin_sam3_threshold.setFixedWidth(70)
        self.spin_sam3_threshold.setToolTip("Score SAM3 minimum (stratégies SAM3 et Hybride).\n0.75 = score ≥ 75 %")
        sam3_thresh_row.addStretch()
        sam3_thresh_row.addWidget(self.spin_sam3_threshold)
        layout.addLayout(sam3_thresh_row)

        # ── Boutons de recherche ──────────────────────────────────────────────
        self._sep(layout)
        layout.addWidget(self._section_label("Recherche — tout le dossier"))

        # Recherche par box (nouvelle)
        self.btn_search_box = QPushButton("🔲 Rechercher par box")
        self.btn_search_box.setEnabled(False)
        self.btn_search_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_search_box.setToolTip("Lance la recherche sur la région dessinée avec la stratégie sélectionnée.\nDessinez d'abord une boîte sur l'image.")
        self.btn_search_box.clicked.connect(self._on_search_box)
        layout.addWidget(self.btn_search_box)

        # Recherche par texte (existante, renommée pour clarté)
        self.btn_search_all = QPushButton("🔍 Rechercher par texte")
        self.btn_search_all.setEnabled(False)
        self.btn_search_all.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_search_all.setToolTip("Recherche l'objet du prompt texte sur toutes les images via SAM3.")
        self.btn_search_all.clicked.connect(self._on_search_all)
        layout.addWidget(self.btn_search_all)

        btn_cancel_row = QHBoxLayout()
        self.btn_cancel_search = QPushButton("⛔ Annuler")
        self.btn_cancel_search.setVisible(False)
        self.btn_cancel_search.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_cancel_search.clicked.connect(self.signal_search_cancel)
        btn_cancel_row.addWidget(self.btn_cancel_search)
        layout.addLayout(btn_cancel_row)

        # ── Mode attente ──────────────────────────────────────────────────────
        self._sep(layout)
        from PyQt6.QtWidgets import QCheckBox as _QCB

        self.checkbox_wait_end = _QCB("⏳ Attendre la fin")
        self.checkbox_wait_end.setChecked(False)
        self.checkbox_wait_end.setToolTip(
            "Si coché, les résultats s'affichent tous d'un coup à la fin de la recherche,\n"
            "triés du plus proche au moins proche.\n"
            "Par défaut (décoché), les résultats apparaissent au fur et à mesure\n"
            "dans l'ordre de traitement — idéal pour les longues recherches."
        )
        self.checkbox_wait_end.toggled.connect(self.signal_wait_mode_changed)
        layout.addWidget(self.checkbox_wait_end)

        layout.addStretch()
        self._apply_stylesheet()

    def _sep(self, layout: QVBoxLayout) -> None:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {COLORS['border']};")
        layout.addWidget(sep)

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-size: 11px; color: {COLORS['text_secondary']}; font-weight: 600;")
        return lbl

    def _apply_stylesheet(self) -> None:
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
            QDoubleSpinBox {{
                background-color: {c["bg_input"]}; color: {c["text_primary"]};
                border: 1px solid {c["border"]}; border-radius: 4px;
                padding: 2px 6px; font-size: 12px;
            }}
            QSlider::groove:horizontal {{
                height: 4px; background: {c["border"]}; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {c["accent"]}; border: none;
                width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
            }}
            QSlider::sub-page:horizontal {{
                background: {c["accent"]}; border-radius: 2px;
            }}
            QRadioButton {{
                font-size: 12px;
                padding: 2px 0px;
            }}
            QRadioButton::indicator {{
                width: 14px; height: 14px;
            }}
        """)

    # ── API externe ───────────────────────────────────────────────────────────

    def set_ready(self, ready: bool) -> None:
        """Active ou désactive les contrôles de segmentation courante."""
        for w in (
            self.text_input,
            self.btn_segment,
            self.btn_positive,
            self.btn_negative,
            self.slider_conf,
            self.btn_reset,
            self.btn_search_all,
        ):
            w.setEnabled(ready)
        # Le bouton box search n'est actif que si prêt ET qu'une box existe
        self.btn_search_box.setEnabled(ready and self.has_box())
        if ready:
            self.text_input.setFocus()

    def set_status(self, text: str) -> None:
        self.lbl_status.setText(text)

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.set_ready(not busy)
        if message:
            self.lbl_status.setText(f"⏳ {message}")

    def set_searching(self, searching: bool) -> None:
        """Bascule l'état visuel pendant la recherche globale."""
        self.btn_search_all.setVisible(not searching)
        self.btn_search_box.setVisible(not searching)
        self.btn_cancel_search.setVisible(searching)

    def is_positive_mode(self) -> bool:
        return self.btn_positive.isChecked()

    def current_wait_mode(self) -> bool:
        """Retourne True si l'utilisateur veut attendre la fin avant d'afficher."""
        return self.checkbox_wait_end.isChecked()

    def current_embed_threshold(self) -> float:
        return self.spin_embed_threshold.value()

    def current_sam3_threshold(self) -> float:
        return self.spin_sam3_threshold.value()

    # ── Slots internes ────────────────────────────────────────────────────────

    def _on_text_submit(self) -> None:
        text = self.text_input.text().strip()
        if text:
            self.signal_text_prompt.emit(text)

    def _on_box_mode(self) -> None:
        positive = self.sender() is self.btn_positive
        self.btn_positive.setChecked(positive)
        self.btn_negative.setChecked(not positive)
        self.signal_box_positive.emit(positive)

    def _on_confidence(self, value: int) -> None:
        f = value / 100.0
        self.lbl_conf_val.setText(f"{f:.2f}")
        self.signal_confidence_changed.emit(f)

    def _on_search_all(self) -> None:
        """Recherche texte globale via SAM3 (comportement original)."""
        text = self.text_input.text().strip()
        if not text:
            self.lbl_status.setText("⚠️ Saisissez d'abord un prompt texte.")
            return
        self.signal_search_requested.emit(text, self.spin_sam3_threshold.value())

    def _on_search_box(self) -> None:
        """Recherche par box avec la stratégie sélectionnée."""
        if not self.has_box():
            self.lbl_status.setText("⚠️ Dessinez d'abord une boîte sur l'image.")
            return
        self.signal_box_search_requested.emit(self.current_embed_threshold(), self.current_sam3_threshold())


# ═════════════════════════════════════════════════════════════════════════════
#  Dialog principal
# ═════════════════════════════════════════════════════════════════════════════


class Sam3Dialog(QMainWindow):
    """
    Fenêtre SAM3 interactive.

    QMainWindow (et non QDialog) pour avoir :
      - Les 3 boutons natifs : réduire / plein écran / fermer
      - Fenêtre non bloquante : on peut continuer à utiliser l'app
        pendant qu'une analyse globale tourne en arrière-plan
      - Deux QDockWidget : contrôles SAM3 (droite) et résultats (bas)

    Appel : Sam3Dialog(...).show()  — plus exec()
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

        self.setWindowTitle(title or "SAM3 — Segmentation interactive")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowCloseButtonHint)

        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(screen.width(), screen.height())

        self._build_ui()
        self._connect_vm()
        self._init_image()

    # ── Construction ─────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── Zone centrale : barre de zoom + canvas ────────────────────────────
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        central_layout.addWidget(self._build_topbar())

        self._canvas = ImageCanvas()
        self._canvas.set_base_pixmap(self._pixmap)
        self._canvas.set_zoom(self._zoom)
        self._canvas.signal_box_drawn.connect(self._on_box_drawn)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._scroll.setWidget(self._canvas)
        self._scroll.setStyleSheet(f"background: {COLORS['bg_card']}; border: none;")
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.wheelEvent = self._on_scroll_wheel
        central_layout.addWidget(self._scroll)

        self.setCentralWidget(central)

        # ── Contenu du dock : sidebar + séparateur + résultats ────────────────
        self._sidebar_content = Sam3SidebarContent()
        self._sidebar_content.signal_text_prompt.connect(self._vm.apply_text_prompt)
        self._sidebar_content.signal_box_positive.connect(self._canvas.set_box_positive)
        self._sidebar_content.signal_confidence_changed.connect(self._vm.set_confidence)
        self._sidebar_content.signal_reset.connect(self._vm.reset_prompts)
        self._sidebar_content.signal_search_requested.connect(self._on_search_requested)
        self._sidebar_content.signal_box_search_requested.connect(self._on_box_search_requested)
        self._sidebar_content.signal_search_cancel.connect(self._vm.cancel_search)

        self._results_panel = SearchResultsPanel(folder=self._vm._gallery_vm.current_folder)
        self._results_panel.signal_image_clicked.connect(self._on_result_clicked)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {COLORS['border']};")

        dock_content = QWidget()
        dock_layout = QVBoxLayout(dock_content)
        dock_layout.setContentsMargins(0, 0, 0, 0)
        dock_layout.setSpacing(0)
        dock_layout.addWidget(self._sidebar_content, stretch=1)
        dock_layout.addWidget(sep)
        dock_layout.addWidget(self._results_panel)

        scroll_dock = QScrollArea()
        scroll_dock.setWidget(dock_content)
        scroll_dock.setWidgetResizable(True)
        scroll_dock.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_dock.setStyleSheet("border: none;")

        dock = QDockWidget("Contrôles SAM3", self)
        dock.setObjectName("dock_sam3_controls")
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        dock.setWidget(scroll_dock)
        dock.setMinimumWidth(300)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

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
        bar_w.setStyleSheet(f"background: {COLORS['bg_primary']};border-bottom: 1px solid {COLORS['border']};")
        return bar_w

    # ── Connexion ViewModel → View ────────────────────────────────────────────

    def _connect_vm(self) -> None:
        vm = self._vm
        sb = self._sidebar_content

        vm.signal_model_loading.connect(lambda: sb.set_status("⏳ Chargement du modèle…"))
        vm.signal_model_ready.connect(self._on_model_ready)
        vm.signal_model_error.connect(lambda e: sb.set_status(f"❌ Erreur modèle : {e}"))
        vm.signal_encoding.connect(lambda: sb.set_busy(True, "Encodage de l'image…"))
        vm.signal_encoded.connect(self._on_encoded)
        vm.signal_encoding_error.connect(lambda e: sb.set_status(f"❌ Encodage : {e}"))
        vm.signal_segmenting.connect(lambda: sb.set_busy(True, "Segmentation en cours…"))
        vm.signal_overlay_ready.connect(self._on_overlay_ready)
        vm.signal_segment_error.connect(lambda e: sb.set_status(f"❌ Segmentation : {e}"))
        vm.signal_resetting.connect(lambda: sb.set_busy(True, "Réinitialisation…"))
        vm.signal_reset_done.connect(self._on_reset_done)

        # Recherche (texte ou box)
        vm.signal_search_started.connect(self._on_search_started)
        vm.signal_search_progress.connect(self._results_panel.update_progress)
        vm.signal_search_match.connect(self._results_panel.add_result)
        vm.signal_search_finished.connect(self._on_search_finished)
        vm.signal_search_cancelled.connect(self._on_search_cancelled)
        vm.signal_search_error.connect(lambda e: sb.set_status(f"❌ Recherche : {e}"))

        # Stratégie active
        vm.signal_box_search_strategy.connect(self._on_box_search_strategy)

        # Mode attente : synchronise checkbox → panel dès le départ
        sb.signal_wait_mode_changed.connect(self._results_panel.set_wait_mode)

    # ── Initialisation image ──────────────────────────────────────────────────

    def _init_image(self) -> None:
        if self._vm.is_model_loaded:
            self._vm.encode_image(self._pixmap, self._img_path)
        else:
            self._sidebar_content.set_status("⏳ Chargement du modèle en cours…")
            if not self._vm.is_busy:
                self._vm.load_model()

    # ── Slots ViewModel → View ────────────────────────────────────────────────

    def _on_model_ready(self) -> None:
        self._sidebar_content.set_status("✅ Modèle prêt")
        if not self._vm.is_image_encoded:
            self._vm.encode_image(self._pixmap, self._img_path)

    def _on_encoded(self) -> None:
        self._sidebar_content.set_ready(True)
        self._sidebar_content.set_status("✅ Prêt — saisissez un prompt ou dessinez une boîte")

    def _on_overlay_ready(self, overlay: MaskOverlay) -> None:
        self._sidebar_content.set_ready(True)
        n = len(overlay.masks)
        self._sidebar_content.set_status(f"✅ {n} objet(s) trouvé(s)")
        self._canvas.set_overlay(overlay)

    def _on_reset_done(self) -> None:
        self._canvas.clear_overlay()
        self._sidebar_content.set_ready(True)
        self._sidebar_content.set_status("✅ Prompts réinitialisés")

    def _on_box_search_strategy(self, strategy_name: str) -> None:
        """Informe la sidebar de la stratégie active lors d'une recherche par box."""
        label = _STRATEGY_LABELS.get(strategy_name, strategy_name)
        self._sidebar_content.set_status(f"🔍 Recherche par box — stratégie : {label}")

    # ── Slots recherche globale ───────────────────────────────────────────────

    def _on_search_requested(self, text: str, threshold: float) -> None:
        """Relaie la demande de recherche texte globale (SAM3) au ViewModel."""
        self._results_panel.set_folder(self._vm._gallery_vm.current_folder)
        self._results_panel.set_wait_mode(self._sidebar_content.current_wait_mode())
        self._vm.search_objects(text, threshold)

    def _on_box_search_requested(self, embed_threshold: float, sam3_threshold: float) -> None:
        """Relaie la demande de recherche par box au ViewModel."""
        box = self._sidebar_content.get_last_box()
        if box is None:
            self._sidebar_content.set_status("⚠️ Aucune box disponible.")
            return

        x0, y0, x1, y1 = box
        strategy = self._sidebar_content.current_strategy()

        self._results_panel.set_folder(self._vm._gallery_vm.current_folder)
        self._results_panel.set_wait_mode(self._sidebar_content.current_wait_mode())
        self._vm.search_from_box(
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
            img_w=self._img_w,
            img_h=self._img_h,
            pixmap=self._pixmap,
            strategy_name=strategy,
            threshold=embed_threshold,
            sam3_threshold=sam3_threshold,
        )

    def _on_search_started(self, total: int) -> None:
        self._sidebar_content.set_searching(True)
        self._sidebar_content.set_status(f"🔍 Analyse de {total} image(s)…")
        self._results_panel.start_search(total)

    def _on_search_finished(self, matched: list) -> None:
        self._sidebar_content.set_searching(False)
        n = len(matched)
        self._sidebar_content.set_status(f"✅ Recherche terminée — {n} correspondance(s)")
        self._results_panel.finish_search(matched)

    def _on_search_cancelled(self) -> None:
        self._sidebar_content.set_searching(False)
        self._sidebar_content.set_status("⛔ Recherche annulée")
        self._results_panel.show_cancelled()

    def _on_result_clicked(self, img_name: str) -> None:
        """Charge l'image cliquée dans le canvas et la sélectionne dans la galerie."""
        folder = self._vm._gallery_vm.current_folder
        if not folder:
            return
        img_path = os.path.join(folder, img_name)
        pixmap = QPixmap(img_path)
        if pixmap.isNull():
            return

        self._pixmap = pixmap
        self._img_path = img_path
        self._img_w = pixmap.width()
        self._img_h = pixmap.height()
        self._canvas.set_base_pixmap(pixmap)
        self._canvas.set_zoom(self._zoom)
        self.setWindowTitle(img_name)

        # Invalide la box mémorisée (elle concerne l'ancienne image)
        self._sidebar_content._last_box = None
        self._sidebar_content.btn_search_box.setEnabled(False)

        if self._vm.is_model_loaded and not self._vm.is_busy:
            self._vm.encode_image(pixmap, img_path)
            self._sidebar_content.set_status(f"⏳ Encodage de {img_name}…")

    # ── Slots UI → ViewModel ──────────────────────────────────────────────────

    def _on_box_drawn(self, x0: float, y0: float, x1: float, y1: float) -> None:
        """Appelé quand l'utilisateur finit de dessiner une box.

        Déclenche la segmentation SAM3 courante ET mémorise les coordonnées
        pour une éventuelle recherche par box.
        """
        positive = self._sidebar_content.is_positive_mode()
        # Segmentation de l'image courante (comportement original)
        self._vm.apply_box_prompt(x0, y0, x1, y1, self._img_w, self._img_h, positive)
        # Mémorisation pour la recherche par box
        self._sidebar_content.set_last_box(x0, y0, x1, y1)

    # ── Zoom ──────────────────────────────────────────────────────────────────

    def _apply_zoom(self, zoom: float) -> None:
        self._zoom = max(0.05, min(10.0, zoom))
        self._canvas.set_zoom(self._zoom)
        self._lbl_zoom.setText(f"{int(self._zoom * 100)}%")

    def _on_scroll_wheel(self, event) -> None:
        delta = 0.1 if event.angleDelta().y() > 0 else -0.1
        self._apply_zoom(self._zoom + delta)
