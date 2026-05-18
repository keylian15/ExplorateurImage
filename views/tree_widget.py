from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from models.tree.search_tree import SearchTree


class SearchNodeLabel(QLabel):
    """Label cliquable représentant un noeud de l'arbre de recherche."""

    clicked = pyqtSignal(str)  # node_id

    def __init__(self, text: str, node_id: str, is_root: bool = False, is_current: bool = False, depth: int = 0, parent=None):
        super().__init__(parent)
        self._node_id = node_id
        self._is_root = is_root
        self.setText(text)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        if is_root:
            self.setStyleSheet("color: #9ca3af;font-size: 11px;font-style: italic;padding: 2px 0px;")
        else:
            indent = depth * 12
            bg = "#1e293b" if is_current else "transparent"
            border_left = f"border-left: 2px solid {'#3b82f6' if is_current else '#374151'};"
            self.setStyleSheet(f"color: {'#e5e7eb' if is_current else '#9ca3af'};font-size: 12px;padding: 3px 6px;margin-left: {indent}px;background: {bg};border-radius: 3px;{border_left}")
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip(f"Naviguer vers : {text}")

    def mousePressEvent(self, event):
        if not self._is_root and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._node_id)
        super().mousePressEvent(event)


class TreeViewWidget(QWidget):
    """Composant visuel de l'arbre de recherche.

    Affiche la racine en haut, puis les noeuds enfants indentés.
    Chaque noeud affiche le texte de la requête associée.
    """

    node_clicked = pyqtSignal(str)  # node_id

    def __init__(self, tree: SearchTree, parent=None):
        super().__init__(parent)
        self.tree = tree

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Zone scrollable pour l'arbre
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("border: none; background: transparent;")
        self._scroll.setMaximumHeight(300)

        self._content = QWidget()
        self._content.setStyleSheet("background: transparent;")
        self._tree_layout = QVBoxLayout(self._content)
        self._tree_layout.setContentsMargins(0, 0, 0, 0)
        self._tree_layout.setSpacing(2)
        self._tree_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._scroll.setWidget(self._content)
        root_layout.addWidget(self._scroll)

        self.refresh()

    def refresh(self):
        """Reconstruit l'affichage de l'arbre."""
        # Vider le layout
        while self._tree_layout.count():
            item = self._tree_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if self.tree.root is None:
            placeholder = QLabel("Aucune recherche sauvegardée")
            placeholder.setStyleSheet("color: #4b5563; font-size: 11px; font-style: italic; padding: 4px;")
            self._tree_layout.addWidget(placeholder)
            return

        # Noeud racine
        root_lbl = SearchNodeLabel(
            text="Historique",
            node_id=self.tree.root.id,
            is_root=True,
        )
        self._tree_layout.addWidget(root_lbl)

        # Séparateur sous la racine
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #1f2937; margin: 2px 0px;")
        self._tree_layout.addWidget(sep)

        # Enfants récursifs (on skip la racine __root__)
        def add_children(node, depth: int):
            for child in node.children:
                is_current = child == self.tree.current
                query_text = child.query if hasattr(child, "query") else child.id
                lbl = SearchNodeLabel(
                    text=query_text,
                    node_id=child.id,
                    is_root=False,
                    is_current=is_current,
                    depth=depth,
                )
                lbl.clicked.connect(self.node_clicked)
                self._tree_layout.addWidget(lbl)

                if child.children:
                    add_children(child, depth + 1)

        add_children(self.tree.root, depth=0)

        # Stretch pour pousser vers le haut
        self._tree_layout.addStretch()
