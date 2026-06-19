"""Gestion centralisée de la palette de couleurs de l'application avec persistance JSON.

Permet de charger, modifier et sauvegarder dynamiquement les couleurs utilisées
dans l'interface, tout en garantissant une base cohérente grâce à une fusion
automatique avec les valeurs par défaut.

Responsabilités :
 1. Charger la palette depuis un fichier JSON
 2. Assurer la cohérence des clés via une fusion avec les valeurs par défaut
 3. Sauvegarder les modifications de la palette
 4. Fournir un accès aux couleurs par défaut

Contenu :
 - Palette par défaut (_DEFAULTS)
 - Fonctions de chargement, sauvegarde et accès aux valeurs
 - Gestion du fichier de persistance (colors.json)
"""

from __future__ import annotations

import json
import os

COLORS_FILE = "colors.json"

# Palette par défaut — identique à l'ancien COLORS dans styles.py
_DEFAULTS: dict[str, str] = {
    "bg_primary": "#0f172a",
    "bg_secondary": "#111827",
    "bg_card": "#1f2937",
    "bg_input": "#111827",
    "bg_hover": "#1e293b",
    "text_primary": "#e5e7eb",
    "text_secondary": "#9ca3af",
    "text_muted": "#6b7280",
    "text_disabled": "#4b5563",
    "accent": "#3b82f6",
    "accent_hover": "#60a5fa",
    "accent_pressed": "#2563eb",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "error": "#ef4444",
    "info": "#3b82f6",
    "border": "#1f2937",
    "border_focus": "#3b82f6",
    "thumb_placeholder": "#1f2937",
    "thumb_loading_text": "#6b7280",
    "selection_border": "#3b82f6",
    "indexed_dot": "#22c55e",
}


def load() -> dict[str, str]:
    """Charge colors.json. Fusionne avec les défauts pour les clés manquantes.

    Returns:
        dict[str, str]: Palette de couleurs.

    """
    if os.path.exists(COLORS_FILE):
        try:
            with open(COLORS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            merged = dict(_DEFAULTS)
            merged.update({k: v for k, v in data.items() if k in _DEFAULTS})
            return merged
        except Exception:
            pass
    return dict(_DEFAULTS)


def save(colors: dict[str, str]) -> None:
    """Écrit colors.json.

    Args:
        colors (dict[str, str]): Palette à sauvegarder.

    """
    with open(COLORS_FILE, "w", encoding="utf-8") as f:
        json.dump(colors, f, indent=2, ensure_ascii=False)


def defaults() -> dict[str, str]:
    """Retourne une copie des couleurs par défaut.

    Returns:
        dict[str, str]: Couleurs par défaut.

    """
    return dict(_DEFAULTS)
