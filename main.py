"""
Point d'entrée principal de l'application Explorateur d'images.

Initialise Qt, charge la configuration, instancie le client Ollama et la
fenêtre principale. Les ViewModels sont désormais créés par chaque workspace.

Responsabilités :
 1. Initialiser l'application Qt (QApplication)
 2. Appliquer le stylesheet global
 3. Charger la configuration applicative
 4. Instancier le client Ollama partagé
 5. Créer et afficher la MainWindow
 6. Lancer la boucle événementielle Qt
"""

import sys

from PyQt6.QtWidgets import QApplication

from models import config_repository
from services.i18n_manager import I18nManager
from services.ollama_wrapper import OllamaWrapper
from services.sam3_service import Sam3Service
from services.workers import Sam3LoadWorker
from styles import get_stylesheet
from views.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(get_stylesheet())

    client = OllamaWrapper()
    config = config_repository.load()
    translator = I18nManager()
    translator.set_language("en")

    sam3_service = Sam3Service()

    window = MainWindow(client, config, translator, sam3_service)
    window.show()

    sam3_load_worker = Sam3LoadWorker(sam3_service)
    sam3_load_worker.start()
    window._sam3_load_worker = sam3_load_worker

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
