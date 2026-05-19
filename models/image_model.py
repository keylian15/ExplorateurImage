"""
Affichage et gestion d'une grille d'images avec thumbnails dans Qt.

Ce module fournit :
 - un modèle léger basé sur les noms de fichiers (sans chargement d'images en mémoire),
 - un delegate responsable du rendu visuel des cellules (thumbnails, sélection, état indexé,
   état épinglé),
 - une gestion performante du chargement asynchrone des images via cache et scheduler.

Responsabilités :
 1. Fournir un modèle Qt représentant une liste d'images sans charger les fichiers en mémoire
 2. Gérer les états associés aux images (sélection, indexation, épinglage, mises à jour)
 3. Exposer des rôles Qt personnalisés pour l'UI (nom, sélection, indexation, épinglage)
 4. Dessiner chaque cellule de la grille avec un delegate personnalisé
    (thumbnail, bordure, indicateurs indexé + épinglé)
 5. Interagir avec un cache de thumbnails pour éviter les rechargements inutiles
 6. Déclencher la génération asynchrone des thumbnails manquants via un scheduler
 7. Notifier la vue lors de la disponibilité d'un nouveau thumbnail

Contenu :
 - Modèle Qt basé sur QAbstractListModel
 - Delegate de rendu basé sur QStyledItemDelegate
 - Rôles Qt personnalisés pour les données d'affichage
 - Intégration cache + génération asynchrone des thumbnails
 - Logique de rendu (sélection, indexation, épinglage, placeholder, bordures)
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QPoint,
    QRect,
    QSize,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QStyle, QStyledItemDelegate

from services.thumbnail_cache import ThumbnailCache
from services.workers import ThumbnailScheduler
from styles import COLORS, THUMB

# ── Rôles personnalisés ───────────────────────────────────────────────────────
IMG_NAME_ROLE = Qt.ItemDataRole.UserRole + 1
INDEXED_ROLE = Qt.ItemDataRole.UserRole + 2
SELECTED_ROLE = Qt.ItemDataRole.UserRole + 3
PINNED_ROLE = Qt.ItemDataRole.UserRole + 4

# ── Couleurs (depuis styles.py) ───────────────────────────────────────────────
_COL_PLACEHOLDER = QColor(COLORS["thumb_placeholder"])
_COL_INDEXED_DOT = QColor(COLORS["indexed_dot"])
_COL_BORDER_SEL = QColor(COLORS["selection_border"])
_COL_BORDER_NORM = QColor("transparent")
_COL_LOADING_TXT = QColor(COLORS["thumb_loading_text"])

# ── Couleurs spécifiques à l'épingle ─────────────────────────────────────────
_COL_PIN_BG = QColor(245, 158, 11, 220)  # ambre semi-transparent (warning)
_COL_PIN_BG_HOVER = QColor(245, 158, 11, 255)  # ambre plein au survol
_COL_PIN_ICON = QColor(255, 255, 255)  # icône blanche


# ═════════════════════════════════════════════════════════════════════════════
#  Modèle
# ═════════════════════════════════════════════════════════════════════════════


class ImageListModel(QAbstractListModel):
    """Stocke une liste ordonnée de noms de fichiers images."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._images: list[str] = []
        self._indexed: set[str] = set()
        self._selected: str | None = None
        self._pinned: set[str] = set()

    def set_images(self, images: list[str]):
        """Remplace la liste d'images par une nouvelle. Réinitialise la sélection.

        Args:
            images (list[str]): La nouvelle liste de noms de fichiers.
        """

        self.beginResetModel()
        self._images = list(images)
        self.endResetModel()

    def set_indexed(self, indexed: set[str]):
        """Met à jour la liste des images indexées. Émet un signal de changement de données pour les images concernées.

        Args:
            indexed (set[str]): Le nouvel ensemble de noms de fichiers indexés.
        """

        self._indexed = indexed
        if self._images:
            self.dataChanged.emit(self.index(0), self.index(len(self._images) - 1), [INDEXED_ROLE])

    def set_pinned(self, pinned: set[str]):
        """Met à jour l'ensemble des images épinglées.

        Args:
            pinned (set[str]): Le nouvel ensemble de noms de fichiers épinglés.
        """
        self._pinned = set(pinned)
        if self._images:
            self.dataChanged.emit(self.index(0), self.index(len(self._images) - 1), [PINNED_ROLE])

    def set_selected(self, img_name: str | None):
        """Met à jour l'image sélectionnée. Émet un signal de changement de données pour l'ancienne et la nouvelle image sélectionnée.

        Args:
            img_name (str | None): Le nom de fichier de la nouvelle image sélectionnée, ou None pour aucune sélection.
        """

        old = self._selected
        self._selected = img_name
        for name in (old, img_name):
            if name and name in self._images:
                mi = self.index(self._images.index(name))
                self.dataChanged.emit(mi, mi, [SELECTED_ROLE])

    def image_at(self, row: int) -> str:
        """Retourne le nom de fichier de l'image à la ligne donnée.

        Args:
            row (int): L'index de la ligne.
        Returns:
            str: Le nom de fichier de l'image à la ligne donnée.
        """
        return self._images[row]

    def row_of(self, img_name: str) -> int | None:
        """Retourne l'index de la ligne de l'image donnée, ou None si elle n'est pas dans la liste.

        Args:
            img_name (str): Le nom de fichier de l'image.
        Returns:
            int | None: L'index de la ligne de l'image, ou None si elle n'est pas dans la liste.
        """

        try:
            return self._images.index(img_name)
        except ValueError:
            return None

    def notify_image_updated(self, img_name: str):
        """Indique que l'image donnée a été mise à jour. Émet un signal de changement de données pour cette image.

        Args:
            img_name (str): Le nom de fichier de l'image mise à jour.
        """

        row = self.row_of(img_name)
        if row is not None:
            mi = self.index(row)
            self.dataChanged.emit(mi, mi)

    # ── Interface QAbstractListModel ──────────────────────────────────────────

    def rowCount(self, _parent: QModelIndex | None = None) -> int:
        """Retourne le nombre d'images dans la liste.

        Args:
            _parent (QModelIndex | None): Ignoré, car ce modèle n'est pas hiérarchique.
        Returns:
            int: Le nombre d'images dans la liste.
        """

        return len(self._images)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole) -> str | bool | None:
        """Retourne les données pour une cellule donnée et un rôle donné.

        Args:
            index (QModelIndex): L'index de la cellule.
            role (Qt.ItemDataRole): Le rôle pour lequel les données sont demandées.
        Returns:
            str | bool | None: Les données pour la cellule et le rôle donnés, ou None si l'index n'est pas valide ou si le rôle n'est pas reconnu.
        """

        if not index.isValid() or index.row() >= len(self._images):
            return None
        name = self._images[index.row()]
        if role == IMG_NAME_ROLE:
            return name
        if role == INDEXED_ROLE:
            return name in self._indexed
        if role == SELECTED_ROLE:
            return name == self._selected
        if role == PINNED_ROLE:
            return name in self._pinned
        if role == Qt.ItemDataRole.DisplayRole:
            return name
        return None


