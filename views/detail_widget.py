"""
Panneau de détail d'une image dans l'interface de la galerie.

Ce composant constitue la vue dédiée à l'inspection et à l'édition des métadonnées
d'une image sélectionnée. Il permet d'afficher un aperçu, de modifier la description
et les mots-clés, de déclencher l'auto-complétion, de visualiser les images similaires
et d'épingler/désépingler une image.

Toute la logique métier est déléguée au ViewModel associé : ce widget ne gère que
l'affichage et la propagation des interactions utilisateur.

Le clic sur l'aperçu (gauche ou droit) ouvre désormais Sam3Dialog pour permettre
la segmentation interactive avec SAM3.

Contenu :
 - Aperçu cliquable de l'image avec ouverture Sam3Dialog
 - Champs d'édition (description, mots-clés, nom de fichier)
 - Bouton d'auto-complétion des métadonnées
 - Bouton 📌 d'épinglage/désépinglage
 - Grille des images similaires avec scores de proximité
 - Interaction temps réel avec le ViewModel via signaux Qt

Responsabilités :
 1. Afficher les métadonnées de l'image sélectionnée
 2. Permettre l'édition de la description, des mots-clés et du nom de fichier
 3. Déclencher les actions utilisateur (rename, auto-complétion, sauvegarde, pin)
 4. Afficher dynamiquement les images similaires et leurs scores
 5. Ouvrir Sam3Dialog pour la segmentation interactive
 6. Refléter l'état du ViewModel sans contenir de logique métier
"""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence, QPixmap
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from styles import (
    image_preview_style,
    neighbor_thumb_style,
    rename_error_style,
    score_label_style,
    section_title_style,
)
from viewmodels.detail_vm import DetailViewModel
from viewmodels.sam3_vm import Sam3ViewModel
from views.components.clickable_label import ClickableLabel
from views.components.sam3_dialog import Sam3Dialog


