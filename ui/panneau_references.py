"""Panneau de références grammaticales — fiches thématiques depuis JSON.

Architecture v3 :
- Chargement JIT : seule la fiche sélectionnée est construite en widgets
- Zoom par QGraphicsView.scale() : pas de reconstruction au zoom
- Cache LRU : les N dernières fiches sont gardées, les autres libérées
"""

import json
from pathlib import Path
from dataclasses import dataclass

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor, QWheelEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame, QPushButton, QGraphicsView, QGraphicsScene,
    QGraphicsProxyWidget,
)

from core.config import (
    COULEUR_FOND, COULEUR_PANNEAU, COULEUR_BORDURE, COULEUR_ACCENT,
    COULEUR_TEXTE_SECONDAIRE, COULEUR_TEXTE_MUET,
    police_texte, police_titre, police_mono,
)

# Répertoire par défaut des fiches
#REFERENCES_DIR = Path(__file__).parent.parent / "references"
from core.paths import REFERENCES_DIR
# Tailles de base
_BASE = {
    "section_titre": 12,
    "texte": 14,
    "exemple": 13,
    "regle": 13,
    "tableau": 13,
    "header": 26,
    "resume": 13,
    "bouton": 11,
}

# Zoom
ZOOM_MIN = 0.5
ZOOM_MAX = 3.0
ZOOM_STEP = 0.1
ZOOM_DEFAULT = 1.0

# Cache LRU : nombre de fiches gardées en mémoire
CACHE_MAX = 5


# ═════════════════════════════════════════════════════════════════════
# Modèle de données
# ═════════════════════════════════════════════════════════════════════

@dataclass
class ThemeReference:
    id: str
    titre: str
    icone: str
    ordre: int
    resume: str
    sections: list[dict]
    chemin: Path
    hooks: list[str] = None  # clés de légende rattachées (ex: ["sustantivo", "sujeto"])

    def __post_init__(self):
        if self.hooks is None:
            self.hooks = []

    @classmethod
    def charger(cls, chemin: Path) -> "ThemeReference | None":
        try:
            data = json.loads(chemin.read_text(encoding="utf-8"))
            return cls(
                id=data.get("id", chemin.stem),
                titre=data.get("titre", chemin.stem),
                icone=data.get("icone", "📖"),
                ordre=data.get("ordre", 99),
                resume=data.get("resume", ""),
                sections=data.get("sections", []),
                chemin=chemin,
                hooks=data.get("hooks", []),
            )
        except (json.JSONDecodeError, KeyError, OSError) as e:
            print(f"[Références] Erreur chargement {chemin}: {e}")
            return None


def charger_themes(repertoire: Path | None = None) -> list[ThemeReference]:
    rep = repertoire or REFERENCES_DIR
    if not rep.exists():
        print(f"[Références] Répertoire absent: {rep}")
        return []
    themes = []
    for f in sorted(rep.glob("*.json")):
        theme = ThemeReference.charger(f)
        if theme:
            themes.append(theme)
            print(f"[Références] Chargé: {theme.icone} {theme.titre} ({f.name})")
    themes.sort(key=lambda t: t.ordre)
    return themes


def _sz(base_key: str) -> int:
    """Taille de police de base (le zoom est géré par QGraphicsView.scale)."""
    return _BASE[base_key]


# ═════════════════════════════════════════════════════════════════════
# Rendu des sections
# ═════════════════════════════════════════════════════════════════════

def _style_section_titre() -> str:
    return (
        f"color: {COULEUR_ACCENT.name()}; font-weight: bold; "
        f"letter-spacing: 1px; padding: 8px 0 4px 0; "
        f"font-size: {_sz('section_titre')}px;"
    )


def _creer_section_texte(section: dict) -> QWidget:
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setContentsMargins(0, 0, 0, 8)
    layout.setSpacing(4)

    titre = QLabel(section.get("titre", "").upper())
    titre.setStyleSheet(_style_section_titre())
    layout.addWidget(titre)

    contenu = QLabel(section.get("contenu", ""))
    contenu.setWordWrap(True)
    contenu.setStyleSheet(
        f"color: {COULEUR_TEXTE_SECONDAIRE.name()}; "
        f"line-height: 1.5; padding: 4px 0; "
        f"font-size: {_sz('texte')}px;"
    )
    layout.addWidget(contenu)
    return w