# ═════════════════════════════════════════════════════════════════════════════
#  Delegate
# ═════════════════════════════════════════════════════════════════════════════


class ImageGridDelegate(QStyledItemDelegate):
    """Dessine chaque cellule : thumbnail, bordure de sélection, point indexé, badge épinglé."""

    signal_repaint_requested = pyqtSignal(str)

    BORDER = THUMB["border_width"]
    DOT_RADIUS = THUMB["dot_radius"]
    PADDING = THUMB["padding"]

    # Dimensions du badge 📌 (coin haut-gauche)
    PIN_BADGE_SIZE = 20  # taille du carré de fond arrondi
    PIN_FONT_SIZE = 11  # taille de l'emoji en px

    def __init__(
        self,
        cache: ThumbnailCache,
        scheduler: ThumbnailScheduler,
        cell_size: int = 192,
        parent=None,
    ):
        """Initialise le delegate avec une référence au cache de thumbnails et au scheduler de génération de thumbnails.

        Args:
            cache (ThumbnailCache): Le cache de thumbnails à utiliser pour récupérer les thumbnails à dessiner
            scheduler (ThumbnailScheduler): Le scheduler de génération de thumbnails à utiliser pour demander la génération de thumbnails manquants
            cell_size (int, optional): La taille des cellules en pixels. Par défaut à 192.
            parent (Any, optional): Le parent QObject. Par défaut à None.
        """

        super().__init__(parent)
        self.cache = cache
        self.scheduler = scheduler
        self.cell_size = cell_size
        self.scheduler.signal_thumbnail_ready.connect(self.on_signal_thumbnail_ready)

    def sizeHint(self, _option, _index) -> QSize:
        """Override de la méthode sizeHint pour retourner la taille des cellules.

        Args:
            _option (QStyleOptionViewItem): Les options de style du QListView
            _index (QModelIndex): L'index du QListView

        Returns:
            QSize: La taille des cellules en pixels
        """
        return QSize(self.cell_size, self.cell_size)

    def set_cell_size(self, size: int):
        """Met à jour la taille des cellules.

        Args:
            size (int): La nouvelle taille des cellules en pixels.
        Returns:
            None
        """

        self.cell_size = size

    def paint(self, painter: QPainter, option, index: QModelIndex):
        """Dessine une cellule : thumbnail centré, bordure bleue si sélectionnée,
        point vert si indexée, badge 📌 en haut à gauche si épinglée.

        Args:
            painter (QPainter): Le painter à utiliser pour dessiner la cellule.
            option (QStyleOptionViewItem): Les options de dessin fournies par Qt.
            index (QModelIndex): L'index de la cellule à dessiner.
        """
        img_name = index.data(IMG_NAME_ROLE)
        if not img_name:
            return

        is_selected = index.data(SELECTED_ROLE) or bool(option.state & QStyle.StateFlag.State_Selected)
        is_indexed = index.data(INDEXED_ROLE)
        is_pinned = index.data(PINNED_ROLE)
        rect: QRect = option.rect
        inner = rect.adjusted(self.BORDER, self.BORDER, -self.BORDER, -self.BORDER)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(rect, _COL_PLACEHOLDER)

        # ── Thumbnail ─────────────────────────────────────────────────────────
        pixmap: QPixmap | None = self.cache.get(img_name)
        if pixmap is not None:
            pw, ph = pixmap.width(), pixmap.height()
            x = inner.x() + (inner.width() - pw) // 2
            y = inner.y() + (inner.height() - ph) // 2
            painter.drawPixmap(x, y, pixmap)
        else:
            self.scheduler.submit(img_name)
            painter.setPen(_COL_LOADING_TXT)
            painter.drawText(inner, Qt.AlignmentFlag.AlignCenter, "...")

        # ── Bordure de sélection ──────────────────────────────────────────────
        border_color = _COL_BORDER_SEL if is_selected else _COL_BORDER_NORM
        painter.setPen(QPen(border_color, self.BORDER))
        painter.drawRect(rect.adjusted(self.BORDER // 2, self.BORDER // 2, -self.BORDER // 2, -self.BORDER // 2))

        # ── Point "indexé" (coin bas-droit) ───────────────────────────────────
        if is_indexed:
            painter.setBrush(QBrush(_COL_INDEXED_DOT))
            painter.setPen(Qt.PenStyle.NoPen)
            cx = rect.right() - self.DOT_RADIUS - 4
            cy = rect.bottom() - self.DOT_RADIUS - 4
            painter.drawEllipse(QPoint(cx, cy), self.DOT_RADIUS, self.DOT_RADIUS)

        # ── Badge 📌 (coin haut-gauche) ───────────────────────────────────────
        if is_pinned:
            self.draw_pin_badge(painter, rect)

        painter.restore()

    def draw_pin_badge(self, painter: QPainter, cell_rect: QRect):
        """Dessine le badge épingle dans le coin haut-gauche de la cellule.

        Le badge est un petit carré arrondi ambré avec l'emoji 📌 centré.

        Args:
            painter (QPainter): Le painter actif.
            cell_rect (QRect): Rectangle de la cellule entière.
        """
        margin = self.BORDER + 3
        size = self.PIN_BADGE_SIZE

        badge_rect = QRect(
            cell_rect.left() + margin,
            cell_rect.top() + margin,
            size,
            size,
        )

        # Fond arrondi ambré semi-transparent
        painter.setBrush(QBrush(_COL_PIN_BG))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect, 4, 4)

        # Emoji 📌 centré dans le badge
        font = QFont()
        font.setPixelSize(self.PIN_FONT_SIZE)
        painter.setFont(font)
        painter.setPen(_COL_PIN_ICON)
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, "📌")

    def on_signal_thumbnail_ready(self, img_name: str):
        """Emet un signal pour indiquer que le thumbnail d'une image est prêt, afin que la cellule correspondante soit redessinée.

        Args:
            img_name (str): Le nom de fichier de l'image dont le thumbnail est prêt.
        """

        self.signal_repaint_requested.emit(img_name)
