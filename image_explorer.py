import json
import sys
import os
from map_widget import MapTab

from PyQt6.QtWidgets import (
    QApplication, QDialog, QSpinBox, QTabWidget, QWidget, QPushButton, QFileDialog,
    QVBoxLayout, QLabel, QScrollArea, QGridLayout,
    QHBoxLayout, QTextEdit, QLineEdit, QProgressBar,
    QListView, QAbstractItemView, QDockWidget, QMainWindow,
)
from PyQt6.QtGui import QPixmap, QWheelEvent
from PyQt6.QtCore import (
    Qt, QTimer, QSize, QModelIndex,
)

from ollama_wrapper_iut import OllamaWrapper
from thumbnail_cache import ThumbnailCache
from workers import (
    ThumbnailScheduler,
    AutoCompleteWorker,
    AutoCompleteAllWorker,
    SaveMetadataWorker,
)
from image_model import ImageListModel, ImageGridDelegate, IMG_NAME_ROLE

# ─────────────────────────────────────────────────────────────
DEFAULT_THUMB_SIZE = 192
SIZE_LEVELS = [48, 64, 96, 128, 192, 256, 384, 512]
SIZE_INDEX_DEFAULT = 4   # 192 px
LRU_MAX_MEMORY = 600
PREFETCH_ROWS = 3   # lignes supplémentaires chargées hors viewport
EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp")

MODEL_EMBEDDING = 'nomic-embed-text:v1.5'
# ─────────────────────────────────────────────────────────────


class ClickableLabel(QLabel):
    def __init__(self, text_or_parent=None, parent=None):
        if isinstance(text_or_parent, str):
            super().__init__(text_or_parent, parent)
        elif isinstance(text_or_parent, QWidget):
            super().__init__(text_or_parent)
        else:
            super().__init__(parent)
        self.rightClicked = None  # callback clic droit
        self.leftClicked = None   # callback clic gauche

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            if self.rightClicked:
                self.rightClicked()
        elif event.button() == Qt.MouseButton.LeftButton:
            if self.leftClicked:
                self.leftClicked()


