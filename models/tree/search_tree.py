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

    @classmethod
    def from_dict(cls, data: dict) -> "SearchTree":
        """Reconstruit un SearchTree depuis un dict sérialisé (issu de to_dict).

        Seuls les noeuds non-racine (hors __root__) sont restaurés comme
        SearchNode. La racine __root__ est recréée proprement via create_root.

        Args:
            data (dict): Dictionnaire sérialisé produit par to_dict.

        Returns:
            SearchTree: Arbre restauré, ou arbre vide si data est invalide.
        """
        tree = cls()

        if not data or not isinstance(data, dict):
            tree.create_root(query="__root__", results=[])
            return tree

        nodes_data = data.get("nodes", [])
        current_id = data.get("current_id")

        if not nodes_data:
            tree.create_root(query="__root__", results=[])
            return tree

        # Index des données brutes par id
        raw_by_id: dict[str, dict] = {n["id"]: n for n in nodes_data if "id" in n}

        # Trouver la racine dans les données
        root_id = data.get("root_id")
        root_data = raw_by_id.get(root_id) if root_id else None

        if root_data is None:
            tree.create_root(query="__root__", results=[])
            return tree

        # Recréer les noeuds (sans liens parent/enfant pour l'instant)
        node_objs: dict[str, SearchNode] = {}
        for nd in nodes_data:
            nid = nd.get("id")
            if not nid:
                continue
            node = SearchNode(
                query=nd.get("query", ""),
                results=nd.get("results", []),
                node_id=nid,
            )
            node_objs[nid] = node

        # Racine
        root_node = node_objs.get(root_id)
        if root_node is None:
            tree.create_root(query="__root__", results=[])
            return tree

        tree.root = root_node
        tree.current = root_node
        tree._nodes[root_id] = root_node

        # Reconstruire les liens parent → enfants
        for nd in nodes_data:
            nid = nd.get("id")
            if not nid or nid == root_id:
                continue
            parent_id = nd.get("parent_id")
            node = node_objs.get(nid)
            parent = node_objs.get(parent_id) if parent_id else None
            if node is None:
                continue
            if parent is not None:
                parent.children.append(node)
                node.parent = parent
            tree._nodes[nid] = node

        # Restaurer le noeud courant
        if current_id and current_id in tree._nodes:
            tree.current = tree._nodes[current_id]

        return tree
