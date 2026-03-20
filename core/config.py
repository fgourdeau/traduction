"""Configuration globale — couleurs, catégories grammaticales."""

from PySide6.QtGui import QColor, QFont

# ─── Couleurs par catégorie grammaticale ─────────────────────────────
COULEURS_CATEGORIES: dict[str, str] = {
    "sustantivo":   "#2563eb",
    "verbo":        "#dc2626",
    "adjetivo":     "#059669",
    "adverbio":     "#7c3aed",
    "pronombre":    "#d97706",
    "preposición":  "#6b7280",
    "preposicion":  "#6b7280",
    "artículo":     "#64748b",
    "articulo":     "#64748b",
    "conjunción":   "#6b7280",
    "conjuncion":   "#6b7280",
    "determinante": "#64748b",
    "interjección":  "#ec4899",
    "interjeccion": "#ec4899",
    "numeral":      "#0891b2",
}

COULEUR_DEFAUT = "#1a1613"

# ─── Couleurs de fond par groupe syntaxique ──────────────────────────
# Chaque groupe est affiché avec un fond semi-transparent
# reprenant la couleur de la catégorie grammaticale associée.
COULEURS_GROUPES: dict[str, str] = {
    "sujeto":       "#d97706",   # pronombre (orange)
    "verbo":        "#dc2626",   # verbo (rouge)
    "complemento":  "#2563eb",   # sustantivo (bleu)
    "relativa":     "#059669",   # adjetivo (vert)
}

OPACITE_FOND_GROUPE = 25  # 0-255


def couleur_fond_groupe(groupe: str) -> QColor | None:
    """QColor semi-transparente pour le fond d'un groupe, ou None."""
    normalized = groupe.lower().strip()
    hex_color = COULEURS_GROUPES.get(normalized)
    if hex_color is None:
        return None
    c = QColor(hex_color)
    c.setAlpha(OPACITE_FOND_GROUPE)
    return c


# ─── Labels français pour groupes ────────────────────────────────────
LABELS_GROUPES: dict[str, str] = {
    "sujeto":       "Sujet",
    "verbo":        "Groupe verbal",
    "complemento":  "Complément",
    "relativa":     "Relative",
}


# ─── Couleurs UI ─────────────────────────────────────────────────────
COULEUR_FOND = QColor("#f6f1eb")
COULEUR_PANNEAU = QColor("#fffdf9")
COULEUR_SELECTION = QColor("#fff3e0")
COULEUR_ACCENT = QColor("#c0582a")
COULEUR_EXPRESSION = QColor("#c0582a")
COULEUR_BORDURE = QColor("#e0d6c8")
COULEUR_TEXTE_SECONDAIRE = QColor("#5c5349")
COULEUR_TEXTE_MUET = QColor("#9b9084")

# ─── Polices ─────────────────────────────────────────────────────────
def police_texte(taille: int = 16) -> QFont:
    f = QFont("IBM Plex Sans", taille)
    return f

def police_titre(taille: int = 20) -> QFont:
    f = QFont("DM Serif Display", taille)
    return f

def police_mono(taille: int = 12) -> QFont:
    f = QFont("JetBrains Mono", taille)
    return f


def couleur_pour_categorie(categorie: str) -> QColor:
    """Retourne la QColor correspondant à une catégorie grammaticale."""
    normalized = categorie.lower().strip()
    hex_color = COULEURS_CATEGORIES.get(normalized, COULEUR_DEFAUT)
    return QColor(hex_color)


def couleur_douce_pour_categorie(categorie: str) -> QColor:
    """Version assombrie / désaturée — pour le texte analysé au repos."""
    c = couleur_pour_categorie(categorie)
    # Mélanger avec noir pour assombrir tout en perdant du chroma
    r = int(c.red() * 0.55 + 60 * 0.45)
    g = int(c.green() * 0.55 + 60 * 0.45)
    b = int(c.blue() * 0.55 + 60 * 0.45)
    return QColor(r, g, b)


# ─── Labels français pour catégories ─────────────────────────────────
LABELS_CATEGORIES: dict[str, str] = {
    "sustantivo":   "Nom",
    "verbo":        "Verbe",
    "adjetivo":     "Adjectif",
    "adverbio":     "Adverbe",
    "pronombre":    "Pronom",
    "preposición":  "Préposition",
    "preposicion":  "Préposition",
    "artículo":     "Article",
    "articulo":     "Article",
    "conjunción":   "Conjonction",
    "conjuncion":   "Conjonction",
    "determinante": "Déterminant",
    "interjección":  "Interjection",
    "interjeccion": "Interjection",
    "numeral":      "Numéral",
}