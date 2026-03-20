"""SceneTexte — QGraphicsScene pour le rendu interactif du texte analysé.

Le texte OCR brut est affiché en noir, en respectant le formatage d'origine.
Sélection = numéro de phrase surligné (pas de gras, pas d'encadré).
Les mots analysés utilisent des couleurs douces ; le hover ravive la couleur.
"""

import re
from dataclasses import dataclass

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import (
    QColor, QFont, QPen, QBrush, QPainterPath, QCursor,
)
from PySide6.QtWidgets import (
    QGraphicsScene, QGraphicsView, QGraphicsRectItem,
    QGraphicsSimpleTextItem, QGraphicsPathItem,
    QWidget, QVBoxLayout,
)

from core.event_bus import bus
from core.modeles import PhraseAnalysee
from core.config import (
    couleur_pour_categorie, couleur_douce_pour_categorie,
    couleur_fond_groupe, police_texte, police_mono,
    COULEUR_FOND, COULEUR_ACCENT, COULEUR_EXPRESSION,
)

COULEUR_NOIR = QColor("#1a1613")
COULEUR_NUM_NORMAL = QColor("#9b9084")
COULEUR_NUM_ACTIF = QColor("#ffffff")
FOND_NUM_ACTIF = QColor("#c0582a")


# ═════════════════════════════════════════════════════════════════════
# Items graphiques
# ═════════════════════════════════════════════════════════════════════

class GroupeFondItem(QGraphicsRectItem):
    """Rectangle de fond coloré pour un groupe syntaxique."""

    def __init__(self, rect: QRectF, couleur: QColor):
        super().__init__(rect)
        self.setPen(QPen(Qt.NoPen))
        self.setBrush(QBrush(couleur))
        self.setZValue(-0.5)


class NumPhraseItem(QGraphicsSimpleTextItem):
    """Numéro de phrase — surligné quand la phrase est active."""

    def __init__(self, numero: str, font: QFont):
        super().__init__(numero)
        self.setFont(font)
        self.setBrush(QBrush(COULEUR_NUM_NORMAL))
        self._fond: QGraphicsRectItem | None = None

    def set_actif(self, on: bool, scene: QGraphicsScene) -> None:
        if on:
            self.setBrush(QBrush(COULEUR_NUM_ACTIF))
            if self._fond is None:
                r = self.boundingRect()
                pad = 3
                fond_rect = QRectF(
                    self.pos().x() - pad, self.pos().y() - pad,
                    r.width() + 2 * pad, r.height() + 2 * pad,
                )
                self._fond = QGraphicsRectItem(fond_rect)
                self._fond.setPen(QPen(Qt.NoPen))
                self._fond.setBrush(QBrush(FOND_NUM_ACTIF))
                self._fond.setZValue(self.zValue() - 0.1)
                scene.addItem(self._fond)
        else:
            self.setBrush(QBrush(COULEUR_NUM_NORMAL))
            if self._fond is not None:
                scene.removeItem(self._fond)
                self._fond = None


class MotItem(QGraphicsSimpleTextItem):
    """Item graphique pour un mot — cliquable, coloré par catégorie."""

    def __init__(self, texte: str, index_phrase: int, index_mot: int,
                 font: QFont):
        super().__init__(texte)
        self.index_phrase = index_phrase
        self.index_mot = index_mot
        self.categorie: str = ""
        self.est_expression: bool = False
        self.groupe: str = ""

        self.setFont(font)
        self.setBrush(QBrush(COULEUR_NOIR))
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setAcceptHoverEvents(True)
        self._analysed = False

    def appliquer_analyse(self, categorie: str, groupe: str,
                          est_expression: bool) -> None:
        """Colore le mot (couleur douce) après réception de l'analyse."""
        self.categorie = categorie
        self.groupe = groupe
        self.est_expression = est_expression
        self._analysed = True
        self.setBrush(QBrush(couleur_douce_pour_categorie(categorie)))

    def hoverEnterEvent(self, event):
        if self._analysed:
            # Raviver la couleur pleine au hover
            self.setBrush(QBrush(couleur_pour_categorie(self.categorie)))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        if self._analysed:
            self.setBrush(QBrush(couleur_douce_pour_categorie(self.categorie)))
        else:
            self.setBrush(QBrush(COULEUR_NOIR))
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            bus().phrase_selectionnee.emit(self.index_phrase)
            if self._analysed:
                if self.est_expression:
                    bus().expression_cliquee.emit(
                        self.index_phrase, self.index_mot)
                else:
                    bus().mot_clique.emit(self.index_phrase, self.index_mot)
        elif event.button() == Qt.RightButton:
            bus().traduction_demandee.emit(self.index_phrase)
            event.accept()
            return
        super().mousePressEvent(event)


