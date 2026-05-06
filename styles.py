"""
styles.py — Thème visuel global de l'application.

C'est le SEUL fichier à modifier pour changer l'apparence.
Toutes les couleurs, polices, marges et QSS sont centralisées ici.

Les couleurs (COLORS) sont désormais persistées dans colors.json
et gérées via models/color_repository.py, ce qui permet leur édition
en direct depuis l'onglet Thème sans redémarrer l'application.
"""

from models import color_repository

# ── Palette de base ───────────────────────────────────────────────────────────
# Chargée depuis colors.json (avec fallback sur les défauts intégrés)

COLORS: dict[str, str] = color_repository.load()

# ── Typographie ───────────────────────────────────────────────────────────────

FONTS = {
    "family": "Segoe UI, Arial, sans-serif",
    "size_normal": "13px",
    "size_small": "11px",
    "size_large": "15px",
    "size_title": "16px",
    "weight_bold": "600",
    "weight_normal": "400",
}

# ── Dimensions ────────────────────────────────────────────────────────────────

METRICS = {
    "border_radius": "6px",
    "border_radius_sm": "4px",
    "border_radius_lg": "10px",
    "padding_sm": "4px 8px",
    "padding_md": "6px 12px",
    "padding_lg": "8px 16px",
    "spacing_xs": "4px",
    "spacing_sm": "8px",
    "spacing_md": "12px",
    "spacing_lg": "16px",
}

# ── Thumbnail / grille ────────────────────────────────────────────────────────

THUMB = {
    "default_size": 192,
    "size_levels": [48, 64, 96, 128, 192, 256, 384, 512],
    "size_index_default": 4,  # 192 px
    "lru_max_memory": 600,
    "prefetch_rows": 3,
    "spacing": 4,
    "border_width": 2,
    "dot_radius": 5,
    "padding": 4,
}

# ── QSS global ───────────────────────────────────────────────────────────────
# Injecté une seule fois dans QApplication.setStyleSheet().
# Relu à chaque appel → les changements de COLORS sont pris en compte.


