"""Onglet de personnalisation du thème visuel de l'application.

Responsabilités :
 1. Afficher les thèmes prédéfinis sous forme de cartes cliquables
 2. Permettre l'édition couleur par couleur via swatch et champ hexadécimal
 3. Charger un preset sans sauvegarder (prévisualisation)
 4. Sauvegarder les couleurs dans colors.json et appliquer le stylesheet Qt en live
 5. Réinitialiser le thème vers le preset par défaut
 6. Permettre le changement de langue et déclencher le redémarrage de l'application
"""

from __future__ import annotations

from PyQt6 import QtGui
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
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

import styles
from models import color_repository
from services.i18n_manager import I18nManager
from styles import get_stylesheet, style_label_name_style, style_label_subname_style, style_presset_style, style_separator_style, style_tittle_style
from views.components.language_selector import LanguageSelector

# ── Labels lisibles en français ───────────────────────────────────────────────

_LABELS: dict[str, tuple[str, str]] = {
    "bg_primary": ("Fond principal", "Arrière-plan de la fenêtre"),
    "bg_secondary": ("Fond secondaire", "Panneaux, barres"),
    "bg_card": ("Fond carte", "Cartes, docks, onglets"),
    "bg_input": ("Fond champ de saisie", "Inputs, textareas"),
    "bg_hover": ("Fond survol", "Hover des éléments"),
    "text_primary": ("Texte principal", "Texte courant"),
    "text_secondary": ("Texte secondaire", "Labels, sous-titres"),
    "text_muted": ("Texte atténué", "Placeholders"),
    "text_disabled": ("Texte désactivé", "Boutons désactivés"),
    "accent": ("Accent", "Couleur principale, focus"),
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
    "indexed_dot": ("Point indexé", "Pastille « indexé »"),
}

_GROUPS: list[tuple[str, list[str]]] = [
    ("Fonds", ["bg_primary", "bg_secondary", "bg_card", "bg_input", "bg_hover"]),
    ("Texte", ["text_primary", "text_secondary", "text_muted", "text_disabled"]),
    ("Accent", ["accent", "accent_hover", "accent_pressed"]),
    ("États", ["success", "warning", "error", "info"]),
    ("Bordures", ["border", "border_focus"]),
    ("Thumbnails & Galerie", ["thumb_placeholder", "thumb_loading_text", "selection_border", "indexed_dot"]),
]

# ── Thèmes prédéfinis ─────────────────────────────────────────────────────────

PRESETS: dict[str, dict] = {
    "Bleu nuit": {
        # Thème par défaut — bleu nuit profond, accent bleu
        "bg_primary": "#0f172a",
        "bg_secondary": "#111827",
        "bg_card": "#1f2937",
        "bg_input": "#111827",
        "bg_hover": "#1e293b",
        "text_primary": "#e5e7eb",
        "text_secondary": "#9ca3af",
        "text_muted": "#6b7280",
        "text_disabled": "#4b5563",
        "accent": "#3b82f6",
        "accent_hover": "#60a5fa",
        "accent_pressed": "#2563eb",
        "success": "#22c55e",
        "warning": "#f59e0b",
        "error": "#ef4444",
        "info": "#3b82f6",
        "border": "#1f2937",
        "border_focus": "#3b82f6",
        "thumb_placeholder": "#1f2937",
        "thumb_loading_text": "#6b7280",
        "selection_border": "#3b82f6",
        "indexed_dot": "#22c55e",
    },
    "Noir minuit": {
        # Thème sombre pur — noir charbon, accent violet
        "bg_primary": "#0a0a0a",
        "bg_secondary": "#111111",
        "bg_card": "#1a1a1a",
        "bg_input": "#111111",
        "bg_hover": "#222222",
        "text_primary": "#f0f0f0",
        "text_secondary": "#a0a0a0",
        "text_muted": "#606060",
        "text_disabled": "#404040",
        "accent": "#a855f7",
        "accent_hover": "#c084fc",
        "accent_pressed": "#7c3aed",
        "success": "#22c55e",
        "warning": "#f59e0b",
        "error": "#ef4444",
        "info": "#a855f7",
        "border": "#222222",
        "border_focus": "#a855f7",
        "thumb_placeholder": "#1a1a1a",
        "thumb_loading_text": "#505050",
        "selection_border": "#a855f7",
        "indexed_dot": "#22c55e",
    },
    "Blanc givré": {
        # Thème clair — fond blanc cassé, accent teal
        "bg_primary": "#f8fafc",
        "bg_secondary": "#f1f5f9",
        "bg_card": "#ffffff",
        "bg_input": "#ffffff",
        "bg_hover": "#e2e8f0",
        "text_primary": "#0f172a",
        "text_secondary": "#475569",
        "text_muted": "#94a3b8",
        "text_disabled": "#cbd5e1",
        "accent": "#0d9488",
        "accent_hover": "#0f766e",
        "accent_pressed": "#115e59",
        "success": "#16a34a",
        "warning": "#d97706",
        "error": "#dc2626",
        "info": "#0d9488",
        "border": "#e2e8f0",
        "border_focus": "#0d9488",
        "thumb_placeholder": "#e2e8f0",
        "thumb_loading_text": "#94a3b8",
        "selection_border": "#0d9488",
        "indexed_dot": "#16a34a",
    },
}