def _creer_section_tableau(section: dict) -> QWidget:
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setContentsMargins(0, 0, 0, 12)
    layout.setSpacing(4)

    titre = QLabel(section.get("titre", "").upper())
    titre.setStyleSheet(_style_section_titre())
    layout.addWidget(titre)

    colonnes = section.get("colonnes", [])
    lignes = section.get("lignes", [])
    accent = COULEUR_ACCENT.name()
    bordure = COULEUR_BORDURE.name()
    fond = "#f6f1eb"
    fs = _sz("tableau")

    html = (
        f'<table cellspacing="0" cellpadding="6" '
        f'style="border-collapse:collapse; width:100%; font-size:{fs}px;">'
    )
    html += "<tr>"
    for col in colonnes:
        html += (
            f'<th style="background:{accent}; color:white; '
            f'padding:6px 10px; text-align:left; '
            f'border:1px solid {bordure};">{col}</th>'
        )
    html += "</tr>"
    for i, ligne in enumerate(lignes):
        bg = fond if i % 2 == 0 else "white"
        html += "<tr>"
        for j, cell in enumerate(ligne):
            weight = "bold" if j == 0 else "normal"
            html += (
                f'<td style="background:{bg}; padding:5px 10px; '
                f'border:1px solid {bordure}; font-weight:{weight};">'
                f'{cell}</td>'
            )
        html += "</tr>"
    html += "</table>"

    lbl = QLabel(html)
    lbl.setTextFormat(Qt.RichText)
    lbl.setWordWrap(True)
    layout.addWidget(lbl)
    return w


def _creer_section_exemples(section: dict) -> QWidget:
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setContentsMargins(0, 0, 0, 8)
    layout.setSpacing(4)

    titre = QLabel(section.get("titre", "").upper())
    titre.setStyleSheet(_style_section_titre())
    layout.addWidget(titre)

    accent = COULEUR_ACCENT.name()
    muet = COULEUR_TEXTE_MUET.name()
    fs = _sz("exemple")

    for item in section.get("items", []):
        es = item.get("es", "")
        fr = item.get("fr", "")
        html = (
            f'<span style="color:{accent}; font-weight:bold; font-size:{fs}px;">'
            f'{es}</span><br>'
            f'<span style="color:{muet}; font-style:italic; font-size:{fs - 1}px;">'
            f'{fr}</span>'
        )
        lbl = QLabel(html)
        lbl.setTextFormat(Qt.RichText)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            "background: #f6f1eb; padding: 8px 12px; "
            "border-radius: 4px; margin: 2px 0;"
        )
        layout.addWidget(lbl)
    return w


def _creer_section_regles(section: dict) -> QWidget:
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setContentsMargins(0, 0, 0, 8)
    layout.setSpacing(4)

    titre = QLabel(section.get("titre", "").upper())
    titre.setStyleSheet(_style_section_titre())
    layout.addWidget(titre)

    accent = COULEUR_ACCENT.name()
    fs = _sz("regle")

    for item in section.get("items", []):
        regle = item.get("regle", "")
        detail = item.get("detail", "")
        html = (
            f'<span style="color:{accent}; font-weight:bold; font-size:{fs}px;">'
            f'▸ {regle}</span><br>'
            f'<span style="color:#5c5349; font-size:{fs - 1}px;">{detail}</span>'
        )
        lbl = QLabel(html)
        lbl.setTextFormat(Qt.RichText)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("padding: 4px 0 4px 8px;")
        layout.addWidget(lbl)
    return w


_SECTION_RENDERERS = {
    "texte": _creer_section_texte,
    "tableau": _creer_section_tableau,
    "exemples": _creer_section_exemples,
    "regles": _creer_section_regles,
}


# ═════════════════════════════════════════════════════════════════════
# Construire le widget d'une fiche (appelé JIT)
# ═════════════════════════════════════════════════════════════════════

