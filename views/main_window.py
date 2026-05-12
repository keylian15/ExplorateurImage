"""
views/main_window.py

Fenêtre principale de l'application — architecture multi-workspace.

La fenêtre principale centralise la gestion des workspaces affichés sous forme
d'onglets dans un QTabWidget. Chaque onglet correspond à une instance autonome
de WorkspaceWidget contenant sa propre galerie, carte et état utilisateur.

L'objectif de cette classe est uniquement d'orchestrer l'interface et la
persistance des workspaces. Aucune logique métier liée au traitement des images
ou à l'IA n'est implémentée ici.


Responsabilités :
    1. Restaurer les workspaces depuis la configuration au démarrage
    2. Créer un workspace vide par défaut si aucun n'est sauvegardé
    3. Ajouter de nouveaux workspaces via l'onglet « + »
    4. Supprimer dynamiquement des workspaces
    5. Renommer un workspace par double-clic sur son onglet
    6. Persister automatiquement tous les changements
       (y compris k_neighbors, map_params et pinned_images)
    7. Synchroniser la visibilité des docks entre workspaces
    8. Garantir qu'au moins un workspace reste ouvert
"""

from __future__ import annotations

import os

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QInputDialog,
    QMainWindow,
    QTabBar,
    QTabWidget,
    QWidget,
)

from models import config_repository
from models import workspace_repository as ws_repo
from services.ollama_wrapper import OllamaWrapper
from views.workspace_widget import WorkspaceWidget

# ──────────────────────────────────────────────────────────────────────────────
# QTabBar renommable
# ──────────────────────────────────────────────────────────────────────────────


class RenamableTabBar(QTabBar):
    """
    QTabBar personnalisé supportant le double-clic sur les onglets.

    Cette classe expose un signal permettant à la fenêtre principale
    d'ouvrir une boîte de dialogue de renommage lorsqu'un utilisateur
    double-clique sur un onglet.
    """

    tab_double_clicked = pyqtSignal(int)

    def mouseDoubleClickEvent(self, event):
        """
        Intercepte le double-clic sur un onglet.

        Args:
            event: Événement Qt de double-clic souris.
        """
        index = self.tabAt(event.pos())

        if index >= 0:
            self.tab_double_clicked.emit(index)

        super().mouseDoubleClickEvent(event)


# ──────────────────────────────────────────────────────────────────────────────
# Widget placeholder du bouton +
# ──────────────────────────────────────────────────────────────────────────────


class PlusPlaceholder(QWidget):
    """
    Widget fantôme utilisé pour représenter l'onglet « + ».

    Cet onglet n'héberge aucun contenu réel.
    Il sert uniquement de déclencheur de création de workspace.
    """

    pass


# ──────────────────────────────────────────────────────────────────────────────
# Fenêtre principale
# ──────────────────────────────────────────────────────────────────────────────