# Métadonnées visuelles pour chaque preset
_PRESET_META: dict[str, tuple[str, str]] = {
    "Bleu nuit": ("🌙", "Sombre · Bleu acier"),
    "Noir minuit": ("⬛", "Sombre · Violet profond"),
    "Blanc givré": ("☀️", "Clair  · Teal"),
}

_MAX_LIGHTNESS = 128  # seuil pour déterminer si une couleur est "sombre" ou "claire" (0-255)

# ═════════════════════════════════════════════════════════════════════════════
#  Carte de preset cliquable
# ═════════════════════════════════════════════════════════════════════════════


class PresetCard(QWidget):
    """Bouton carte représentant un thème prédéfini avec swatches de prévisualisation."""

    signal_clicked = pyqtSignal(str)  # nom du preset

    def __init__(self, name: str, colors: dict[str, str]) -> None:
        """Initialise la carte de preset.

        Args:
            name (str): Nom du preset.
            colors (dict[str, str]): Dictionnaire des couleurs du preset.

        """
        super().__init__()
        self._name = name
        emoji, subtitle = _PRESET_META.get(name, ("🎨", ""))

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"Cliquer pour charger le thème « {name} »")
        self.setFixedWidth(210)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # ── Swatches de prévisualisation ──────────────────────────────────────
        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(4)
        swatch_keys = ["bg_primary", "bg_card", "accent", "success", "text_primary"]
        for key in swatch_keys:
            hex_val = colors.get(key, "#888888")
            dot = QLabel()
            dot.setFixedSize(20, 20)
            is_dark = QColor(hex_val).lightness() < _MAX_LIGHTNESS
            border = "#444" if is_dark else "#ccc"
            dot.setStyleSheet(f"background-color: {hex_val}; border-radius: 10px;border: 1px solid {border};")
            swatch_row.addWidget(dot)
        swatch_row.addStretch()
        layout.addLayout(swatch_row)

        # ── Nom ───────────────────────────────────────────────────────────────
        lbl_name = QLabel(f"{emoji}  {name}")
        lbl_name.setStyleSheet(style_label_name_style())
        layout.addWidget(lbl_name)

        # ── Sous-titre ────────────────────────────────────────────────────────
        lbl_sub = QLabel(subtitle)
        lbl_sub.setStyleSheet(style_label_subname_style())
        layout.addWidget(lbl_sub)

        # Style de la carte
        bg = colors.get("bg_card", "#1f2937")
        border = colors.get("border", "#374151")
        self.setProperty("class", "preset-card")
        self.setStyleSheet(
            f"""
            QWidget[class="preset-card"] {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
            QWidget[class="preset-card"]:hover {{
                border: 1px solid #3b82f6;
            }}
            """
        )

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        """Émet le signal de clic si le bouton gauche est pressé.

        Args:
            event (QtGui.QMouseEvent): Événement de souris.

        """
        if event.button() == Qt.MouseButton.LeftButton:
            self.signal_clicked.emit(self._name)
        super().mousePressEvent(event)


