"""Gestion centralisée de la configuration globale de l'application.

Résponsabilités :
 1. Charger la configuration depuis un fichier JSON avec fallback sécurisé
 2. Sauvegarder les paramètres utilisateur de manière persistante
 3. Garantir des valeurs par défaut pour les champs manquants

Contenu :
 - Valeurs par défaut de configuration (_DEFAULTS)
 - Lecture / écriture du fichier de configuration
"""

from __future__ import annotations

import json
import os

CONFIG_FILE = "config.json"

_DEFAULTS = {"workspaces": [], "language": "fr"}


def load() -> dict:
    """Charge la configuration depuis le fichier config.json, ou retourne les valeurs par défaut si le fichier n'existe pas ou est invalide.

    Returns:
        dict: Configuration ou les valeurs par défaut.

    """
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                data = json.load(f)
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
