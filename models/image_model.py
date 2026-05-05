"""
Modèle et delegate Qt pour l'affichage d'une grille d'images avec thumbnails.

Le module fournit un modèle léger basé sur les noms de fichiers (sans charger les images en mémoire)
et un delegate responsable du rendu des cellules : affichage des thumbnails via cache, gestion du chargement
asynchrone, indication des éléments sélectionnés et marqués comme indexés.

Il s'appuie sur un cache de thumbnails et un scheduler pour générer les images manquantes à la demande,
afin de garantir de bonnes performances même avec un grand nombre d'images.
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QPoint,
    QRect,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QStyle, QStyledItemDelegate

from services.thumbnail_cache import ThumbnailCache
from services.workers import ThumbnailScheduler
from styles import COLORS, THUMB

# ── Rôles personnalisés ───────────────────────────────────────────────────────
IMG_NAME_ROLE = Qt.ItemDataRole.UserRole + 1
INDEXED_ROLE = Qt.ItemDataRole.UserRole + 2
SELECTED_ROLE = Qt.ItemDataRole.UserRole + 3

# ── Couleurs (depuis styles.py) ───────────────────────────────────────────────
_COL_PLACEHOLDER = QColor(COLORS["thumb_placeholder"])
_COL_INDEXED_DOT = QColor(COLORS["indexed_dot"])
_COL_BORDER_SEL = QColor(COLORS["selection_border"])
_COL_BORDER_NORM = QColor("transparent")
_COL_LOADING_TXT = QColor(COLORS["thumb_loading_text"])


# ═════════════════════════════════════════════════════════════════════════════
#  Modèle
# ═════════════════════════════════════════════════════════════════════════════


class ImageListModel(QAbstractListModel):
    """Stocke une liste ordonnée de noms de fichiers images."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._images: list[str] = []
        self._indexed: set[str] = set()
        self._selected: str | None = None

    def set_images(self, images: list[str]) -> None:
        """Remplace la liste d'images par une nouvelle. Réinitialise la sélection.

        Args:
            images (list[str]): La nouvelle liste de noms de fichiers.
        """

        self.beginResetModel()
        self._images = list(images)
        self.endResetModel()

    def set_indexed(self, indexed: set[str]) -> None:
        """Met à jour la liste des images indexées. Émet un signal de changement de données pour les images concernées.

        Args:
            indexed (set[str]): Le nouvel ensemble de noms de fichiers indexés.
        """

        self._indexed = indexed
        if self._images:
            self.dataChanged.emit(self.index(0), self.index(len(self._images) - 1), [INDEXED_ROLE])

    def set_selected(self, img_name: str | None) -> None:
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

    def notify_image_updated(self, img_name: str) -> None:
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
        if role == Qt.ItemDataRole.DisplayRole:
            return name
        return None


# ═════════════════════════════════════════════════════════════════════════════
#  Delegate
# ═════════════════════════════════════════════════════════════════════════════


class ImageGridDelegate(QStyledItemDelegate):
    """Dessine chaque cellule : thumbnail, bordure de sélection, point indexé."""

    repaint_requested = pyqtSignal(str)

    BORDER = THUMB["border_width"]
    DOT_RADIUS = THUMB["dot_radius"]
    PADDING = THUMB["padding"]

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
            cell_size (int, optional): La taille des cellules en pixels. Par défaut à
            parent (Any, optional): Le parent QObject. Par défaut à None.
        """

        super().__init__(parent)
        self.cache = cache
        self.scheduler = scheduler
        self.cell_size = cell_size
        self.scheduler.thumbnail_ready.connect(self.on_thumbnail_ready)

    def set_cell_size(self, size: int) -> None:
        """Met à jour la taille des cellules.

        Args:
            size (int): La nouvelle taille des cellules en pixels.
        Returns:
            None
        """

        self.cell_size = size

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        """Dessine une cellule : thumbnail centré, bordure bleue si sélectionnée, point vert si indexée.

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
        rect: QRect = option.rect
        inner = rect.adjusted(self.BORDER, self.BORDER, -self.BORDER, -self.BORDER)

        painter.save()
        painter.fillRect(rect, _COL_PLACEHOLDER)

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

        border_color = _COL_BORDER_SEL if is_selected else _COL_BORDER_NORM
        painter.setPen(QPen(border_color, self.BORDER))
        painter.drawRect(rect.adjusted(self.BORDER // 2, self.BORDER // 2, -self.BORDER // 2, -self.BORDER // 2))

        if is_indexed:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QBrush(_COL_INDEXED_DOT))
            painter.setPen(Qt.PenStyle.NoPen)
            cx = rect.right() - self.DOT_RADIUS - 4
            cy = rect.bottom() - self.DOT_RADIUS - 4
            painter.drawEllipse(QPoint(cx, cy), self.DOT_RADIUS, self.DOT_RADIUS)

        painter.restore()

    def on_thumbnail_ready(self, img_name: str) -> None:
        """Emet un signal pour indiquer que le thumbnail d'une image est prêt, afin que la cellule correspondante soit redessinée.

        Args:
            img_name (str): Le nom de fichier de l'image dont le thumbnail est prêt.
        """

        self.repaint_requested.emit(img_name)