def _construire_fiche_widget(theme: ThemeReference, largeur: int = 800) -> QWidget:
    """Construit le widget d'une fiche. Appelé une seule fois par thème (cache LRU)."""
    content = QWidget()
    content.setFixedWidth(largeur)
    content.setStyleSheet(f"background: {COULEUR_PANNEAU.name()};")

    layout = QVBoxLayout(content)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(6)

    header = QLabel(f"{theme.icone} {theme.titre}")
    header.setFont(police_titre(_sz("header")))
    header.setStyleSheet(f"color: {COULEUR_ACCENT.name()}; padding-bottom: 4px;")
    layout.addWidget(header)

    resume = QLabel(theme.resume)
    resume.setWordWrap(True)
    resume.setStyleSheet(
        f"color: {COULEUR_TEXTE_MUET.name()}; "
        f"font-style: italic; padding-bottom: 12px; "
        f"font-size: {_sz('resume')}px;"
    )
    layout.addWidget(resume)

    sep = QFrame()
    sep.setFrameShape(QFrame.HLine)
    sep.setStyleSheet(f"color: {COULEUR_BORDURE.name()};")
    layout.addWidget(sep)

    for section in theme.sections:
        section_type = section.get("type", "texte")
        renderer = _SECTION_RENDERERS.get(section_type, _creer_section_texte)
        widget = renderer(section)
        layout.addWidget(widget)

    layout.addStretch()

    # Forcer le calcul de la taille
    content.adjustSize()
    return content


# ═════════════════════════════════════════════════════════════════════
# Vue zoomable pour une fiche
# ═════════════════════════════════════════════════════════════════════