class SoulignementItem(QGraphicsPathItem):
    """Souligné ondulé sous les expressions idiomatiques."""

    def __init__(self, x: float, y: float, largeur: float):
        super().__init__()
        path = QPainterPath()
        amplitude = 2.0
        pas = 4.0
        path.moveTo(x, y)
        cx = x
        up = True
        while cx < x + largeur:
            dy = -amplitude if up else amplitude
            path.quadTo(cx + pas / 2, y + dy, cx + pas, y)
            cx += pas
            up = not up
        self.setPath(path)
        pen = QPen(COULEUR_EXPRESSION, 1.8)
        pen.setCapStyle(Qt.RoundCap)
        self.setPen(pen)


class BlocPhraseItem(QGraphicsRectItem):
    """Rectangle de fond invisible mais cliquable pour une phrase."""

    def __init__(self, rect: QRectF, index_phrase: int):
        super().__init__(rect)
        self.index_phrase = index_phrase
        self.setPen(QPen(Qt.NoPen))
        self.setBrush(QBrush(Qt.transparent))
        self.setCursor(QCursor(Qt.PointingHandCursor))

    def contextMenuEvent(self, event):
        bus().traduction_demandee.emit(self.index_phrase)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            bus().phrase_selectionnee.emit(self.index_phrase)
        super().mousePressEvent(event)


# ═════════════════════════════════════════════════════════════════════
# Découpage phrases
# ═════════════════════════════════════════════════════════════════════

@dataclass
class _TokenPhrase:
    texte: str
    ip: int
    im: int


def _decouper_phrases(texte: str) -> tuple[list[str], list[list[_TokenPhrase]]]:
    """Découpe en phrases (par ponctuation) tout en gardant la structure ligne OCR."""
    phrase_re = re.compile(r'[^.!?…]+[.!?…]+')

    phrases_textes: list[str] = []

    # Texte plat → découper en phrases
    texte_plat = texte.replace("\n", " ")
    matches = phrase_re.findall(texte_plat)
    reste = phrase_re.sub("", texte_plat).strip()

    for m in matches:
        m = m.strip()
        if m:
            phrases_textes.append(m)
    if reste:
        phrases_textes.append(reste)

    # Séquence plate (ip, im) pour chaque mot
    flat_phrase_mots: list[tuple[int, int]] = []
    for ip, pt in enumerate(phrases_textes):
        for im, _ in enumerate(pt.split()):
            flat_phrase_mots.append((ip, im))

    # Parcourir ligne par ligne pour la mise en page
    lignes = texte.split("\n")
    lignes_tokens: list[list[_TokenPhrase]] = []
    flat_idx = 0

    for ligne in lignes:
        ligne_s = ligne.strip()
        if not ligne_s:
            lignes_tokens.append([])
            continue

        tokens: list[_TokenPhrase] = []
        for mot_str in ligne_s.split():
            if flat_idx < len(flat_phrase_mots):
                ip, im = flat_phrase_mots[flat_idx]
            else:
                ip = len(phrases_textes) - 1
                im = 0
            tokens.append(_TokenPhrase(mot_str, ip, im))
            flat_idx += 1

        lignes_tokens.append(tokens)

    return phrases_textes, lignes_tokens


# ═════════════════════════════════════════════════════════════════════
# Scène principale
# ═════════════════════════════════════════════════════════════════════

