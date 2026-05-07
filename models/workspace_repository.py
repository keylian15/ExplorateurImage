"""
Gestion de la persistance des espaces de travail (workspaces).

Chaque workspace est un espace de travail indépendant avec son propre dossier
d'images et son nom personnalisé. La liste des workspaces est stockée dans
config.json sous la clé « workspaces ».

Responsabilités :
 1. Charger la liste des workspaces depuis la configuration
 2. Sauvegarder les modifications (ajout, suppression, renommage, dossier)
 3. Construire des entrées de workspace standardisées
 4. Garantir au moins un workspace par défaut
"""

from __future__ import annotations

import uuid

# ── Structure d'un workspace ──────────────────────────────────────────────────


def make_workspace(name: str = "Workspace", folder: str | None = None) -> dict:
    """Crée un nouveau dict de workspace.

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
    }


# ── Lecture / écriture ────────────────────────────────────────────────────────


def load(config: dict) -> list[dict]:
    """Retourne la liste des workspaces depuis la config.
    Garantit au moins un workspace par défaut.

    Args:
        config (dict): Configuration globale.

    Returns:
        list[dict]: Liste de workspaces.
    """
    workspaces = config.get("workspaces")

    if not isinstance(workspaces, list) or not workspaces:
        return [make_workspace("Workspace 1")]
    # Validation minimale de chaque entrée
    validated = []
    for ws in workspaces:
        if isinstance(ws, dict) and "id" in ws and "name" in ws:
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
        **kwargs: Champs à mettre à jour (name, folder…).

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
