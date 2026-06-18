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
    ) -> None:
        """Initialise un noeud de l'arbre de recherche.

        Args:
            query (str): La recherche.
            results (list[str] | None, optional): Les noms d'images trouvés. Defaults to None.
            node_id (str | None, optional): L'id du node. Defaults to None.

        """
        super().__init__(node_id=node_id)

        self.query: str = query
        self.results: list[str] = results or []

    def to_dict(self) -> dict:
        """Sérialise le noeud de recherche.

        Returns:
            dict: Le dictionnaire correspondant au noeud

        """
        base = super().to_dict()

        base.update(
            {
                "type": "SearchNode",
                "query": self.query,
                "results": self.results,
            }
        )

        return base