class SceneTexte(QGraphicsScene):
    """Scène : texte OCR brut → sélection → analyse à la demande."""

    MARGE_GAUCHE = 50.0
    MARGE_HAUT = 25.0
    ESPACEMENT_MOT = 8.0
    ESPACEMENT_LIGNE = 6.0
    ESPACEMENT_PARA = 18.0
    LARGEUR_MAX = 700.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackgroundBrush(QBrush(COULEUR_FOND))

        self._textes_phrases: list[str] = []
        self._blocs: list[BlocPhraseItem] = []
        self._nums: list[NumPhraseItem] = []
        self._mots_items: list[list[MotItem]] = []
        self._fonds_groupes: list[list[GroupeFondItem]] = []
        self._soulignements: list[list[SoulignementItem]] = []
        self._analyses: dict[int, PhraseAnalysee] = {}
        self._index_selection: int = -1
        self._font = police_texte(17)
        self._font_num = police_mono(10)

        bus().phrase_selectionnee.connect(self._on_phrase_selectionnee)

    # ─── Chargement texte OCR brut ────────────────────────────────

    def charger_texte_brut(self, texte: str) -> None:
        """Affiche le texte OCR en respectant le formatage d'origine."""
        self.clear()
        self._blocs = []
        self._nums = []
        self._mots_items = []
        self._fonds_groupes = []
        self._soulignements = []
        self._analyses = {}
        self._index_selection = -1

        phrases_textes, lignes_tokens = _decouper_phrases(texte)
        self._textes_phrases = phrases_textes
        nb_phrases = len(phrases_textes)

        for _ in range(nb_phrases):
            self._mots_items.append([])
            self._fonds_groupes.append([])
            self._soulignements.append([])

        # ─── Mise en page : suivre les lignes OCR ────────────────
        y = self.MARGE_HAUT
        ligne_hauteur = 0.0
        phrase_bounds: dict[int, list[float]] = {}

        for ligne_toks in lignes_tokens:
            if not ligne_toks:
                y += ligne_hauteur + self.ESPACEMENT_PARA
                ligne_hauteur = 0.0
                continue

            x = self.MARGE_GAUCHE
            ligne_hauteur = 0.0

            for tok in ligne_toks:
                item = MotItem(tok.texte, tok.ip, tok.im, self._font)
                rect = item.boundingRect()

                if (x + rect.width() > self.MARGE_GAUCHE + self.LARGEUR_MAX
                        and x > self.MARGE_GAUCHE):
                    x = self.MARGE_GAUCHE
                    y += ligne_hauteur + self.ESPACEMENT_LIGNE
                    ligne_hauteur = 0.0

                item.setPos(x, y)
                self.addItem(item)
                ligne_hauteur = max(ligne_hauteur, rect.height())
                x += rect.width() + self.ESPACEMENT_MOT

                self._mots_items[tok.ip].append(item)

                if tok.ip not in phrase_bounds:
                    phrase_bounds[tok.ip] = [y, y + ligne_hauteur]
                else:
                    phrase_bounds[tok.ip][0] = min(phrase_bounds[tok.ip][0], y)
                    phrase_bounds[tok.ip][1] = max(
                        phrase_bounds[tok.ip][1], y + ligne_hauteur)

            y += ligne_hauteur + self.ESPACEMENT_LIGNE

        # ─── Blocs de fond par phrase (invisibles, cliquables) ────
        for ip in range(nb_phrases):
            if ip in phrase_bounds:
                y_min, y_max = phrase_bounds[ip]
                bloc_rect = QRectF(
                    self.MARGE_GAUCHE - 10, y_min - 4,
                    self.LARGEUR_MAX + 20, y_max - y_min + 8,
                )
            else:
                bloc_rect = QRectF(0, 0, 0, 0)
            bloc = BlocPhraseItem(bloc_rect, ip)
            bloc.setZValue(-1)
            self.addItem(bloc)
            self._blocs.append(bloc)

        # ─── Numéros de phrase ────────────────────────────────────
        for ip in range(nb_phrases):
            num = NumPhraseItem(f"{ip + 1}", self._font_num)
            if ip in phrase_bounds:
                num.setPos(8, phrase_bounds[ip][0] + 2)
            self.addItem(num)
            self._nums.append(num)

        self.setSceneRect(self.itemsBoundingRect().adjusted(-10, -10, 30, 30))

        if self._blocs:
            self._selectionner(0)

    def phrases_texte(self) -> list[str]:
        """Retourne les textes des phrases découpées (pour lancement batch)."""
        return list(self._textes_phrases)

    # ─── Sélection ────────────────────────────────────────────────

    def _on_phrase_selectionnee(self, index: int) -> None:
        self._selectionner(index)

    def _selectionner(self, index: int) -> None:
        if not self._blocs:
            return
        index = max(0, min(index, len(self._blocs) - 1))
        if index == self._index_selection:
            return

        # Dé-sélectionner l'ancienne
        if 0 <= self._index_selection < len(self._nums):
            self._nums[self._index_selection].set_actif(False, self)

        self._index_selection = index

        # Activer le numéro
        if 0 <= index < len(self._nums):
            self._nums[index].set_actif(True, self)

        # Demander l'analyse si pas encore faite
        if index not in self._analyses and index < len(self._textes_phrases):
            bus().analyse_phrase_demandee.emit(
                index, self._textes_phrases[index])

    def phrase_suivante(self) -> None:
        if self._index_selection < len(self._blocs) - 1:
            bus().phrase_selectionnee.emit(self._index_selection + 1)

    def phrase_precedente(self) -> None:
        if self._index_selection > 0:
            bus().phrase_selectionnee.emit(self._index_selection - 1)

    # ─── Appliquer l'analyse d'une phrase ─────────────────────────

    def appliquer_analyse(self, index: int, phrase: PhraseAnalysee) -> None:
        """Colore les mots de la phrase `index` (couleurs douces)."""
        if index in self._analyses:
            return
        self._analyses[index] = phrase

        items = self._mots_items[index]
        indices_expr = phrase.indices_expressions()

        for im, item in enumerate(items):
            if im < len(phrase.mots):
                mot = phrase.mots[im]
                item.appliquer_analyse(
                    mot.categorie, mot.groupe, im in indices_expr)

        # ─── Fonds de groupes ─────────────────────────────────────
        for fg in self._fonds_groupes[index]:
            self.removeItem(fg)
        self._fonds_groupes[index] = []

        PAD_X, PAD_Y = 3.0, 2.0

        spans: list[tuple[str, int, int]] = []
        if items:
            cur_grp = items[0].groupe
            cur_start = 0
            for i in range(1, len(items)):
                grp = items[i].groupe
                same_line = abs(items[i].pos().y() - items[i-1].pos().y()) < 2
                if grp == cur_grp and same_line:
                    continue
                if cur_grp:
                    spans.append((cur_grp, cur_start, i))
                cur_grp = grp
                cur_start = i
            if cur_grp:
                spans.append((cur_grp, cur_start, len(items)))

        for groupe, deb, fin in spans:
            couleur = couleur_fond_groupe(groupe)
            if couleur is None:
                continue
            first, last = items[deb], items[fin - 1]
            x_min = first.pos().x() - PAD_X
            y_min = first.pos().y() - PAD_Y
            x_max = last.pos().x() + last.boundingRect().width() + PAD_X
            h = first.boundingRect().height()
            y_max = y_min + h + 2 * PAD_Y
            rect = QRectF(x_min, y_min, x_max - x_min, y_max - y_min)
            fond = GroupeFondItem(rect, couleur)
            self.addItem(fond)
            self._fonds_groupes[index].append(fond)

        # ─── Soulignements expressions ────────────────────────────
        for s in self._soulignements[index]:
            self.removeItem(s)
        self._soulignements[index] = []

        for expr in phrase.expressions:
            expr_items = [items[i] for i in expr.indices if i < len(items)]
            if not expr_items:
                continue
            by_line: dict[int, list[MotItem]] = {}
            for ei in expr_items:
                by_line.setdefault(round(ei.pos().y()), []).append(ei)
            for ly, line_items in by_line.items():
                x_min = min(it.pos().x() for it in line_items)
                x_max = max(
                    it.pos().x() + it.boundingRect().width()
                    for it in line_items
                )
                h = line_items[0].boundingRect().height()
                s = SoulignementItem(x_min, ly + h + 2, x_max - x_min)
                self.addItem(s)
                self._soulignements[index].append(s)


# ═════════════════════════════════════════════════════════════════════
# Widget conteneur
# ═════════════════════════════════════════════════════════════════════

class VueTexte(QWidget):
    """QGraphicsView + gestion clavier Tab/Shift+Tab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = SceneTexte()
        self._view = QGraphicsView(self._scene)
        from PySide6.QtGui import QPainter
        self._view.setRenderHint(QPainter.Antialiasing, True)
        self._view.setRenderHint(QPainter.TextAntialiasing, True)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._view.setStyleSheet(
            "QGraphicsView { border: none; background: transparent; }")
        self._view.setFocusPolicy(Qt.StrongFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

        self._view.installEventFilter(self)

    @property
    def scene(self) -> SceneTexte:
        return self._scene

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj == self._view and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Tab:
                self._scene.phrase_suivante()
                self._ensure_visible()
                return True
            elif event.key() == Qt.Key_Backtab:
                self._scene.phrase_precedente()
                self._ensure_visible()
                return True
        return super().eventFilter(obj, event)

    def _ensure_visible(self) -> None:
        idx = self._scene._index_selection
        if 0 <= idx < len(self._scene._blocs):
            self._view.ensureVisible(self._scene._blocs[idx], 20, 40)