from models.tree.search_node import SearchNode
from models.tree.tree import Tree


class SearchTree(Tree):
    """
    Arbre de recherche.

    Chaque noeud représente :
    - une requête
    - un set de résultats
    """

    def create_root(self, query: str, results: list[str]) -> SearchNode:
        """Crée la racine de l'arbre avec une requête et ses résultats associés

        Args:
            query (str): Requête de recherche.
            results (list[str]): Résultats associés à la requête.

        Returns:
            SearchNode: Noeud racine créé.
        """

        node = SearchNode(query=query, results=results)
        self.add_root(node)
        return node

    def push_search(
        self,
        query: str,
        results: list[str],
    ) -> SearchNode:
        """Ajoute un noeud de recherche enfant au noeud courant

        Args:
            query (str): Requête de recherche.
            results (list[str]): Résultats associés à la requête.


        Returns:
            SearchNode: Noeud de recherche ajouté.
        """

        if self.current is None:
            raise ValueError("No current node")

        node = SearchNode(query=query, results=results, parent=self.current)

        self.current.add_child(node)
        self._nodes[node.id] = node
        self.current = node
        return node

    def return_to_root(self) -> SearchNode:
        """Retourne à la racine de l'arbre

        Returns:
            SearchNode: Noeud racine.
        """

        self.current = self.root
        return self.current

    def to_dict(self) -> dict:
        """
        Sérialise l'arbre de recherche.
        """

        return {
            "type": "SearchTree",
            "root_id": self.root.id if self.root else None,
            "current_id": self.current.id if self.current else None,
            "nodes": [node.to_dict() for node in self.iter_nodes()],
        }
