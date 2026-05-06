"""
views/style_tab.py

Onglet "Thème" : éditeur visuel de la palette COLORS.

Chaque entrée du dictionnaire COLORS est présentée avec :
  - un label lisible en français
  - un aperçu de la couleur actuelle (carré coloré cliquable)
  - la valeur hexadécimale éditable
  - un QColorDialog pour choisir graphiquement

Les modifications sont appliquées en temps réel au stylesheet Qt
et persistées dans colors.json via color_repository.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QColorDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from models import color_repository
from styles import get_stylesheet

# ── Labels lisibles en français ───────────────────────────────────────────────

_LABELS: dict[str, tuple[str, str]] = {
    # clé: (label affiché, description courte)
    "bg_primary": ("Fond principal", "Arrière-plan de la fenêtre"),
    "bg_secondary": ("Fond secondaire", "Panneaux, barres"),
    "bg_card": ("Fond carte", "Cartes, docks, onglets"),
    "bg_input": ("Fond champ de saisie", "Inputs, textareas"),
    "bg_hover": ("Fond survol", "Hover des éléments"),
    "text_primary": ("Texte principal", "Texte courant"),
    "text_secondary": ("Texte secondaire", "Labels, sous-titres"),
    "text_muted": ("Texte atténué", "Placeholders"),
    "text_disabled": ("Texte désactivé", "Boutons désactivés"),
    "accent": ("Accent", "Bleu principal, focus"),
    "accent_hover": ("Accent survol", "Hover des accents"),
    "accent_pressed": ("Accent pressé", "Clic sur accents"),
    "success": ("Succès", "Vert, images indexées"),
    "warning": ("Avertissement", "Orange"),
    "error": ("Erreur", "Rouge"),
    "info": ("Info", "Bleu info"),
    "border": ("Bordure", "Séparateurs, contours"),
    "border_focus": ("Bordure focus", "Contour au focus"),
    "thumb_placeholder": ("Placeholder thumbnail", "Fond cellule en attente"),
    "thumb_loading_text": ("Texte chargement", "« … » pendant le chargement"),
    "selection_border": ("Bordure sélection", "Contour image sélectionnée"),
    "indexed_dot": ("Point indexé", "Pastille verte « indexé »"),
}

# Groupes pour organiser visuellement les lignes
_GROUPS: list[tuple[str, list[str]]] = [
    ("Fonds", ["bg_primary", "bg_secondary", "bg_card", "bg_input", "bg_hover"]),
    ("Texte", ["text_primary", "text_secondary", "text_muted", "text_disabled"]),
    ("Accent", ["accent", "accent_hover", "accent_pressed"]),
    ("États", ["success", "warning", "error", "info"]),
    ("Bordures", ["border", "border_focus"]),
    ("Thumbnails & Galerie", ["thumb_placeholder", "thumb_loading_text", "selection_border", "indexed_dot"]),
]


# ═════════════════════════════════════════════════════════════════════════════
#  Widget "swatch + hex input" pour une seule couleur
# ═════════════════════════════════════════════════════════════════════════════


class ColorRow(QWidget):
    """Ligne d'édition pour une couleur : swatch + champ hex."""

    changed = pyqtSignal(str, str)  # (key, new_hex)

    def __init__(self, key: str, hex_color: str, parent=None):
        super().__init__(parent)
        self._key = key
        self._hex = hex_color.strip()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Swatch cliquable
        self._swatch = QLabel()
        self._swatch.setFixedSize(28, 28)
        self._swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        self._swatch.setToolTip("Cliquer pour choisir une couleur")
        self._swatch.mousePressEvent = lambda _e: self.open_picker()
        self.update_swatch(self._hex)
        layout.addWidget(self._swatch)

        # Champ hex
        self._edit = QLineEdit(self._hex)
        self._edit.setFixedWidth(90)
        self._edit.setMaxLength(7)
        self._edit.setPlaceholderText("#rrggbb")
        self._edit.textChanged.connect(self.on_text_changed)
        layout.addWidget(self._edit)

    def update_swatch(self, hex_color: str):
        """Met à jour la couleur du swatch.

        Args:
            hex_color (str): Couleur au format hexa."""
        color = QColor(hex_color)
        if color.isValid():
            # Bordure contrastée pour les couleurs sombres
            border_col = "#555" if color.lightness() < 128 else "#999"
            self._swatch.setStyleSheet(f"background-color: {hex_color};border: 1px solid {border_col};border-radius: 4px;")

    def on_text_changed(self, text: str):
        """Déclenche le signal si la valeur hex est valide.

        Args:
            text (str): Nouvelle valeur hex."""
        if QColor(text).isValid():
            self._hex = text
            self.update_swatch(text)
            self.changed.emit(self._key, text)

    def open_picker(self):
        """Ouvre le QColorDialog."""
        initial = QColor(self._hex) if QColor(self._hex).isValid() else QColor("#ffffff")
        color = QColorDialog.getColor(initial, self, "Choisir une couleur")
        if color.isValid():
            hex_val = color.name()  # "#rrggbb"
            self._edit.setText(hex_val)  # déclenche on_text_changed

    def set_color(self, hex_color: str):
        """Met à jour la couleur depuis l'extérieur.

        Args:
            hex_color (str): Nouvelle valeur hex."""
        self._edit.blockSignals(True)
        self._edit.setText(hex_color)
        self._hex = hex_color
        self.update_swatch(hex_color)
        self._edit.blockSignals(False)

    @property
    def current_hex(self) -> str:
        """Retourne la valeur hex.

        Returns:
            str: Valeur hex."""
        return self._hex


