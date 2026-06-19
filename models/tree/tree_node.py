"""models/tree/tree_node.py.

Noeud générique d'arbre.

Cette classe représente uniquement la structure d'un arbre :
- parent
- enfants
- id

Elle ne contient aucune logique métier spécifique.
Les spécialisations (SearchNode, HistoryNode, etc.)
hériteront de cette classe.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4


class TreeNode:
    """Noeud générique d'arbre."""

    def __init__(
        self,
        node_id: str | None = None,
        parent: TreeNode | None = None,
    ) -> None:
        """Initialise un nœud de l'arbre.

        Crée un nœud avec un identifiant unique et un parent optionnel.
        Si aucun identifiant n'est fourni, un UUID est généré automatiquement.

        Args:
            node_id (str | None, optional): Identifiant unique du nœud. Généré automatiquement si None.
            parent (TreeNode | None, optional): Nœud parent. None si le nœud est racine.

        """
        self.id: str = node_id or str(uuid4())
        self.parent: TreeNode | None = parent
        self.children: list[TreeNode] = []

    @property
    def has_parent(self) -> bool:
        """Indique si le noeud possède un parent."""
        return self.parent is not None

    @property
    def has_children(self) -> bool:
        """Indique si le noeud possède des enfants."""
        return len(self.children) > 0

    def add_child(self, child: TreeNode) -> None:
        """Ajoute un enfant au noeud.

        Args:
            child (TreeNode): Noeud enfant.

        """
        child.parent = self
        self.children.append(child)

    def remove_child(self, child: TreeNode) -> None:
        """Retire un enfant du noeud.

        Args:
            child (TreeNode): Noeud à retirer.

        """
        if child in self.children:
            self.children.remove(child)
            child.parent = None

    def clear_children(self) -> None:
        """Retire tous les enfants."""
        for child in self.children:
            child.parent = None

        self.children.clear()

    def is_root(self) -> bool:
        """Indique si le noeud est la racine."""
        return self.parent is None

    def depth(self) -> int:
        """Renvoie la profondeur du noeud.

        Returns:
            int: Profondeur dans l'arbre.

        """
        depth = 0
        current = self.parent

        while current is not None:
            depth += 1
            current = current.parent

        return depth

    def iter_parents(self) -> Iterator[TreeNode]:
        """Itérer sur les parents du nœud.

        Yields:
            TreeNode: les nœuds parents successifs jusqu'à la racine.

        """
        current = self.parent

        while current is not None:
            yield current
            current = current.paren

    def iter_children_recursive(self) -> Iterator[TreeNode]:
        """Itérer récursivement sur tous les enfants.

        Yields:
            TreeNode: chaque nœud enfant (incluant les descendants).

        """
        for child in self.children:
            yield child
            yield from child.iter_children_recursive()

    def to_dict(self) -> dict:
        """Sérialise le noeud.

        Returns:
            dict

        """
        return {
            "id": self.id,
            "parent_id": self.parent.id if self.parent else None,
            "children_ids": [child.id for child in self.children],
        }
