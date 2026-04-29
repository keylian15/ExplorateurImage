"""
ImageListModel   - QAbstractListModel stockant uniquement des noms de fichiers.
ImageGridDelegate - QStyledItemDelegate dessinant thumbnails + indicateur d'index.

Le QListView fait le travail de virtualisation : seules les cellules
visibles à l'écran déclenchent un appel à paint(). Le delegate demande
le thumbnail au cache ; s'il est absent, il peint un placeholder et
déclenche le chargement asynchrone via ThumbnailScheduler.
"""

from __future__ import annotations

from PyQt6.QtCore import (
    Qt, QAbstractListModel, QModelIndex, QSize, QRect, QPoint,
    pyqtSignal
)
from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen, QBrush
from PyQt6.QtWidgets import QStyledItemDelegate, QStyle

from thumbnail_cache import ThumbnailCache
from workers import ThumbnailScheduler


# ──────────────────────────────────────────────
#  Rôles personnalisés
# ──────────────────────────────────────────────

IMG_NAME_ROLE = Qt.ItemDataRole.UserRole + 1   # str  : nom du fichier
INDEXED_ROLE = Qt.ItemDataRole.UserRole + 2   # bool : présent dans index.json
SELECTED_ROLE = Qt.ItemDataRole.UserRole + 3   # bool : sélectionné (highlight)


# ──────────────────────────────────────────────
#  Modèle
# ──────────────────────────────────────────────

