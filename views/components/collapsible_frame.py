"""CollapsibleFrame (PyQt6).

Widget conteneur réutilisable avec en-tête cliquable permettant de replier ou déplier
dynamiquement son contenu.

Responsabilités principales :
- Fournir un cadre visuel stylisé (bordure, fond, séparateur)
- Afficher un titre avec une flèche indiquant l'état (ouvert / fermé)
- Gérer l'interaction utilisateur pour replier / déplier la zone de contenu
- Exposer un layout interne pour ajouter des widgets enfants
- Encapsuler une logique UI réutilisable pour structurer des panneaux pliables
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from styles import COLORS


class CollapsibleFrame(QWidget):
    """QFrame avec titre cliquable pour replier/déplier le contenu."""

    def __init__(self, title: str) -> None:
        """Initialise le QFrame.

        Args:
            title (str): Le titre a mettre.

        """
        super().__init__()
        c = COLORS
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Frame extérieur (bordure) ──────────────────────────────────────
        self._frame = QFrame()
        self._frame.setFrameShape(QFrame.Shape.StyledPanel)
        self._frame.setObjectName("zone_frame")
        self._frame.setStyleSheet(
            f"QFrame#zone_frame {{ border: 1px solid {c['border_focus']}; border-radius: 6px; background: {c['bg_card']}; }}"
            f"QFrame#zone_frame > QLabel {{ border: none; background: transparent; }}"
            f"QFrame#zone_frame > QFrame {{ border: none; background: transparent; }}"
        )
        frame_layout = QVBoxLayout(self._frame)
        frame_layout.setContentsMargins(10, 8, 10, 10)
        frame_layout.setSpacing(8)
        root.addWidget(self._frame)

        # ── Header cliquable ───────────────────────────────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)

        self._arrow = QLabel("▼")
        self._arrow.setFixedWidth(16)
        self._arrow.setStyleSheet(f"font-size: 10px; color: {c['accent']}; border: none; background: transparent;")
        header.addWidget(self._arrow)

        lbl = QLabel(title)
        lbl.setStyleSheet(f"font-size: 12px; color: {c['text_primary']}; font-weight: 700; border: none; background: transparent;")
        header.addWidget(lbl)
        header.addStretch()

        # Widget cliquable qui contient le header
        self._header_widget = QWidget()
        self._header_widget.setLayout(header)
        self._header_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header_widget.setStyleSheet("background: transparent;")
        self._header_widget.mousePressEvent = lambda _: self.toggle()
        frame_layout.addWidget(self._header_widget)

        # ── Séparateur ─────────────────────────────────────────────────────
        self._sep = QFrame()
        self._sep.setFrameShape(QFrame.Shape.HLine)
        self._sep.setStyleSheet(f"color: {c['border']}; border-top: 1px solid {c['border']};")
        frame_layout.addWidget(self._sep)

        # ── Contenu (dépliable) ────────────────────────────────────────────
        self._content_widget = QWidget()
        self._content_widget.setStyleSheet("background: transparent;")
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(8)
        frame_layout.addWidget(self._content_widget)

        self._collapsed = False

    def toggle(self) -> None:
        """Bascule entre replié et déplié."""
        self._collapsed = not self._collapsed
        self._content_widget.setVisible(not self._collapsed)
        self._sep.setVisible(not self._collapsed)
        self._arrow.setText("▶" if self._collapsed else "▼")

    def content_layout(self) -> QVBoxLayout:
        """Retourne le layout dans lequel ajouter les widgets enfants."""
        return self._content_layout
