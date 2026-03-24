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
    """Découpe en phrases (par ponctuation) tout en gardant la structure ligne OCR.

    Retourne (phrases_textes, lignes_tokens) où chaque token a son ip (index phrase)
    et im (index mot dans la phrase).
    """
    phrase_re = re.compile(r'[^.!?…]+[.!?…]+')

    phrases_textes: list[str] = []

    # Texte plat → reconstituer les mots coupés en fin de ligne (césure)
    # "memo-\nrizado" → "memorizado"
    texte_plat = re.sub(r'(\w)-\s*\n\s*(\w)', r'\1\2', texte)
    texte_plat = texte_plat.replace("\n", " ")
    # Normaliser les espaces multiples
    texte_plat = re.sub(r"\s+", " ", texte_plat).strip()

    matches = phrase_re.findall(texte_plat)
    reste = phrase_re.sub("", texte_plat).strip()

    for m in matches:
        m = m.strip()
        if m:
            phrases_textes.append(m)
    if reste:
        phrases_textes.append(reste)

    # Construire une séquence plate de (ip, im) en matchant par position
    # dans le texte plat, pas par comptage de mots split.
    # On utilise le texte plat pour assigner chaque mot de chaque ligne
    # à la bonne phrase.

    # Position de départ de chaque phrase dans le texte plat
    phrase_starts: list[int] = []
    search_start = 0
    for pt in phrases_textes:
        # Chercher les mots de cette phrase séquentiellement
        pos = texte_plat.find(pt.split()[0], search_start) if pt.split() else search_start
        if pos < 0:
            pos = search_start
        phrase_starts.append(pos)
        search_start = pos + len(pt)

    def _trouver_phrase(pos_dans_plat: int) -> int:
        """Retourne l'index de la phrase qui contient cette position."""
        for i in range(len(phrase_starts) - 1, -1, -1):
            if pos_dans_plat >= phrase_starts[i]:
                return i
        return 0

    # Parcourir ligne par ligne pour la mise en page
    lignes = texte.split("\n")
    lignes_tokens: list[list[_TokenPhrase]] = []
    pos_plat = 0  # position courante dans texte_plat
    mot_compteurs: dict[int, int] = {}  # ip → prochain im

    for ligne in lignes:
        ligne_s = ligne.strip()
        if not ligne_s:
            lignes_tokens.append([])
            continue

        tokens: list[_TokenPhrase] = []
        for mot_str in ligne_s.split():
            # Trouver ce mot dans le texte plat
            idx = texte_plat.find(mot_str, pos_plat)
            if idx < 0:
                # Fallback : chercher après normalisation
                idx = pos_plat

            ip = _trouver_phrase(idx)
            im = mot_compteurs.get(ip, 0)
            mot_compteurs[ip] = im + 1

            tokens.append(_TokenPhrase(mot_str, ip, im))
            pos_plat = idx + len(mot_str)

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
        self._texte_brut: str = ""  # texte original avec formatage
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

    def charger_texte_brut(self, texte: str, auto_select: bool = True) -> None:
        """Affiche le texte OCR en respectant le formatage d'origine.

        Si auto_select=False, ne sélectionne pas la première phrase
        (utile pour le chargement depuis la base, où les analyses sont
        appliquées après le chargement du texte).
        """
        self.clear()
        self._blocs = []
        self._nums = []
        self._mots_items = []
        self._fonds_groupes = []
        self._soulignements = []
        self._analyses = {}
        self._index_selection = -1
        self._texte_brut = texte

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

            y += ligne_hauteur + self.ESPACEMENT_LIGNE

        # ─── Blocs de fond par phrase (basés sur les mots réels) ────
        for ip in range(nb_phrases):
            items = self._mots_items[ip]
            if not items:
                bloc = BlocPhraseItem(QRectF(0, 0, 0, 0), ip)
                bloc.setZValue(-1)
                self.addItem(bloc)
                self._blocs.append(bloc)
                continue

            # Bounds réels des mots de cette phrase
            x_min = min(it.pos().x() for it in items)
            x_max = max(it.pos().x() + it.boundingRect().width() for it in items)
            y_min = min(it.pos().y() for it in items)
            y_max = max(it.pos().y() + it.boundingRect().height() for it in items)

            bloc_rect = QRectF(
                x_min - 6, y_min - 4,
                x_max - x_min + 12, y_max - y_min + 8,
            )
            bloc = BlocPhraseItem(bloc_rect, ip)
            bloc.setZValue(-1)
            self.addItem(bloc)
            self._blocs.append(bloc)

        # ─── Numéros de phrase (au premier mot, décalés si collision) ──
        used_num_positions: list[tuple[float, float]] = []  # (x, y) déjà utilisées
        NUM_OFFSET_Y = 0.0  # décalage vertical si collision

        for ip in range(nb_phrases):
            items = self._mots_items[ip]
            num = NumPhraseItem(f"{ip + 1}", self._font_num)

            if items:
                first = items[0]
                num_y = first.pos().y() + 2

                # Vérifier collision avec un numéro déjà placé sur la même ligne
                for ux, uy in used_num_positions:
                    if abs(uy - num_y) < 12 and ux < 20:
                        # Décaler ce numéro en dessous du dernier mot de la ligne
                        num_y = uy + 12
                        break

                num.setPos(8, num_y)
                used_num_positions.append((8, num_y))
            else:
                num.setPos(8, 0)

            self.addItem(num)
            self._nums.append(num)

        self.setSceneRect(self.itemsBoundingRect().adjusted(-10, -10, 30, 30))

        if self._blocs and auto_select:
            self._selectionner(0)

    def phrases_texte(self) -> list[str]:
        """Retourne les textes des phrases découpées (pour lancement batch)."""
        return list(self._textes_phrases)

    def texte_brut(self) -> str:
        """Retourne le texte brut original avec formatage préservé."""
        return self._texte_brut

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
        """Colore les mots de la phrase `index` (couleurs douces).

        Utilise un matching par contenu textuel pour aligner les mots
        analysés aux tokens visuels, même si la ponctuation crée des
        décalages d'index.
        """
        if index in self._analyses:
            return
        self._analyses[index] = phrase

        items = self._mots_items[index]
        indices_expr = phrase.indices_expressions()

        # Construire le mapping token visuel → mot analysé.
        # Algorithme séquentiel bidirectionnel :
        # 1. Pour chaque token visuel, chercher le mot analysé dans un look-ahead
        # 2. Si pas de match, vérifier si c'est le token qui est un artefact
        #    (ponctuation, chiffre isolé) ou si le mot analysé est en avance
        # L'ordre séquentiel garantit que les mots répétés matchent correctement.

        import unicodedata

        def _normaliser(s: str) -> str:
            """Retire la ponctuation périphérique pour comparaison."""
            s = s.strip()
            while s and not s[0].isalnum():
                s = s[1:]
            while s and not s[-1].isalnum():
                s = s[:-1]
            return s

        def _est_ponctuation(s: str) -> bool:
            """Vérifie si un token est uniquement de la ponctuation/symboles."""
            return bool(s) and all(
                unicodedata.category(c).startswith(('P', 'S', 'Z'))
                or c in '()[]{}¡!¿?«»"""\',;:-–—…·•/\\'
                for c in s
            )

        def _match(token_n: str, mot_n: str) -> bool:
            """Teste si un token normalisé correspond à un mot normalisé."""
            if not token_n or not mot_n:
                return False
            if token_n == mot_n:
                return True
            if token_n.lower() == mot_n.lower():
                return True
            if mot_n in token_n:  # "(REUTERS)" contient "REUTERS"
                return True
            if token_n in mot_n:  # token partiel dans mot fusionné
                return True
            return False

        mot_idx = 0
        item_to_mot: dict[int, int] = {}
        LOOK = 4  # fenêtre de look-ahead dans chaque direction
        nb_mots = len(phrase.mots)

        # Pré-calculer les paires de césure : token finissant par "-"
        # suivi d'un token texte → les deux forment un seul mot
        cesure_pairs: dict[int, int] = {}  # item_idx_debut → item_idx_fin
        for ii in range(len(items) - 1):
            txt = items[ii].text().strip()
            if txt.endswith('-') and len(txt) > 1:
                # Le token suivant non-ponctuation est la suite
                for jj in range(ii + 1, min(ii + 3, len(items))):
                    txt_suite = _normaliser(items[jj].text().strip())
                    if txt_suite and not _est_ponctuation(items[jj].text().strip()):
                        cesure_pairs[ii] = jj
                        break

        skip_items: set[int] = set()  # items déjà traités comme suite de césure

        for item_idx, item in enumerate(items):
            if mot_idx >= nb_mots:
                break
            if item_idx in skip_items:
                continue

            token_text = item.text().strip()
            token_norm = _normaliser(token_text)

            # Token vide ou ponctuation pure → sauter le token
            if not token_norm or _est_ponctuation(token_text):
                continue

            # ─── Césure : token finit par "-" → concaténer avec le suivant ───
            if item_idx in cesure_pairs:
                suite_idx = cesure_pairs[item_idx]
                # Reconstituer le mot : "memo" + "rizado" = "memorizado"
                prefixe = token_norm  # "memo" (trait d'union retiré par _normaliser)
                suffixe = _normaliser(items[suite_idx].text().strip())
                mot_reconstitue = prefixe + suffixe

                matched_cesure = False
                for offset in range(min(LOOK, nb_mots - mot_idx)):
                    mot_norm = _normaliser(phrase.mots[mot_idx + offset].mot)
                    if _match(mot_reconstitue, mot_norm):
                        # Les deux tokens pointent vers le même mot analysé
                        item_to_mot[item_idx] = mot_idx + offset
                        item_to_mot[suite_idx] = mot_idx + offset
                        skip_items.add(suite_idx)
                        mot_idx = mot_idx + offset + 1
                        matched_cesure = True
                        break

                if matched_cesure:
                    continue

            # ─── Matching normal ─────────────────────────────────────────

            # Chercher un match dans les prochains mots analysés
            matched = False
            for offset in range(min(LOOK, nb_mots - mot_idx)):
                mot_norm = _normaliser(phrase.mots[mot_idx + offset].mot)
                if _match(token_norm, mot_norm):
                    item_to_mot[item_idx] = mot_idx + offset
                    mot_idx = mot_idx + offset + 1
                    matched = True
                    break

            if matched:
                continue

            # Pas de match en avant dans les mots.
            # Peut-être que le MOT ANALYSÉ courant correspond à un token
            # visuel plus loin (le token courant est un artefact non analysé).
            # Regarder si les prochains tokens visuels matchent le mot courant.
            # Si oui, on saute ce token (artefact). Si non, on avance mot_idx
            # (le mot analysé n'a pas de token visuel correspondant).
            mot_norm_courant = _normaliser(phrase.mots[mot_idx].mot)
            found_later = False
            for future in range(1, min(LOOK + 1, len(items) - item_idx)):
                future_idx = item_idx + future
                if future_idx >= len(items):
                    break
                future_norm = _normaliser(items[future_idx].text().strip())
                if future_norm and _match(future_norm, mot_norm_courant):
                    found_later = True
                    break

            if not found_later:
                # Le mot analysé courant n'a pas de token visuel correspondant
                # → avancer mot_idx pour ne pas bloquer le reste
                mot_idx += 1

        # Log des tokens non matchés (debug)
        unmatched = [
            (i, items[i].text().strip()) for i in range(len(items))
            if i not in item_to_mot
            and not _est_ponctuation(items[i].text().strip())
            and _normaliser(items[i].text().strip())
        ]
        if unmatched:
            print(f"[Match] Phrase {index}: {len(unmatched)} non matchés: "
                  f"{[t for _, t in unmatched[:8]]}")

        # Appliquer les couleurs via le mapping
        for item_idx, item in enumerate(items):
            if item_idx in item_to_mot:
                im = item_to_mot[item_idx]
                mot = phrase.mots[im]
                item.appliquer_analyse(
                    mot.categorie, mot.groupe, im in indices_expr)
                # Stocker l'index du mot analysé pour les clics
                item.index_mot = im

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

        # Mapping inversé : index mot analysé → index item visuel
        mot_to_item = {v: k for k, v in item_to_mot.items()}

        for expr in phrase.expressions:
            expr_item_indices = [mot_to_item[i] for i in expr.indices
                                if i in mot_to_item]
            expr_items = [items[i] for i in expr_item_indices if i < len(items)]
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