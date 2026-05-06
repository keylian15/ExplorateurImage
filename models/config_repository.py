"""
Gestion centralisée de la configuration globale de l'application.

Résponsabilités :
 1. Charger la configuration depuis un fichier JSON avec fallback sécurisé
 2. Sauvegarder les paramètres utilisateur de manière persistante
 3. Garantir des valeurs par défaut pour les champs manquants
 4. Extraire et typer les paramètres liés à la carte (UMAP / HDBSCAN)
 5. Mettre à jour proprement les paramètres sans altérer la structure globale

Contenu :
 - Valeurs par défaut de configuration (_DEFAULTS)
 - Lecture / écriture du fichier de configuration
 - Accès simplifié aux paramètres de la carte
 - Utilitaires de mise à jour des paramètres
"""

from __future__ import annotations

import json
import os

CONFIG_FILE = "config.json"

_DEFAULTS = {
    "default_folder": None,
    "k_neighbors": 5,
    "map_params": {
        "umap_n_neighbors": 30,
        "umap_min_dist": 0.3,
        "hdbscan_min_cluster": 15,
    },
}


def load() -> dict:
    """Charge la configuration depuis le fichier config.json, ou retourne les valeurs par défaut si le fichier n'existe pas ou est invalide.

    Returns:
        dict: Configuration ou les valeurs par défaut."""

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                data = json.load(f)
            # Fusionne avec les défauts pour les clés manquantes
            merged = dict(_DEFAULTS)
            merged.update(data)
            return merged
        except Exception:
            pass
    return dict(_DEFAULTS)


def save(config: dict):
    """Enregistre la configuration dans le fichier config.json.

    Args:
        config (dict): La configuration à enregistrer.
    """
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_map_params(config: dict) -> dict:
    """Extrait les paramètres de la carte depuis la configuration, en appliquant les valeurs par défaut pour les clés manquantes.

    Args:
        config (dict): La configuration à utiliser.

    Returns:
        dict: Paramètres de la carte ou les valeurs par défaut."""
    raw = config.get("map_params", {})
    defaults = _DEFAULTS["map_params"]
    return {
        "umap_n_neighbors": int(raw.get("umap_n_neighbors", defaults["umap_n_neighbors"])),
        "umap_min_dist": float(raw.get("umap_min_dist", defaults["umap_min_dist"])),
        "hdbscan_min_cluster": int(raw.get("hdbscan_min_cluster", defaults["hdbscan_min_cluster"])),
    }


def set_map_params(config: dict, params: dict) -> dict:
    """Retourne une nouvelle configuration avec les paramètres de la carte mis à jour.

    Args:
        config (dict): La configuration à mettre à jour.
        params (dict): Les nouveaux paramètres de la carte.

    Returns:
        dict: Nouvelle configuration avec les paramètres de la carte mis à jour."""
    config = dict(config)
    config["map_params"] = params
    return config
