"""Sélecteur de langue visuel, dynamique selon les langues présentes dans i18n.json.

Ce composant affiche une grille de « cartes » cliquables, une par langue
disponible (déterminée dynamiquement via I18nManager.available_languages()).
Cliquer sur une carte différente de la langue active émet un signal et
déclenche le redémarrage de l'application pour appliquer la nouvelle langue
partout (y compris les libellés construits une seule fois au démarrage).

Contenu :
 - LanguageCard : carte cliquable représentant une langue
 - LanguageSelector : grille de LanguageCard + label de section

Responsabilités :
 1. Lister dynamiquement les langues disponibles depuis I18nManager
 2. Afficher la langue active de manière visuellement distincte
 3. Émettre un signal lors du choix d'une nouvelle langue
 4. Ne contenir aucune logique de persistance ou de redémarrage
    (déléguée à la fenêtre principale / main.py)
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from services.i18n_manager import I18nManager
from styles import (
    COLORS,
    lang_card_style,
    lang_check_style,
    lang_flag_style,
    lang_name_style,
    style_presset_style,
)


class LanguageCard(QWidget):
    """Carte cliquable représentant une langue disponible."""

    signal_clicked = pyqtSignal(str)  # code langue

    def __init__(self, code: str, label: str, selected: bool, parent=None):
        """Args:
        code (str): Code de la langue (ex: "fr", "en").
        label (str): Libellé affiché (ex: "🇫🇷 Français").
        selected (bool): True si cette langue est la langue active.

        """
        super().__init__(parent)
        self._code = code
        self._selected = selected

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("class", "lang-card")
        self.setFixedWidth(120)
        self.setFixedHeight(84)
        self.setStyleSheet(lang_card_style(selected))

        # Sépare emoji et nom pour les styler indépendamment
        parts = label.split(" ", 1)
        flag = parts[0] if parts else "🌐"
        name = parts[1] if len(parts) > 1 else code.upper()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 6)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # ── Ligne supérieure : drapeau + coche si actif ──────────────────────
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(4)

        flag_lbl = QLabel(flag)
        flag_lbl.setStyleSheet(lang_flag_style())
        flag_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addStretch()
        top_row.addWidget(flag_lbl)
        top_row.addStretch()
        layout.addLayout(top_row)

        # ── Nom de la langue ──────────────────────────────────────────────────
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(lang_name_style(selected))
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name_lbl)

        # ── Coche "actif" ─────────────────────────────────────────────────────
        check_lbl = QLabel("✓ Actif" if selected else " ")
        check_lbl.setStyleSheet(lang_check_style())
        check_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(check_lbl)

        self.setToolTip(f"Passer l'application en {name}")

    def mousePressEvent(self, event):
        """Émet signal_clicked si la carte n'est pas déjà sélectionnée.

        Args:
            event (QMouseEvent): Événement de clic.

        """
        if event.button() == Qt.MouseButton.LeftButton and not self._selected:
            self.signal_clicked.emit(self._code)
        super().mousePressEvent(event)


class LanguageSelector(QWidget):
    """Grille de cartes de langue, construite dynamiquement depuis i18n.json."""

    # Émis quand l'utilisateur choisit une nouvelle langue différente de l'actuelle.
    signal_language_chosen = pyqtSignal(str)  # nouveau code langue

    def __init__(self, translator: I18nManager, parent=None):
        """Args:
        translator (I18nManager): Gestionnaire de traduction (fournit la
            langue active et la liste des langues disponibles).

        """
        super().__init__(parent)
        self.translator = translator
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        lbl_title = QLabel(self.translator.tr("Langue de l'application"))
        lbl_title.setStyleSheet(style_presset_style())
        layout.addWidget(lbl_title)

        lbl_hint = QLabel(self.translator.tr("Le changement de langue redémarre l'application."))
        lbl_hint.setStyleSheet(f"font-size: 11px; color: {COLORS['text_muted']}; font-style: italic;")
        layout.addWidget(lbl_hint)

        grid_row = QHBoxLayout()
        grid_row.setSpacing(10)

        for code in self.translator.available_languages():
            label = self.translator.language_label(code)
            selected = code == self.translator.lang
            card = LanguageCard(code, label, selected)
            card.signal_clicked.connect(self.signal_language_chosen.emit)
            grid_row.addWidget(card)

        grid_row.addStretch()
        layout.addLayout(grid_row)
