from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget


class TreeViewWidget(QWidget):
    def __init__(self, tree):
        super().__init__()

        self.tree = tree

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        self.refresh()

    def refresh(self):

        # clear layout
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if self.tree.root is None:
            self.layout.addWidget(QLabel("Empty tree"))
            return

        def add_node(node, depth=0):

            label = node.query if hasattr(node, "query") else node.id

            q = QLabel("  " * depth + label)

            # root styling simple
            if node == self.tree.root:
                q.setStyleSheet("font-weight: bold;")

            self.layout.addWidget(q)

            for child in node.children:
                add_node(child, depth + 1)

        add_node(self.tree.root)