# ═════════════════════════════════════════════════════════════════════════════
#  Widget "swatch + hex input" pour une seule couleur
# ═════════════════════════════════════════════════════════════════════════════


class ColorRow(QWidget):
    """Ligne d'édition pour une couleur : swatch + champ hex."""

    signal_changed = pyqtSignal(str, str)  # (key, new_hex)

    def __init__(self, key: str, hex_color: str) -> None:
        """Initialise le widget.

        Args:
            key (str): Clé de la couleur (ex: "bg_primary").
            hex_color (str): Valeur hexadécimale initiale (ex: "#1f2937").

        """
        super().__init__()
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

    def update_swatch(self, hex_color: str) -> None:
        """Met à jour la couleur du swatch.

        Args:
            hex_color (str): Couleur au format hexa.

        """
        color = QColor(hex_color)
        if color.isValid():
            # Bordure contrastée pour les couleurs sombres
            border_col = "#555" if color.lightness() < _MAX_LIGHTNESS else "#999"
            self._swatch.setStyleSheet(f"background-color: {hex_color};border: 1px solid {border_col};border-radius: 4px;")

    def on_text_changed(self, text: str) -> None:
        """Déclenche le signal si la valeur hex est valide.

        Args:
            text (str): Nouvelle valeur hex.

        """
        if QColor(text).isValid():
            self._hex = text
            self.update_swatch(text)
            self.signal_changed.emit(self._key, text)

    def open_picker(self) -> None:
        """Ouvre le QColorDialog."""
        initial = QColor(self._hex) if QColor(self._hex).isValid() else QColor("#ffffff")
        color = QColorDialog.getColor(initial, self, "Choisir une couleur")
        if color.isValid():
            self._edit.setText(color.name())

    def set_color(self, hex_color: str) -> None:
        """Met à jour la couleur depuis l'extérieur.

        Args:
            hex_color (str): Nouvelle valeur hex.

        """
        self._edit.blockSignals(True)
        self._edit.setText(hex_color)
        self._hex = hex_color
        self.update_swatch(hex_color)
        self._edit.blockSignals(False)

    @property
    def current_hex(self) -> str:
        """Retourne la valeur hex.

        Returns:
            str: Valeur hex.

        """
        return self._hex


# ═════════════════════════════════════════════════════════════════════════════
#  Onglet principal
# ═════════════════════════════════════════════════════════════════════════════


