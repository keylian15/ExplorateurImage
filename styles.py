"""
Ce module centralise l'ensemble du système de style de l'application (QSS, couleurs, typographie et métriques).
Il constitue l'unique point de configuration de l'apparence graphique et permet une mise à jour dynamique du thème.

Les couleurs sont chargées depuis `colors.json` via `color_repository`, ce qui permet leur modification en temps réel
depuis l'interface utilisateur sans redémarrage de l'application.

Responsabilités :
1. Définir et centraliser la palette de couleurs globale (COLORS)
2. Définir la typographie (polices, tailles, graisses)
3. Définir les métriques UI (padding, marges, arrondis, espacements)
4. Générer dynamiquement la feuille de style QSS globale (get_stylesheet)
5. Fournir des styles réutilisables pour les composants UI (helpers inline)
6. Assurer la cohérence visuelle entre tous les modules de l'application
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
    """Génère et retourne la feuille de style QSS complète de l'application.

    La feuille de style est construite dynamiquement à partir des dictionnaires
    COLORS, FONTS et METRICS. Elle couvre tous les widgets Qt utilisés dans
    l'application : fenêtre principale, onglets, boutons, champs de saisie,
    scrollbars, liste d'images, dock, barre de progression, tooltips, etc.

    Doit être rappelée et réinjectée via ``QApplication.setStyleSheet()``
    chaque fois que COLORS est modifié (par exemple depuis l'onglet Thème)
    pour que les changements soient pris en compte en live.

    Returns:
        str: La feuille de style QSS complète prête à être passée à
             ``QApplication.setStyleSheet()``.
    """
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
    """Retourne le style QSS pour le widget d'aperçu de l'image sélectionnée.

    Applique une bordure fine, des coins arrondis et le fond « carte »
    défini dans COLORS. Utilisé dans le dock de détail.

    Returns:
        str: Chaîne de style QSS inline.
    """
    return f"border: 1px solid {COLORS['border']}; border-radius: {METRICS['border_radius']}; background: {COLORS['bg_card']};"


def neighbor_thumb_style(selected: bool = False) -> str:
    """Retourne le style QSS pour une miniature de voisin dans la grille de similaires.

    La couleur de bordure change selon l'état de sélection :
    accent si sélectionné, bordure neutre sinon.

    Args:
        selected (bool): True si la miniature est actuellement sélectionnée.
                         Defaults to False.

    Returns:
        str: Chaîne de style QSS inline.
    """
    color = COLORS["accent"] if selected else COLORS["border"]
    return f"border: 1px solid {color}; border-radius: {METRICS['border_radius_sm']}; background: {COLORS['bg_card']};"


def score_label_style() -> str:
    """Retourne le style QSS pour le label de score de similarité cosinus.

    Applique une petite taille de police et la couleur de texte secondaire,
    afin que le score reste discret sous chaque miniature de voisin.

    Returns:
        str: Chaîne de style QSS inline.
    """
    return f"font-size: {FONTS['size_small']}; color: {COLORS['text_secondary']};"


def section_title_style() -> str:
    """Retourne le style QSS pour les titres de section dans le dock de détail.

    Applique une graisse élevée, une marge supérieure et la couleur de texte
    principale pour distinguer visuellement les sections (ex : « Images similaires »).

    Returns:
        str: Chaîne de style QSS inline.
    """
    return f"font-weight: {FONTS['weight_bold']}; margin-top: 8px; color: {COLORS['text_primary']};"


def fullscreen_bar_style() -> str:
    """Retourne le style QSS pour la barre de contrôle du dialog plein écran.

    Applique le fond principal et une bordure inférieure séparant la barre
    des boutons de zoom de la zone d'affichage de l'image.

    Returns:
        str: Chaîne de style QSS inline.
    """
    return f"background: {COLORS['bg_primary']}; border-bottom: 1px solid {COLORS['border']};"


def fullscreen_scroll_style() -> str:
    """Retourne le style QSS pour la zone de défilement du dialog plein écran.

    Combine le fond « carte » avec la suppression de toute bordure visible,
    afin que la zone d'image occupe l'espace sans cadre superflu.

    Returns:
        str: Chaîne de style QSS inline.
    """
    return f"background: {COLORS['bg_card']}; {no_border_style()}"


def fullscreen_label_style() -> str:
    """Retourne le style QSS pour le QLabel portant l'image en plein écran.

    Applique uniquement le fond « carte » pour assurer un arrière-plan cohérent
    derrière l'image zoomée, quelle que soit sa taille.

    Returns:
        str: Chaîne de style QSS inline.
    """
    return f"background: {COLORS['bg_card']};"


def rename_error_style() -> str:
    """Retourne le style QSS signalant une erreur de renommage sur le champ de titre.

    Applique une bordure rouge (couleur ``error`` du thème) et des coins arrondis
    au QLineEdit du nom de fichier lorsque le renommage échoue.

    Returns:
        str: Chaîne de style QSS inline.
    """
    return f"border: 1px solid {COLORS['error']}; border-radius: {METRICS['border_radius']};"


def legend_label_style() -> str:
    """Retourne le style QSS pour le titre de la légende de la carte 2D.

    Applique une graisse élevée et la taille de police normale pour que
    l'en-tête « Clusters » reste lisible dans le panneau latéral de la carte.

    Returns:
        str: Chaîne de style QSS inline.
    """
    return f"font-weight: {FONTS['weight_bold']}; font-size: {FONTS['size_normal']};"


def dot_color_style(color_name: str) -> str:
    """Retourne le style QSS pour le point coloré d'un cluster dans la légende.

    Génère un petit carré plein aux coins arrondis avec la couleur du cluster,
    utilisé comme indicateur visuel à côté du nom du cluster.

    Args:
        color_name (str): Objet QColor dont la méthode ``name()`` fournit
                          la valeur hexadécimale (ex : ``QColor("#5488C8")``).

    Returns:
        str: Chaîne de style QSS inline.
    """
    return f"background:{color_name.name()}; border-radius: {METRICS['border_radius']};"


def dot_label_style() -> str:
    """Retourne le style QSS pour le label textuel d'un cluster dans la légende.

    Applique une petite taille de police pour que les noms de clusters restent
    compacts dans le panneau latéral de la carte 2D.

    Returns:
        str: Chaîne de style QSS inline.
    """
    return f"font-size: {FONTS['size_small']};"


def style_label_name_style() -> str:
    """Retourne le style QSS pour le nom d'une couleur dans l'onglet Thème.

    Applique une graisse élevée et la taille de police normale afin que
    le nom de chaque entrée de couleur (ex : « Fond principal ») soit
    clairement lisible dans la grille de l'éditeur.

    Returns:
        str: Chaîne de style QSS inline.
    """
    return f"font-weight: {FONTS['weight_bold']}; font-size: {FONTS['size_normal']};"


def style_label_subname_style() -> str:
    """Retourne le style QSS pour la description courte d'une couleur dans l'onglet Thème.

    Applique une petite taille de police et la couleur de texte secondaire,
    afin que la description reste discrète sous le nom principal de la couleur.

    Returns:
        str: Chaîne de style QSS inline.
    """
    return f"font-size: {FONTS['size_small']}; color: {COLORS['text_secondary']};"


def style_tittle_style() -> str:
    """Retourne le style QSS pour le titre principal de l'onglet Thème.

    Applique une grande taille de police et une graisse élevée pour mettre
    en valeur le titre « Éditeur de paramètres » en haut de l'onglet.

    Returns:
        str: Chaîne de style QSS inline.
    """
    return f"font-size: {FONTS['size_large']}; font-weight: {FONTS['weight_bold']};"


def style_presset_style() -> str:
    """Retourne le style QSS pour le label de section « Thèmes prédéfinis ».

    Applique une petite taille de police en majuscules, un espacement de
    lettres élargi et la couleur de texte secondaire, dans le style des
    titres de section discrets (uppercase + letter-spacing).

    Returns:
        str: Chaîne de style QSS inline.
    """
    return f"font-weight: {FONTS['weight_bold']}; font-size: {FONTS['size_small']}; color: {COLORS['text_secondary']}; text-transform: uppercase; letter-spacing: 1px;"


def style_separator_style() -> str:
    """Retourne le style QSS pour les séparateurs horizontaux de l'onglet Thème.

    Utilise la couleur « bg_card » pour que les lignes de séparation entre
    les groupes de couleurs restent subtiles et cohérentes avec le fond.

    Returns:
        str: Chaîne de style QSS inline.
    """
    return f"color: {COLORS['bg_card']};"


def no_border_style() -> str:
    """Retourne le style QSS supprimant toute bordure visible sur un widget.

    Utile pour les QScrollArea ou tout conteneur dont on veut effacer le
    cadre par défaut de Qt.

    Returns:
        str: Chaîne de style QSS inline (``"border: none;"``).
    """
    return "border: none;"


# ── Sélecteur de langue ───────────────────────────────────────────────────────


def lang_card_style(selected: bool = False) -> str:
    """Retourne le style QSS pour une carte de langue cliquable.

    Affiche une bordure accentuée si la langue est actuellement sélectionnée,
    une bordure neutre sinon. Coins arrondis et fond « carte » dans les deux cas.

    Args:
        selected (bool): True si cette langue est la langue active.

    Returns:
        str: Chaîne de style QSS.
    """
    border = COLORS["accent"] if selected else COLORS["border"]
    bg = COLORS["bg_hover"] if selected else COLORS["bg_card"]
    width = 2 if selected else 1
    return (
        f'QWidget[class="lang-card"] {{'
        f"background-color: {bg};"
        f"border: {width}px solid {border};"
        f"border-radius: {METRICS['border_radius_lg']};"
        f"}}"
        f'QWidget[class="lang-card"]:hover {{'
        f"border: 2px solid {COLORS['accent_hover']};"
        f"}}"
    )


def lang_flag_style() -> str:
    """Retourne le style QSS pour l'emoji drapeau d'une carte de langue.

    Applique une grande taille de police pour que le drapeau soit
    immédiatement reconnaissable dans la grille de sélection.

    Returns:
        str: Chaîne de style QSS inline.
    """
    return "font-size: 28px; border: none; background: transparent;"


def lang_name_style(selected: bool = False) -> str:
    """Retourne le style QSS pour le nom d'une langue dans sa carte.

    Le texte est en accent et en gras si la langue est sélectionnée,
    en texte secondaire sinon.

    Args:
        selected (bool): True si cette langue est la langue active.

    Returns:
        str: Chaîne de style QSS inline.
    """
    color = COLORS["accent"] if selected else COLORS["text_secondary"]
    weight = FONTS["weight_bold"] if selected else FONTS["weight_normal"]
    return f"font-size: {FONTS['size_small']}; color: {color}; font-weight: {weight}; border: none; background: transparent;"


def lang_check_style() -> str:
    """Retourne le style QSS pour la coche affichée sur la langue active.

    Applique la couleur de succès et une taille de police adaptée pour
    indiquer clairement la langue actuellement sélectionnée.

    Returns:
        str: Chaîne de style QSS inline.
    """
    return f"color: {COLORS['success']}; font-size: 14px; font-weight: {FONTS['weight_bold']}; border: none; background: transparent;"
