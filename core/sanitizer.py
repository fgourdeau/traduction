"""Sanitizer — nettoie le texte brut avant découpage et analyse.

Appliqué entre OCR/collage et l'affichage/analyse. Objectif :
- Le texte affiché = le texte envoyé à Claude = tokens 1:1
- Retirer le bruit des articles web (crédits, liens, dates, métadonnées)
- Normaliser espaces et ponctuation
- Garder le texte narratif espagnol intact
"""

import re
import unicodedata


def sanitiser(texte: str) -> str:
    """Nettoie un texte brut pour l'analyse grammaticale espagnole.

    Étapes :
    1. Normaliser Unicode (NFC)
    2. Retirer les lignes de bruit (métadonnées, crédits, liens)
    3. Normaliser la ponctuation et les espaces
    4. Reconstruire un texte propre
    """
    texte = _normaliser_unicode(texte)
    lignes = texte.split("\n")
    lignes = [_nettoyer_ligne(l) for l in lignes]
    lignes = [l for l in lignes if not _est_ligne_bruit(l)]
    texte = "\n".join(lignes)
    texte = _normaliser_espaces(texte)
    return texte.strip()


# ─── Étape 1 : Unicode ──────────────────────────────────────────

def _normaliser_unicode(texte: str) -> str:
    """NFC + remplacer les variantes Unicode par des formes standard."""
    texte = unicodedata.normalize("NFC", texte)
    # Guillemets typographiques → guillemets droits
    texte = texte.replace("\u201c", '"').replace("\u201d", '"')  # " "
    texte = texte.replace("\u2018", "'").replace("\u2019", "'")  # ' '
    texte = texte.replace("\u00ab", '"').replace("\u00bb", '"')  # « »
    # Tirets longs → tiret simple
    texte = texte.replace("\u2013", "-").replace("\u2014", "-")  # – —
    # Espaces insécables et variantes
    texte = texte.replace("\u00a0", " ")   # espace insécable
    texte = texte.replace("\u200b", "")    # zero-width space
    texte = texte.replace("\u200c", "")    # zero-width non-joiner
    texte = texte.replace("\u200d", "")    # zero-width joiner
    texte = texte.replace("\ufeff", "")    # BOM
    return texte


# ─── Étape 2 : Détection de lignes de bruit ─────────────────────

# Patterns de lignes à supprimer
_PATTERNS_BRUIT = [
    # Crédits photo / agence
    re.compile(r"^\s*\(?(REUTERS|AFP|EFE|AP|Getty|EPA)\)?\s*$", re.I),
    re.compile(r"^\s*\w+\s+\w+\s+\((REUTERS|AFP|EFE|AP|Getty)\)\s*$", re.I),
    # Lignes de partage social
    re.compile(r"Compartir\s+en\s+\w+", re.I),
    re.compile(r"Copiar\s+enlace", re.I),
    # Lignes "Ir a los comentarios"
    re.compile(r"^\s*Ir\s+a\s+los\s+comentarios\s*$", re.I),
    # Date/heure de publication (ex: "París - 18 MAR 2026 - 04:24 GMT-5")
    re.compile(r"^\s*\w+\s*-\s*\d{1,2}\s+\w{3}\s+\d{4}\s*-\s*\d{2}:\d{2}"),
    # Lignes de navigation web
    re.compile(r"^\s*(Volver|Siguiente|Anterior|Cerrar|Menú)\s*$", re.I),
    # Lignes avec seulement un nombre (pagination, etc.)
    re.compile(r"^\s*\d{1,3}\s*$"),
]

# Ligne trop courte pour être une phrase (sauf si c'est un mot espagnol plausible)
_MIN_LONGUEUR_LIGNE = 3


def _est_ligne_bruit(ligne: str) -> bool:
    """Détecte si une ligne est du bruit (métadonnées, liens, crédits)."""
    stripped = ligne.strip()

    # Ligne vide → garder (sert de séparateur de paragraphe)
    if not stripped:
        return False

    # Trop court (1-2 chars non-ponctuation)
    alpha = re.sub(r"[^a-záéíóúüñ]", "", stripped, flags=re.I)
    if len(alpha) < _MIN_LONGUEUR_LIGNE and len(stripped) < 10:
        return True

    # Patterns connus
    for pattern in _PATTERNS_BRUIT:
        if pattern.search(stripped):
            return True

    # Ligne qui ne contient que des noms propres répétés (byline)
    # Ex: "Daniel Verdú Daniel Verdú"
    mots = stripped.split()
    if len(mots) >= 2 and len(mots) <= 6:
        # Vérifier si c'est une répétition exacte
        moitie = len(mots) // 2
        if mots[:moitie] == mots[moitie:2 * moitie] and all(
            m[0].isupper() for m in mots if m[0].isalpha()
        ):
            return True

    return False


# ─── Étape 3 : Nettoyage de ligne ───────────────────────────────

def _nettoyer_ligne(ligne: str) -> str:
    """Nettoie une ligne individuelle."""
    # Retirer les tokens de partage collés (WhatsappCompartir en Facebook...)
    ligne = re.sub(
        r"(Compartir\s+en\s+\w+)+Copiar\s+enlace",
        "", ligne, flags=re.I,
    )
    ligne = re.sub(r"Compartir\s+en\s+\w+", "", ligne, flags=re.I)
    ligne = re.sub(r"Copiar\s+enlace", "", ligne, flags=re.I)

    return ligne


# ─── Étape 4 : Espaces ──────────────────────────────────────────

def _normaliser_espaces(texte: str) -> str:
    """Normalise les espaces multiples, tabs, etc."""
    # Tabs → espaces
    texte = texte.replace("\t", " ")
    # Espaces multiples → simple (sauf sauts de ligne)
    texte = re.sub(r"[^\S\n]+", " ", texte)
    # Lignes vides multiples → une seule
    texte = re.sub(r"\n{3,}", "\n\n", texte)
    # Espaces en début/fin de ligne
    texte = re.sub(r" *\n *", "\n", texte)
    return texte