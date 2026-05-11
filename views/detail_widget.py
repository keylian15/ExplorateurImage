"""
Panneau de détail d'une image dans l'interface de la galerie.

Ce composant constitue la vue dédiée à l'inspection et à l'édition des métadonnées
d'une image sélectionnée. Il permet d'afficher un aperçu, de modifier la description
et les mots-clés, de déclencher l'auto-complétion, de visualiser les images similaires
et d'épingler/désépingler une image.

Toute la logique métier est déléguée au ViewModel associé : ce widget ne gère que
l'affichage et la propagation des interactions utilisateur.

Contenu :
 - Aperçu cliquable de l'image avec ouverture plein écran
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
 5. Ouvrir une visualisation plein écran de l'image
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
from views.components.clickable_label import ClickableLabel
from views.components.fullscreen_dialog import FullscreenDialog


class DetailWidget(QWidget):
    """Class qui gere le widget de detail."""

    def __init__(self, detail_vm: DetailViewModel, parent=None):
        """
        Args:
            detail_vm (DetailViewModel): Le viewmodel de ce widget.
        """
        super().__init__(parent)
        self._vm = detail_vm
        self._current_pixmap: QPixmap | None = None

        self.build_ui()
        self.connect_vm()

    # ── Construction ─────────────────────────────────────────────────────────

    def build_ui(self):
        """Construit l'interface utilisateur."""
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
        self.preview.setToolTip("Cliquer pour voir en plein écran")
        self.preview.leftClicked = self.open_fullscreen
        self.preview.rightClicked = self.open_fullscreen
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
        """Connect la view au viewmodel."""
        # View → ViewModel
        self.btn_rename.clicked.connect(lambda: self._vm.rename(self.title_edit.text().strip()))
        self.btn_autocomplete.clicked.connect(self._vm.auto_complete)
        self.btn_pin.clicked.connect(self._vm.toggle_pin)
        self.spin_k.valueChanged.connect(self.on_k_changed)

        # Raccourci clavier
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
        self._vm.preview_ready.connect(self.on_preview_ready)
        self._vm.metadata_loaded.connect(self.on_metadata_loaded)
        self._vm.neighbors_ready.connect(self.display_neighbors)
        self._vm.save_started.connect(lambda: self.lbl_loading.setVisible(True))
        self._vm.save_finished.connect(lambda: self.lbl_loading.setVisible(False))
        self._vm.save_error.connect(
            lambda msg: (
                self.lbl_loading.setVisible(False),
                print(f"[SAVE ERROR] {msg}"),
            )
        )
        self._vm.autocomplete_started.connect(self.on_autocomplete_started)
        self._vm.autocomplete_finished.connect(self.on_autocomplete_finished)
        self._vm.autocomplete_error.connect(self.on_autocomplete_error)
        self._vm.rename_done.connect(self.on_rename_done)
        self._vm.rename_error.connect(self.on_rename_error)
        self._vm.pin_changed.connect(self.on_pin_changed)

    # ── Slots ViewModel → View ────────────────────────────────────────────────

    def on_preview_ready(self, pixmap: QPixmap, _img_name: str):
        """Callback appelé lorsque la preview est prête pour l'afficher.

        Args:
            pixmap (QPixmap): La pixmap à afficher.
            _img_name (str): Le nom de l'image."""
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

    def on_metadata_loaded(self, img_name: str, desc: str, keywords: list[str]):
        """Callback appelé lorsque les métadonnées sont chargées pour les afficher.

        Args:
            img_name (str): Le nom de l'image.
            desc (str): La description de l'image.
            keywords (list[str]): Les mots-clés de l'image.
        """
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

    def on_pin_changed(self, img_name: str, is_pinned: bool):
        """Met à jour le bouton 📌 selon l'état d'épinglage de l'image affichée.

        Args:
            img_name (str): Nom de l'image concernée.
            is_pinned (bool): True si l'image est épinglée.
        """
        # Ne mettre à jour le bouton que si c'est bien l'image actuellement affichée
        if img_name != self.title_edit.text():
            return

        # Bloquer le signal clicked pour éviter une boucle
        self.btn_pin.blockSignals(True)
        self.btn_pin.setChecked(is_pinned)
        self.btn_pin.blockSignals(False)

        if is_pinned:
            self.btn_pin.setToolTip("Désépingler cette image")
            self.btn_pin.setStyleSheet("color: #f59e0b;")  # orange = épinglé
        else:
            self.btn_pin.setToolTip("Épingler cette image")
            self.btn_pin.setStyleSheet("")

    def display_neighbors(self, neighbors: dict[str, float]):
        """Affiche les voisins de l'image.

        Args:
            neighbors (dict[str, float]): Les voisins de l'image.
        """
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
            thumb.setToolTip("Clic gauche : sélectionner | Clic droit : plein écran")
            thumb.leftClicked = lambda n=neighbor_name: self._vm._gallery_vm.select_image(n)
            thumb.rightClicked = lambda p=pixmap_full: self.open_fullscreen_with(p)

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

    def on_autocomplete_started(self):
        """Callback lorsque l'auto-completion est en cours."""
        self.lbl_loading.setVisible(True)
        self.btn_autocomplete.setEnabled(False)

    def on_autocomplete_finished(self, desc: str, keywords: list[str]):
        """Callback lorsque l'auto-completion est terminé.

        Args:
            desc (str): Description de l'image.
            keywords (list[str]): Mots-clés de l'image."""
        self.desc_edit.setText(desc)
        self.keywords_edit.setText(", ".join(keywords))
        self.lbl_loading.setVisible(False)
        self.btn_autocomplete.setEnabled(True)

    def on_autocomplete_error(self, msg: str):
        """Callback lorsque l'auto-completion échoue.

        Args:
            msg (str): Message d'erreur.
        """
        self.title_edit.setText(f"Erreur : {msg}")
        self.lbl_loading.setVisible(False)
        self.btn_autocomplete.setEnabled(True)

    def on_rename_done(self, new_name: str):
        """Met a jour le titre de l'item.

        Args:
            new_name (str): Nouveau nom de l'item."""
        self.title_edit.setText(new_name)
        self.title_edit.setStyleSheet("")
        self.title_edit.setToolTip("")

    def on_rename_error(self, msg: str):
        """Indique que la modification du titre a échoué."""
        self.title_edit.setStyleSheet(rename_error_style())
        self.title_edit.setToolTip(f"❌ {msg}")

    def on_k_changed(self, value: int):
        """Recharge les voisins lorsque k change."""
        self._vm.k_neighbors = value
        self._vm.refresh_neighbors()

    # ── Plein écran ───────────────────────────────────────────────────────────

    def open_fullscreen(self):
        """Ouvre l'image en plein écran."""
        self.open_fullscreen_with(self._current_pixmap)

    def open_fullscreen_with(self, pixmap: QPixmap | None):
        """Ouvre l'image donnée en plein écran.

        Args:
            pixmap (QPixmap): Image à afficher."""
        if not pixmap or pixmap.isNull():
            return
        title = self.title_edit.text()
        dlg = FullscreenDialog(pixmap, title, self)
        dlg.exec()

    # ── Sauvegarde déclenchée par l'UI ────────────────────────────────────────

    def schedule_vm_save(self):
        """Enregistre les données dans le modèle."""
        desc = self.desc_edit.toPlainText()
        keywords = [k.strip() for k in self.keywords_edit.text().split(",") if k.strip()]
        self._vm.schedule_save(desc, keywords)
