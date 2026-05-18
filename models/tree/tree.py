"""
models/tree/tree.py

Arbre générique.

Cette classe gère :
- la structure globale
- le noeud courant
- la navigation
- l'ajout de noeuds
- la recherche de noeuds

Aucune logique métier spécifique ne doit être ajoutée ici.
"""

from __future__ import annotations

from models.tree.tree_node import TreeNode


class Tree:
    """Arbre générique."""

    def __init__(self) -> None:
        """Initialise un arbre vide."""

        self.root: TreeNode | None = None
        self.current: TreeNode | None = None
        self._nodes: dict[str, TreeNode] = {}

    @property
    def is_empty(self) -> bool:
        """Indique si l'arbre est vide."""

        return self.root is None

    def clear(self) -> None:
        """Vide complètement l'arbre."""

        self.root = None
        self.current = None
        self._nodes.clear()

    def add_root(self, node: TreeNode) -> None:
        """
        Définit la racine de l'arbre.

        Args:
            node (TreeNode): Noeud racine.

        Raises:
            ValueError:
                Si une racine existe déjà.
        """

        if self.root is not None:
            raise ValueError("L'arbre possède déjà une racine.")

        self.root = node
        self.current = node

        self._nodes[node.id] = node

    def push(self, node: TreeNode) -> None:
        """
        Ajoute un noeud enfant au noeud courant
        et le définit comme noeud courant.

        Args:
            node (TreeNode): Noeud à ajouter.

        Raises:
            ValueError:
                Si l'arbre ne possède pas de racine.
        """

        if self.current is None:
            raise ValueError("Impossible de push sans racine.")

        self.current.add_child(node)

        self._nodes[node.id] = node

        self.current = node

    def back(self) -> TreeNode | None:
        """
        Revient au parent du noeud courant.

        Returns:
            TreeNode | None:
                Nouveau noeud courant.
        """

        if self.current is None:
            return None

        if self.current.parent is None:
            return self.current

        self.current = self.current.parent

        return self.current

    def set_current(self, node_id: str) -> TreeNode | None:
        """
        Définit le noeud courant.

        Args:
            node_id (str): ID du noeud.

        Returns:
            TreeNode | None:
                Noeud trouvé.
        """

        node = self._nodes.get(node_id)

        if node is not None:
            self.current = node
        else:
            print("noeud non trouvé : ", node_id)

        return node

    def get_node(self, node_id: str) -> TreeNode | None:
        """
        Récupère un noeud par son ID.

        Args:
            node_id (str): ID du noeud.

        Returns:
            TreeNode | None
        """

        return self._nodes.get(node_id)

    def contains(self, node_id: str) -> bool:
        """
        Indique si un noeud existe.

        Args:
            node_id (str): ID du noeud.

        Returns:
            bool
        """

        return node_id in self._nodes

    def iter_nodes(self):
        """
        Itère sur tous les noeuds.

        Yields:
            TreeNode
        """

        yield from self._nodes.values()

    def to_dict(self) -> dict:
        """
        Sérialise l'arbre.

        Returns:
            dict
        """

        return {
            "root_id": (self.root.id if self.root else None),
            "current_id": (self.current.id if self.current else None),
            "nodes": [node.to_dict() for node in self.iter_nodes()],
        }

    def print_tree(self) -> None:
        """
        Affiche tout l'arbre de manière hiérarchique.
        """

        if self.root is None:
            print("[Tree] empty")
            return

        print("\n[Tree] full structure:\n")

        def print_node(node, depth=0):

            label = getattr(node, "query", None) or node.id

            prefix = "  " * depth

            current_marker = ""
            if node == self.current:
                current_marker = "  <-- CURRENT"

            print(f"{prefix}- {label} ({node.id}){current_marker}")

            for child in node.children:
                print_node(child, depth + 1)

        print_node(self.root)