class StyleTab(QWidget):
    """Onglet Éditeur de paramètres visuel."""

    def __init__(self, translator: I18nManager) -> None:
        """Initialise le widget.

        Args:
            translator (I18nManager): Gestionnaire de traduction.

        """
        super().__init__()
        self.translator = translator
        self._colors: dict[str, str] = color_repository.load()
        self._rows: dict[str, ColorRow] = {}

        self.build_ui()

    # ── Construction ──────────────────────────────────────────────────────────

    def build_ui(self) -> None:
        """Construit le widget."""
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        # ── En-tête ───────────────────────────────────────────────────────────
        header = QHBoxLayout()
        title = QLabel(self.translator.tr("Éditeur de paramètres"))
        title.setStyleSheet(style_tittle_style())
        header.addWidget(title)
        header.addStretch()

        self._btn_reset = QPushButton(self.translator.tr("↺ Réinitialiser"))
        self._btn_reset.setToolTip(self.translator.tr("Revenir aux couleurs par défaut"))
        self._btn_reset.clicked.connect(self.reset_defaults)
        header.addWidget(self._btn_reset)

        self._btn_apply = QPushButton(self.translator.tr("✓ Appliquer"))
        self._btn_apply.setToolTip(self.translator.tr("Appliquer et sauvegarder le thème"))
        self._btn_apply.clicked.connect(self.apply)
        header.addWidget(self._btn_apply)

        root.addLayout(header)

        sep0 = QFrame()
        sep0.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(sep0)

        # ── Section langue ────────────────────────────────────────────────────
        self._lang_selector = LanguageSelector(self.translator)
        self._lang_selector.signal_language_chosen.connect(self.on_language_chosen)
        root.addWidget(self._lang_selector)

        sep_lang = QFrame()
        sep_lang.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(sep_lang)

        # ── Section thèmes prédéfinis ─────────────────────────────────────────
        lbl_presets = QLabel(self.translator.tr("Thèmes prédéfinis"))
        lbl_presets.setStyleSheet(style_presset_style())
        root.addWidget(lbl_presets)

        presets_row = QHBoxLayout()
        presets_row.setSpacing(10)
        for preset_name, preset_colors in PRESETS.items():
            card = PresetCard(preset_name, preset_colors)
            card.signal_clicked.connect(self.load_preset)
            presets_row.addWidget(card)
        presets_row.addStretch()
        root.addLayout(presets_row)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(sep1)

        # ── Personnalisation fine ─────────────────────────────────────────────
        lbl_custom = QLabel(self.translator.tr("Personnalisation fine"))
        lbl_custom.setStyleSheet(style_presset_style())
        root.addWidget(lbl_custom)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(4, 4, 4, 4)
        content_layout.setSpacing(16)

        for group_name, keys in _GROUPS:
            content_layout.addWidget(self.build_group(group_name, keys))

        content_layout.addStretch()
        scroll_area.setWidget(content)
        root.addWidget(scroll_area)

        # ── Barre de statut ───────────────────────────────────────────────────
        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet(style_label_subname_style())
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
            color_row.signal_changed.connect(self.on_color_changed)
            grid.addWidget(color_row, row_idx, 2)
            self._rows[key] = color_row

        layout.addLayout(grid)

        # Séparateur de groupe
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(style_separator_style())
        layout.addWidget(sep)

        return group

    # ── Logique ───────────────────────────────────────────────────────────────

    def on_color_changed(self, key: str, hex_val: str) -> None:
        """Met à jour le dict interne quand une couleur change.

        Args:
            key (str): Clé de la couleur modifiée.
            hex_val (str): Nouvelle valeur hexadécimale de la couleur.

        """
        self._colors[key] = hex_val
        self._lbl_status.setText(self.translator.tr("Modifié : {label} → {hex_val} (non sauvegardé)").format(label=_LABELS.get(key, (key,))[0], hex_val=hex_val))

    def load_preset(self, name: str) -> None:
        """Charge un thème prédéfini dans tous les champs sans sauvegarder.

        Args:
            name (str): Nom du preset à charger.

        """
        preset = PRESETS.get(name, {})
        for key, row in self._rows.items():
            if key in preset:
                row.set_color(preset[key])
        self._colors.update(preset)
        self._lbl_status.setText(self.translator.tr("Thème « {name} » chargé — cliquez « ✓ Appliquer » pour confirmer.").format(name=name))

    def apply(self) -> None:
        """Sauvegarde colors.json et applique le stylesheet Qt en live."""
        color_repository.save(self._colors)

        # Recharge le module styles avec les nouvelles couleurs
        styles.COLORS.update(self._colors)

        # Applique le stylesheet Qt global
        app = QApplication.instance()
        if app:
            app.setStyleSheet(get_stylesheet())

        self._lbl_status.setText(self.translator.tr("✅ Thème sauvegardé et appliqué."))

    def reset_defaults(self) -> None:
        """Charge le thème par défaut (Bleu nuit) sans sauvegarder."""
        self.load_preset("Bleu nuit")
        self._lbl_status.setText(self.translator.tr("Thème « Bleu nuit » restauré — cliquez « ✓ Appliquer » pour confirmer."))

    def on_language_chosen(self, lang_code: str) -> None:
        """Change la langue active, persiste le choix et redémarre l'application.

        Args:
            lang_code (str): Nouveau code de langue (ex: "en", "fr").

        """
        self.translator.set_language(lang_code)
        self._lbl_status.setText(self.translator.tr("🌐 Langue changée — redémarrage…"))

        from main import restart_app  # noqa: PLC0415 Pour éviter les imports circulaires.

        # Petit délai pour laisser le label s'afficher avant le redémarrage.
        QTimer.singleShot(150, restart_app)