class ImageListModel(QAbstractListModel):
    """
    Stocke une liste ordonnée de noms de fichiers images.
    N'alloue aucune ressource graphique.
    """

    def __init__(self, parent=None):
        """Initialise le modèle avec une liste vide, aucun index, et aucune sélection."""

        super().__init__(parent)
        self._images: list[str] = []
        self._indexed: set[str] = set()   # noms présents dans index.json
        self._selected: str | None = None

    # ──────────────────────────────────────────────
    # Fonctions Publiques
    # ──────────────────────────────────────────────

    def set_images(self, images: list[str]):
        """Remplace la liste d'images par une nouvelle liste. Notifie la vue du changement.

        Args:
            images (list[str]): La nouvelle liste de noms d'images.
        """

        self.beginResetModel()
        self._images = list(images)
        self.endResetModel()

    def set_indexed(self, indexed: set[str]):
        """Met à jour l'ensemble des images indexées et notifie la vue du changement.

        Args:
            indexed (set[str]): L'ensemble des noms d'images indexées.
        """
        self._indexed = indexed
        if self._images:
            top = self.index(0)
            bottom = self.index(len(self._images) - 1)
            self.dataChanged.emit(top, bottom, [INDEXED_ROLE])

    def set_selected(self, img_name: str | None):
        """Met à jour l'image sélectionnée et notifie la vue du changement.

        Args:
            img_name (str | None): Le nom de l'image sélectionnée.
        """

        old = self._selected
        self._selected = img_name
        for name in (old, img_name):
            if name and name in self._images:
                idx = self._images.index(name)
                mi = self.index(idx)
                self.dataChanged.emit(mi, mi, [SELECTED_ROLE])

    def image_at(self, row: int) -> str:
        """Retourne le nom de l'image à la ligne donnée.
        Args:
            row (int): La ligne.

        Returns:
            str: Le nom de l'image.
            """

        return self._images[row]

    def row_of(self, img_name: str) -> int | None:
        """Retourne la ligne de l'image donnée, ou None si elle n'est pas dans la liste.
        Args:
            img_name (str): Le nom de l'image.

        Returns:    
            int | None: La ligne de l'image, ou None si elle n'est pas dans la liste.
        """

        try:
            return self._images.index(img_name)
        except ValueError:
            return None

    def notify_image_updated(self, img_name: str):
        """Force le repaint d'une cellule (thumbnail chargé, indexation changée...).

        Args:
            img_name (str): Le nom de l'image.
        """
        row = self.row_of(img_name)
        if row is not None:
            mi = self.index(row)
            self.dataChanged.emit(mi, mi)

    # ──────────────────────────────────────────────
    # Interface QAbstractListModel
    # ──────────────────────────────────────────────

    def rowCount(self, _parent=QModelIndex()) -> int:
        """Retourne le nombre d'images dans la liste.
        Args:
            _parent: Ignoré (paramètre requis par l'interface)."""
        return len(self._images)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        """Retourne les données pour une cellule donnée et un rôle donné.
        Args:
            index (QModelIndex): La cellule demandée.
            role: Le rôle de données demandé (nom de fichier, indexé, sélectionné...).
        Returns:
            Les données correspondant au rôle demandé, ou None si le rôle n'est pas reconnu.
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


# ──────────────────────────────────────────────
#  Delegate
# ──────────────────────────────────────────────

# Couleurs
_COL_PLACEHOLDER = QColor("#2b2b2b")
_COL_INDEXED_DOT = QColor("#4caf50")
_COL_BORDER_SEL = QColor("#4a90d9")
_COL_BORDER_NORM = QColor("transparent")
_COL_LOADING_TXT = QColor("#888888")


class ImageGridDelegate(QStyledItemDelegate):
    """
    Dessine chaque cellule :
      - thumbnail (depuis le cache) ou placeholder gris
      - point vert si l'image est dans l'index
      - bordure bleue si sélectionnée

    Demande le chargement asynchrone des thumbnails manquants via
    ThumbnailScheduler.
    """

    # Émis quand on a besoin d'un repaint suite à thumbnail chargé.
    # Connecté par la vue après construction.
    repaint_requested = pyqtSignal(str)

    BORDER = 2
    DOT_RADIUS = 5
    PADDING = 4

    def __init__(self, cache: ThumbnailCache,
                 scheduler: ThumbnailScheduler,
                 cell_size: int = 192,
                 parent=None):
        """Initialise le delegate avec le cache de thumbnails, le scheduler, et la taille de cellule.
        Args:
            cache (ThumbnailCache): Le cache de thumbnails à utiliser pour récupérer les pixmaps.
            scheduler (ThumbnailScheduler): Le scheduler pour demander le chargement asynchrone des thumbnails
            cell_size (int, optional): La taille (largeur et hauteur) de chaque cellule. Defaults to 192.
            parent: Le parent QObject. Defaults to None.
        """
        super().__init__(parent)
        self.cache = cache
        self.scheduler = scheduler
        self.cell_size = cell_size

        # Quand un thumbnail est prêt : repaint de la cellule correspondante
        self.scheduler.thumbnail_ready.connect(self._on_thumbnail_ready)

    # ──────────────────────────────────────────────
    # Taille de cellule
    # ──────────────────────────────────────────────

    def sizeHint(self, _option, _index) -> QSize:
        """Retourne la taille de chaque cellule (carrée, définie par cell_size).
        Args:
            _option: Ignoré (paramètre requis par l'interface).
            _index: Ignoré (paramètre requis par l'interface).
        """
        return QSize(self.cell_size, self.cell_size)

    def set_cell_size(self, size: int):
        """Set la taille des cellules et émet un signal pour que la vue se mette à jour.

        Args:
            size (int): La nouvelle taille des cellules.
        """
        self.cell_size = size

    # ──────────────────────────────────────────────
    # Dessin
    # ──────────────────────────────────────────────

    def paint(self, painter: QPainter, option, index: QModelIndex):
        """Dessine la cellule : thumbnail ou placeholder, bordure de sélection, et point indexé.
        Args:
            painter (QPainter): Le painter utilisé pour dessiner la cellule.
            option: Les options de style pour la cellule (contient notamment le rectangle de dessin).
            index (QModelIndex): L'index de la cellule à dessiner (contient les données de l'image).
        """
        img_name = index.data(IMG_NAME_ROLE)
        if not img_name:
            return

        is_selected = index.data(SELECTED_ROLE) or bool(
            option.state & QStyle.StateFlag.State_Selected
        )
        is_indexed = index.data(INDEXED_ROLE)

        rect: QRect = option.rect
        inner = rect.adjusted(
            self.BORDER, self.BORDER,
            -self.BORDER, -self.BORDER
        )

        painter.save()
        # ──────────────────────────────────────────────
        # FOND
        # ──────────────────────────────────────────────

        painter.fillRect(rect, _COL_PLACEHOLDER)

        # ──────────────────────────────────────────────
        # THUMBNAIL ou PLACEHOLDER
        # ──────────────────────────────────────────────

        pixmap: QPixmap | None = self.cache.get(img_name)

        if pixmap is not None:
            # Centrer dans la cellule
            pw, ph = pixmap.width(), pixmap.height()
            x = inner.x() + (inner.width() - pw) // 2
            y = inner.y() + (inner.height() - ph) // 2
            painter.drawPixmap(x, y, pixmap)
        else:
            # Placeholder : on demande le chargement
            self.scheduler.submit(img_name)
            painter.setPen(_COL_LOADING_TXT)
            painter.drawText(inner, Qt.AlignmentFlag.AlignCenter, "...")

        # ──────────────────────────────────────────────
        # BORDURE DE SÉLECTION
        # ──────────────────────────────────────────────

        border_color = _COL_BORDER_SEL if is_selected else _COL_BORDER_NORM
        pen = QPen(border_color, self.BORDER)
        painter.setPen(pen)
        painter.drawRect(rect.adjusted(
            self.BORDER // 2, self.BORDER // 2,
            -self.BORDER // 2, -self.BORDER // 2
        ))

        # ──────────────────────────────────────────────
        # INDICATEUR INDEXÉ
        # ──────────────────────────────────────────────

        if is_indexed:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QBrush(_COL_INDEXED_DOT))
            painter.setPen(Qt.PenStyle.NoPen)
            cx = rect.right() - self.DOT_RADIUS - 4
            cy = rect.bottom() - self.DOT_RADIUS - 4
            painter.drawEllipse(
                QPoint(cx, cy),
                self.DOT_RADIUS, self.DOT_RADIUS
            )

        painter.restore()

    # ──────────────────────────────────────────────
    # SLOT : thumbnail prêt
    # ──────────────────────────────────────────────

    def _on_thumbnail_ready(self, img_name: str, _pixmap: QPixmap):
        """Quand un thumbnail est prêt, on demande un repaint de la cellule correspondante.
        Args:
            img_name (str): Le nom de l'image dont le thumbnail est prêt.
            _pixmap (QPixmap): Le pixmap du thumbnail (non utilisé ici, car le cache a déjà été mis à jour).
        """
        # Le cache a déjà été mis à jour par ThumbnailScheduler.
        # On demande juste au modèle de notifier la vue.
        self.repaint_requested.emit(img_name)
