"""
views/gallery_widget.py

Widget galerie : barre de recherche, QListView en mode icônes,
barre de progression pour le batch, contrôle du zoom (Ctrl+molette).

Ne contient aucune logique métier : tout passe par GalleryViewModel
et AutocompleteViewModel.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QProgressBar, QLabel,
    QListView, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QSize, QTimer, QModelIndex
from PyQt6.QtGui import QPixmap

from viewmodels.gallery_vm import GalleryViewModel
from viewmodels.autocomplete_vm import AutocompleteViewModel
from models.image_model import IMG_NAME_ROLE
from styles import THUMB
from views.components.fullscreen_dialog import FullscreenDialog

PREFETCH_ROWS = THUMB["prefetch_rows"]


class GalleryWidget(QWidget):
    def __init__(self, gallery_vm: GalleryViewModel,
                 autocomplete_vm: AutocompleteViewModel,
                 parent=None):
        super().__init__(parent)
        self._gvm  = gallery_vm
        self._avm  = autocomplete_vm

        self._build_ui()
        self._connect_vm()

    # ── Construction ─────────────────────────────────────────────────────────

    def _build_ui(self):
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

        self.search_bar = QLineEdit()
        self.search_bar.setObjectName("search_bar")
        self.search_bar.setPlaceholderText("Rechercher…")
        top.addWidget(self.search_bar, stretch=1)

        self.btn_cancel = QPushButton("Annuler")
        self.btn_cancel.setVisible(False)
        top.addWidget(self.btn_cancel)

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
        self.list_view.setToolTip(
            "Clic gauche : sélectionner | Clic droit : voir en plein écran"
        )
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
        self._prefetch_timer.timeout.connect(self._prefetch_visible)

    def _connect_vm(self):
        # View → ViewModel
        self.search_bar.textChanged.connect(self._gvm.schedule_search)
        self.btn_batch.clicked.connect(self._avm.start)
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.list_view.clicked.connect(self._on_item_clicked)
        self.list_view.customContextMenuRequested.connect(self._on_right_click)
        self.list_view.verticalScrollBar().valueChanged.connect(
            lambda: self._prefetch_timer.start()
        )

        # ViewModel → View
        self._gvm.cell_size_changed.connect(self._on_cell_size_changed)

        self._avm.started.connect(self._on_batch_started)
        self._avm.progress.connect(self._on_batch_progress)
        self._avm.finished.connect(self._on_batch_finished)

    # ── Slots View → ViewModel ─────────────────────────────────────────────

    def _on_item_clicked(self, index: QModelIndex):
        img_name = index.data(IMG_NAME_ROLE)
        if img_name:
            self._gvm.select_image(img_name)

    def _on_right_click(self, pos):
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

    def _on_cancel(self):
        self._avm.cancel()
        self.btn_cancel.setEnabled(False)
        self.progress_label.setText("⛔ Annulation…")

    # ── Slots ViewModel → View ─────────────────────────────────────────────

    def _on_cell_size_changed(self, size: int):
        self.list_view.setGridSize(QSize(size + 8, size + 8))
        self.list_view.doItemsLayout()
        QTimer.singleShot(50, self._prefetch_visible)

    def _on_batch_started(self, total: int):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.progress_label.setText(f"0 / {total} — en attente…")
        self.progress_label.setVisible(True)
        self.btn_batch.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(True)

    def _on_batch_progress(self, done: int, total: int, label: str):
        self.progress_bar.setValue(done)
        self.progress_label.setText(f"{done} / {total} — {label}")

    def _on_batch_finished(self, cancelled: bool):
        total = self.progress_bar.maximum()
        self.progress_label.setText(
            "⛔ Annulé" if cancelled else f"✅ Terminé — {total} images traitées"
        )
        self.btn_batch.setEnabled(True)
        self.btn_cancel.setVisible(False)
        QTimer.singleShot(4000, lambda: (
            self.progress_bar.setVisible(False),
            self.progress_label.setVisible(False),
        ))

    # ── Zoom (Ctrl + molette) ─────────────────────────────────────────────────

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self._gvm.zoom_in()
            else:
                self._gvm.zoom_out()
        else:
            super().wheelEvent(event)

    # ── Prefetch ──────────────────────────────────────────────────────────────

    def _prefetch_visible(self):
        vp   = self.list_view.viewport()
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
