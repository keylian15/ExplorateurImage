"""ViewModel de la carte 2D sémantique.

Ce composant gère la génération et l'affichage de la projection 2D des images
à partir de leurs embeddings. Il orchestre le calcul UMAP + HDBSCAN via un worker,
tout en assurant la persistance d'un cache pour éviter des recalculs coûteux.

Il sert d'interface entre les données (index + embeddings), les paramètres de
configuration et la vue, en exposant des signaux de progression et de résultats.

Contenu :
 - Lancement et supervision du calcul de projection 2D
 - Gestion des paramètres UMAP et HDBSCAN (par workspace)
 - Chargement et sauvegarde d'un cache pickle des résultats
 - Réutilisation du cache pour éviter les recalculs
 - Communication des clusters nommés et du résultat final
 - Recherche sémantique sur la carte avec filtrage des noeuds
 - Arbre de recherche avec historique et affinage

Responsabilités :
 1. Charger et filtrer les embeddings depuis l'index des images
 2. Déclencher le calcul de la carte via MapWorker
 3. Gérer les paramètres de réduction dimensionnelle et clustering (par workspace)
 4. Sauvegarder les résultats (points, labels, clusters) dans un cache pickle
 5. Restaurer les résultats depuis le cache si disponible
 6. Notifier la vue de l'avancement et du résultat final
 7. Synchroniser les paramètres avec la configuration persistante du workspace
 8. Filtrer les noeuds visibles selon une requête sémantique
 9. Gérer l'arbre de recherche avec historique et affinage
"""

from __future__ import annotations

import os
import pickle

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from models import config_repository
from models import workspace_repository as ws_repo
from models.tree.search_tree import SearchTree
from services.i18n_manager import I18nManager
from services.ollama_wrapper import OllamaWrapper
from services.workers import MapWorker
from viewmodels.gallery_vm import GalleryViewModel

_MAP_CACHE_DIR = ".semantic_map"
_MAP_CACHE_FILE = "map_cache.pkl"
MODEL_EMBED = "nomic-embed-text:v1.5"


