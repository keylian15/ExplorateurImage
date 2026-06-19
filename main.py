"""Point d'entrée principal de l'application Explorateur d'images.

Initialise Qt, charge la configuration, instancie le client Ollama et la
fenêtre principale. Les ViewModels sont désormais créés par chaque workspace.

Responsabilités :
 1. Initialiser l'application Qt (QApplication)
 2. Appliquer le stylesheet global
 3. Charger la configuration applicative
 4. Instancier le client Ollama partagé
 5. Créer et afficher la MainWindow
 6. Lancer la boucle événementielle Qt
 7. Permettre le redémarrage complet de l'application (changement de langue)
"""

import os
import sys

from PyQt6.QtWidgets import QApplication

from models import config_repository
from services.i18n_manager import I18nManager
from services.ollama_wrapper import OllamaWrapper
from services.sam3_service import Sam3Service
from services.workers import Sam3LoadWorker
from styles import get_stylesheet
from views.main_window import MainWindow


def restart_app() -> None:
    """Redémarre complètement le processus de l'application.

    Utilisé après un changement de langue : la configuration (incluant la
    nouvelle langue) a déjà été sauvegardée dans config.json via
    I18nManager.set_language(), donc le nouveau processus la rechargera
    automatiquement au démarrage.

    Remplace le processus courant via os.execv (même interpréteur, mêmes
    arguments), ce qui évite de laisser un second processus tourner et
    libère proprement les ressources (incluant SAM3) avant le redémarrage.
    """
    python = sys.executable
    os.execv(python, [python, *sys.argv])


def main() -> None:
    """Point d'entrée principal de l'application.

    Initialise l'application Qt, charge la configuration globale et instancie
    les services principaux (client LLM, gestionnaire i18n, service SAM3).

    Met également en place le chargement asynchrone du modèle SAM3 avant de
    lancer la boucle d'événements de l'application.

    Workflow :
    - création de QApplication
    - application du style global
    - chargement de la configuration
    - initialisation des services (Ollama, i18n, SAM3)
    - création et affichage de la fenêtre principale
    - lancement du worker de chargement SAM3
    - démarrage de la boucle Qt
    """
    app = QApplication(sys.argv)
    app.setStyleSheet(get_stylesheet())

    client = OllamaWrapper()
    config = config_repository.load()

    saved_lang = config.get("language", "fr")
    translator = I18nManager(lang=saved_lang)

    sam3_service = Sam3Service()

    window = MainWindow(client, config, translator, sam3_service)
    window.show()

    sam3_load_worker = Sam3LoadWorker(sam3_service)
    sam3_load_worker.start()
    window._sam3_load_worker = sam3_load_worker

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
