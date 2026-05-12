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
    ) -> None:

        self.action_type = action_type
        self.payload = payload
        self.active_view = active_view
        self.id = str(uuid.uuid4())
        self.timestamp = time.time()
        self.parent: HistoryNode | None = None
        self.children: list[HistoryNode] = []

    def add_child(self, child: HistoryNode) -> None:

        child.parent = self

        self.children.append(child)

    @property
    def is_root(self) -> bool:
        """
        Indique si le noeud est la racine de l'arbre.
        """

        return self.parent is None
