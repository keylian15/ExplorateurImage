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
from services.ollama_wrapper import OllamaWrapper
from styles import get_stylesheet
from views.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(get_stylesheet())

    client = OllamaWrapper()
    config = config_repository.load()

    window = MainWindow(client, config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
