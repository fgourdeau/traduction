"""Panneau de références grammaticales — fiches thématiques depuis JSON.

Architecture v4 :
- Barre latérale verticale à gauche avec groupes thématiques colorés
- Couleurs et groupes lus dynamiquement depuis les champs JSON
  (« groupe » et « couleur_groupe »)
- Chargement JIT : seule la fiche sélectionnée est construite en widgets
- Zoom par QGraphicsView.scale() : pas de reconstruction au zoom
"""

import json
from pathlib import Path
from collections import OrderedDict
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor, QWheelEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame, QPushButton, QGraphicsView, QGraphicsScene,
    QGraphicsProxyWidget, QSizePolicy,
)

from core.config import (
    COULEUR_FOND, COULEUR_PANNEAU, COULEUR_BORDURE, COULEUR_ACCENT,
    COULEUR_TEXTE_SECONDAIRE, COULEUR_TEXTE_MUET,
    police_texte, police_titre, police_mono,
)

# Répertoire par défaut des fiches
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
    "groupe_titre": 9,
}

# Zoom
ZOOM_MIN = 0.5
ZOOM_MAX = 3.0
ZOOM_STEP = 0.1
ZOOM_DEFAULT = 1.0

# Largeur barre latérale
SIDEBAR_WIDTH = 180

# Groupe par défaut si absent du JSON
GROUPE_DEFAUT = "Autre"
COULEUR_GROUPE_DEFAUT = "#888888"


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
    hooks: list[str] = field(default_factory=list)
    groupe: str = GROUPE_DEFAUT
    couleur_groupe: str = COULEUR_GROUPE_DEFAUT

    @classmethod
    def charger(cls, chemin: Path) -> "ThemeReference | None":
        try:
            data = json.loads(chemin.read_text(encoding="utf-8"))
            groupe_lu = data.get("groupe", GROUPE_DEFAUT)
            couleur_lue = data.get("couleur_groupe", COULEUR_GROUPE_DEFAUT)
            print(f"[Réf DEBUG] {chemin.name}: "
                  f"groupe={groupe_lu!r}, couleur={couleur_lue!r}, "
                  f"clés racine={[k for k in data.keys() if k not in ('sections',)]}")
            return cls(
                id=data.get("id", chemin.stem),
                titre=data.get("titre", chemin.stem),
                icone=data.get("icone", "📖"),
                ordre=data.get("ordre", 99),
                resume=data.get("resume", ""),
                sections=data.get("sections", []),
                chemin=chemin,
                hooks=data.get("hooks", []),
                groupe=groupe_lu,
                couleur_groupe=couleur_lue,
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
            print(f"[Références] Chargé: {theme.icone} {theme.titre} "
                  f"[{theme.groupe}] ({f.name})")
    themes.sort(key=lambda t: t.ordre)
    return themes


def _sz(base_key: str) -> int:
    """Taille de police de base (le zoom est géré par QGraphicsView.scale)."""
    return _BASE[base_key]


# ═════════════════════════════════════════════════════════════════════
# Rendu des sections (inchangé)
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
    """Construit le widget d'une fiche. Appelé une seule fois par thème."""
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
    content.adjustSize()
    return content


# ═════════════════════════════════════════════════════════════════════
# Vue zoomable pour une fiche
# ═════════════════════════════════════════════════════════════════════

class _FicheView(QGraphicsView):
    """QGraphicsView qui affiche un widget de fiche avec zoom par scale()."""

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
            parent = self.parent()
            while parent and not isinstance(parent, PanneauReferences):
                parent = parent.parent()
            if parent:
                parent._on_zoom_changed(self._zoom)
            event.accept()
        else:
            super().wheelEvent(event)


# ═════════════════════════════════════════════════════════════════════
# Barre latérale verticale groupée
# ═════════════════════════════════════════════════════════════════════

class _BarreLaterale(QScrollArea):
    """Barre latérale avec boutons groupés par thème, couleurs dynamiques."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._boutons: list[QPushButton] = []
        self._callback = None

        self.setWidgetResizable(True)
        self.setFixedWidth(SIDEBAR_WIDTH)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setStyleSheet(
            f"QScrollArea {{ background: {COULEUR_PANNEAU.name()}; border: none; }}"
            f"QScrollBar:vertical {{ width: 6px; }}"
            f"QScrollBar::handle:vertical {{ background: {COULEUR_BORDURE.name()}; "
            f"border-radius: 3px; min-height: 20px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical "
            f"{{ height: 0; }}"
        )

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(6, 8, 6, 8)
        self._layout.setSpacing(2)
        self.setWidget(self._container)

    def set_callback(self, callback) -> None:
        self._callback = callback

    def peupler(self, themes: list[ThemeReference]) -> None:
        """Construit les boutons groupés depuis les thèmes."""
        # Nettoyer
        for btn in self._boutons:
            btn.deleteLater()
        self._boutons.clear()

        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not themes:
            return

        # Grouper par nom de groupe (en préservant l'ordre d'apparition)
        groupes: OrderedDict[str, list[tuple[int, ThemeReference]]] = OrderedDict()
        for i, theme in enumerate(themes):
            nom_groupe = theme.groupe
            if nom_groupe not in groupes:
                groupes[nom_groupe] = []
            groupes[nom_groupe].append((i, theme))

        # Construire les groupes
        for nom_groupe, items in groupes.items():
            couleur = items[0][1].couleur_groupe

            # Titre du groupe
            lbl_groupe = QLabel(nom_groupe.upper())
            lbl_groupe.setStyleSheet(
                f"color: {couleur}; "
                f"font-size: {_sz('groupe_titre')}px; "
                f"font-weight: bold; "
                f"letter-spacing: 1.5px; "
                f"padding: 8px 4px 3px 4px; "
                f"border: none; "
                f"background: transparent;"
            )
            self._layout.addWidget(lbl_groupe)

            # Boutons du groupe
            for idx, theme in items:
                btn = self._creer_bouton(idx, theme, couleur)
                self._layout.addWidget(btn)
                self._boutons.append(btn)

        self._layout.addStretch()

    def _creer_bouton(self, index: int, theme: ThemeReference,
                      couleur: str) -> QPushButton:
        """Crée un bouton de thème avec indicateur de couleur latéral."""
        btn = QPushButton(f"{theme.icone}  {theme.titre}")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setCheckable(True)
        btn.setFixedHeight(30)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        c = QColor(couleur)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-left: 3px solid transparent;
                border-radius: 0;
                padding: 4px 8px;
                font-size: {_sz('bouton')}px;
                color: {COULEUR_TEXTE_SECONDAIRE.name()};
                text-align: left;
            }}
            QPushButton:hover {{
                background: rgba({c.red()}, {c.green()}, {c.blue()}, 25);
                border-left: 3px solid {couleur};
                color: {couleur};
            }}
            QPushButton:checked {{
                background: rgba({c.red()}, {c.green()}, {c.blue()}, 35);
                border-left: 3px solid {couleur};
                color: {couleur};
                font-weight: bold;
            }}
        """)

        btn.clicked.connect(lambda checked, idx=index: self._on_click(idx))
        return btn

    def _on_click(self, index: int) -> None:
        if self._callback:
            self._callback(index)

    def set_selection(self, index: int) -> None:
        """Met à jour l'état checked des boutons."""
        for i, btn in enumerate(self._boutons):
            btn.setChecked(i == index)

    def boutons(self) -> list[QPushButton]:
        return self._boutons


