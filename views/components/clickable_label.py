"""
views/components/clickable_label.py

QLabel avec callbacks clic gauche et droit.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QWidget


class ClickableLabel(QLabel):
    def __init__(self, text_or_parent=None, parent=None):
        if isinstance(text_or_parent, str):
            super().__init__(text_or_parent, parent)
        elif isinstance(text_or_parent, QWidget):
            super().__init__(text_or_parent)
        else:
            super().__init__(parent)
        self.rightClicked = None
        self.leftClicked = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            if self.rightClicked:
                self.rightClicked()
        elif event.button() == Qt.MouseButton.LeftButton:
            if self.leftClicked:
                self.leftClicked()
