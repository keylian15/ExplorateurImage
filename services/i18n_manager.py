import json
from pathlib import Path

from models import config_repository


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
