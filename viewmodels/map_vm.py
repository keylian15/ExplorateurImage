"""
ViewModel de la carte 2D sémantique.

Ce composant gère la génération et l'affichage de la projection 2D des images
à partir de leurs embeddings. Il orchestre le calcul UMAP + HDBSCAN via un worker,
tout en assurant la persistance d'un cache pour éviter des recalculs coûteux.

Il sert d'interface entre les données (index + embeddings), les paramètres de
configuration et la vue, en exposant des signaux de progression et de résultats.

Contenu :
 - Lancement et supervision du calcul de projection 2D
 - Gestion des paramètres UMAP et HDBSCAN
 - Chargement et sauvegarde d'un cache pickle des résultats
 - Réutilisation du cache pour éviter les recalculs
 - Communication des clusters nommés et du résultat final
 - Recherche sémantique sur la carte avec filtrage des noeuds

Responsabilités :
 1. Charger et filtrer les embeddings depuis l'index des images
 2. Déclencher le calcul de la carte via MapWorker
 3. Gérer les paramètres de réduction dimensionnelle et clustering
 4. Sauvegarder les résultats (points, labels, clusters) dans un cache pickle
 5. Restaurer les résultats depuis le cache si disponible
 6. Notifier la vue de l'avancement et du résultat final
 7. Synchroniser les paramètres avec la configuration persistante
 8. Filtrer les noeuds visibles selon une requête sémantique
"""

from __future__ import annotations

import os
import pickle

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from models import config_repository
from services.ollama_wrapper import OllamaWrapper
from services.workers import MapWorker
from viewmodels.gallery_vm import GalleryViewModel

_MAP_CACHE_FILE = "map_cache.pkl"

MODEL_EMBED = "nomic-embed-text:v1.5"


class MapViewModel(QObject):
    """Class qui représente la carte 2D sémantique."""

    # ── Signaux vers la View ──────────────────────────────────────────────────
    compute_started = pyqtSignal()
    compute_progress = pyqtSignal(str)
    # points, labels, names, cluster_names
    compute_finished = pyqtSignal(list, list, list, dict)
    cluster_named = pyqtSignal(int, str)
    compute_error = pyqtSignal(str)
    params_changed = pyqtSignal(dict)
    # noms des images à mettre en valeur (liste vide = tout afficher)
    search_results_changed = pyqtSignal(list)

    def __init__(self, client: OllamaWrapper, config: dict, gallery_vm: GalleryViewModel, parent=None):
        """
        Args:
            client (OllamaWrapper): client Ollama
            config (dict): configuration
            gallery_vm (GalleryViewModel): ViewModel de la gallerie
        """

        super().__init__(parent)
        self._client = client
        self._config = config
        self._gallery_vm = gallery_vm
        self._worker: MapWorker | None = None
        self._params = config_repository.get_map_params(config)

        # Debounce pour la recherche
        self._search_timer = QTimer()
        self._search_timer.setInterval(300)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self.do_search)
        self._search_text = ""

    # ── Paramètres ────────────────────────────────────────────────────────────

    @property
    def params(self) -> dict:
        """Renvoie les paramètres de la carte

        Returns:
            dict: paramètres."""
        return dict(self._params)

    def apply_params(self, params: dict):
        """Modifie les paramètres de la carte

        Args:
            params (dict): Nouveaux paramètres.
        """
        self._params = params
        self._config = config_repository.set_map_params(self._config, params)
        config_repository.save(self._config)
        self.params_changed.emit(params)
        self.compute()

    # ── Calcul ────────────────────────────────────────────────────────────────

    def compute(self):
        """Démarre le calcul de la carte."""
        if self._worker and self._worker.isRunning():
            return

        indexed = {k: v for k, v in self._gallery_vm.index.items() if v.get("embedding") and len(v["embedding"]) > 0}
        if len(indexed) < 2:
            self.compute_error.emit(f"Pas assez d'embeddings ({len(indexed)} / min 2).")
            return

        self.compute_started.emit()
        self._worker = MapWorker(
            indexed,
            self._client,
            umap_n_neighbors=self._params["umap_n_neighbors"],
            umap_min_dist=self._params["umap_min_dist"],
            hdbscan_min_cluster=self._params["hdbscan_min_cluster"],
        )
        self._worker.progress.connect(self.compute_progress)
        self._worker.cluster_named.connect(self.cluster_named)
        self._worker.finished.connect(self.on_finished)
        self._worker.error.connect(self.compute_error)
        self._worker.start()

    def autoload(self):
        """Lance depuis le cache si disponible, sinon calcule."""
        cache = self.load_cache()
        if cache:
            self.compute_finished.emit(
                cache["points"],
                cache["labels"],
                cache["names"],
                cache["cluster_names"],
            )
        else:
            self.compute()

    def on_finished(self, points: list[tuple[float, float]], labels: list[int], names: list[str], cluster_names: dict[int, str]):
        """Callback du worker.

        Args:
            points (list[tuple[float, float]]): Les points de la carte.
            names (list[str]): Les noms des images.
            cluster_names (dict[int, str]): Les noms des clusters.
        """

        self.save_cache(points, labels, names, cluster_names)
        self.compute_finished.emit(points, labels, names, cluster_names)

    # ── Recherche sémantique ──────────────────────────────────────────────────

    def schedule_search(self, text: str):
        """Déclenche une recherche avec debounce.

        Args:
            text (str): Texte de la requête.
        """
        self._search_text = text
        self._search_timer.start()

    def do_search(self):
        """Effectue la recherche et émet le signal avec les résultats."""
        text = self._search_text.strip()
        if not text:
            # Requête vide → tout afficher
            self.search_results_changed.emit([])
            return

        # Réutilise la logique de recherche sémantique du GalleryViewModel
        results = self._gallery_vm.filtered_images(text)
        self.search_results_changed.emit(results)

    def clear_search(self):
        """Vide la recherche et réaffiche tous les noeuds."""
        self._search_text = ""
        self._search_timer.stop()
        self.search_results_changed.emit([])

    # ── Cache pickle ──────────────────────────────────────────────────────────

    def save_cache(self, points: list[tuple[float, float]], labels: list[int], names: list[str], cluster_names: dict[int, str]):
        """Sauvegarde le cache.

        Args:
            points (list[tuple[float, float]]): Les points de la carte.
            labels (list[int]): Les labels des points.
            names (list[str]): Les noms des images.
            cluster_names (dict[int, str]): Les noms des clusters.
        """
        data = {"points": points, "labels": labels, "names": names, "cluster_names": cluster_names}
        with open(_MAP_CACHE_FILE, "wb") as f:
            pickle.dump(data, f)

    def load_cache(self) -> dict | None:
        """Charge le cache.

        Returns:
            dict | None: Le cache ou None si il n'existe pas.
        """
        if not os.path.exists(_MAP_CACHE_FILE):
            return None
        try:
            with open(_MAP_CACHE_FILE, "rb") as f:
                return pickle.load(f)
        except Exception:
            return None
