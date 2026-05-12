from __future__ import annotations

import time
import uuid

from services.history.history_types import HistoryActionType


class HistoryNode:
    def __init__(
        self,
        action_type: HistoryActionType,
        payload: dict,
        active_view: str = "gallery",
        node_id: str | None = None,
        timestamp: float | None = None,
    ) -> None:

        self.action_type = action_type
        self.payload = payload
        self.active_view = active_view
        self.id = node_id or str(uuid.uuid4())
        self.timestamp = timestamp or time.time()
        self.parent: HistoryNode | None = None
        self.children: list[HistoryNode] = []

    def add_child(self, child: HistoryNode) -> None:

        child.parent = self
        self.children.append(child)

    @property
    def is_root(self) -> bool:
        """Indique si le noeud est la racine de l'arbre."""
        return self.parent is None

    # ── Sérialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Sérialise le noeud en dict (sans les enfants ni le parent — géré par HistoryTree).

        Returns:
            dict: Représentation sérialisable du noeud.
        """
        return {
            "id": self.id,
            "action_type": self.action_type.name,
            "payload": self.payload,
            "active_view": self.active_view,
            "timestamp": self.timestamp,
            "parent_id": self.parent.id if self.parent else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> HistoryNode:
        """Désérialise un noeud depuis un dict. Les liens parent/enfants sont
        reconstruits par HistoryTree.from_list().

        Args:
            data (dict): Dict sérialisé.

        Returns:
            HistoryNode: Noeud reconstruit.
        """
        return cls(
            action_type=HistoryActionType[data["action_type"]],
            payload=data["payload"],
            active_view=data.get("active_view", "gallery"),
            node_id=data["id"],
            timestamp=data.get("timestamp"),
        )
