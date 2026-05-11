"""
Gestion de la persistance des espaces de travail (workspaces).

Chaque workspace est un espace de travail indépendant avec son propre dossier
d'images, son nom personnalisé, ses paramètres de carte (UMAP/HDBSCAN) et son
nombre de voisins (k_neighbors).

La liste des workspaces est stockée dans config.json sous la clé « workspaces ».

Responsabilités :
 1. Charger la liste des workspaces depuis la configuration
 2. Sauvegarder les modifications (ajout, suppression, renommage, dossier)
 3. Construire des entrées de workspace standardisées
 4. Garantir au moins un workspace par défaut
 5. Fournir les valeurs par défaut de map_params et k_neighbors
"""

from __future__ import annotations

import uuid

# ── Valeurs par défaut ────────────────────────────────────────────────────────

_DEFAULT_MAP_PARAMS = {
    "umap_n_neighbors": 30,
    "umap_min_dist": 0.3,
    "hdbscan_min_cluster": 15,
}

_DEFAULT_K_NEIGHBORS = 5

# ── Structure d'un workspace ──────────────────────────────────────────────────


def make_workspace(name: str = "Workspace", folder: str | None = None) -> dict:
    """Crée un nouveau dict de workspace avec ses propres paramètres.

    Args:
        name (str): Nom affiché dans l'onglet.
        folder (str | None): Chemin du dossier d'images, ou None.

    Returns:
        dict: Entrée workspace standardisée.
    """
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "folder": folder,
        "k_neighbors": _DEFAULT_K_NEIGHBORS,
        "map_params": dict(_DEFAULT_MAP_PARAMS),
    }


def default_map_params() -> dict:
    """Retourne une copie des paramètres de carte par défaut.

    Returns:
        dict: Paramètres UMAP/HDBSCAN par défaut.
    """
    return dict(_DEFAULT_MAP_PARAMS)


def default_k_neighbors() -> int:
    """Retourne le nombre de voisins par défaut.

    Returns:
        int: k_neighbors par défaut.
    """
    return _DEFAULT_K_NEIGHBORS


def get_map_params(ws_data: dict) -> dict:
    """Extrait les paramètres de carte d'un workspace, avec fallback sur les défauts.

    Args:
        ws_data (dict): Données du workspace.

    Returns:
        dict: Paramètres UMAP/HDBSCAN.
    """
    raw = ws_data.get("map_params", {})
    defaults = _DEFAULT_MAP_PARAMS
    return {
        "umap_n_neighbors": int(raw.get("umap_n_neighbors", defaults["umap_n_neighbors"])),
        "umap_min_dist": float(raw.get("umap_min_dist", defaults["umap_min_dist"])),
        "hdbscan_min_cluster": int(raw.get("hdbscan_min_cluster", defaults["hdbscan_min_cluster"])),
    }


def get_k_neighbors(ws_data: dict) -> int:
    """Extrait k_neighbors d'un workspace, avec fallback sur la valeur par défaut.

    Args:
        ws_data (dict): Données du workspace.

    Returns:
        int: k_neighbors.
    """
    return int(ws_data.get("k_neighbors", _DEFAULT_K_NEIGHBORS))


# ── Lecture / écriture ────────────────────────────────────────────────────────


def load(config: dict) -> list[dict]:
    """Retourne la liste des workspaces depuis la config.
    Garantit au moins un workspace par défaut.
    Injecte les valeurs par défaut pour les clés manquantes.

    Args:
        config (dict): Configuration globale.

    Returns:
        list[dict]: Liste de workspaces.
    """
    workspaces = config.get("workspaces")

    if not isinstance(workspaces, list) or not workspaces:
        return [make_workspace("Workspace 1")]

    validated = []
    for ws in workspaces:
        if isinstance(ws, dict) and "id" in ws and "name" in ws:
            # Injecte les clés manquantes pour la rétrocompatibilité
            if "k_neighbors" not in ws:
                ws = dict(ws)
                ws["k_neighbors"] = _DEFAULT_K_NEIGHBORS
            if "map_params" not in ws:
                ws = dict(ws)
                ws["map_params"] = dict(_DEFAULT_MAP_PARAMS)
            validated.append(ws)

    return validated if validated else [make_workspace("Workspace 1")]


def save(config: dict, workspaces: list[dict]) -> dict:
    """Met à jour la liste des workspaces dans la config et retourne la config modifiée.

    Args:
        config (dict): Configuration globale.
        workspaces (list[dict]): Nouvelle liste de workspaces.

    Returns:
        dict: Configuration mise à jour.
    """
    config = dict(config)
    config["workspaces"] = workspaces
    return config


def update_workspace(workspaces: list[dict], ws_id: str, **kwargs) -> list[dict]:
    """Met à jour les champs d'un workspace identifié par son id.

    Args:
        workspaces (list[dict]): Liste courante.
        ws_id (str): Identifiant du workspace à modifier.
        **kwargs: Champs à mettre à jour (name, folder, k_neighbors, map_params…).

    Returns:
        list[dict]: Liste mise à jour (copie défensive).
    """
    result = []
    for ws in workspaces:
        if ws["id"] == ws_id:
            ws = dict(ws)
            ws.update(kwargs)
        result.append(ws)
    return result


def remove_workspace(workspaces: list[dict], ws_id: str) -> list[dict]:
    """Supprime un workspace de la liste. Garantit qu'il en reste au moins un.

    Args:
        workspaces (list[dict]): Liste courante.
        ws_id (str): Identifiant du workspace à supprimer.

    Returns:
        list[dict]: Liste mise à jour.
    """
    filtered = [ws for ws in workspaces if ws["id"] != ws_id]
    return filtered if filtered else [make_workspace("Workspace 1")]
