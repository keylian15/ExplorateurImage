"""
views/components/fullscreen_dialog.py

Dialog de visualisation plein écran avec zoom molette et boutons.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from styles import fullscreen_bar_style


class FullscreenDialog(QDialog):
    def __init__(self, pixmap: QPixmap, title: str = "", parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self.setWindowTitle(title)

        from PyQt6.QtWidgets import QApplication

        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(screen.width(), screen.height())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Barre du haut ─────────────────────────────────────────────────────
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 4, 8, 4)

        self._btn_out = QPushButton("🔍 -")
        self._btn_in = QPushButton("🔍 +")
        self._btn_reset = QPushButton("↺ Reset")
        self._lbl_zoom = QLabel("100%")
        self._lbl_zoom.setFixedWidth(55)
        self._lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)

        for btn in (self._btn_out, self._btn_in, self._btn_reset):
            btn.setFixedHeight(28)

        bar.addWidget(self._btn_out)
        bar.addWidget(self._lbl_zoom)
        bar.addWidget(self._btn_in)
        bar.addWidget(self._btn_reset)
        bar.addStretch()

        bar_w = QWidget()
        bar_w.setLayout(bar)
        bar_w.setStyleSheet(fullscreen_bar_style())
        bar_w.setFixedHeight(40)
        layout.addWidget(bar_w)

        # ── Zone image ────────────────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setStyleSheet("background: #121212; border: none;")
        self._scroll.setWidgetResizable(False)

        self._lbl_img = QLabel()
        self._lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_img.setStyleSheet("background: #121212;")
        self._scroll.setWidget(self._lbl_img)
        layout.addWidget(self._scroll)

        # ── Zoom ──────────────────────────────────────────────────────────────
        self._factor = 1.0
        STEP, MIN, MAX = 0.15, 0.1, 10.0

        dpr = self._lbl_img.devicePixelRatio()

        def render(f):
            w = int(dpr * screen.width() * f)
            h = int(dpr * screen.height() * f)
            scaled = pixmap.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            self._lbl_img.setPixmap(scaled)
            self._lbl_img.resize(scaled.width() // int(dpr), scaled.height() // int(dpr))
            self._lbl_zoom.setText(f"{int(f * 100)}%")

        def zoom_in():
            self._factor = min(MAX, self._factor + STEP)
            render(self._factor)

        def zoom_out():
            self._factor = max(MIN, self._factor - STEP)
            render(self._factor)

        def zoom_reset():
            self._factor = 1.0
            render(1.0)

        self._scroll.wheelEvent = lambda e: zoom_in() if e.angleDelta().y() > 0 else zoom_out()
        self._btn_in.clicked.connect(zoom_in)
        self._btn_out.clicked.connect(zoom_out)
        self._btn_reset.clicked.connect(zoom_reset)

        render(0.75)
