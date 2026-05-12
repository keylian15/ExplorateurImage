from __future__ import annotations

from services.history.history_node import HistoryNode
from services.history.history_types import HistoryActionType


class HistoryTree:
    def __init__(self) -> None:

        self.root: HistoryNode | None = None
        self.current: HistoryNode | None = None

    def push(
        self,
        action_type: HistoryActionType,
        payload: dict,
        active_view: str = "gallery",
    ) -> HistoryNode:

        node = HistoryNode(
            action_type=action_type,
            payload=payload,
            active_view=active_view,
        )

        # Verif de l'initialisation.
        if not self.root:
            self.root = node
        else:
            self.current.add_child(node)

        self.current = node

        return node

    def back(self) -> HistoryNode | None:

        if not self.can_go_back():
            return None

        self.current = self.current.parent

        return self.current

    def can_go_back(self) -> bool:

        return self.current is not None and self.current.parent is not None

    # ── Sérialisation ─────────────────────────────────────────────────────────

    def to_list(self) -> list[dict]:
        """Sérialise tout l'arbre en liste plate de dicts.
        Chaque noeud contient un `parent_id` pour reconstruire les liens.

        Returns:
            list[dict]: Liste de noeuds sérialisés, dans l'ordre BFS.
        """
        if not self.root:
            return []

        result = []
        queue = [self.root]
        while queue:
            node = queue.pop(0)
            result.append(node.to_dict())
            queue.extend(node.children)

        return result

    @classmethod
    def from_list(cls, data: list[dict], current_id: str | None) -> HistoryTree:
        """Reconstruit un HistoryTree depuis une liste plate de dicts.

        Args:
            data (list[dict]): Liste sérialisée produite par to_list().
            current_id (str | None): ID du noeud courant à restaurer.

        Returns:
            HistoryTree: Arbre reconstruit.
        """
        tree = cls()
        if not data:
            return tree

        # Première passe : créer tous les noeuds indexés par id
        nodes: dict[str, HistoryNode] = {}
        for item in data:
            try:
                node = HistoryNode.from_dict(item)
                nodes[node.id] = node
            except (KeyError, ValueError):
                # Action type inconnu ou données corrompues → on saute
                continue

        # Deuxième passe : reconstruire les liens parent/enfants
        for item in data:
            node_id = item.get("id")
            parent_id = item.get("parent_id")
            if node_id not in nodes:
                continue
            node = nodes[node_id]
            if parent_id and parent_id in nodes:
                parent = nodes[parent_id]
                parent.add_child(node)
            else:
                # Pas de parent → c'est la racine
                if tree.root is None:
                    tree.root = node

        # Restaurer le noeud courant
        if current_id and current_id in nodes:
            tree.current = nodes[current_id]
        elif tree.root:
            # Fallback : noeud le plus récent (dernier enfant en profondeur)
            tree.current = tree._find_deepest_current(tree.root)

        return tree

    def _find_deepest_current(self, node: HistoryNode) -> HistoryNode:
        """Retourne le noeud le plus profond (dernier enfant récursif).

        Args:
            node (HistoryNode): Noeud de départ.

        Returns:
            HistoryNode: Noeud le plus profond.
        """
        while node.children:
            node = node.children[-1]
        return node

    def current_id(self) -> str | None:
        """Retourne l'id du noeud courant.

        Returns:
            str | None: ID du noeud courant, ou None si l'arbre est vide.
        """
        return self.current.id if self.current else None
