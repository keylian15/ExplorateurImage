from models.tree.tree_node import TreeNode


class SearchNode(TreeNode):
    """Noeud de recherche.

    Contient :
    - la requête
    - les résultats associés (noms d'images)
    """

    def __init__(
        self,
        query: str,
        results: list[str] | None = None,
        node_id: str | None = None,
        parent=None,
    ):
        super().__init__(node_id=node_id, parent=parent)

        self.query: str = query
        self.results: list[str] = results or []

    def to_dict(self) -> dict:
        """Sérialise le noeud de recherche."""
        base = super().to_dict()

        base.update(
            {
                "type": "SearchNode",
                "query": self.query,
                "results": self.results,
            }
        )

        return base
