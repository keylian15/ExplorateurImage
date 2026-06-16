"""Composant UI QLabel interactif avec gestion des clics.

Ce widget étend QLabel pour permettre l'ajout de callbacks sur les clics gauche
et droit de la souris, facilitant l'interaction directe dans l'interface.

Contenu :
 - Détection des clics souris (gauche et droit)
 - Exécution de callbacks personnalisés
 - Initialisation flexible (texte ou parent QWidget)

Responsabilités :
 1. Étendre QLabel avec une interaction souris personnalisée
 2. Déclencher une action sur clic gauche si un callback est défini
 3. Déclencher une action sur clic droit si un callback est défini
 4. Gérer proprement l'initialisation selon le type d'argument fourni
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QWidget


class ClickableLabel(QLabel):
    """Class qui représente une QLabel avec callbacks clic gauche et droit."""

    def __init__(self, text_or_parent=None, parent=None):
        """Args:
        text_or_parent (str | QWidget, optional): Texte du QLabel ou QWidget parent. Defaults to None.
        parent (QWidget, optional): QWidget parent. Defaults to None.
        """
        if isinstance(text_or_parent, str):
            super().__init__(text_or_parent, parent)
        elif isinstance(text_or_parent, QWidget):
            super().__init__(text_or_parent)
        else:
            super().__init__(parent)
        self.rightClicked = None
        self.leftClicked = None

    def mousePressEvent(self, event):
        """Detect le clic gauche et droit.

        Args:
            event (QMouseEvent): Event de clic.

        """
        if event.button() == Qt.MouseButton.RightButton:
            if self.rightClicked:
                self.rightClicked()
        elif event.button() == Qt.MouseButton.LeftButton:
            if self.leftClicked:
                self.leftClicked()