class ImageExplorer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.client = OllamaWrapper()
        
        self.setWindowTitle("Explorateur d'images")
        screen = QApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen)

        # ── État interne ──────────────────────────────────────
        self.index: dict = {}
        self.selected_image: str | None = None
        self.current_folder: str | None = None
        self.k_neighbors: int = 5

        # Workers "one-shot"
        self.worker: AutoCompleteWorker | None = None
        self.batch_worker: AutoCompleteAllWorker | None = None
        self.save_worker: SaveMetadataWorker | None = None

        # ── Cache + scheduler ─────────────────────────────────
        _dummy = os.path.expanduser("~")
        self.cache = ThumbnailCache(_dummy, DEFAULT_THUMB_SIZE, LRU_MAX_MEMORY)
        self.scheduler = ThumbnailScheduler(self.cache)

        # ── Modèle + delegate ─────────────────────────────────
        self.model = ImageListModel()
        self.delegate = ImageGridDelegate(
            self.cache, self.scheduler, DEFAULT_THUMB_SIZE)
        self.delegate.repaint_requested.connect(self._on_repaint_requested)

        # ── Taille des cellules ───────────────────────────────
        self.size_index = SIZE_INDEX_DEFAULT
        self.image_size = SIZE_LEVELS[self.size_index]

        # ── Timers ────────────────────────────────────────────
        self.save_timer = QTimer()
        self.save_timer.setInterval(2000)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.save_metadata)

        self.search_timer = QTimer()
        self.search_timer.setInterval(200)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.execute_search)

        # ── UI ────────────────────────────────────────────────
        self._build_ui()

        # ── Config + chargement initial ───────────────────────
        config = self._load_config()
        self.current_folder = config.get("default_folder")
        self.k_neighbors = config.get("k_neighbors", 5)
        self.neighbors_input.setValue(self.k_neighbors)

        if self.current_folder and os.path.exists(self.current_folder):
            self._open_folder_internal(self.current_folder)

    # ═════════════════════════════════════════════════════════
    #  Construction UI
    # ═════════════════════════════════════════════════════════

    def _build_ui(self):
        # ── Widget central ────────────────────────────────────
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)

        # ── Barre du haut ─────────────────────────────────────
        top = QHBoxLayout()

        self.open_button = QPushButton("Ouvrir un dossier")
        self.open_button.clicked.connect(self.open_folder)
        top.addWidget(self.open_button)

        self.auto_complete_all_button = QPushButton("Tout auto-compléter")
        self.auto_complete_all_button.clicked.connect(self.auto_complete_all)
        top.addWidget(self.auto_complete_all_button)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Rechercher...")
        self.search_bar.textChanged.connect(self.schedule_search)
        top.addWidget(self.search_bar)

        self.cancel_button = QPushButton("Annuler")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_batch)
        top.addWidget(self.cancel_button)

        top.addStretch()
        main_layout.addLayout(top)

        # ── QListView ─────────────────────────────────────────
        self.list_view = QListView()
        self.list_view.setModel(self.model)
        self.list_view.setItemDelegate(self.delegate)
        self.list_view.setViewMode(QListView.ViewMode.IconMode)
        self.list_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.list_view.setMovement(QListView.Movement.Static)
        self.list_view.setUniformItemSizes(True)
        self.list_view.setGridSize(
            QSize(self.image_size + 8, self.image_size + 8))
        self.list_view.setSpacing(4)
        self.list_view.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.list_view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_view.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list_view.setToolTip("Clic gauche : sélectionner une image | Clic droit : voir en plein écran")

        # Clic gauche -> sélection
        self.list_view.clicked.connect(self._on_item_clicked)
        # Clic droit -> gros plan (via contextMenuEvent intercepté)
        self.list_view.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_view.customContextMenuRequested.connect(
            self._on_grid_right_click)

        # Préchargement lors du scroll
        self.list_view.verticalScrollBar().valueChanged.connect(
            self._schedule_prefetch)
        self._prefetch_timer = QTimer()
        self._prefetch_timer.setInterval(100)
        self._prefetch_timer.setSingleShot(True)
        self._prefetch_timer.timeout.connect(self._prefetch_visible)

        main_layout.addWidget(self.list_view)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("")
        self.progress_label.setVisible(False)
        main_layout.addWidget(self.progress_label)

        self.tabs = QTabWidget()
        self.tabs.addTab(central_widget, "Galerie")
        self.map_tab = MapTab(self)
        self.tabs.addTab(self.map_tab, "Carte 2D")
        self.setCentralWidget(self.tabs)

        # ── Dock droit ────────────────────────────────────────
        self.dock = QDockWidget("Détails de l'image", self)
        self.dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        # Contenu du dock
        dock_content = QWidget()
        right_layout = QVBoxLayout(dock_content)

        title_layout = QHBoxLayout()
        self.title = QLineEdit()
        self.title.setPlaceholderText("Nom de l'image...")
        title_layout.addWidget(self.title)

        self.rename_button = QPushButton("✏️")
        self.rename_button.setFixedWidth(32)
        self.rename_button.setToolTip("Renommer le fichier")
        self.rename_button.clicked.connect(self.rename_image)
        title_layout.addWidget(self.rename_button)
        right_layout.addLayout(title_layout)

        # Container pour l'aperçu + bouton
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(2)

        # Label image
        self.image_preview = ClickableLabel()
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setFixedHeight(200)
        self.image_preview.setStyleSheet("border: 1px solid #ccc;")
        self.image_preview.setCursor(Qt.CursorShape.PointingHandCursor)
        self.image_preview.rightClicked = self.image_preview.leftClicked = self.open_fullscreen_preview
        self.image_preview.setToolTip("Cliquer pour voir en plein écran")

        preview_layout.addWidget(self.image_preview)
        right_layout.addWidget(preview_container)

        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText("Description...")
        self.desc_edit.textChanged.connect(self.schedule_save)
        right_layout.addWidget(self.desc_edit)

        self.keywords_edit = QLineEdit()
        self.keywords_edit.setPlaceholderText("mot1, mot2, mot3")
        self.keywords_edit.textChanged.connect(self.schedule_save)
        right_layout.addWidget(self.keywords_edit)

        self.auto_complete_button = QPushButton("Auto-compléter")
        self.auto_complete_button.clicked.connect(self.auto_complete)
        right_layout.addWidget(self.auto_complete_button)

        self.loading_label = QLabel("Analyse en cours...")
        self.loading_label.setVisible(False)
        right_layout.addWidget(self.loading_label)

        # Voisins
        neighbors_header = QHBoxLayout()
        self.neighbors_label = ClickableLabel("Images similaires")
        self.neighbors_label.setStyleSheet(
            "font-weight: bold; margin-top: 8px;")
        self.neighbors_input = QSpinBox()
        self.neighbors_input.setMinimum(1)
        self.neighbors_input.setMaximum(100)
        self.neighbors_input.setValue(5)
        self.neighbors_input.valueChanged.connect(
            self._on_neighbors_input_changed)
        neighbors_header.addWidget(self.neighbors_label)
        neighbors_header.addWidget(self.neighbors_input)
        neighbors_header.addStretch()
        right_layout.addLayout(neighbors_header)

        self.neighbors_scroll = QScrollArea()
        self.neighbors_scroll.setFixedHeight(220)
        self.neighbors_scroll.setWidgetResizable(True)
        self.neighbors_widget = QWidget()
        self.neighbors_grid = QGridLayout()
        self.neighbors_grid.setSpacing(4)
        self.neighbors_widget.setLayout(self.neighbors_grid)
        self.neighbors_scroll.setWidget(self.neighbors_widget)
        right_layout.addWidget(self.neighbors_scroll)

        self.dock.setWidget(dock_content)
        self.dock.setMinimumWidth(280)

        # Caché par défaut, affiché à la sélection d'une image
        self.dock.setVisible(False)

        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)

    # ═════════════════════════════════════════════════════════
    #  Clic droit dans la grille -> gros plan
    # ═════════════════════════════════════════════════════════

    def _on_grid_right_click(self, pos):
        index = self.list_view.indexAt(pos)
        if not index.isValid():
            return
        img_name = index.data(IMG_NAME_ROLE)
        if not img_name:
            return

        self.open_fullscreen_preview(
            QPixmap(os.path.join(self.current_folder, img_name)))

    # ═════════════════════════════════════════════════════════
    #  Config
    # ═════════════════════════════════════════════════════════

    def _load_config(self) -> dict:
        if os.path.exists("config.json"):
            with open("config.json", "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_config(self):
        config = {
            "default_folder": self.current_folder,
            "k_neighbors":    self.k_neighbors,
        }
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    # ═════════════════════════════════════════════════════════
    #  Index
    # ═════════════════════════════════════════════════════════

    def _load_index(self):
        index_path = os.path.join(self.current_folder, "index.json")
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                self.index = json.load(f)
        else:
            self.index = {}
        self.model.set_indexed(set(self.index.keys()))

    def _save_index(self):
        index_path = os.path.join(self.current_folder, "index.json")
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(self.index, f, indent=2, ensure_ascii=False)

    # ═════════════════════════════════════════════════════════
    #  Ouverture dossier
    # ═════════════════════════════════════════════════════════

    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choisir un dossier")
        if not folder:
            return
        self._open_folder_internal(folder)

    def _open_folder_internal(self, folder: str):
        self.current_folder = folder
        self._save_config()

        # Réinitialise le cache sur le nouveau dossier
        self.cache.set_folder(folder)
        self.cache.resize(self.image_size)
        self.scheduler.set_cache(self.cache)

        self._load_index()
        self._refresh_image_list()

    # ═════════════════════════════════════════════════════════
    #  Chargement / filtrage des images
    # ═════════════════════════════════════════════════════════

    def _refresh_image_list(self, images: list[str] | None = None):
        """
        Met à jour le modèle avec une liste d'images.
        Si images=None, charge tout le dossier courant.
        """
        if images is None:
            try:
                images = [
                    f for f in os.listdir(self.current_folder)
                    if f.lower().endswith(EXTENSIONS)
                ]
            except FileNotFoundError:
                images = []

        self.model.set_images(images)
        # Précharger le viewport initial
        QTimer.singleShot(50, self._prefetch_visible)

    def _filtered_images(self, filter_text: str, images: list[str] | None = None) -> list[str]:
        """Retourne une liste d'images filtrée et triée par pertinence par rapport au texte de recherche.
        Si images est fourni, ne filtre que cette liste (ex: résultats précédents)
        Avec une approche hybride : score de similarité cosinus sur les embeddings + correspondance texte (description + mots-clés).

        Args: 
            filter_text: le texte de recherche
            images: liste optionnelle d'images à filtrer (si None, filtre tout le dossier)

        Returns:
            une liste d'images triée par pertinence
        """

        ft = filter_text.lower().strip()
        query_embedding = self.client.embed(model=MODEL_EMBEDDING, text=ft)

        if images is None:
            images = list(self.index.keys())

        scores = {}

        for key in images:
            data = self.index[key]

            # 1. Score embedding
            sim = self.client.similarite_cosinus(query_embedding, data["embedding"])

            # 2. Score texte (booléen)
            text_match = (ft in data.get("description", "").lower()
                          or ft in " ".join(data.get("keywords", [])).lower())

            score = 0

            # Pondération embedding vs texte : 70% embedding, 30% texte
            score += sim * 1.0

            # Bonus si le texte correspond
            if text_match:
                score += 0.3

            # Bonus si la similarité est déjà élevée et que le texte correspond (renforce la pertinence)
            if sim > 0.5 and text_match:
                score += 0.5

            scores[key] = score

        sorted_items = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [name for name, _ in sorted_items[:100]]

    # ═════════════════════════════════════════════════════════
    #  Lazy loading / prefetch
    # ═════════════════════════════════════════════════════════

    def _schedule_prefetch(self):
        self._prefetch_timer.start()

    def _prefetch_visible(self):
        """Soumet au scheduler tous les thumbnails visibles + marge."""
        vp = self.list_view.viewport()
        rect = vp.rect()

        # Étendre le rect de PREFETCH_ROWS lignes vers le bas
        extra = PREFETCH_ROWS * (self.image_size + 8)
        rect.setHeight(rect.height() + extra)

        # Parcours des indices visibles
        # QListView.indexAt / visualRect permettent de scanner la zone
        col_count = max(1, vp.width() // (self.image_size + 8))
        total = self.model.rowCount()
        if total == 0:
            return

        # Premier index visible
        first_visible = self.list_view.indexAt(vp.rect().topLeft())
        if not first_visible.isValid():
            first_visible = self.model.index(0)

        start_row = max(0, first_visible.row())

        for row in range(start_row, total):
            mi = self.model.index(row)
            vis_rect = self.list_view.visualRect(mi)
            if vis_rect.top() > rect.bottom():
                break
            img_name = self.model.image_at(row)
            self.scheduler.submit(img_name)

    # ═════════════════════════════════════════════════════════
    #  Sélection
    # ═════════════════════════════════════════════════════════

    def _on_item_clicked(self, index: QModelIndex):
        img_name = index.data(IMG_NAME_ROLE)
        if img_name:
            self._select_image(img_name)

    def _select_image(self, img_name: str):
        self.selected_image = img_name
        self.model.set_selected(img_name)

        # Aperçu haute résolution
        path = os.path.join(self.current_folder, img_name)
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.image_preview.clear()
            self._current_pixmap = None
        else:
            self._current_pixmap = pixmap
            scaled = pixmap.scaled(
                self.image_preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.image_preview.setPixmap(scaled)

        # Afficher le dock s'il est fermé
        if not self.dock.isVisible():
            self.dock.setVisible(True)

        self.title.setText(img_name)
        self.title.setStyleSheet("")
        self.title.setToolTip("")

        # Remplir description / mots-clés sans déclencher les timers
        self.desc_edit.blockSignals(True)
        self.keywords_edit.blockSignals(True)

        data = self.index.get(img_name)
        if data:
            self.desc_edit.setText(data.get("description", ""))
            self.keywords_edit.setText(", ".join(data.get("keywords", [])))
        else:
            self.desc_edit.setText("")
            self.keywords_edit.setText("")

        self.desc_edit.blockSignals(False)
        self.keywords_edit.blockSignals(False)

        self._display_neighbors(img_name)
        
        if hasattr(self, "map_tab"):
            self.map_tab.on_image_selected(img_name)

    def open_fullscreen_preview(self, pixmap_override: QPixmap | None = None):
        """Ouvre le gros plan. Si pixmap_override est fourni, affiche cette image
        à la place de _current_pixmap (utile pour les voisins)."""

        pixmap_current = pixmap_override or getattr(
            self, "_current_pixmap", None)
        if pixmap_current is None or pixmap_current.isNull():
            return

        screen = QApplication.primaryScreen().availableGeometry()

        dialog = QDialog(self)
        dialog.setWindowTitle(self.selected_image)
        dialog.setWindowState(Qt.WindowState.WindowActive)
        dialog.resize(screen.width(), screen.height())

        # ── Layout principal ──────────────────────────────────
        main_layout = QVBoxLayout(dialog)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Barre du haut ─────────────────────────────────────
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 4, 8, 4)

        btn_zoom_in = QPushButton("🔍 +")
        btn_zoom_out = QPushButton("🔍 -")
        btn_reset = QPushButton("↺ Reset")
        lbl_zoom = QLabel("100%")
        lbl_zoom.setFixedWidth(55)
        lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)

        for btn in (btn_zoom_in, btn_zoom_out, btn_reset):
            btn.setFixedHeight(28)

        bar.addWidget(btn_zoom_out)
        bar.addWidget(lbl_zoom)
        bar.addWidget(btn_zoom_in)
        bar.addWidget(btn_reset)
        bar.addStretch()

        bar_widget = QWidget()
        bar_widget.setLayout(bar)
        bar_widget.setStyleSheet("background: #1e1e1e; color: white;")
        bar_widget.setFixedHeight(40)
        main_layout.addWidget(bar_widget)

        # ── Zone image scrollable ──────────────────────────────
        scroll = QScrollArea()
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setStyleSheet("background: #121212; border: none;")
        scroll.setWidgetResizable(False)

        lbl_img = QLabel()
        lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_img.setStyleSheet("background: #121212;")
        scroll.setWidget(lbl_img)
        main_layout.addWidget(scroll)

        # ── État du zoom ───────────────────────────────────────
        zoom_state = {"factor": 1.0}
        ZOOM_STEP = 0.15
        ZOOM_MIN = 0.1
        ZOOM_MAX = 10.0

        dpr = lbl_img.devicePixelRatio()

        def render(factor):
            w = int(dpr * screen.width() * factor)
            h = int(dpr * screen.height() * factor)
            scaled = pixmap_current.scaled(
                w, h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(dpr)
            lbl_img.setPixmap(scaled)
            lbl_img.resize(scaled.width() // int(dpr),
                           scaled.height() // int(dpr))
            lbl_zoom.setText(f"{int(factor * 100)}%")

        def zoom_in():
            zoom_state["factor"] = min(
                ZOOM_MAX, zoom_state["factor"] + ZOOM_STEP)
            render(zoom_state["factor"])

        def zoom_out():
            zoom_state["factor"] = max(
                ZOOM_MIN, zoom_state["factor"] - ZOOM_STEP)
            render(zoom_state["factor"])

        def zoom_reset():
            zoom_state["factor"] = 1.0
            render(1.0)

        # ── Zoom molette ───────────────────────────────────────
        def on_wheel(event: QWheelEvent):
            if event.angleDelta().y() > 0:
                zoom_in()
            else:
                zoom_out()

        scroll.wheelEvent = on_wheel

        # ── Connexions ─────────────────────────────────────────
        btn_zoom_in.clicked.connect(zoom_in)
        btn_zoom_out.clicked.connect(zoom_out)
        btn_reset.clicked.connect(zoom_reset)

        # ── Rendu initial ──────────────────────────────────────
        render(.75)

        self.fullscreen_window = dialog
        dialog.exec()

    def open_fullscreen_preview_demo(self):
        """Version de démonstration pour comparer les différentes sources de thumbnails."""
        pixmap_thumb = self.image_preview.pixmap()
        pixmap_current = getattr(self, "_current_pixmap", None)

        if pixmap_current is None or pixmap_current.isNull():
            return

        path = os.path.join(self.current_folder, self.selected_image)
        pixmap_fresh = QPixmap(path)

        self.fullscreen_window = QDialog(self)
        self.fullscreen_window.setWindowTitle("Comparaison 4 sources")
        self.fullscreen_window.resize(1800, 650)

        main_layout = QHBoxLayout(self.fullscreen_window)

        sources = [
            (pixmap_thumb,   "Thumbnail (aperçu dock)",      False),
            (pixmap_current, "_current_pixmap (stocké)",     False),
            (pixmap_fresh,   "Neuf + DPI scaling",           True),
            (pixmap_fresh,   "Chargement neuf (disque)",     False),
        ]

        for pixmap, title, use_dpi in sources:
            side = QVBoxLayout()

            lbl_title = QLabel(title)
            lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_title.setStyleSheet("font-weight: bold; margin-bottom: 4px;")

            lbl_img = QLabel()
            lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)

            if pixmap and not pixmap.isNull():
                if use_dpi:
                    dpr = lbl_img.devicePixelRatio()
                    scaled = pixmap.scaled(
                        int(dpr * 360), int(dpr * 520),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    scaled.setDevicePixelRatio(dpr)
                else:
                    scaled = pixmap.scaled(
                        360, 520,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                lbl_img.setPixmap(scaled)
                size_txt = f"{pixmap.width()} × {pixmap.height()} px"
            else:
                lbl_img.setText("(aucun pixmap)")
                size_txt = "—"

            lbl_size = QLabel(size_txt)
            lbl_size.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_size.setStyleSheet("color: #888; font-size: 11px;")

            side.addWidget(lbl_title)
            side.addWidget(lbl_img)
            side.addWidget(lbl_size)
            main_layout.addLayout(side)

        self.fullscreen_window.exec()

    # ═════════════════════════════════════════════════════════
    #  Repaint demandé par le delegate
    # ═════════════════════════════════════════════════════════

    def _on_repaint_requested(self, img_name: str):
        self.model.notify_image_updated(img_name)

    # ═════════════════════════════════════════════════════════
    #  Recherche
    # ═════════════════════════════════════════════════════════

    def schedule_search(self):
        self.search_timer.start()

    def execute_search(self):
        text = self.search_bar.text().strip()
        if text:
            self._refresh_image_list(self._filtered_images(text))
        else:
            self._refresh_image_list()

    # ═════════════════════════════════════════════════════════
    #  Zoom (Ctrl+molette)
    # ═════════════════════════════════════════════════════════

    def _zoom_in(self):
        if self.size_index < len(SIZE_LEVELS) - 1:
            self.size_index += 1
            self.image_size = SIZE_LEVELS[self.size_index]
            self._apply_zoom()

    def _zoom_out(self):
        if self.size_index > 0:
            self.size_index -= 1
            self.image_size = SIZE_LEVELS[self.size_index]
            self._apply_zoom()

    def _apply_zoom(self):
        self.cache.resize(self.image_size)
        self.scheduler.flush_pending()
        self.delegate.set_cell_size(self.image_size)
        self.list_view.setGridSize(
            QSize(self.image_size + 8, self.image_size + 8))
        # Force le recalcul de la disposition
        self.list_view.doItemsLayout()
        QTimer.singleShot(50, self._prefetch_visible)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self._zoom_in()
            else:
                self._zoom_out()
        else:
            super().wheelEvent(event)

    # ═════════════════════════════════════════════════════════
    #  Sauvegarde metadata
    # ═════════════════════════════════════════════════════════

    def schedule_save(self):
        if self.selected_image:
            self.save_timer.start()

    def save_metadata(self):
        if not self.selected_image or not self.current_folder:
            return
        desc = self.desc_edit.toPlainText()
        keywords = [k.strip()
                    for k in self.keywords_edit.text().split(",") if k.strip()]

        self.loading_label.setVisible(True)
        self.save_worker = SaveMetadataWorker(
            self.selected_image, self.current_folder, desc, keywords, self.client
        )
        self.save_worker.finished.connect(self._on_save_done)
        self.save_worker.error.connect(self._on_save_error)
        self.save_worker.start()

    def _on_save_done(self):
        self.loading_label.setVisible(False)
        self._load_index()

    def _on_save_error(self, msg: str):
        self.loading_label.setVisible(False)
        print(f"[SAVE ERROR] {msg}")

    # ═════════════════════════════════════════════════════════
    #  Auto-complétion (une image)
    # ═════════════════════════════════════════════════════════

    def auto_complete(self):
        if not self.selected_image or not self.current_folder:
            return
        if self.worker and self.worker.isRunning():
            return

        path = os.path.join(self.current_folder, self.selected_image)
        self.auto_complete_button.setEnabled(False)
        self.loading_label.setVisible(True)

        self.worker = AutoCompleteWorker(path, self.client)
        self.worker.finished.connect(self._on_auto_complete_done)
        self.worker.error.connect(self._on_auto_complete_error)
        self.worker.start()

    def _on_auto_complete_done(self, result: dict):
        self.desc_edit.setText(result["description"])
        self.keywords_edit.setText(", ".join(result["keywords"]))
        self._reset_loading_state()

    def _on_auto_complete_error(self, msg: str):
        self.title.setText(f"Erreur : {msg}")
        self._reset_loading_state()

    def _reset_loading_state(self):
        self.loading_label.setVisible(False)
        self.auto_complete_button.setEnabled(True)

    # ═════════════════════════════════════════════════════════
    #  Auto-complétion batch
    # ═════════════════════════════════════════════════════════

    def auto_complete_all(self):
        if not self.current_folder:
            return
        if self.batch_worker and self.batch_worker.isRunning():
            return

        images = []
        for file in os.listdir(self.current_folder):
            if file.lower().endswith(EXTENSIONS):
                if file not in self.index:
                    images.append(file)

        if not images:
            return

        total = len(images)
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.progress_label.setText(f"0 / {total} — en attente...")
        self.progress_label.setVisible(True)
        self.auto_complete_all_button.setEnabled(False)
        self.auto_complete_button.setEnabled(False)
        self.cancel_button.setVisible(True)
        self.cancel_button.setEnabled(True)

        self.batch_worker = AutoCompleteAllWorker(
            self.current_folder, images, self.client)
        self.batch_worker.image_done.connect(self._on_batch_image_done)
        self.batch_worker.image_error.connect(self._on_batch_image_error)
        self.batch_worker.all_done.connect(self._on_batch_all_done)
        self.batch_worker.start()

    def _on_batch_image_done(self, idx: int, img_name: str, result: dict):
        desc = result["description"]
        keywords = result["keywords"]

        embedding = self.client.embed(
            model=MODEL_EMBEDDING,
            text=self.client.build_embedding(desc, keywords)
        )
        self.index[img_name] = {
            "id":          img_name,
            "path":        os.path.join(self.current_folder, img_name),
            "description": desc,
            "keywords":    keywords,
            "embedding":   embedding,
        }
        self._save_index()
        self.model.set_indexed(set(self.index.keys()))

        total = self.progress_bar.maximum()
        done = idx + 1
        self.progress_bar.setValue(done)
        self.progress_label.setText(f"{done} / {total} — ✅ {img_name}")

        if img_name == self.selected_image:
            self.desc_edit.setText(desc)
            self.keywords_edit.setText(", ".join(keywords))

    def _on_batch_image_error(self, idx: int, img_name: str, msg: str):
        total = self.progress_bar.maximum()
        self.progress_bar.setValue(idx + 1)
        self.progress_label.setText(
            f"{idx + 1} / {total} — ❌ {img_name} : {msg}")

    def _on_batch_all_done(self):
        cancelled = self.batch_worker._cancelled
        total = self.progress_bar.maximum()
        self.progress_label.setText(
            "⛔ Annulé" if cancelled else f"✅ Terminé — {total} images traitées"
        )
        self.auto_complete_all_button.setEnabled(True)
        self.auto_complete_button.setEnabled(True)
        self.cancel_button.setVisible(False)
        QTimer.singleShot(4000, lambda: (
            self.progress_bar.setVisible(False),
            self.progress_label.setVisible(False),
        ))

    def cancel_batch(self):
        if self.batch_worker and self.batch_worker.isRunning():
            self.batch_worker.cancel()
            self.cancel_button.setEnabled(False)
            self.progress_label.setText("⛔ Annulation...")

    # ═════════════════════════════════════════════════════════
    #  Renommage
    # ═════════════════════════════════════════════════════════

    def rename_image(self):
        if not self.selected_image or not self.current_folder:
            return
        new_name = self.title.text().strip()
        if not new_name or new_name == self.selected_image:
            return

        old_ext = os.path.splitext(self.selected_image)[1]
        if not os.path.splitext(new_name)[1]:
            new_name += old_ext

        old_path = os.path.join(self.current_folder, self.selected_image)
        new_path = os.path.join(self.current_folder, new_name)

        if os.path.exists(new_path):
            self.title.setText(self.selected_image)
            self.title.setStyleSheet("border: 1px solid red;")
            self.title.setToolTip("❌ Un fichier avec ce nom existe déjà")
            return

        try:
            os.rename(old_path, new_path)
        except OSError as e:
            self.title.setStyleSheet("border: 1px solid red;")
            self.title.setToolTip(f"❌ Erreur : {e}")
            return

        # Invalider le cache thumbnail de l'ancien nom
        self.cache.invalidate(self.selected_image)

        # Mettre à jour l'index
        if self.selected_image in self.index:
            data = self.index.pop(self.selected_image)
            data["id"] = new_name
            data["path"] = new_path
            self.index[new_name] = data
            self._save_index()

        self.selected_image = new_name
        self.title.setStyleSheet("")
        self.title.setToolTip("")
        self._refresh_image_list()

    # ═════════════════════════════════════════════════════════
    #  Voisins (similarité cosinus)
    # ═════════════════════════════════════════════════════════

    def _get_neighbors(self, img_name: str, top_k: int = 5) -> dict:
        if img_name not in self.index:
            return {}
        entry = self.index[img_name]
        if "embedding" not in entry:
            return {}

        scores = {}
        for key, data in self.index.items():
            if key == img_name or "embedding" not in data:
                continue
            scores[key] = self.client.similarite_cosinus(
                entry["embedding"], data["embedding"]
            )
        return dict(sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k])

    def _display_neighbors(self, img_name: str):
        # Vider la grille
        for i in reversed(range(self.neighbors_grid.count())):
            w = self.neighbors_grid.itemAt(i).widget()
            if w:
                w.deleteLater()

        entry = self.index.get(img_name)
        if not entry or not entry.get("embedding"):
            self.neighbors_label.setText("Images similaires (pas d'embedding)")
            return

        neighbors = self._get_neighbors(img_name, top_k=self.k_neighbors)
        if not neighbors:
            self.neighbors_label.setText("Images similaires (aucune)")
            return

        self.neighbors_label.setText(
            f"Images similaires (top {len(neighbors)})")
        THUMB = 80
        col, row = 0, 0

        for neighbor_name, score in neighbors.items():
            path = os.path.join(self.current_folder, neighbor_name)
            pixmap = QPixmap(path)
            if pixmap.isNull():
                continue

            # Pixmap pleine résolution pour le gros plan
            pixmap_full = QPixmap(path)

            pixmap_scaled = pixmap.scaled(
                THUMB, THUMB,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

            cell = QWidget()
            cell_layout = QVBoxLayout()
            cell_layout.setContentsMargins(2, 2, 2, 2)
            cell_layout.setSpacing(2)

            # Thumbnail
            thumb = ClickableLabel()
            thumb.setPixmap(pixmap_scaled)
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb.setStyleSheet("border: 1px solid #ccc; border-radius: 3px;")
            thumb.setCursor(Qt.CursorShape.PointingHandCursor)
            thumb.setToolTip("Clic gauche : sélectionner | Clic droit : voir en plein écran")

            # Clic gauche -> sélectionner l'image
            thumb.leftClicked = lambda n=neighbor_name: self._select_image(n)

            # Clic droit -> gros plan de ce voisin
            thumb.rightClicked = lambda p=pixmap_full: self.open_fullscreen_preview(
                p)

            score_label = QLabel(f"{score:.2f}")
            score_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            score_label.setStyleSheet("font-size: 10px; color: #666;")

            cell_layout.addWidget(thumb)
            cell_layout.addWidget(score_label)
            cell.setLayout(cell_layout)
            self.neighbors_grid.addWidget(cell, row, col)

            col += 1
            if col == 3:
                col, row = 0, row + 1

    def _on_neighbors_input_changed(self):
        self.k_neighbors = self.neighbors_input.value()
        self._save_config()
        if self.selected_image:
            self._display_neighbors(self.selected_image)


# ═════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ImageExplorer()
    window.show()
    sys.exit(app.exec())
