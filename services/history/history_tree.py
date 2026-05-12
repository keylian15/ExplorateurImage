from services.history.history_node import HistoryNode
from services.history.history_types import HistoryActionType


class HistoryTree:
    def __init__(self) -> None:

        self.root: HistoryNode = None
        self.current: HistoryNode = None

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

        return self.current.parent is not None
