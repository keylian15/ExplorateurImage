import json
from pathlib import Path

from models import config_repository

# ── Métadonnées d'affichage pour les langues connues ──────────────────────────
# Utilisé uniquement pour l'affichage (nom lisible + drapeau).
# Si une langue présente dans i18n.json n'est pas dans ce dict, on affiche
# simplement son code en majuscules avec un drapeau générique.
_LANGUAGE_META: dict[str, tuple[str, str]] = {
    "fr": ("Français", "🇫🇷"),
    "en": ("English", "🇬🇧"),
    "es": ("Español", "🇪🇸"),
    "de": ("Deutsch", "🇩🇪"),
    "it": ("Italiano", "🇮🇹"),
    "pt": ("Português", "🇵🇹"),
    "nl": ("Nederlands", "🇳🇱"),
    "ja": ("日本語", "🇯🇵"),
    "zh": ("中文", "🇨🇳"),
    "ko": ("한국어", "🇰🇷"),
    "ru": ("Русский", "🇷🇺"),
    "ar": ("العربية", "🇸🇦"),
}


class I18nManager:
    def __init__(self, lang: str = "fr", file_path: str = "i18n.json"):
        self.file_path = Path(file_path)
        self.lang = lang
        self.translations: dict[str, dict[str, str]] = {}
        self.load()

    def load(self) -> None:
        """Charge le fichier JSON unique."""
        if not self.file_path.exists():
            raise FileNotFoundError(f"Fichier introuvable : {self.file_path}")

        with open(self.file_path, encoding="utf-8") as f:
            self.translations = json.load(f)

    def set_language(self, lang: str) -> None:
        """Change la langue active + persist config."""
        self.lang = lang

        current_config = config_repository.load()
        current_config["language"] = lang
        config_repository.save(current_config)

    def tr(self, text: str) -> str:
        """
        Retourne la traduction (clé = texte FR).
        """
        entry = self.translations.get(text)

        if not entry:
            return text

        return entry.get(self.lang, text)

    # ──────────────────────────────────────────────────────────────────────
    # Langues disponibles
    # ──────────────────────────────────────────────────────────────────────

    def available_languages(self) -> list[str]:
        """Renvoie la liste triée des codes de langue présents dans i18n.json.

        Parcourt toutes les entrées de traduction et collecte l'union des clés
        de langue rencontrées. "fr" est toujours inclus en premier (langue
        source), suivi des autres langues triées alphabétiquement.

        Returns:
            list[str]: Liste des codes de langue (ex: ["fr", "en", "es"]).
        """
        codes: set[str] = set()
        for entry in self.translations.values():
            if isinstance(entry, dict):
                codes.update(entry.keys())

        codes.add("fr")

        others = sorted(c for c in codes if c != "fr")
        return ["fr", *others]

    @staticmethod
    def language_label(code: str) -> str:
        """Retourne un libellé lisible (emoji + nom) pour un code de langue.

        Args:
            code (str): Code de langue (ex: "fr", "en").

        Returns:
            str: Libellé du type "🇫🇷 Français", ou "🌐 EN" si inconnu.
        """
        name, flag = _LANGUAGE_META.get(code, (code.upper(), "🌐"))
        return f"{flag} {name}"
