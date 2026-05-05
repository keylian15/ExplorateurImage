"""
viewmodels/map_vm.py

Logique de la carte 2D sémantique :
  - chargement/sauvegarde du cache pickle
  - lancement du MapWorker (UMAP + HDBSCAN)
  - paramètres UMAP/HDBSCAN (lu/écrit via config_repository)
"""
from __future__ import annotations
import os
import pickle

from PyQt6.QtCore import QObject, pyqtSignal

from models import config_repository
from services.ollama_wrapper import OllamaWrapper
from services.workers import MapWorker

_MAP_CACHE_FILE = "map_cache.pkl"


class MapViewModel(QObject):
    # ── Signaux vers la View ──────────────────────────────────────────────────
    compute_started   = pyqtSignal()
    compute_progress  = pyqtSignal(str)
    compute_finished  = pyqtSignal(list, list, list, dict)  # points, labels, names, cluster_names
    cluster_named     = pyqtSignal(int, str)
    compute_error     = pyqtSignal(str)
    params_changed    = pyqtSignal(dict)

    def __init__(self, client: OllamaWrapper, config: dict, gallery_vm, parent=None):
        super().__init__(parent)
        self._client     = client
        self._config     = config
        self._gallery_vm = gallery_vm
        self._worker: MapWorker | None = None
        self._params = config_repository.get_map_params(config)

    # ── Paramètres ────────────────────────────────────────────────────────────

    @property
    def params(self) -> dict:
        return dict(self._params)

    def apply_params(self, params: dict):
        self._params = params
        self._config = config_repository.set_map_params(self._config, params)
        config_repository.save(self._config)
        self.params_changed.emit(params)
        self.compute()

    # ── Calcul ────────────────────────────────────────────────────────────────

    def compute(self):
        if self._worker and self._worker.isRunning():
            return

        indexed = {
            k: v for k, v in self._gallery_vm.index.items()
            if v.get("embedding") and len(v["embedding"]) > 0
        }
        if len(indexed) < 2:
            self.compute_error.emit(
                f"Pas assez d'embeddings ({len(indexed)} / min 2)."
            )
            return

        self.compute_started.emit()
        self._worker = MapWorker(
            indexed, self._client,
            umap_n_neighbors=self._params["umap_n_neighbors"],
            umap_min_dist=self._params["umap_min_dist"],
            hdbscan_min_cluster=self._params["hdbscan_min_cluster"],
        )
        self._worker.progress.connect(self.compute_progress)
        self._worker.cluster_named.connect(self.cluster_named)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self.compute_error)
        self._worker.start()

    def autoload(self):
        """Lance depuis le cache si disponible, sinon calcule."""
        cache = self._load_cache()
        if cache:
            self.compute_finished.emit(
                cache["points"], cache["labels"],
                cache["names"],  cache["cluster_names"],
            )
        else:
            self.compute()

    # ── Slots privés ──────────────────────────────────────────────────────────

    def _on_finished(self, points, labels, names, cluster_names):
        self._save_cache(points, labels, names, cluster_names)
        self.compute_finished.emit(points, labels, names, cluster_names)

    # ── Cache pickle ──────────────────────────────────────────────────────────

    def _save_cache(self, points, labels, names, cluster_names):
        data = {"points": points, "labels": labels,
                "names": names, "cluster_names": cluster_names}
        with open(_MAP_CACHE_FILE, "wb") as f:
            pickle.dump(data, f)

    def _load_cache(self) -> dict | None:
        if not os.path.exists(_MAP_CACHE_FILE):
            return None
        try:
            with open(_MAP_CACHE_FILE, "rb") as f:
                return pickle.load(f)
        except Exception:
            return None