def get_stylesheet() -> str:
    c = COLORS
    f = FONTS
    m = METRICS
    return f"""
    /* ── Base ── */
    QWidget {{
        background-color: {c["bg_primary"]};
        color: {c["text_primary"]};
        font-family: {f["family"]};
        font-size: {f["size_normal"]};
    }}

    /* ── Fenêtre principale ── */
    QMainWindow {{
        background-color: {c["bg_primary"]};
    }}

    /* ── Onglets ── */
    QTabWidget::pane {{
        border: 1px solid {c["border"]};
        border-radius: {m["border_radius"]};
    }}
    QTabBar::tab {{
        background: {c["bg_card"]};
        color: {c["text_secondary"]};
        padding: {m["padding_md"]};
        margin-right: 2px;
        border-top-left-radius: {m["border_radius"]};
        border-top-right-radius: {m["border_radius"]};
    }}
    QTabBar::tab:selected {{
        background: {c["bg_secondary"]};
        color: {c["text_primary"]};
        border-bottom: 2px solid {c["accent"]};
    }}
    QTabBar::tab:hover:!selected {{
        background: {c["bg_hover"]};
        color: {c["text_primary"]};
    }}

    /* ── Boutons ── */
    QPushButton {{
        background-color: {c["bg_card"]};
        color: {c["text_primary"]};
        border: 1px solid {c["border"]};
        border-radius: {m["border_radius"]};
        padding: {m["padding_md"]};
        min-width: 80px;
    }}
    QPushButton:hover {{
        background-color: {c["bg_hover"]};
        border-color: {c["accent"]};
    }}
    QPushButton:pressed {{
        background-color: {c["accent_pressed"]};
        color: #ffffff;
    }}
    QPushButton:disabled {{
        color: {c["text_disabled"]};
        border-color: {c["border"]};
    }}
    QPushButton:checked {{
        background-color: {c["accent"]};
        color: #ffffff;
        border-color: {c["accent"]};
    }}

    /* ── Champs texte ── */
    QLineEdit, QTextEdit {{
        background-color: {c["bg_input"]};
        color: {c["text_primary"]};
        border: 1px solid {c["border"]};
        border-radius: {m["border_radius"]};
        padding: {m["padding_sm"]};
        selection-background-color: {c["accent"]};
    }}
    QLineEdit:focus, QTextEdit:focus {{
        border-color: {c["border_focus"]};
    }}
    QLineEdit::placeholder {{
        color: {c["text_muted"]};
    }}

    /* ── Barre de recherche (plus grande) ── */
    QLineEdit#search_bar {{
        font-size: {f["size_large"]};
        padding: 6px 14px;
        border-radius: {m["border_radius_lg"]};
    }}

    /* ── SpinBox ── */
    QSpinBox, QDoubleSpinBox {{
        background-color: {c["bg_input"]};
        color: {c["text_primary"]};
        border: 1px solid {c["border"]};
        border-radius: {m["border_radius"]};
        padding: 3px 6px;
    }}
    QSpinBox:focus, QDoubleSpinBox:focus {{
        border-color: {c["border_focus"]};
    }}
    QSpinBox::up-button, QSpinBox::down-button,
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        width: 0px;
        height: 0px;
        border: none;
    }}

    QSpinBox::up-arrow, QSpinBox::down-arrow,
    QDoubleSpinBox::up-arrow, QDoubleSpinBox::down-arrow {{
        image: none;
    }}

    /* ── Scroll ── */
    QScrollBar:vertical {{
        background: {c["bg_secondary"]};
        width: 8px;
        margin: 0;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: {c["text_muted"]};
        border-radius: 4px;
        min-height: 20px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {c["text_secondary"]};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background: {c["bg_secondary"]};
        height: 8px;
        margin: 0;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal {{
        background: {c["text_muted"]};
        border-radius: 4px;
        min-width: 20px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {c["text_secondary"]};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}

    /* ── ListView (galerie) ── */
    QListView {{
        background-color: {c["bg_primary"]};
        border: none;
    }}
    QListView::item:selected {{
        background: transparent;
    }}

    /* ── Dock ── */
    QDockWidget {{
        color: {c["text_primary"]};
        font-weight: {f["weight_bold"]};
    }}
    QDockWidget::title {{
        background: {c["bg_card"]};
        padding: 6px 10px;
        border-bottom: 1px solid {c["border"]};
    }}

    /* ── Progress bar ── */
    QProgressBar {{
        background-color: {c["bg_card"]};
        border: 1px solid {c["border"]};
        border-radius: {m["border_radius"]};
        text-align: center;
        color: {c["text_primary"]};
        height: 18px;
    }}
    QProgressBar::chunk {{
        background-color: {c["accent"]};
        border-radius: {m["border_radius_sm"]};
    }}

    /* ── Tooltip ── */
    QToolTip {{
        background-color: {c["bg_card"]};
        color: {c["text_primary"]};
        border: 1px solid {c["border"]};
        border-radius: {m["border_radius_sm"]};
        padding: 4px 8px;
        font-size: {f["size_small"]};
    }}

    /* ── Séparateur ── */
    QFrame[frameShape="4"],
    QFrame[frameShape="5"] {{
        color: {c["border"]};
    }}

    /* ── ScrollArea ── */
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollArea > QWidget > QWidget {{
        background: transparent;
    }}

    /* ── Labels ── */
    QLabel {{
        color: {c["text_primary"]};
    }}
    QLabel[class="muted"] {{
        color: {c["text_secondary"]};
        font-size: {f["size_small"]};
    }}

    /* ── Graphics View (carte 2D) ── */
    QGraphicsView {{
        background-color: {c["bg_secondary"]};
        border: 1px solid {c["border"]};
        border-radius: {m["border_radius"]};
    }}
    """


# ── Helpers inline ────────────────────────────────────────────────────────────


def image_preview_style() -> str:
    return f"border: 1px solid {COLORS['border']}; border-radius: {METRICS['border_radius']}; background: {COLORS['bg_card']};"


def neighbor_thumb_style(selected: bool = False) -> str:
    color = COLORS["accent"] if selected else COLORS["border"]
    return f"border: 1px solid {color}; border-radius: {METRICS['border_radius_sm']}; background: {COLORS['bg_card']};"


def score_label_style() -> str:
    return f"font-size: {FONTS['size_small']}; color: {COLORS['text_secondary']};"


def section_title_style() -> str:
    return f"font-weight: {FONTS['weight_bold']}; margin-top: 8px; color: {COLORS['text_primary']};"


def fullscreen_bar_style() -> str:
    return f"background: {COLORS['bg_primary']}; border-bottom: 1px solid {COLORS['border']};"


def fullscreen_scroll_style() -> str:
    return f"background: {COLORS['bg_card']}; {no_border_style()}"


def fullscreen_label_style() -> str:
    return f"background: {COLORS['bg_card']};"


def rename_error_style() -> str:
    return f"border: 1px solid {COLORS['error']}; border-radius: {METRICS['border_radius']};"


def legend_label_style() -> str:
    return f"font-weight: {FONTS['weight_bold']}; font-size: {FONTS['size_normal']};"


def dot_color_style(color_name: str) -> str:
    return f"background:{color_name.name()}; border-radius: {METRICS['border_radius']};"


def dot_label_style() -> str:
    return f"font-size: {FONTS['size_small']};"


def no_border_style() -> str:
    return "border: none;"
