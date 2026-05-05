"""
views/detail_widget.py

Contenu du dock "Détails de l'image" :
  - aperçu cliquable (plein écran)
  - champs description / mots-clés
  - bouton auto-compléter
  - grille des images similaires

Pure View : toute la logique est dans DetailViewModel.
"""
from __future__ import annotations
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QLineEdit,
    QScrollArea, QGridLayout, QSpinBox,
)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, QTimer

from viewmodels.detail_vm import DetailViewModel
from views.components.clickable_label import ClickableLabel
from views.components.fullscreen_dialog import FullscreenDialog
from styles import (
    image_preview_style, neighbor_thumb_style,
    score_label_style, section_title_style,
)


class DetailWidget(QWidget):
    def __init__(self, detail_vm: DetailViewModel, parent=None):
        super().__init__(parent)
        self._vm = detail_vm
        self._current_pixmap: QPixmap | None = None

        self._build_ui()
        self._connect_vm()

    # ── Construction ─────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── Titre + renommage ─────────────────────────────────────────────────
        title_row = QHBoxLayout()
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Nom de l'image…")
        title_row.addWidget(self.title_edit)

        self.btn_rename = QPushButton("✏️")
        self.btn_rename.setFixedWidth(32)
        self.btn_rename.setToolTip("Renommer le fichier")
        title_row.addWidget(self.btn_rename)
        layout.addLayout(title_row)

        # ── Aperçu ────────────────────────────────────────────────────────────
        self.preview = ClickableLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedHeight(200)
        self.preview.setStyleSheet(image_preview_style())
        self.preview.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview.setToolTip("Cliquer pour voir en plein écran")
        self.preview.leftClicked  = self._open_fullscreen
        self.preview.rightClicked = self._open_fullscreen
        layout.addWidget(self.preview)

        # ── Description ───────────────────────────────────────────────────────
        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText("Description…")
        layout.addWidget(self.desc_edit)

        # ── Mots-clés ─────────────────────────────────────────────────────────
        self.keywords_edit = QLineEdit()
        self.keywords_edit.setPlaceholderText("mot1, mot2, mot3")
        layout.addWidget(self.keywords_edit)

        # ── Bouton auto-compléter ─────────────────────────────────────────────
        self.btn_autocomplete = QPushButton("Auto-compléter")
        layout.addWidget(self.btn_autocomplete)

        self.lbl_loading = QLabel("Analyse en cours…")
        self.lbl_loading.setVisible(False)
        layout.addWidget(self.lbl_loading)

        # ── En-tête voisins ───────────────────────────────────────────────────
        neighbors_hdr = QHBoxLayout()
        self.lbl_neighbors = QLabel("Images similaires")
        self.lbl_neighbors.setStyleSheet(section_title_style())
        self.spin_k = QSpinBox()
        self.spin_k.setMinimum(1)
        self.spin_k.setMaximum(100)
        self.spin_k.setValue(self._vm.k_neighbors)
        neighbors_hdr.addWidget(self.lbl_neighbors)
        neighbors_hdr.addWidget(self.spin_k)
        neighbors_hdr.addStretch()
        layout.addLayout(neighbors_hdr)

        # ── Grille voisins ────────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setFixedHeight(220)
        scroll.setWidgetResizable(True)
        self._neighbors_widget = QWidget()
        self._neighbors_grid   = QGridLayout()
        self._neighbors_grid.setSpacing(4)
        self._neighbors_widget.setLayout(self._neighbors_grid)
        scroll.setWidget(self._neighbors_widget)
        layout.addWidget(scroll)

    def _connect_vm(self):
        # View → ViewModel
        self.btn_rename.clicked.connect(
            lambda: self._vm.rename(self.title_edit.text().strip())
        )
        self.btn_autocomplete.clicked.connect(self._vm.auto_complete)
        self.spin_k.valueChanged.connect(self._on_k_changed)

        # Debounce sauvegarde
        self._save_timer = QTimer()
        self._save_timer.setInterval(300)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._schedule_vm_save)

        self.desc_edit.textChanged.connect(lambda: self._save_timer.start())
        self.keywords_edit.textChanged.connect(lambda: self._save_timer.start())

        # ViewModel → View
        self._vm.preview_ready.connect(self._on_preview_ready)
        self._vm.metadata_loaded.connect(self._on_metadata_loaded)
        self._vm.neighbors_ready.connect(self._display_neighbors)
        self._vm.save_started.connect(lambda: self.lbl_loading.setVisible(True))
        self._vm.save_finished.connect(lambda: self.lbl_loading.setVisible(False))
        self._vm.save_error.connect(lambda msg: (
            self.lbl_loading.setVisible(False),
            print(f"[SAVE ERROR] {msg}"),
        ))
        self._vm.autocomplete_started.connect(self._on_autocomplete_started)
        self._vm.autocomplete_finished.connect(self._on_autocomplete_finished)
        self._vm.autocomplete_error.connect(self._on_autocomplete_error)
        self._vm.rename_done.connect(self._on_rename_done)
        self._vm.rename_error.connect(self._on_rename_error)

    # ── Slots ViewModel → View ────────────────────────────────────────────────

    def _on_preview_ready(self, pixmap: QPixmap, img_name: str):
        self._current_pixmap = pixmap
        if pixmap.isNull():
            self.preview.clear()
        else:
            scaled = pixmap.scaled(
                self.preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.preview.setPixmap(scaled)

    def _on_metadata_loaded(self, img_name: str, desc: str, keywords: list):
        self.title_edit.setText(img_name)
        self.title_edit.setStyleSheet("")
        self.title_edit.setToolTip("")

        # Bloquer les signaux pour ne pas déclencher la sauvegarde
        self.desc_edit.blockSignals(True)
        self.keywords_edit.blockSignals(True)
        self.desc_edit.setText(desc)
        self.keywords_edit.setText(", ".join(keywords))
        self.desc_edit.blockSignals(False)
        self.keywords_edit.blockSignals(False)

    def _display_neighbors(self, neighbors: dict):
        # Vider la grille
        for i in reversed(range(self._neighbors_grid.count())):
            w = self._neighbors_grid.itemAt(i).widget()
            if w:
                w.deleteLater()

        if not neighbors:
            self.lbl_neighbors.setText("Images similaires (aucune)")
            return

        self.lbl_neighbors.setText(f"Images similaires (top {len(neighbors)})")
        folder = self._vm._folder
        THUMB  = 80
        col, row = 0, 0

        for neighbor_name, score in neighbors.items():
            if not folder:
                continue
            path   = os.path.join(folder, neighbor_name)
            pixmap = QPixmap(path)
            if pixmap.isNull():
                continue

            pixmap_full   = QPixmap(path)
            pixmap_scaled = pixmap.scaled(
                THUMB, THUMB,
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
            thumb.setToolTip("Clic gauche : sélectionner | Clic droit : plein écran")
            thumb.leftClicked  = lambda n=neighbor_name: self._vm._gallery_vm.select_image(n)
            thumb.rightClicked = lambda p=pixmap_full: self._open_fullscreen_with(p)

            score_lbl = QLabel(f"{score:.2f}")
            score_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            score_lbl.setStyleSheet(score_label_style())

            cell_layout.addWidget(thumb)
            cell_layout.addWidget(score_lbl)
            cell.setLayout(cell_layout)
            self._neighbors_grid.addWidget(cell, row, col)

            col += 1
            if col == 3:
                col, row = 0, row + 1

    def _on_autocomplete_started(self):
        self.lbl_loading.setVisible(True)
        self.btn_autocomplete.setEnabled(False)

    def _on_autocomplete_finished(self, desc: str, keywords: list):
        self.desc_edit.setText(desc)
        self.keywords_edit.setText(", ".join(keywords))
        self.lbl_loading.setVisible(False)
        self.btn_autocomplete.setEnabled(True)

    def _on_autocomplete_error(self, msg: str):
        self.title_edit.setText(f"Erreur : {msg}")
        self.lbl_loading.setVisible(False)
        self.btn_autocomplete.setEnabled(True)

    def _on_rename_done(self, new_name: str):
        self.title_edit.setText(new_name)
        self.title_edit.setStyleSheet("")
        self.title_edit.setToolTip("")

    def _on_rename_error(self, msg: str):
        self.title_edit.setStyleSheet("border: 1px solid red;")
        self.title_edit.setToolTip(f"❌ {msg}")

    def _on_k_changed(self, value: int):
        self._vm.k_neighbors = value
        self._vm.refresh_neighbors()

    # ── Plein écran ───────────────────────────────────────────────────────────

    def _open_fullscreen(self):
        self._open_fullscreen_with(self._current_pixmap)

    def _open_fullscreen_with(self, pixmap: QPixmap | None):
        if not pixmap or pixmap.isNull():
            return
        title = self.title_edit.text()
        dlg   = FullscreenDialog(pixmap, title, self)
        dlg.exec()

    # ── Sauvegarde déclenchée par l'UI ────────────────────────────────────────

    def _schedule_vm_save(self):
        desc     = self.desc_edit.toPlainText()
        keywords = [k.strip() for k in self.keywords_edit.text().split(",") if k.strip()]
        self._vm.schedule_save(desc, keywords)