class DetailWidget(QWidget):
    """Panneau de détail d'une image sélectionnée."""

    def __init__(
        self,
        detail_vm: DetailViewModel,
        sam3_vm: Sam3ViewModel,
        parent=None,
    ):
        """
        Args:
            detail_vm: Le viewmodel de ce widget.
            sam3_vm: ViewModel SAM3 partagé du workspace.
        """
        super().__init__(parent)
        self._vm = detail_vm
        self._sam3_vm = sam3_vm
        self._current_pixmap: QPixmap | None = None
        self._current_img_path: str | None = None

        self.build_ui()
        self.connect_vm()

    # ── Construction ─────────────────────────────────────────────────────────

    def build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── Titre + renommage + épingle ───────────────────────────────────────
        title_row = QHBoxLayout()
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Nom de l'image…")
        title_row.addWidget(self.title_edit)

        self.btn_rename = QPushButton("✏️")
        self.btn_rename.setFixedWidth(32)
        self.btn_rename.setToolTip("Renommer le fichier")
        title_row.addWidget(self.btn_rename)

        self.btn_pin = QPushButton("📌")
        self.btn_pin.setFixedWidth(32)
        self.btn_pin.setToolTip("Épingler / désépingler cette image")
        self.btn_pin.setCheckable(True)
        title_row.addWidget(self.btn_pin)

        layout.addLayout(title_row)

        # ── Aperçu ────────────────────────────────────────────────────────────
        self.preview = ClickableLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedHeight(200)
        self.preview.setStyleSheet(image_preview_style())
        self.preview.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview.setToolTip("Clic : ouvrir dans SAM3 (segmentation interactive)")
        self.preview.leftClicked = self.open_sam3_dialog
        self.preview.rightClicked = self.open_sam3_dialog
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
        self._neighbors_grid = QGridLayout()
        self._neighbors_grid.setSpacing(4)
        self._neighbors_widget.setLayout(self._neighbors_grid)
        scroll.setWidget(self._neighbors_widget)
        layout.addWidget(scroll)

    def connect_vm(self):
        # View → ViewModel
        self.btn_rename.clicked.connect(lambda: self._vm.rename(self.title_edit.text().strip()))
        self.btn_autocomplete.clicked.connect(self._vm.auto_complete)
        self.btn_pin.clicked.connect(self._vm.toggle_pin)
        self.spin_k.valueChanged.connect(self.on_k_changed)

        action_pin = QAction("Search", self)
        action_pin.setShortcut(QKeySequence("Ctrl+E"))
        action_pin.triggered.connect(lambda: self._vm.toggle_pin())
        self.addAction(action_pin)

        # Debounce sauvegarde
        self._save_timer = QTimer()
        self._save_timer.setInterval(300)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.schedule_vm_save)

        self.desc_edit.textChanged.connect(lambda: self._save_timer.start())
        self.keywords_edit.textChanged.connect(lambda: self._save_timer.start())

        # ViewModel → View
        self._vm.signal_preview_ready.connect(self.on_signal_preview_ready)
        self._vm.signal_metadata_loaded.connect(self.on_signal_metadata_loaded)
        self._vm.signal_neighbors_ready.connect(self.display_neighbors)
        self._vm.signal_save_started.connect(lambda: self.lbl_loading.setVisible(True))
        self._vm.signal_save_finished.connect(lambda: self.lbl_loading.setVisible(False))
        self._vm.signal_save_error.connect(
            lambda msg: (
                self.lbl_loading.setVisible(False),
                print(f"[SAVE ERROR] {msg}"),
            )
        )
        self._vm.signal_autocomplete_started.connect(self.on_signal_autocomplete_started)
        self._vm.signal_autocomplete_finished.connect(self.on_signal_autocomplete_finished)
        self._vm.signal_autocomplete_error.connect(self.on_signal_autocomplete_error)
        self._vm.signal_rename_done.connect(self.on_signal_rename_done)
        self._vm.signal_rename_error.connect(self.on_signal_rename_error)
        self._vm.signal_pin_changed.connect(self.on_signal_pin_changed)

    # ── Slots ViewModel → View ────────────────────────────────────────────────

    def on_signal_preview_ready(self, pixmap: QPixmap, img_name: str):
        self._current_pixmap = pixmap
        # Conserve le chemin absolu pour Sam3Dialog
        folder = self._vm._folder
        self._current_img_path = os.path.join(folder, img_name) if folder else None

        if pixmap.isNull():
            self.preview.clear()
        else:
            scaled = pixmap.scaled(
                self.preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.preview.setPixmap(scaled)

    def on_signal_metadata_loaded(self, img_name: str, desc: str, keywords: list[str]):
        self.title_edit.setText(img_name)
        self.title_edit.setStyleSheet("")
        self.title_edit.setToolTip("")

        self.desc_edit.blockSignals(True)
        self.keywords_edit.blockSignals(True)
        self.desc_edit.setText(desc)
        self.keywords_edit.setText(", ".join(keywords))
        self.desc_edit.blockSignals(False)
        self.keywords_edit.blockSignals(False)

    def on_signal_pin_changed(self, img_name: str, is_pinned: bool):
        if img_name != self.title_edit.text():
            return
        self.btn_pin.blockSignals(True)
        self.btn_pin.setChecked(is_pinned)
        self.btn_pin.blockSignals(False)
        if is_pinned:
            self.btn_pin.setToolTip("Désépingler cette image")
            self.btn_pin.setStyleSheet("color: #f59e0b;")
        else:
            self.btn_pin.setToolTip("Épingler cette image")
            self.btn_pin.setStyleSheet("")

    def display_neighbors(self, neighbors: dict[str, float]):
        for i in reversed(range(self._neighbors_grid.count())):
            w = self._neighbors_grid.itemAt(i).widget()
            if w:
                w.deleteLater()

        if not neighbors:
            self.lbl_neighbors.setText("Images similaires (aucune)")
            return

        self.lbl_neighbors.setText(f"Images similaires (top {len(neighbors)})")
        folder = self._vm._folder
        THUMB = 80
        col, row = 0, 0

        for neighbor_name, score in neighbors.items():
            if not folder:
                continue
            path = os.path.join(folder, neighbor_name)
            pixmap = QPixmap(path)
            if pixmap.isNull():
                continue

            pixmap_full = QPixmap(path)
            pixmap_scaled = pixmap.scaled(
                THUMB,
                THUMB,
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
            thumb.setToolTip("Clic gauche : sélectionner | Clic droit : SAM3")
            thumb.leftClicked = lambda n=neighbor_name: self._vm._gallery_vm.select_image(n)
            thumb.rightClicked = lambda p=pixmap_full, np_=path: self._open_sam3_with(p, np_)

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

    def on_signal_autocomplete_started(self):
        self.lbl_loading.setVisible(True)
        self.btn_autocomplete.setEnabled(False)

    def on_signal_autocomplete_finished(self, desc: str, keywords: list[str]):
        self.desc_edit.setText(desc)
        self.keywords_edit.setText(", ".join(keywords))
        self.lbl_loading.setVisible(False)
        self.btn_autocomplete.setEnabled(True)

    def on_signal_autocomplete_error(self, msg: str):
        self.title_edit.setText(f"Erreur : {msg}")
        self.lbl_loading.setVisible(False)
        self.btn_autocomplete.setEnabled(True)

    def on_signal_rename_done(self, new_name: str):
        self.title_edit.setText(new_name)
        self.title_edit.setStyleSheet("")
        self.title_edit.setToolTip("")

    def on_signal_rename_error(self, msg: str):
        self.title_edit.setStyleSheet(rename_error_style())
        self.title_edit.setToolTip(f"❌ {msg}")

    def on_k_changed(self, value: int):
        self._vm.k_neighbors = value
        self._vm.refresh_neighbors()

    # ── SAM3 ─────────────────────────────────────────────────────────────────

    def open_sam3_dialog(self):
        """Ouvre Sam3Dialog pour l'image actuellement affichée."""
        self._open_sam3_with(self._current_pixmap, self._current_img_path)

    def _open_sam3_with(self, pixmap: QPixmap | None, img_path: str | None):
        if not pixmap or pixmap.isNull():
            return
        title = self.title_edit.text()
        dlg = Sam3Dialog(
            pixmap=pixmap,
            sam3_vm=self._sam3_vm,
            title=title,
            img_path=img_path,
            parent=self,
        )
        dlg.exec()

    # ── Sauvegarde ────────────────────────────────────────────────────────────

    def schedule_vm_save(self):
        desc = self.desc_edit.toPlainText()
        keywords = [k.strip() for k in self.keywords_edit.text().split(",") if k.strip()]
        self._vm.schedule_save(desc, keywords)