class MapViewModel(QObject):
    """Class qui représente la carte 2D sémantique."""

    # ── Signaux vers la View ──────────────────────────────────────────────────
    signal_compute_started = pyqtSignal()
    signal_compute_progress = pyqtSignal(str)
    # points, labels, names, cluster_names
    signal_compute_finished = pyqtSignal(list, list, list, dict)
    signal_cluster_named = pyqtSignal(int, str)
    signal_compute_error = pyqtSignal(str)
    signal_params_changed = pyqtSignal(dict)
    # noms des images à mettre en valeur (liste vide = tout afficher)
    signal_search_results_changed = pyqtSignal(list)
    # une recherche a été sauvegardée dans l'arbre
    signal_saved_search = pyqtSignal()

    def __init__(
        self,
        client: OllamaWrapper,
        config: dict,
        gallery_vm: GalleryViewModel,
        ws_id: str,
        ws_data: dict,
        translator: I18nManager,
    ) -> None:
        """Initialise la map 2D.

        Args:
            client (OllamaWrapper): client Ollama
            config (dict): configuration globale
            gallery_vm (GalleryViewModel): ViewModel de la gallerie
            ws_id (str): identifiant du workspace
            ws_data (dict): données du workspace (contient map_params et history_search)
            translator (I18nManager): gestionnaire de traduction.

        """
        super().__init__()
        self._client = client
        self._config = config
        self._gallery_vm = gallery_vm
        self._ws_id = ws_id
        self._worker: MapWorker | None = None
        self._params = ws_repo.get_map_params(ws_data)
        self.translator = translator

        # ── Recherche ─────────────────────────────────────────────────────────
        self._search_text = ""
        self._result_names: list[str] = []
        self._affinage_enabled = False

        # Debounce pour la recherche
        self._search_timer = QTimer()
        self._search_timer.setInterval(300)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self.do_search)

        # Restauration de l'arbre de recherche depuis ws_data
        search_trees = ws_repo.get_search_trees(ws_data) if ws_data else {"gallery": {}, "map": {}}
        map_tree_data = search_trees.get("map", {})
        if map_tree_data:
            self.search_tree = SearchTree.from_dict(map_tree_data)
        else:
            self.search_tree = SearchTree()
            self.search_tree.create_root(query="__root__", results=[])

    # ── Paramètres ────────────────────────────────────────────────────────────

    @property
    def params(self) -> dict:
        """Renvoie les paramètres de la carte.

        Returns:
            dict: paramètres.

        """
        return dict(self._params)

    def apply_params(self, params: dict) -> None:
        """Set les paramètres de la carte et les persiste dans le workspace.

        Args:
            params (dict): Nouveaux paramètres.

        """
        self._params = params
        self.save_params_to_workspace(params)
        self.signal_params_changed.emit(params)
        self.compute()

    def save_params_to_workspace(self, params: dict) -> None:
        """Sauvegarde les paramètres de la carte dans le workspace courant.

        Args:
            params (dict): Paramètres à persister dans le workspace.

        """
        workspaces = ws_repo.load(self._config)
        workspaces = ws_repo.update_workspace(workspaces, self._ws_id, map_params=params)
        self._config = ws_repo.save(self._config, workspaces)
        config_repository.save(self._config)

    # ── Calcul ────────────────────────────────────────────────────────────────

    def compute(self) -> None:
        """Démarre le calcul de la carte."""
        if self._worker and self._worker.isRunning():
            return

        indexed = {k: v for k, v in self._gallery_vm.index.items() if v.get("embedding") and len(v["embedding"]) > 0}
        indexed_size_min = 2
        if len(indexed) < indexed_size_min:
            self.signal_compute_error.emit(self.translator.tr("Pas assez d'embeddings ({count} / min 2).").format(count=len(indexed)))
            return

        self.signal_compute_started.emit()
        self._worker = MapWorker(
            indexed,
            self._client,
            umap_n_neighbors=self._params["umap_n_neighbors"],
            umap_min_dist=self._params["umap_min_dist"],
            hdbscan_min_cluster=self._params["hdbscan_min_cluster"],
        )
        self._worker.signal_progress.connect(self.signal_compute_progress)
        self._worker.signal_cluster_named.connect(self.signal_cluster_named)
        self._worker.signal_finished.connect(self.on_finished)
        self._worker.signal_error.connect(self.signal_compute_error)
        self._worker.start()

    def autoload(self) -> None:
        """Lance depuis le cache si disponible, sinon calcule."""
        cache = self.load_cache()
        if cache:
            self.signal_compute_finished.emit(
                cache["points"],
                cache["labels"],
                cache["names"],
                cache["cluster_names"],
            )
        else:
            self.compute()

    def on_finished(self, points: list[tuple[float, float]], labels: list[int], names: list[str], cluster_names: dict[int, str]) -> None:
        """Sauvegarde les résultats du worker et déclenche le signal de fin de calcul.

        Args:
            points (list[tuple[float, float]]): Coordonnées des points calculés sur la carte.
            labels (list[int]): Labels associés aux clusters.
            names (list[str]): Noms des éléments (images ou données associées).
            cluster_names (dict[int, str]): Correspondance entre identifiants de clusters et leurs noms.

        """
        self.save_cache(points, labels, names, cluster_names)
        self.signal_compute_finished.emit(points, labels, names, cluster_names)

    # ── Recherche sémantique ──────────────────────────────────────────────────

    def schedule_search(self, text: str) -> None:
        """Déclenche une recherche avec debounce.

        Args:
            text (str): Texte de la requête.

        """
        self._search_text = text
        self._search_timer.start()

    def do_search(self) -> None:
        """Effectue la recherche et émet le signal avec les résultats."""
        text = self._search_text.strip()
        if not text:
            self._result_names = []
            self.signal_search_results_changed.emit([])
            return

        context = None
        if self._affinage_enabled and self.search_tree.current:
            context = self.search_tree.current.results

        self._result_names = self._gallery_vm.filtered_images(filter_text=text, context=context)
        self.signal_search_results_changed.emit(self._result_names)

    def clear_search(self) -> None:
        """Vide la recherche et réaffiche tous les noeuds."""
        self._search_text = ""
        self._result_names = []
        self._search_timer.stop()
        self.signal_search_results_changed.emit([])

    def save_search(self) -> None:
        """Enregistre la recherche courante dans l'arbre de recherche."""
        text = self._search_text.strip()
        if not text:
            return

        if not self._affinage_enabled:
            self.search_tree.return_to_root()

        self.search_tree.push_search(
            query=text,
            results=self._result_names,
        )
        self.signal_saved_search.emit()

    def set_affinage(self, enabled: bool) -> None:
        """Active ou désactive l'affinage des recherches.

        Args:
            enabled (bool): Si True, les recherches suivantes seront affinées
                            à partir des résultats actuels.

        """
        self._affinage_enabled = enabled
        self.do_search()

    # ── Cache pickle ──────────────────────────────────────────────────────────

    def cache_path(self) -> str:
        """Construit le chemin du cache de la map pour le workspace actuel.

        Returns:
            str: chemin du fichier pickle.

        """
        folder = self._gallery_vm.current_folder

        cache_dir = os.path.join(folder, _MAP_CACHE_DIR)
        os.makedirs(cache_dir, exist_ok=True)

        return os.path.join(cache_dir, _MAP_CACHE_FILE)

    def save_cache(self, points: list[tuple[float, float]], labels: list[int], names: list[str], cluster_names: dict[int, str]) -> None:
        """Sauvegarde le cache.

        Args:
            points (list[tuple[float, float]]): Les points de la carte.
            labels (list[int]): Les labels des points.
            names (list[str]): Les noms des images.
            cluster_names (dict[int, str]): Les noms des clusters.

        """
        data = {"points": points, "labels": labels, "names": names, "cluster_names": cluster_names}
        with open(self.cache_path(), "wb") as f:
            pickle.dump(data, f)

    def load_cache(self) -> dict | None:
        """Charge le cache.

        Returns:
            dict | None: Le cache ou None si il n'existe pas.

        """
        try:
            path = self.cache_path()

            if not os.path.exists(path):
                return None

            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception:
            return None
