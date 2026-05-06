"""
Point d'entrée principal de l'application Explorateur d'images.

Ce module initialise l'environnement d'exécution PyQt, charge la configuration globale,
instancie les services nécessaires ainsi que l'ensemble des ViewModels, puis crée et
affiche la fenêtre principale de l'application.

Il orchestre uniquement le démarrage de l'application sans contenir de logique métier.
Toute la logique fonctionnelle est déléguée aux ViewModels et aux services.

Responsabilités :
 1. Initialiser l'application Qt (QApplication)
 2. Appliquer le stylesheet global de l'interface
 3. Charger la configuration applicative (config_repository)
 4. Instancier les services externes (OllamaWrapper)
 5. Créer les ViewModels dans le bon ordre de dépendance
 6. Instancier et afficher la MainWindow
 7. Ouvrir automatiquement le dossier par défaut si configuré
 8. Lancer la boucle événementielle Qt
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
