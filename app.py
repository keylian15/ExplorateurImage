import json
import sys
import os
from time import sleep
from PIL.ImageChops import screen
from PyQt6.QtWidgets import (
    QApplication, QSpinBox, QWidget, QPushButton, QFileDialog,
    QVBoxLayout, QLabel, QScrollArea, QGridLayout,
    QHBoxLayout, QTextEdit, QLineEdit, QProgressBar
)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import QTimer, Qt, QThread, pyqtSignal
from ollama_wrapper_iut import OllamaWrapper

client = OllamaWrapper()


# ───────── WORKER : UNE IMAGE ─────────
class AutoCompleteWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, image_path):
        super().__init__()
        self.image_path = image_path

    def run(self):
        try:
            result = client.get_description_and_keywords_from_image(
                self.image_path)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# ───────── WORKER : TOUTES LES IMAGES ─────────
class AutoCompleteAllWorker(QThread):
    # progression : (index traité, nom image, résultat dict)
    image_done = pyqtSignal(int, str, dict)
    # erreur non bloquante sur une image
    image_error = pyqtSignal(int, str, str)
    # fin de batch
    all_done = pyqtSignal()

    def __init__(self, folder, images):
        super().__init__()
        self.folder = folder
        self.images = images   # liste de noms de fichiers
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        for i, img_name in enumerate(self.images):
            if self._cancelled:
                break
            path = os.path.join(self.folder, img_name)
            try:
                result = client.get_description_and_keywords_from_image(path)
                self.image_done.emit(i, img_name, result)
            except Exception as e:
                self.image_error.emit(i, img_name, str(e))
        self.all_done.emit()

# ───────── WORKER : SAUVEGARDE METADATA (description + keywords + embedding) ─────────


class SaveMetadataWorker(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, image_name, folder, desc, keywords):
        super().__init__()
        self.image_name = image_name
        self.folder = folder
        self.desc = desc
        self.keywords = keywords

    def run(self):
        try:
            embedding = client.embed(
                model='nomic-embed-text:v1.5',
                text=client.build_embedding(self.desc, self.keywords)
            )

            index_path = os.path.join(self.folder, "index.json")

            if os.path.exists(index_path):
                with open(index_path, "r", encoding="utf-8") as f:
                    index = json.load(f)
            else:
                index = {}

            index[self.image_name] = {
                "id": self.image_name,
                "path": os.path.join(self.folder, self.image_name),
                "description": self.desc,
                "keywords": self.keywords,
                "embedding": embedding
            }

            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(index, f, indent=2, ensure_ascii=False)

            self.finished.emit()

        except Exception as e:
            self.error.emit(str(e))


