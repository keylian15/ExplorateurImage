"""
main.py — Point d'entrée de l'application.

Responsabilités :
  1. Créer QApplication et appliquer le stylesheet global
  2. Instancier les services (OllamaWrapper)
  3. Charger la config
  4. Instancier les ViewModels dans l'ordre (GalleryVM en premier, les autres en dépendent)
  5. Instancier la MainWindow
  6. Ouvrir le dossier par défaut si présent dans la config
"""

import sys

from PyQt6.QtWidgets import QApplication

from models import config_repository
from services.ollama_wrapper import OllamaWrapper
from styles import get_stylesheet
from viewmodels.autocomplete_vm import AutocompleteViewModel
from viewmodels.detail_vm import DetailViewModel
from viewmodels.gallery_vm import GalleryViewModel
from viewmodels.map_vm import MapViewModel
from views.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(get_stylesheet())

    # ── Services ──────────────────────────────────────────────────────────────
    client = OllamaWrapper()
    config = config_repository.load()

    # ── ViewModels ────────────────────────────────────────────────────────────
    gallery_vm = GalleryViewModel(client, config)
    detail_vm = DetailViewModel(client, config, gallery_vm)
    autocomplete_vm = AutocompleteViewModel(client, gallery_vm)
    map_vm = MapViewModel(client, config, gallery_vm)

    # ── Fenêtre ───────────────────────────────────────────────────────────────
    window = MainWindow(gallery_vm, detail_vm, autocomplete_vm, map_vm)
    window.show()

    # ── Dossier par défaut ────────────────────────────────────────────────────
    default_folder = config.get("default_folder")
    if default_folder:
        import os

        if os.path.exists(default_folder):
            gallery_vm.open_folder(default_folder)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