class MainWindow(QMainWindow):
    """
    Fenêtre principale multi-workspace de l'application.

    Chaque workspace est affiché sous forme d'onglet indépendant.
    La fenêtre gère leur cycle de vie complet :
        - création
        - suppression
        - renommage
        - restauration
        - persistance (dossier, k_neighbors, map_params, pinned_images)

    Args:
        client (OllamaWrapper):
            Client Ollama partagé entre tous les workspaces.

        config (dict):
            Configuration globale chargée au démarrage.
    """

    def __init__(self, client: OllamaWrapper, config: dict):
        super().__init__()

        self.client = client
        self.config = config
        self._tab_flip_direction = 1

        self.setWindowTitle("Explorateur d'images")

        screen = QApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen)

        self.workspaces: dict[str, WorkspaceWidget] = {}

        self.create_shortcuts()
        self.build_ui()
        self.restore_workspaces()

    # ──────────────────────────────────────────────────────────────────────
    # Raccourcis
    # ──────────────────────────────────────────────────────────────────────

    def create_shortcuts(self):
        """Créer tous les raccourcis clavier."""

        # Nouvel onglet
        action_new_workspace = QAction("New Workspace", self)
        action_new_workspace.setShortcut(QKeySequence("Ctrl+T"))
        action_new_workspace.triggered.connect(lambda: self.create_workspace())

        self.addAction(action_new_workspace)

        # Fermer l'onglet
        action_close_workspace = QAction("Close Workspace", self)
        action_close_workspace.setShortcut(QKeySequence("Ctrl+W"))
        action_close_workspace.triggered.connect(lambda: self.on_tab_close_requested(self.tabs.currentIndex()))

        self.addAction(action_close_workspace)

        # Changer d'onglet
        action_flip_tab = QAction(self)
        action_flip_tab.setShortcut(QKeySequence("Ctrl+Tab"))
        action_flip_tab.triggered.connect(self.flip_flop_tab)

        self.addAction(action_flip_tab)

    def flip_flop_tab(self):
        """
        Alterne entre onglets en inversant la direction à chaque appel.
        """
        count = self.tabs.count() - 1

        current = self.tabs.currentIndex()

        if count <= 1:
            next_index = current + 1
        else:
            next_index = (current + self._tab_flip_direction) % count

        self.tabs.setCurrentIndex(next_index)

        self._tab_flip_direction *= -1

    # ──────────────────────────────────────────────────────────────────────
    # Construction
    # ──────────────────────────────────────────────────────────────────────

    def build_ui(self):
        """
        Construit l'interface principale.

        Initialise :
            - le QTabWidget principal
            - la gestion des fermetures d'onglets
            - le déplacement d'onglets
            - l'onglet spécial « + »
        """

        tab_bar = RenamableTabBar()
        tab_bar.tab_double_clicked.connect(self.on_tab_double_clicked)

        self.tabs = QTabWidget()

        self.tabs.setTabBar(tab_bar)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)

        self.setCentralWidget(self.tabs)

        self.tabs.addTab(PlusPlaceholder(), "+")

        plus_idx = self.tabs.count() - 1

        self.tabs.tabBar().setTabButton(
            plus_idx,
            QTabBar.ButtonPosition.RightSide,
            None,
        )

        self.tabs.tabBar().setTabButton(
            plus_idx,
            QTabBar.ButtonPosition.LeftSide,
            None,
        )

        self.tabs.tabCloseRequested.connect(self.on_tab_close_requested)
        self.tabs.currentChanged.connect(self.on_tab_changed)

    # ──────────────────────────────────────────────────────────────────────
    # Restauration
    # ──────────────────────────────────────────────────────────────────────

    def restore_workspaces(self):
        """
        Recharge les workspaces sauvegardés dans la configuration.

        Si aucun workspace n'existe, un workspace vide est créé
        automatiquement.
        """
        workspaces = ws_repo.load(self.config)

        for ws_data in workspaces:
            self.create_workspace(
                ws_id=ws_data["id"],
                name=ws_data["name"],
                folder=ws_data.get("folder"),
                ws_data=ws_data,
            )

        if not self.workspaces:
            self.create_workspace()

    # ──────────────────────────────────────────────────────────────────────
    # Génération de nom
    # ──────────────────────────────────────────────────────────────────────

    def next_workspace_name(self) -> str:
        """
        Génère automatiquement un nom de workspace sans collision.

        Returns:
            str:
                Nom unique au format « Workspace N ».
        """
        existing = {ws.ws_name for ws in self.workspaces.values()}

        n = 1

        while f"Workspace {n}" in existing:
            n += 1

        return f"Workspace {n}"

    # ──────────────────────────────────────────────────────────────────────
    # Création
    # ──────────────────────────────────────────────────────────────────────

    def create_workspace(
        self,
        ws_id: str | None = None,
        name: str | None = None,
        folder: str | None = None,
        ws_data: dict | None = None,
    ) -> WorkspaceWidget:
        """
        Crée et insère un nouveau workspace.

        Args:
            ws_id (str | None): Identifiant existant lors d'une restauration.
            name (str | None): Nom du workspace.
            folder (str | None): Dossier à restaurer.
            ws_data (dict | None): Données.

        Returns:
            WorkspaceWidget: Nouveau workspace.
        """
        is_new = ws_id is None

        if is_new:
            resolved_name = name or self.next_workspace_name()
            data = ws_repo.make_workspace(name=resolved_name)
            ws_id = data["id"]
            name = data["name"]
            ws_data = data
        else:
            name = name or self.next_workspace_name()
            # ws_data fourni lors de la restauration ; sinon on crée des défauts
            if ws_data is None:
                ws_data = ws_repo.make_workspace(name=name, folder=folder)
                ws_data["id"] = ws_id

        widget = WorkspaceWidget(
            ws_id=ws_id,
            name=name,
            client=self.client,
            config=self.config,
            main_window=self,
            folder=folder,
            ws_data=ws_data,
        )

        widget.folder_changed.connect(self.on_workspace_folder_changed)

        self.workspaces[ws_id] = widget

        self.tabs.currentChanged.disconnect(self.on_tab_changed)

        insert_idx = self.tabs.count() - 1

        self.tabs.insertTab(insert_idx, widget, name)
        self.tabs.setCurrentIndex(insert_idx)

        self.tabs.currentChanged.connect(self.on_tab_changed)

        if is_new:
            self.save_workspaces()

        self.update_close_buttons()

        return widget

    # ──────────────────────────────────────────────────────────────────────
    # Suppression
    # ──────────────────────────────────────────────────────────────────────

    def remove_workspace(self, tab_index: int):
        """
        Supprime un workspace à partir de son index d'onglet.

        La sélection est automatiquement déplacée vers
        un workspace valide afin d'éviter la sélection
        de l'onglet « + ».

        Args:
            tab_index (int):
                Index de l'onglet à supprimer.
        """
        widget = self.tabs.widget(tab_index)

        if not isinstance(widget, WorkspaceWidget):
            return

        ws_id = widget.ws_id

        widget.hide_dock()

        if tab_index < self.tabs.count() - 2:
            next_index = tab_index
        else:
            next_index = max(0, tab_index - 1)

        self.tabs.currentChanged.disconnect(self.on_tab_changed)

        self.tabs.removeTab(tab_index)
        self.tabs.setCurrentIndex(next_index)

        self.tabs.currentChanged.connect(self.on_tab_changed)

        self.workspaces.pop(ws_id, None)

        self.save_workspaces()
        self.update_close_buttons()

    # ──────────────────────────────────────────────────────────────────────
    # Persistance
    # ──────────────────────────────────────────────────────────────────────

    def save_workspaces(self):
        """
        Sauvegarde tous les workspaces dans la configuration.

        Les workspaces sont sauvegardés dans l'ordre actuel des onglets,
        y compris k_neighbors, map_params et pinned_images propres à chaque workspace.
        """
        workspaces = []

        for idx in range(self.tabs.count() - 1):
            widget = self.tabs.widget(idx)

            if isinstance(widget, WorkspaceWidget):
                workspaces.append(
                    {
                        "id": widget.ws_id,
                        "name": widget.ws_name,
                        "folder": widget.current_folder,
                        "k_neighbors": widget.current_k_neighbors,
                        "map_params": widget.current_map_params,
                        "pinned_images": widget.current_pinned_images,
                        "history": widget.current_history,
                        "history_current_id": widget.current_history_current_id,
                    }
                )

        self.config = ws_repo.save(self.config, workspaces)

        config_repository.save(self.config)

    # ──────────────────────────────────────────────────────────────────────
    # Slots Qt
    # ──────────────────────────────────────────────────────────────────────

    def on_tab_close_requested(self, index: int):
        """
        Déclenché lorsqu'un utilisateur ferme un onglet.

        Garantit qu'au moins un workspace reste ouvert.

        Args:
            index (int):
                Index de l'onglet à fermer.
        """
        widget = self.tabs.widget(index)

        if not isinstance(widget, WorkspaceWidget):
            return

        real_count = sum(1 for i in range(self.tabs.count()) if isinstance(self.tabs.widget(i), WorkspaceWidget))

        if real_count <= 1:
            return

        self.remove_workspace(index)

    def on_tab_changed(self, index: int):
        """
        Déclenché lorsqu'un onglet devient actif.

        Fonctionnalités :
            - création d'un workspace via l'onglet « + »
            - masquage des docks inactifs

        Args:
            index (int):
                Index de l'onglet actif.
        """
        widget = self.tabs.widget(index)

        if isinstance(widget, PlusPlaceholder):
            self.create_workspace()
            return

        for ws_widget in self.workspaces.values():
            if ws_widget is not widget:
                ws_widget.hide_dock()

    def on_tab_double_clicked(self, index: int):
        """
        Ouvre une boîte de dialogue de renommage d'onglet.

        Args:
            index (int):
                Index de l'onglet renommé.
        """
        widget = self.tabs.widget(index)

        if not isinstance(widget, WorkspaceWidget):
            return

        new_name, ok = QInputDialog.getText(
            self,
            "Renommer l'espace de travail",
            "Nouveau nom :",
            text=widget.ws_name,
        )

        if ok and new_name.strip():
            new_name = new_name.strip()

            self.tabs.setTabText(index, new_name)

            widget.rename(new_name)

            self.save_workspaces()

    def on_workspace_folder_changed(self, ws_id: str, folder: str):
        """
        Déclenché lorsqu'un workspace change de dossier.

        Si le workspace possède encore son nom automatique,
        il est renommé avec le nom du dossier sélectionné.

        Args:
            ws_id (str):
                Identifiant du workspace.

            folder (str):
                Nouveau dossier sélectionné.
        """
        widget = self.workspaces.get(ws_id)

        if widget is None:
            return

        if widget.ws_name.startswith("Workspace "):
            folder_name = os.path.basename(folder)

            idx = self.tabs.indexOf(widget)

            self.tabs.setTabText(idx, folder_name)

            widget.ws_name = folder_name

        self.save_workspaces()

    # ──────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────

    def update_close_buttons(self):
        """
        Met à jour la visibilité des boutons de fermeture.

        Le dernier workspace restant ne peut pas être fermé.
        """
        real_count = sum(1 for i in range(self.tabs.count()) if isinstance(self.tabs.widget(i), WorkspaceWidget))

        for idx in range(self.tabs.count() - 1):
            widget = self.tabs.widget(idx)

            if isinstance(widget, WorkspaceWidget):
                btn = self.tabs.tabBar().tabButton(
                    idx,
                    QTabBar.ButtonPosition.RightSide,
                )

                if btn:
                    btn.setVisible(real_count > 1)