class ImageExplorer(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Explorateur d'images")
        screen = QApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen)
        self.index = {}
        self.selected_label = None
        self.selected_image = None
        self.current_folder = None
        self.worker = None
        self.batch_worker = None

        # ───────── TIMER DE SAUVEGARDE AUTOMATIQUE ─────────
        self.save_timer = QTimer()
        # TODO : paramétrer le délai après lequel la sauvegarde automatique se déclenche
        self.save_timer.setInterval(2000)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.save_metadata)

        # ───────── TIMER DE RECHERCHE AUTOMATIQUE ─────────
        self.search_timer = QTimer()
        self.search_timer.setInterval(200)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.execute_search)

        # ───────── LAYOUT GLOBAL ─────────
        main_layout = QVBoxLayout()

        # ───────── TOP : BOUTONS ─────────
        top_layout = QHBoxLayout()

        self.open_button = QPushButton("Ouvrir un dossier")
        self.open_button.clicked.connect(self.open_folder)
        top_layout.addWidget(self.open_button)

        self.auto_complete_all_button = QPushButton("Tout auto completer")
        self.auto_complete_all_button.clicked.connect(self.auto_complete_all)
        top_layout.addWidget(self.auto_complete_all_button)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Rechercher...")
        self.search_bar.textChanged.connect(self.schedule_search)
        top_layout.addWidget(self.search_bar)

        self.cancel_button = QPushButton("Annuler")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_batch)
        top_layout.addWidget(self.cancel_button)

        top_layout.addStretch()
        main_layout.addLayout(top_layout)

        # ───────── CENTRE : IMAGES + PANEL DROIT ─────────
        center_layout = QHBoxLayout()

        # ───────── ZONE IMAGES ─────────
        image_layout = QVBoxLayout()
        self.size_levels = [48, 64, 96, 128, 192, 256, 384, 512]
        self.size_index = 4  # démarre à 192px
        self.image_size = self.size_levels[self.size_index]
        self.columns = 4
        self.scroll = QScrollArea()
        self.scroll.viewport().installEventFilter(self)
        self.scroll_widget = QWidget()
        self.grid = QGridLayout()
        self.scroll_widget.setLayout(self.grid)

        self.scroll.setWidget(self.scroll_widget)
        self.scroll.setWidgetResizable(True)

        image_layout.addWidget(self.scroll)

        # Progression batch
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        image_layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("")
        self.progress_label.setVisible(False)
        image_layout.addWidget(self.progress_label)

        center_layout.addLayout(image_layout, 3)

        # ───────── PANEL DROIT (CACHÉ AU DÉBUT) ─────────
        self.right_panel = QWidget()
        right_layout = QVBoxLayout()

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

        self.image_preview = QLabel()
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setFixedHeight(200)
        self.image_preview.setStyleSheet("border: 1px solid #ccc;")
        right_layout.addWidget(self.image_preview)

        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText("Description...")
        self.desc_edit.textChanged.connect(self.schedule_save)
        right_layout.addWidget(self.desc_edit)

        self.keywords_edit = QLineEdit()
        self.keywords_edit.setPlaceholderText("mot1, mot2, mot3")
        self.keywords_edit.textChanged.connect(self.schedule_save)
        right_layout.addWidget(self.keywords_edit)

        # Boutons droite
        self.auto_complete_button = QPushButton("Auto-compléter")
        self.auto_complete_button.clicked.connect(self.auto_complete)
        right_layout.addWidget(self.auto_complete_button)

        self.loading_label = QLabel("Analyse en cours...")
        self.loading_label.setVisible(False)
        right_layout.addWidget(self.loading_label)

        # ───────── VOISINS ─────────
        self.neighbors_container = QHBoxLayout()

        # Label voisins
        self.neighbors_label = QLabel("Images similaires")
        self.neighbors_label.setStyleSheet(
            "font-weight: bold; margin-top: 8px;"
        )

        # Nombre de voisins
        self.neighbors_input = QSpinBox()
        self.neighbors_input.setMinimum(1)
        self.neighbors_input.setMaximum(100)
        self.neighbors_input.setValue(5)
        self.neighbors_input.valueChanged.connect(self.neighbors_input_changed)

        # Ajout dans le layout
        self.neighbors_container.addWidget(self.neighbors_label)
        self.neighbors_container.addWidget(self.neighbors_input)

        self.neighbors_container.addStretch()

        right_layout.addLayout(self.neighbors_container)

        # Défilement pour les voisins
        self.neighbors_scroll = QScrollArea()
        self.neighbors_scroll.setFixedHeight(220)
        self.neighbors_scroll.setWidgetResizable(True)
        self.neighbors_widget = QWidget()
        self.neighbors_grid = QGridLayout()
        self.neighbors_grid.setSpacing(4)
        self.neighbors_widget.setLayout(self.neighbors_grid)
        self.neighbors_scroll.setWidget(self.neighbors_widget)
        right_layout.addWidget(self.neighbors_scroll)

        self.right_panel.setLayout(right_layout)
        self.right_panel.setVisible(False)

        center_layout.addWidget(self.right_panel, 1)

        main_layout.addLayout(center_layout)

        self.setLayout(main_layout)

        # Charger config
        config = self.load_config()
        self.current_folder = config.get("default_folder")
        if self.current_folder and os.path.exists(self.current_folder):
            self.load_images()

        self.k_neighbors = config.get("k_neighbors", 5)
        self.neighbors_input.setValue(self.k_neighbors)

    # ───────── CONFIG ─────────
    def load_config(self):
        if os.path.exists("config.json"):
            with open("config.json", "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_config(self):
        config = {
            "default_folder": self.current_folder,
            "k_neighbors": self.k_neighbors
        }
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    # ───────── INDEX ─────────
    def load_index(self):
        index_path = os.path.join(self.current_folder, "index.json")
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                self.index = json.load(f)
        else:
            self.index = {}

    def save_index(self):
        index_path = os.path.join(self.current_folder, "index.json")
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(self.index, f, indent=2, ensure_ascii=False)

    # ───────── DOSSIER ─────────
    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choisir un dossier")
        if not folder:
            return
        self.current_folder = folder

        self.save_config()
        self.load_images()

    # ───────── IMAGES ─────────
    def clear_grid(self):
        """Vide tous les widgets de la grille."""
        for i in reversed(range(self.grid.count())):
            w = self.grid.itemAt(i).widget()
            if w:
                w.setParent(None)

    def populate_grid(self, images: list[str]):
        """Ajoute une liste d'images dans la grille."""
        row, col = 0, 0
        for img_name in images:
            label = self.load_image(img_name)
            if label is None:
                continue
            self.grid.addWidget(label, row, col)
            col += 1
            if col == self.columns:
                col = 0
                row += 1

    def load_image(self, img_name: str) -> QLabel | None:
        """Crée et retourne un QLabel pour une image, ou None si elle est invalide."""
        path = os.path.join(self.current_folder, img_name)
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return None

        pixmap = pixmap.scaled(
            self.image_size,
            self.image_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setPixmap(pixmap)
        label.setStyleSheet("border: 2px solid transparent;")
        label.setToolTip("Indexé" if img_name in self.index else "Non indexé")
        label.mousePressEvent = lambda e, l=label, n=img_name: self.select_image(
            l, n)
        return label

    def load_images(self):
        """Charge toutes les images du dossier courant."""
        if not self.current_folder:
            return
        self.update_columns()
        self.load_index()
        self.clear_grid()

        try:

            images = [
                f for f in os.listdir(self.current_folder)
                if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp"))
            ]
            self.populate_grid(images)
            
        except FileNotFoundError as e:
            print(f"[ERROR] Dossier introuvable : {e}")

    def load_images_from_filter(self, filter: str):
        """Charge les images dont la description ou les mots-clés matchent le filtre."""
        if not self.current_folder:
            return
        self.update_columns()
        self.load_index()
        self.clear_grid()

        filter = filter.lower().strip()
        images = [
            img_name for img_name, data in self.index.items()
            if filter in data.get("description", "").lower()
            or filter in " ".join(data.get("keywords", [])).lower()
        ]
        self.populate_grid(images)

    def zoom_in(self):
        if self.size_index < len(self.size_levels) - 1:
            self.size_index += 1
            self.image_size = self.size_levels[self.size_index]
            self.reload_images()

    def zoom_out(self):
        if self.size_index > 0:
            self.size_index -= 1
            self.image_size = self.size_levels[self.size_index]
            self.reload_images()

    def update_columns(self):
        available_width = self.scroll.viewport().width()
        self.columns = max(1, available_width // (self.image_size + 8))

    def reload_images(self):
        # vide la grille
        for i in reversed(range(self.grid.count())):
            widget = self.grid.itemAt(i).widget()
            if widget:
                widget.deleteLater()

        # recharge
        self.load_images()

    def rename_image(self):
        if not self.selected_image or not self.current_folder:
            return

        new_name = self.title.text().strip()
        if not new_name or new_name == self.selected_image:
            return

        # Conserver l'extension si l'utilisateur l'a oubliée
        old_ext = os.path.splitext(self.selected_image)[1]
        if not os.path.splitext(new_name)[1]:
            new_name += old_ext

        old_path = os.path.join(self.current_folder, self.selected_image)
        new_path = os.path.join(self.current_folder, new_name)

        if os.path.exists(new_path):
            self.title.setText(self.selected_image)  # rollback
            self.title.setStyleSheet("border: 1px solid red;")
            self.title.setToolTip("❌ Un fichier avec ce nom existe déjà")
            return

        try:
            os.rename(old_path, new_path)
        except OSError as e:
            self.title.setStyleSheet("border: 1px solid red;")
            self.title.setToolTip(f"❌ Erreur : {e}")
            return

        # Mettre à jour l'index
        if self.selected_image in self.index:
            data = self.index.pop(self.selected_image)
            data["id"] = new_name
            data["path"] = new_path
            self.index[new_name] = data
            self.save_index()

        self.selected_image = new_name
        self.title.setStyleSheet("")
        self.title.setToolTip("")
        self.load_images()

    # ───────── SELECTION ─────────
    def select_image(self, label, img_name):
        if self.selected_label is not None:
            try:
                self.selected_label.setStyleSheet(
                    "border: 2px solid transparent;")
            except RuntimeError:
                self.selected_label = None

        self.selected_label = label
        self.selected_image = img_name

        path = os.path.join(self.current_folder, img_name)
        pixmap = QPixmap(path)

        if pixmap.isNull():
            print(f"[WARN] Impossible de charger : {path}")
            self.image_preview.clear()
        else:
            scaled = pixmap.scaled(
                self.image_preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.image_preview.setPixmap(scaled)

        label.setStyleSheet("border: 2px solid blue;")

        # Affiche le panel si première sélection
        if not self.right_panel.isVisible():
            self.right_panel.setVisible(True)

        self.title.setText(img_name)
        self.title.setStyleSheet("")
        self.title.setToolTip("")

        self.desc_edit.blockSignals(True)
        self.keywords_edit.blockSignals(True)

        data = self.index.get(img_name)
        if data:
            self.desc_edit.setText(data.get("description", ""))
            self.keywords_edit.setText(", ".join(data.get("keywords", [])))
        else:
            self.desc_edit.setText("")
            self.keywords_edit.setText("")

        self.display_neighbors(img_name)

        self.desc_edit.blockSignals(False)
        self.keywords_edit.blockSignals(False)

    def execute_search(self):
        text = self.search_bar.text().strip().lower()

        if text:
            self.load_images_from_filter(text)
        else:
            self.load_images()  # reset view

    def schedule_search(self):
        self.search_timer.start()

    # ───────── SAUVEGARDE ────────
    def save_metadata(self):
        if not self.selected_image or not self.current_folder:
            return

        desc = self.desc_edit.toPlainText()
        keywords = [
            k.strip()
            for k in self.keywords_edit.text().split(",")
            if k.strip()
        ]

        # UI feedback
        self.loading_label.setVisible(True)

        self.save_worker = SaveMetadataWorker(
            self.selected_image,
            self.current_folder,
            desc,
            keywords
        )

        self.save_worker.finished.connect(self.on_save_done)
        self.save_worker.error.connect(self.on_save_error)
        self.save_worker.start()

    def schedule_save(self):
        if not self.selected_image:
            return
        self.save_timer.start()

    def on_save_done(self):
        self.loading_label.setVisible(False)
        self.load_index()
        self.load_images()

    def on_save_error(self, msg):
        self.loading_label.setVisible(False)
        print(f"[SAVE ERROR] {msg}")

    # ───────── AUTO-COMPLÉTION (une image) ─────────
    def auto_complete(self):
        if not self.selected_image or not self.current_folder:
            return
        if self.worker and self.worker.isRunning():
            return

        image_path = os.path.join(self.current_folder, self.selected_image)
        self.auto_complete_button.setEnabled(False)
        self.loading_label.setVisible(True)

        self.worker = AutoCompleteWorker(image_path)
        self.worker.finished.connect(self.on_auto_complete_done)
        self.worker.error.connect(self.on_auto_complete_error)
        self.worker.start()

    def on_auto_complete_done(self, result):
        self.desc_edit.setText(result["description"])
        self.keywords_edit.setText(", ".join(result["keywords"]))
        self.reset_loading_state()

    def on_auto_complete_error(self, error_msg):
        self.title.setText(f"Erreur : {error_msg}")
        self.reset_loading_state()

    def reset_loading_state(self):
        self.loading_label.setVisible(False)
        self.auto_complete_button.setEnabled(True)

    # ───────── AUTO-COMPLÉTION BATCH ─────────
    def auto_complete_all(self):
        if not self.current_folder:
            return
        if self.batch_worker and self.batch_worker.isRunning():
            return

        images = [f for f in os.listdir(self.current_folder)
                  if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp"))]
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

        self.batch_worker = AutoCompleteAllWorker(self.current_folder, images)
        self.batch_worker.image_done.connect(self.on_batch_image_done)
        self.batch_worker.image_error.connect(self.on_batch_image_error)
        self.batch_worker.all_done.connect(self.on_batch_all_done)
        self.batch_worker.start()

    def on_batch_image_done(self, idx, img_name, result):
        desc = result["description"]
        keywords = result["keywords"]

        embedding = client.embed(
            model='nomic-embed-text:v1.5',
            text=client.build_embedding(desc, keywords)
        )

        self.index[img_name] = {
            "id": img_name,
            "path": os.path.join(self.current_folder, img_name),
            "description": desc,
            "keywords": keywords,
            "embedding": embedding
        }
        self.save_index()

        total = self.progress_bar.maximum()
        done = idx + 1
        self.progress_bar.setValue(done)
        self.progress_label.setText(f"{done} / {total} — ✅ {img_name}")

        if img_name == self.selected_image:
            self.desc_edit.setText(desc)
            self.keywords_edit.setText(", ".join(keywords))

        self.load_images()

    def on_batch_image_error(self, idx, img_name, error_msg):
        total = self.progress_bar.maximum()
        done = idx + 1
        self.progress_bar.setValue(done)
        self.progress_label.setText(
            f"{done} / {total} — ❌ {img_name} : {error_msg}")

    def on_batch_all_done(self):
        cancelled = self.batch_worker._cancelled
        total = self.progress_bar.maximum()
        done = self.progress_bar.value()

        if cancelled:
            self.progress_label.setText(f"⛔ Annulé")
        else:
            self.progress_label.setText(f"✅ Terminé — {total} images traitées")

        self.auto_complete_all_button.setEnabled(True)
        self.auto_complete_button.setEnabled(True)
        self.cancel_button.setVisible(False)

        sleep(4)  # Laisser le temps de lire le message final
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)

    def cancel_batch(self):
        if self.batch_worker and self.batch_worker.isRunning():
            self.batch_worker.cancel()
            self.cancel_button.setEnabled(False)
            self.progress_label.setText("⛔ Annulation...")

    # ────────── FENETRE ──────────
    def resizeEvent(self, event):
        super().resizeEvent(event)
        available_width = self.scroll.viewport().width()
        new_columns = max(1, available_width // (self.image_size + 8))
        if new_columns != self.columns:
            self.columns = new_columns
            self.reload_images()

    # ────────── EVENTS ──────────
    def wheelEvent(self, event):
        modifiers = event.modifiers()

        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
        else:
            super().wheelEvent(event)

    def eventFilter(self, source, event):
        if source == self.scroll.viewport() and event.type() == event.Type.Wheel:
            modifiers = event.modifiers()

            if modifiers & Qt.KeyboardModifier.ControlModifier:
                if event.angleDelta().y() > 0:
                    self.zoom_in()
                else:
                    self.zoom_out()

                return True  # 👈 bloque le scroll
        return super().eventFilter(source, event)

    # ────────── VOISINS ──────────
    def get_embedding_from_image(self, image_name: str):
        if image_name not in self.index:
            raise ValueError(f"Image '{image_name}' introuvable dans l'index")

        entry = self.index[image_name]

        if "embedding" in entry:
            return entry["embedding"]

        # Fallback : calcul à la volée si absent (images indexées avant la mise à jour)
        description = entry.get("description", "")
        keywords = entry.get("keywords", [])
        return client.embed(
            model='nomic-embed-text:v1.5',
            text=client.build_embedding(description, keywords)
        )

    def get_neighbors(self, image_name: str, top_k=5):

        if image_name not in self.index:
            return

        entry = self.index[image_name]
        neighbors = {}
        for key in self.index.keys():
            if key == image_name:
                continue

            similarity = client.similarite_cosinus(
                entry["embedding"], self.index[key]["embedding"])
            neighbors[key] = similarity

        # Tri des voisins par similarité (du plus similaire au moins similaire)
        sorted_neighbors = sorted(
            neighbors.items(), key=lambda x: x[1], reverse=True)
        return dict(sorted_neighbors[:top_k])

    def display_neighbors(self, img_name):
        # Vider la grille
        for i in reversed(range(self.neighbors_grid.count())):
            w = self.neighbors_grid.itemAt(i).widget()
            if w:
                w.deleteLater()

        if img_name not in self.index or not self.index[img_name].get("embedding"):
            self.neighbors_label.setText("Images similaires (pas d'embedding)")
            return

        neighbors = self.get_neighbors(img_name, top_k=self.k_neighbors)
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

            pixmap = pixmap.scaled(
                THUMB, THUMB,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

            cell = QWidget()
            cell_layout = QVBoxLayout()
            cell_layout.setContentsMargins(2, 2, 2, 2)
            cell_layout.setSpacing(2)

            thumb = QLabel()
            thumb.setPixmap(pixmap)
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb.setStyleSheet("border: 1px solid #ccc; border-radius: 3px;")
            thumb.mousePressEvent = lambda e, l=thumb, n=neighbor_name: self.select_image(
                l, n)
            thumb.setCursor(Qt.CursorShape.PointingHandCursor)

            score_label = QLabel(f"{score:.2f}")
            score_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            score_label.setStyleSheet("font-size: 10px; color: #666;")

            cell_layout.addWidget(thumb)
            cell_layout.addWidget(score_label)
            cell.setLayout(cell_layout)

            self.neighbors_grid.addWidget(cell, row, col)
            col += 1
            if col == 3:
                col = 0
                row += 1

    def neighbors_input_changed(self):
        if self.selected_image:
            self.k_neighbors = self.neighbors_input.value()
            self.save_config()
            self.display_neighbors(self.selected_image)


# ───────── MAIN ─────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ImageExplorer()
    window.show()
    sys.exit(app.exec())