# ═════════════════════════════════════════════════════════════════════
# Panneau principal
# ═════════════════════════════════════════════════════════════════════

class PanneauReferences(QWidget):
    """Panneau de références grammaticales — barre latérale groupée + fiche.

    - Les thèmes sont scannés au chargement (métadonnées seulement)
    - Groupes et couleurs lus depuis les champs JSON (groupe, couleur_groupe)
    - La fiche n'est construite que quand on la sélectionne (JIT)
    - Zoom par QGraphicsView.scale() (pas de reconstruction)
    """

    def __init__(self, repertoire: Path | None = None, parent=None):
        super().__init__(parent)
        self._repertoire = repertoire or REFERENCES_DIR
        self._themes: list[ThemeReference] = []
        self._index_courant: int = -1

        self.setMinimumWidth(300)
        self.setStyleSheet(f"background: {COULEUR_PANNEAU.name()};")

        self._build_ui()
        self.recharger()

    def _build_ui(self) -> None:
        layout_principal = QHBoxLayout(self)
        layout_principal.setContentsMargins(0, 0, 0, 0)
        layout_principal.setSpacing(0)

        # ─── Barre latérale gauche ───────────────────────────────
        self._sidebar = _BarreLaterale(self)
        self._sidebar.set_callback(self._selectionner)
        layout_principal.addWidget(self._sidebar)

        # ─── Séparateur vertical ─────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f"color: {COULEUR_BORDURE.name()};")
        layout_principal.addWidget(sep)

        # ─── Zone droite : fiche + zoom ──────────────────────────
        zone_droite = QWidget()
        layout_droite = QVBoxLayout(zone_droite)
        layout_droite.setContentsMargins(0, 0, 0, 0)
        layout_droite.setSpacing(0)

        # Label zoom en haut à droite
        barre_zoom = QWidget()
        barre_zoom.setFixedHeight(24)
        barre_zoom.setStyleSheet(
            f"background: {COULEUR_PANNEAU.name()}; "
            f"border-bottom: 1px solid {COULEUR_BORDURE.name()};"
        )
        barre_zoom_layout = QHBoxLayout(barre_zoom)
        barre_zoom_layout.setContentsMargins(8, 0, 8, 0)
        barre_zoom_layout.addStretch()

        self._lbl_zoom = QLabel("100%")
        self._lbl_zoom.setFont(police_mono(9))
        self._lbl_zoom.setStyleSheet(
            f"color: {COULEUR_TEXTE_MUET.name()}; padding: 0 4px;"
        )
        self._lbl_zoom.setAlignment(Qt.AlignCenter)
        barre_zoom_layout.addWidget(self._lbl_zoom)
        layout_droite.addWidget(barre_zoom)

        # Vue zoomable
        self._fiche_view = _FicheView(self)
        layout_droite.addWidget(self._fiche_view, stretch=1)

        layout_principal.addWidget(zone_droite, stretch=1)

    def recharger(self) -> None:
        """Recharge les thèmes depuis le répertoire."""
        self._fiche_view.clear()
        self._index_courant = -1

        # Charger les métadonnées
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

        # Peupler la barre latérale
        self._sidebar.peupler(self._themes)

        # Sélectionner le premier
        self._selectionner(0)

    def _selectionner(self, index: int) -> None:
        """Affiche la fiche du thème sélectionné — construction JIT."""
        if not self._themes:
            return
        index = max(0, min(index, len(self._themes) - 1))

        if index == self._index_courant:
            return

        self._index_courant = index
        self._sidebar.set_selection(index)

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