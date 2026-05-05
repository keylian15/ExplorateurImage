"""
Module d'accès au fichier d'index de l'application (index.json).

Ce composant centralise toute la logique de lecture, écriture et mise à jour
de l'index associé à un dossier d'images. Il permet de stocker des métadonnées
par image (chemin, description, mots-clés, embeddings) sans dépendre de Qt
ni d'aucune couche UI.

Il sert de couche persistante simple entre le système de traitement d'images
et le reste de l'application.
"""

from __future__ import annotations

import json
import os


def load(folder: str) -> dict:
    """Charge index.json depuis le dossier donné. Retourne {} si absent.

    Args:
        folder (str): Dossier contenant index.json.

    Returns:
        dict: Contenu de index.json.
    """

    path = get_path(folder)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save(folder: str, index: dict):
    """Écrit index.json dans le dossier donné.

    Args:
        folder (str): Dossier contenant index.json.
        index (dict): Contenu à écrire.
    """

    with open(get_path(folder), "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


def upsert_entry(folder: str, img_name: str, entry: dict) -> dict:
    """Charge l'index, insère/met à jour une entrée, sauvegarde et retourne l'index mis à jour.

    Args:
        folder (str): Dossier contenant index.json.
        img_name (str): Nom de l'image.
        entry (dict): Entrée à insérer/mettre à jour.

    Returns:
        dict: Index mis à jour.
    """

    index = load(folder)
    index[img_name] = entry
    save(folder, index)
    return index


def rename_entry(folder: str, old_name: str, new_name: str, new_path: str) -> dict:
    """Renomme une entrée dans l'index.

    Args:
        folder (str): Dossier contenant index.json.
        old_name (str): Ancien nom de l'image.
        new_name (str): Nouveau nom de l'image.
        new_path (str): Nouveau chemin de l'image.

    Returns:
        dict: Index mis à jour.
    """

    index = load(folder)
    if old_name in index:
        entry = index.pop(old_name)
        entry["id"] = new_name
        entry["path"] = new_path
        index[new_name] = entry
        save(folder, index)
    return index


def build_entry(img_name: str, folder: str, description: str, keywords: list[str], embedding: list[float]) -> dict:
    """Construit un dict d'entrée standardisé.

    Args:
        img_name (str): Nom de l'image.
        folder (str): Dossier contenant l'image.
        description (str): Description de l'image.
        keywords (list[str]): Mots-clés de l'image.
        embedding (list[float]): Embedding de l'image.

    Returns:
        dict: Entrée standardisée.
    """

    return {
        "id": img_name,
        "path": os.path.join(folder, img_name),
        "description": description,
        "keywords": keywords,
        "embedding": embedding,
    }


def get_path(folder: str) -> str:
    """Retourne le chemin du fichier d'index.

    Args:
        folder (str): Dossier contenant l'image.

    Returns:
        str: Chemin du fichier d'index.
    """

    return os.path.join(folder, "index.json")