class _FicheView(QGraphicsView):
    """QGraphicsView qui affiche un widget de fiche avec zoom par scale().

    Le zoom est appliqué par transformation, pas par reconstruction.
    Ctrl+molette = zoom. Molette seule = scroll vertical.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._proxy: QGraphicsProxyWidget | None = None
        self._zoom = ZOOM_DEFAULT

        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("background: transparent; border: none;")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        from PySide6.QtGui import QPainter
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.TextAntialiasing, True)

    def set_widget(self, widget: QWidget) -> None:
        """Affiche un widget dans la scène.

        Détruit le contenu précédent (scene.clear) et affiche le nouveau.
        Pas de cache de widgets — la construction JIT d'une seule fiche est rapide.
        """
        self._scene.clear()
        self._proxy = self._scene.addWidget(widget)
        self._proxy.setTransformOriginPoint(0, 0)
        self._appliquer_zoom()

    def clear(self) -> None:
        self._scene.clear()
        self._proxy = None

    @property
    def zoom(self) -> float:
        return self._zoom

    @zoom.setter
    def zoom(self, value: float) -> None:
        self._zoom = max(ZOOM_MIN, min(ZOOM_MAX, value))
        self._appliquer_zoom()

    def _appliquer_zoom(self) -> None:
        self.resetTransform()
        self.scale(self._zoom, self._zoom)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom = self._zoom + ZOOM_STEP
            elif delta < 0:
                self.zoom = self._zoom - ZOOM_STEP
            # Remonter l'info au panneau parent pour le label
            parent = self.parent()
            while parent and not isinstance(parent, PanneauReferences):
                parent = parent.parent()
            if parent:
                parent._on_zoom_changed(self._zoom)
            event.accept()
        else:
            super().wheelEvent(event)


# ═════════════════════════════════════════════════════════════════════
# Panneau principal
# ═════════════════════════════════════════════════════════════════════

class PanneauReferences(QWidget):
    """Panneau de références grammaticales — chargement JIT + zoom natif.

    - Les thèmes sont scannés au chargement (métadonnées seulement)
    - La fiche n'est construite que quand on la sélectionne
    - Cache LRU garde les N dernières fiches en mémoire
    - Zoom par QGraphicsView.scale() (pas de reconstruction)
    """

    def __init__(self, repertoire: Path | None = None, parent=None):
        super().__init__(parent)
        self._repertoire = repertoire or REFERENCES_DIR
        self._themes: list[ThemeReference] = []
        self._boutons: list[QPushButton] = []
        self._index_courant: int = -1

        self.setMinimumWidth(300)
        self.setStyleSheet(f"background: {COULEUR_PANNEAU.name()};")

        self._build_ui()
        self.recharger()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ─── Barre de thèmes + indicateur zoom ──────────────────
        barre_container = QWidget()
        barre_container.setStyleSheet(
            f"background: {COULEUR_PANNEAU.name()}; "
            f"border-bottom: 1px solid {COULEUR_BORDURE.name()};"
        )
        barre_outer = QHBoxLayout(barre_container)
        barre_outer.setContentsMargins(0, 0, 8, 0)
        barre_outer.setSpacing(4)

        self._barre_scroll = QScrollArea()
        self._barre_scroll.setWidgetResizable(True)
        self._barre_scroll.setFixedHeight(44)
        self._barre_scroll.setFrameShape(QFrame.NoFrame)
        self._barre_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._barre_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._barre_scroll.setStyleSheet("background: transparent; border: none;")

        self._barre_widget = QWidget()
        self._barre_layout = QHBoxLayout(self._barre_widget)
        self._barre_layout.setContentsMargins(8, 4, 8, 4)
        self._barre_layout.setSpacing(4)
        self._barre_layout.addStretch()

        self._barre_scroll.setWidget(self._barre_widget)
        barre_outer.addWidget(self._barre_scroll, stretch=1)

        # Label zoom
        self._lbl_zoom = QLabel("100%")
        self._lbl_zoom.setFont(police_mono(9))
        self._lbl_zoom.setStyleSheet(
            f"color: {COULEUR_TEXTE_MUET.name()}; padding: 0 4px;"
        )
        self._lbl_zoom.setFixedWidth(42)
        self._lbl_zoom.setAlignment(Qt.AlignCenter)
        barre_outer.addWidget(self._lbl_zoom)

        layout.addWidget(barre_container)

        # ─── Vue zoomable ────────────────────────────────────────
        self._fiche_view = _FicheView(self)
        layout.addWidget(self._fiche_view, stretch=1)

    def recharger(self) -> None:
        """Recharge les thèmes depuis le répertoire."""
        # Nettoyer
        for btn in self._boutons:
            self._barre_layout.removeWidget(btn)
            btn.deleteLater()
        self._boutons.clear()
        self._fiche_view.clear()
        self._index_courant = -1

        # Charger les métadonnées (pas les widgets)
        self._themes = charger_themes(self._repertoire)

        if not self._themes:
            return

        # Construire l'index hook → index thème
        self._hook_index: dict[str, int] = {}
        for i, theme in enumerate(self._themes):
            for hook in theme.hooks:
                hook_lower = hook.lower().strip()
                if hook_lower not in self._hook_index:
                    self._hook_index[hook_lower] = i
        if self._hook_index:
            print(f"[Références] Hooks enregistrés: "
                  f"{list(self._hook_index.keys())}")

        # Créer les boutons seulement
        accent = COULEUR_ACCENT.name()
        for i, theme in enumerate(self._themes):
            btn = QPushButton(f"{theme.icone} {theme.titre}")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: 1px solid {COULEUR_BORDURE.name()};
                    border-radius: 4px;
                    padding: 4px 10px;
                    font-size: {_sz('bouton')}px;
                    color: {COULEUR_TEXTE_SECONDAIRE.name()};
                }}
                QPushButton:hover {{
                    background: #fff3e0;
                    border-color: {accent};
                    color: {accent};
                }}
                QPushButton:checked {{
                    background: {accent};
                    color: white;
                    border-color: {accent};
                }}
            """)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, idx=i: self._selectionner(idx))
            self._barre_layout.insertWidget(
                self._barre_layout.count() - 1, btn
            )
            self._boutons.append(btn)

        # Sélectionner le premier (construit JIT)
        self._selectionner(0)

    def _selectionner(self, index: int) -> None:
        """Affiche la fiche du thème sélectionné — construction JIT."""
        if not self._themes:
            return
        index = max(0, min(index, len(self._themes) - 1))

        if index == self._index_courant:
            return

        self._index_courant = index
        for i, btn in enumerate(self._boutons):
            btn.setChecked(i == index)

        theme = self._themes[index]
        print(f"[Références] Affichage: {theme.icone} {theme.titre}")
        widget = _construire_fiche_widget(theme)
        self._fiche_view.set_widget(widget)

    def _on_zoom_changed(self, zoom: float) -> None:
        """Callback depuis _FicheView quand le zoom change."""
        self._lbl_zoom.setText(f"{int(zoom * 100)}%")

    def afficher_par_hook(self, hook: str) -> bool:
        """Affiche le thème rattaché à ce hook. Retourne True si trouvé."""
        idx = self._hook_index.get(hook.lower().strip())
        if idx is not None:
            self._selectionner(idx)
            return True
        return False

    def hooks_disponibles(self) -> set[str]:
        """Retourne l'ensemble des hooks enregistrés (lowercase)."""
        return set(self._hook_index.keys())