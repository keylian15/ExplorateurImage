"""
models/image_model.py

ImageListModel   — QAbstractListModel stockant uniquement des noms de fichiers.
ImageGridDelegate — QStyledItemDelegate dessinant thumbnails + indicateur d'index.

Inchangé fonctionnellement par rapport à la version d'origine.
Les couleurs et dimensions viennent de styles.py.
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._images: list[str] = []
        self._indexed: set[str] = set()
        self._selected: str | None = None

    def set_images(self, images: list[str]):
        self.beginResetModel()
        self._images = list(images)
        self.endResetModel()

    def set_indexed(self, indexed: set[str]):
        self._indexed = indexed
        if self._images:
            self.dataChanged.emit(self.index(0), self.index(len(self._images) - 1), [INDEXED_ROLE])

    def set_selected(self, img_name: str | None):
        old = self._selected
        self._selected = img_name
        for name in (old, img_name):
            if name and name in self._images:
                mi = self.index(self._images.index(name))
                self.dataChanged.emit(mi, mi, [SELECTED_ROLE])

    def image_at(self, row: int) -> str:
        return self._images[row]

    def row_of(self, img_name: str) -> int | None:
        try:
            return self._images.index(img_name)
        except ValueError:
            return None

    def notify_image_updated(self, img_name: str):
        row = self.row_of(img_name)
        if row is not None:
            mi = self.index(row)
            self.dataChanged.emit(mi, mi)

    # ── Interface QAbstractListModel ──────────────────────────────────────────

    def rowCount(self, _parent: QModelIndex | None = None) -> int:
        return len(self._images)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
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
        super().__init__(parent)
        self.cache = cache
        self.scheduler = scheduler
        self.cell_size = cell_size
        self.scheduler.thumbnail_ready.connect(self._on_thumbnail_ready)

    def sizeHint(self, _option, _index) -> QSize:
        return QSize(self.cell_size, self.cell_size)

    def set_cell_size(self, size: int):
        self.cell_size = size

    def paint(self, painter: QPainter, option, index: QModelIndex):
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

    def _on_thumbnail_ready(self, img_name: str, _pixmap: QPixmap):
        self.repaint_requested.emit(img_name)
