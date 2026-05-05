"""
config_repository.py — Lecture / écriture de config.json.

Aucune dépendance Qt. Peut être remplacé sans toucher au reste.
"""
from __future__ import annotations
import json
import os

CONFIG_FILE = "config.json"

_DEFAULTS = {
    "default_folder": None,
    "k_neighbors": 5,
    "map_params": {
        "umap_n_neighbors": 15,
        "umap_min_dist": 0.1,
        "hdbscan_min_cluster": 15,
    },
}


def load() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Fusionne avec les défauts pour les clés manquantes
            merged = dict(_DEFAULTS)
            merged.update(data)
            return merged
        except Exception:
            pass
    return dict(_DEFAULTS)


def save(config: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_map_params(config: dict) -> dict:
    raw = config.get("map_params", {})
    defaults = _DEFAULTS["map_params"]
    return {
        "umap_n_neighbors":    int(raw.get("umap_n_neighbors",    defaults["umap_n_neighbors"])),
        "umap_min_dist":       float(raw.get("umap_min_dist",     defaults["umap_min_dist"])),
        "hdbscan_min_cluster": int(raw.get("hdbscan_min_cluster", defaults["hdbscan_min_cluster"])),
    }


def set_map_params(config: dict, params: dict) -> dict:
    config = dict(config)
    config["map_params"] = params
    return config
