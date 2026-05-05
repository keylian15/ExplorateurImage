"""
index_repository.py — Lecture / écriture de index.json.

Aucune dépendance Qt. Toute la logique d'accès au fichier d'index est ici.
"""
from __future__ import annotations
import json
import os


def load(folder: str) -> dict:
    """Charge index.json depuis le dossier donné. Retourne {} si absent."""
    path = _path(folder)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save(folder: str, index: dict) -> None:
    """Écrit index.json dans le dossier donné."""
    with open(_path(folder), "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


def upsert_entry(folder: str, img_name: str, entry: dict) -> dict:
    """Charge l'index, insère/met à jour une entrée, sauvegarde et retourne l'index mis à jour."""
    index = load(folder)
    index[img_name] = entry
    save(folder, index)
    return index


def rename_entry(folder: str, old_name: str, new_name: str, new_path: str) -> dict:
    """Renomme une entrée dans l'index."""
    index = load(folder)
    if old_name in index:
        entry = index.pop(old_name)
        entry["id"] = new_name
        entry["path"] = new_path
        index[new_name] = entry
        save(folder, index)
    return index


def build_entry(img_name: str, folder: str, description: str,
                keywords: list[str], embedding: list[float]) -> dict:
    """Construit un dict d'entrée standardisé."""
    return {
        "id":          img_name,
        "path":        os.path.join(folder, img_name),
        "description": description,
        "keywords":    keywords,
        "embedding":   embedding,
    }


def _path(folder: str) -> str:
    return os.path.join(folder, "index.json")
