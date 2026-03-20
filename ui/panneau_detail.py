"""Panneau de détail — affiche définition, conjugaison, expression, traduction."""

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame, QScrollArea, QSizePolicy,
)

from core.event_bus import bus
from core.modeles import PhraseAnalysee, MotAnalyse, Expression
from core.config import (
    couleur_pour_categorie, police_texte, police_titre, police_mono,
    LABELS_CATEGORIES, COULEUR_ACCENT, COULEUR_TEXTE_SECONDAIRE,
    COULEUR_TEXTE_MUET, COULEUR_PANNEAU, COULEUR_BORDURE,
)


class PanneauDetail(QWidget):
    """Panneau latéral droit — détails du mot ou de l'expression sélectionnée."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._phrases: dict[int, PhraseAnalysee] = {}
        self.setMinimumWidth(280)
        self.setMaximumWidth(500)
        self.setStyleSheet(f"""
            QWidget {{
                background: {COULEUR_PANNEAU.name()};
            }}
        """)
        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        content = QWidget()
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(24, 24, 24, 24)
        self._layout.setSpacing(0)

        # ─── Section Mot ─────────────────────────────────────────
        self._section_mot = QWidget()
        mot_layout = QVBoxLayout(self._section_mot)
        mot_layout.setContentsMargins(0, 0, 0, 0)
        mot_layout.setSpacing(6)

        self._lbl_mot = QLabel()
        self._lbl_mot.setFont(police_titre(28))
        self._lbl_mot.setWordWrap(True)
        mot_layout.addWidget(self._lbl_mot)

        self._lbl_lemme = QLabel()
        self._lbl_lemme.setFont(police_texte(12))
        self._lbl_lemme.setStyleSheet(f"color: {COULEUR_TEXTE_MUET.name()};")
        mot_layout.addWidget(self._lbl_lemme)

        self._lbl_prononciation = QLabel()
        self._lbl_prononciation.setFont(police_mono(13))
        self._lbl_prononciation.setStyleSheet(f"""
            color: {COULEUR_TEXTE_SECONDAIRE.name()};
            background: #f6f1eb;
            padding: 4px 10px;
            border-radius: 4px;
        """)
        mot_layout.addWidget(self._lbl_prononciation)

        self._lbl_categorie = QLabel()
        self._lbl_categorie.setFont(police_texte(11))
        self._lbl_categorie.setAlignment(Qt.AlignLeft)
        mot_layout.addWidget(self._lbl_categorie)

        # Séparateur
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet(f"color: {COULEUR_BORDURE.name()};")
        mot_layout.addWidget(sep1)

        self._lbl_grammaire = QLabel()
        self._lbl_grammaire.setFont(police_texte(12))
        self._lbl_grammaire.setWordWrap(True)
        self._lbl_grammaire.setStyleSheet(
            f"color: {COULEUR_TEXTE_SECONDAIRE.name()}; line-height: 1.6;"
        )
        mot_layout.addWidget(self._lbl_grammaire)

        # Séparateur
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet(f"color: {COULEUR_BORDURE.name()};")
        mot_layout.addWidget(sep2)

        self._lbl_definition = QLabel()
        self._lbl_definition.setFont(police_texte(13))
        self._lbl_definition.setWordWrap(True)
        self._lbl_definition.setStyleSheet("""
            background: #f6f1eb;
            padding: 14px 16px;
            border-radius: 8px;
            line-height: 1.6;
        """)
        mot_layout.addWidget(self._lbl_definition)

        # Lien WordReference — clic intercepté → signal vers navigateur intégré
        self._lbl_wordref = QLabel()
        self._lbl_wordref.setFont(police_texte(11))
        self._lbl_wordref.setOpenExternalLinks(False)
        self._lbl_wordref.linkActivated.connect(self._on_wordref_click)
        self._lbl_wordref.setStyleSheet(
            f"color: {COULEUR_ACCENT.name()}; padding: 4px 0;"
        )
        mot_layout.addWidget(self._lbl_wordref)

        self._section_mot.hide()
        self._layout.addWidget(self._section_mot)

        # ─── Section Expression ──────────────────────────────────
        self._section_expr = QWidget()
        expr_layout = QVBoxLayout(self._section_expr)
        expr_layout.setContentsMargins(0, 20, 0, 0)
        expr_layout.setSpacing(8)

        lbl_titre_expr = QLabel("EXPRESSION")
        lbl_titre_expr.setFont(police_texte(10))
        lbl_titre_expr.setStyleSheet(
            f"color: {COULEUR_TEXTE_MUET.name()}; letter-spacing: 2px;"
        )
        expr_layout.addWidget(lbl_titre_expr)

        self._lbl_expr_texte = QLabel()
        self._lbl_expr_texte.setFont(police_titre(20))
        self._lbl_expr_texte.setStyleSheet(f"color: {COULEUR_ACCENT.name()};")
        self._lbl_expr_texte.setWordWrap(True)
        expr_layout.addWidget(self._lbl_expr_texte)

        self._lbl_expr_sens = QLabel()
        self._lbl_expr_sens.setFont(police_texte(13))
        self._lbl_expr_sens.setWordWrap(True)
        self._lbl_expr_sens.setStyleSheet(f"""
            background: rgba(192, 88, 42, 0.06);
            border-left: 3px solid {COULEUR_ACCENT.name()};
            padding: 12px 14px;
            border-radius: 4px;
        """)
        expr_layout.addWidget(self._lbl_expr_sens)

        self._section_expr.hide()
        self._layout.addWidget(self._section_expr)

        # ─── Section Traduction ──────────────────────────────────
        self._section_trad = QWidget()
        trad_layout = QVBoxLayout(self._section_trad)
        trad_layout.setContentsMargins(0, 20, 0, 0)
        trad_layout.setSpacing(8)

        lbl_titre_trad = QLabel("TRADUCTION")
        lbl_titre_trad.setFont(police_texte(10))
        lbl_titre_trad.setStyleSheet(
            f"color: {COULEUR_TEXTE_MUET.name()}; letter-spacing: 2px;"
        )
        trad_layout.addWidget(lbl_titre_trad)

        self._lbl_traduction = QLabel()
        self._lbl_traduction.setFont(police_texte(14))
        self._lbl_traduction.setWordWrap(True)
        self._lbl_traduction.setStyleSheet(f"""
            color: {COULEUR_TEXTE_SECONDAIRE.name()};
            font-style: italic;
            padding: 10px 14px;
            background: rgba(192, 88, 42, 0.04);
            border-radius: 6px;
        """)
        trad_layout.addWidget(self._lbl_traduction)

        self._section_trad.hide()
        self._layout.addWidget(self._section_trad)

        # ─── Placeholder ─────────────────────────────────────────
        self._placeholder = QLabel(
            "Cliquez sur un mot pour voir\nsa définition et ses détails."
        )
        self._placeholder.setFont(police_texte(12))
        self._placeholder.setStyleSheet(f"color: {COULEUR_TEXTE_MUET.name()};")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._layout.addWidget(self._placeholder)

        self._layout.addStretch()

        scroll.setWidget(content)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def _connect_signals(self) -> None:
        bus().mot_clique.connect(self._afficher_mot)
        bus().expression_cliquee.connect(self._afficher_expression)
        bus().traduction_demandee.connect(self._afficher_traduction)
        bus().phrase_selectionnee.connect(self._on_phrase_selectionnee)

    def set_phrases(self, phrases: list[PhraseAnalysee]) -> None:
        for i, p in enumerate(phrases):
            self._phrases[i] = p

    def set_phrase(self, index: int, phrase: PhraseAnalysee) -> None:
        self._phrases[index] = phrase

    @Slot(int, int)
    def _afficher_mot(self, ip: int, im: int) -> None:
        if ip not in self._phrases:
            return
        phrase = self._phrases[ip]
        if im >= len(phrase.mots):
            return
        mot = phrase.mots[im]

        self._placeholder.hide()
        self._section_mot.show()

        self._lbl_mot.setText(mot.mot)
        couleur = couleur_pour_categorie(mot.categorie)
        self._lbl_mot.setStyleSheet(f"color: {couleur.name()};")

        self._lbl_lemme.setText(f"lemme : {mot.lemme}")
        self._lbl_prononciation.setText(f"/{mot.prononciation}/")

        label_cat = LABELS_CATEGORIES.get(mot.categorie.lower(), mot.categorie)
        self._lbl_categorie.setText(f"  {label_cat.upper()}  ")
        self._lbl_categorie.setStyleSheet(f"""
            color: white;
            background: {couleur.name()};
            padding: 3px 10px;
            border-radius: 10px;
            font-weight: bold;
            letter-spacing: 1px;
        """)

        # Infos grammaticales
        infos = []
        if mot.genre and mot.genre != "n/a":
            infos.append(f"<b>Genre :</b> {mot.genre}")
        if mot.nombre and mot.nombre != "n/a":
            infos.append(f"<b>Nombre :</b> {mot.nombre}")
        if mot.conjugaison:
            infos.append(f"<b>Conjugaison :</b> {mot.conjugaison}")
        if mot.groupe:
            from core.config import LABELS_GROUPES, COULEURS_GROUPES
            grp_label = LABELS_GROUPES.get(mot.groupe.lower(), mot.groupe)
            grp_color = COULEURS_GROUPES.get(mot.groupe.lower(), "#666")
            infos.append(
                f'<b>Fonction :</b> <span style="color:{grp_color}">{grp_label}</span>'
            )
        self._lbl_grammaire.setText("<br>".join(infos) if infos else "")
        self._lbl_grammaire.setVisible(bool(infos))

        self._lbl_definition.setText(mot.definition)

        # Lien WordReference — auto-chargement + lien cliquable
        lemme = mot.lemme or mot.mot
        url = f"https://www.wordreference.com/esfr/{lemme}"
        self._lbl_wordref.setText(
            f'<a href="{url}" style="color:{COULEUR_ACCENT.name()}">'
            f'→ WordReference : {lemme}</a>'
        )
        bus().wordref_demandee.emit(url)

        # Vérifier aussi si ce mot fait partie d'une expression
        expr = phrase.expression_pour_indice(im)
        if expr:
            self._section_expr.show()
            self._lbl_expr_texte.setText(expr.texte)
            self._lbl_expr_sens.setText(expr.sens)
        else:
            self._section_expr.hide()

    @Slot(int, int)
    def _afficher_expression(self, ip: int, im: int) -> None:
        """Clic sur un mot faisant partie d'une expression."""
        if ip not in self._phrases:
            return
        phrase = self._phrases[ip]
        expr = phrase.expression_pour_indice(im)

        # Afficher aussi le mot
        self._afficher_mot(ip, im)

        if expr:
            self._section_expr.show()
            self._lbl_expr_texte.setText(expr.texte)
            self._lbl_expr_sens.setText(expr.sens)

    @Slot(int)
    def _afficher_traduction(self, ip: int) -> None:
        if ip not in self._phrases:
            return
        phrase = self._phrases[ip]
        self._section_trad.show()
        self._lbl_traduction.setText(phrase.traduction)

    @Slot(int)
    def _on_phrase_selectionnee(self, ip: int) -> None:
        """Quand on change de phrase, afficher sa traduction."""
        self._afficher_traduction(ip)

    def _on_wordref_click(self, url: str) -> None:
        """Clic sur le lien WordReference → émettre le signal pour le navigateur intégré."""
        bus().wordref_demandee.emit(url)