# ═════════════════════════════════════════════════════════════════════════════
#  Onglet principal
# ═════════════════════════════════════════════════════════════════════════════


class StyleTab(QWidget):
    """Onglet éditeur de thème visuel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._colors: dict[str, str] = color_repository.load()
        self._rows: dict[str, ColorRow] = {}

        self.build_ui()

    # ── Construction ──────────────────────────────────────────────────────────

    def build_ui(self):
        """Construit le widget."""
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        # ── Titre + boutons ───────────────────────────────────────────────────
        header = QHBoxLayout()

        title = QLabel("Éditeur de thème")
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        header.addWidget(title)
        header.addStretch()

        self._btn_reset = QPushButton("↺ Réinitialiser")
        self._btn_reset.setToolTip("Revenir aux couleurs par défaut")
        self._btn_reset.clicked.connect(self.reset_defaults)
        header.addWidget(self._btn_reset)

        self._btn_apply = QPushButton("✓ Appliquer")
        self._btn_apply.setToolTip("Appliquer et sauvegarder le thème")
        self._btn_apply.clicked.connect(self.apply)
        header.addWidget(self._btn_apply)

        root.addLayout(header)

        # Ligne de séparation
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(sep)

        # ── Zone scrollable ───────────────────────────────────────────────────
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(4, 4, 4, 4)
        content_layout.setSpacing(16)

        # ── Groupes ───────────────────────────────────────────────────────────
        for group_name, keys in _GROUPS:
            group_widget = self.build_group(group_name, keys)
            content_layout.addWidget(group_widget)

        content_layout.addStretch()
        scroll_area.setWidget(content)
        root.addWidget(scroll_area)

        # ── Barre de statut ───────────────────────────────────────────────────
        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet("color: #9ca3af; font-size: 11px;")
        self._lbl_status.setAlignment(Qt.AlignmentFlag.AlignRight)
        root.addWidget(self._lbl_status)

    def build_group(self, title: str, keys: list[str]) -> QWidget:
        """Construit un groupe de couleurs avec titre.

        Args:
            title (str): Titre du groupe.
            keys (list[str]): Liste des clés de couleurs.

        Returns:
            QWidget: Groupe de couleurs.
        """
        group = QWidget()
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Titre du groupe
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("font-weight: 600; font-size: 12px; color: #9ca3af;text-transform: uppercase; letter-spacing: 1px;")
        layout.addWidget(lbl_title)

        # Grille de couleurs
        grid = QGridLayout()
        grid.setContentsMargins(8, 4, 0, 4)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)

        for row_idx, key in enumerate(keys):
            label_text, description = _LABELS.get(key, (key, ""))
            hex_val = self._colors.get(key, "#000000")

            # Label nom
            lbl = QLabel(label_text)
            lbl.setToolTip(f"{description}\n→ clé : {key}")
            lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            lbl.setMinimumWidth(180)
            grid.addWidget(lbl, row_idx, 0)

            # Description courte
            lbl_desc = QLabel(description)
            lbl_desc.setStyleSheet("color: #6b7280; font-size: 11px;")
            lbl_desc.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            grid.addWidget(lbl_desc, row_idx, 1)

            # Swatch + champ hex
            color_row = ColorRow(key, hex_val)
            color_row.changed.connect(self.on_color_changed)
            grid.addWidget(color_row, row_idx, 2)
            self._rows[key] = color_row

        layout.addLayout(grid)

        # Séparateur de groupe
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #1f2937;")
        layout.addWidget(sep)

        return group

    # ── Logique ───────────────────────────────────────────────────────────────

    def on_color_changed(self, key: str, hex_val: str):
        """Met à jour le dict interne quand une couleur change.

        Args:
            key (str): Clé de la couleur modifiée.
            hex_val (str): Nouvelle valeur hexadécimale de la couleur."""
        self._colors[key] = hex_val
        self._lbl_status.setText(f"Modifié : {_LABELS.get(key, (key,))[0]} → {hex_val}  (non sauvegardé)")

    def apply(self):
        """Sauvegarde et applique le thème à toute l'application."""
        color_repository.save(self._colors)

        # Recharge le module styles avec les nouvelles couleurs
        import styles

        styles.COLORS.update(self._colors)

        # Applique le stylesheet Qt global
        app = QApplication.instance()
        if app:
            app.setStyleSheet(get_stylesheet())

        self._lbl_status.setText("✅ Thème sauvegardé et appliqué.")

    def reset_defaults(self):
        """Réinitialise toutes les couleurs aux valeurs par défaut."""
        defaults = color_repository.defaults()
        for key, row in self._rows.items():
            row.set_color(defaults.get(key, "#000000"))
        self._colors = dict(defaults)
        self._lbl_status.setText("Couleurs réinitialisées — cliquez « Appliquer » pour confirmer.")
