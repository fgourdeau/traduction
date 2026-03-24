"""Fenêtre principale — orchestre capture → analyse Vision → affichage.

Layout 4 colonnes : Capture | Texte analysé + légende | Panneau détail | WordReference
"""

from PySide6.QtCore import Qt, Slot, QUrl
from PySide6.QtGui import QKeySequence, QShortcut, QAction, QColor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QStatusBar, QLabel, QProgressBar, QFrame,
    QMenuBar, QFileDialog, QDockWidget, QLineEdit, QPushButton,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False

import cv2
import numpy as np

from core.event_bus import bus
from core.modeles import PhraseAnalysee
from core.sanitizer import sanitiser
from core.config import (
    COULEUR_FOND, COULEUR_PANNEAU, COULEUR_BORDURE, COULEUR_ACCENT,
    COULEURS_CATEGORIES, LABELS_CATEGORIES, police_texte, police_mono,
)
from ui.capture_widget import CaptureWidget
from ui.scene_texte import VueTexte
from ui.panneau_detail import PanneauDetail
from ui.panneau_references import PanneauReferences
from workers.analyse_worker import OcrWorker, AnalyseWorker

# Résolution minimale pour un bon OCR Vision
MIN_OCR_LONG_SIDE = 1500


class FenetrePrincipale(QMainWindow):
    """Fenêtre principale de l'application."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Analizador — Analyse grammaticale espagnole")
        self.setMinimumSize(1200, 700)
        self.resize(1400, 850)
        self.setDockNestingEnabled(True)
        self.setStyleSheet(f"""
            QMainWindow {{
                background: {COULEUR_FOND.name()};
            }}
            QSplitter::handle {{
                background: {COULEUR_BORDURE.name()};
                width: 1px;
            }}
        """)

        # Workers — pipeline 2 phases
        self._ocr_worker = OcrWorker(self)
        self._analyse_worker = AnalyseWorker(self)

        # État session/page courante (pour navigation)
        self._current_session_id: int | None = None
        self._current_page_id: int | None = None

        self._build_ui()
        self._build_menu()
        self._build_statusbar()
        self._build_legende()
        self._connect_signals()
        self._setup_shortcuts()

    def _build_ui(self) -> None:
        # ─── Colonne centre : Texte analysé (widget central) ─────
        centre = QWidget()
        centre_layout = QVBoxLayout(centre)
        centre_layout.setContentsMargins(0, 0, 0, 0)
        centre_layout.setSpacing(0)

        # Légende des couleurs
        self._legende_widget = QWidget()
        self._legende_layout = QHBoxLayout(self._legende_widget)
        self._legende_layout.setContentsMargins(12, 6, 12, 6)
        self._legende_widget.setStyleSheet(f"background: {COULEUR_PANNEAU.name()};")
        centre_layout.addWidget(self._legende_widget)

        self._vue_texte = VueTexte()
        centre_layout.addWidget(self._vue_texte, stretch=1)

        # ─── Bandeau session / navigation en bas du texte ────────
        self._session_bar = QWidget()
        self._session_bar.setStyleSheet(
            f"background: {COULEUR_PANNEAU.name()}; "
            f"border-top: 1px solid {COULEUR_BORDURE.name()};"
        )
        self._session_bar.setFixedHeight(36)
        sb_layout = QHBoxLayout(self._session_bar)
        sb_layout.setContentsMargins(12, 4, 12, 4)
        sb_layout.setSpacing(8)

        btn_style_small = f"""
            QPushButton {{
                background: {COULEUR_PANNEAU.name()};
                border: 1px solid {COULEUR_BORDURE.name()};
                border-radius: 4px;
                padding: 2px 10px;
                font-size: 11px;
                color: #5c5349;
            }}
            QPushButton:hover {{
                background: #fff3e0;
                border-color: {COULEUR_ACCENT.name()};
                color: {COULEUR_ACCENT.name()};
            }}
            QPushButton:disabled {{
                color: #c4b5a2;
            }}
        """

        # Bouton Ouvrir
        self._btn_ouvrir = QPushButton("📂 Ouvrir")
        self._btn_ouvrir.setToolTip("Ouvrir une page sauvegardée")
        self._btn_ouvrir.setFixedHeight(26)
        self._btn_ouvrir.setStyleSheet(btn_style_small)
        self._btn_ouvrir.clicked.connect(lambda: bus().ouverture_demandee.emit())
        sb_layout.addWidget(self._btn_ouvrir)

        # Bouton page précédente
        self._btn_page_prec = QPushButton("◀")
        self._btn_page_prec.setToolTip("Page précédente")
        self._btn_page_prec.setFixedSize(28, 26)
        self._btn_page_prec.setStyleSheet(btn_style_small)
        self._btn_page_prec.setEnabled(False)
        self._btn_page_prec.clicked.connect(
            lambda: bus().page_precedente_demandee.emit())
        sb_layout.addWidget(self._btn_page_prec)

        # Label session + page
        self._lbl_session_page = QLabel("")
        self._lbl_session_page.setStyleSheet(
            f"color: {COULEUR_ACCENT.name()}; font-size: 12px; "
            f"font-weight: bold;"
        )
        self._lbl_session_page.setAlignment(Qt.AlignCenter)
        sb_layout.addWidget(self._lbl_session_page)

        # Bouton page suivante
        self._btn_page_suiv = QPushButton("▶")
        self._btn_page_suiv.setToolTip("Page suivante")
        self._btn_page_suiv.setFixedSize(28, 26)
        self._btn_page_suiv.setStyleSheet(btn_style_small)
        self._btn_page_suiv.setEnabled(False)
        self._btn_page_suiv.clicked.connect(
            lambda: bus().page_suivante_demandee.emit())
        sb_layout.addWidget(self._btn_page_suiv)

        # Séparateur
        sep_sb = QLabel("│")
        sep_sb.setStyleSheet("color: #c0b8ad;")
        sb_layout.addWidget(sep_sb)

        # Champ nom de session
        self._session_name = QLineEdit()
        self._session_name.setPlaceholderText("Session…")
        self._session_name.setText("Lecture")
        self._session_name.setMaximumWidth(200)
        self._session_name.setFixedHeight(24)
        self._session_name.setStyleSheet(f"""
            QLineEdit {{
                border: 1px solid {COULEUR_BORDURE.name()};
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 11px;
                background: white;
            }}
            QLineEdit:focus {{
                border-color: {COULEUR_ACCENT.name()};
            }}
        """)
        sb_layout.addWidget(self._session_name)

        # Bouton Sauvegarder
        self._btn_sauvegarder = QPushButton("💾 Sauvegarder")
        self._btn_sauvegarder.setToolTip("Sauvegarder la page dans la session")
        self._btn_sauvegarder.setFixedHeight(26)
        self._btn_sauvegarder.setStyleSheet(btn_style_small)
        self._btn_sauvegarder.clicked.connect(
            lambda: bus().sauvegarde_demandee.emit())
        sb_layout.addWidget(self._btn_sauvegarder)

        centre_layout.addWidget(self._session_bar)

        self.setCentralWidget(centre)

        # ─── Dock droit : Panneau détail ─────────────────────────
        self._panneau = PanneauDetail()

        self._dock_detail = QDockWidget("Détail", self)
        self._dock_detail.setWidget(self._panneau)
        self._dock_detail.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )
        self.addDockWidget(Qt.RightDockWidgetArea, self._dock_detail)

        # ─── Dock droit : WordReference (côte à côte avec Détail) ─
        self._webview: QWebEngineView | None = None
        if HAS_WEBENGINE:
            self._webview = QWebEngineView()
            self._webview.setMinimumWidth(350)
            self._webview.setHtml(
                '<html><body style="font-family:sans-serif; color:#9b9084; '
                'display:flex; align-items:center; justify-content:center; '
                'height:100vh; margin:0;">'
                '<p style="text-align:center; font-size:14px;">'
                'Cliquez sur un mot pour charger<br>'
                '<b style="color:#c0582a;">WordReference</b><br>'
                'automatiquement.</p>'
                '</body></html>'
            )

            # Wrapper : barre de recherche + webview
            wordref_wrapper = QWidget()
            wordref_layout = QVBoxLayout(wordref_wrapper)
            wordref_layout.setContentsMargins(0, 0, 0, 0)
            wordref_layout.setSpacing(0)

            # Barre de recherche (Ctrl+F) — cachée par défaut
            self._wordref_search_bar = QWidget()
            self._wordref_search_bar.setFixedHeight(34)
            self._wordref_search_bar.setStyleSheet(
                f"background: {COULEUR_PANNEAU.name()}; "
                f"border-bottom: 1px solid {COULEUR_BORDURE.name()};"
            )
            search_layout = QHBoxLayout(self._wordref_search_bar)
            search_layout.setContentsMargins(6, 3, 6, 3)
            search_layout.setSpacing(4)

            search_icon = QLabel("🔍")
            search_icon.setFixedWidth(20)
            search_layout.addWidget(search_icon)

            self._wordref_search_input = QLineEdit()
            self._wordref_search_input.setPlaceholderText("Rechercher dans la page…")
            self._wordref_search_input.setFixedHeight(26)
            self._wordref_search_input.setStyleSheet(f"""
                QLineEdit {{
                    border: 1px solid {COULEUR_BORDURE.name()};
                    border-radius: 4px;
                    padding: 2px 8px;
                    font-size: 12px;
                    background: white;
                }}
                QLineEdit:focus {{
                    border-color: {COULEUR_ACCENT.name()};
                }}
            """)
            self._wordref_search_input.returnPressed.connect(
                self._wordref_find_next)
            self._wordref_search_input.textChanged.connect(
                self._wordref_find_live)
            search_layout.addWidget(self._wordref_search_input, stretch=1)

            btn_prev = QPushButton("▲")
            btn_prev.setFixedSize(26, 26)
            btn_prev.setToolTip("Précédent")
            btn_prev.clicked.connect(self._wordref_find_prev)
            search_layout.addWidget(btn_prev)

            btn_next = QPushButton("▼")
            btn_next.setFixedSize(26, 26)
            btn_next.setToolTip("Suivant")
            btn_next.clicked.connect(self._wordref_find_next)
            search_layout.addWidget(btn_next)

            btn_close_search = QPushButton("✕")
            btn_close_search.setFixedSize(26, 26)
            btn_close_search.setToolTip("Fermer (Échap)")
            btn_close_search.clicked.connect(self._wordref_close_search)
            search_layout.addWidget(btn_close_search)

            self._wordref_search_bar.hide()
            wordref_layout.addWidget(self._wordref_search_bar)
            wordref_layout.addWidget(self._webview, stretch=1)

            self._dock_wordref = QDockWidget("WordReference", self)
            self._dock_wordref.setWidget(wordref_wrapper)
            self._dock_wordref.setFeatures(
                QDockWidget.DockWidgetMovable
                | QDockWidget.DockWidgetFloatable
                | QDockWidget.DockWidgetClosable
            )
            self.addDockWidget(Qt.RightDockWidgetArea, self._dock_wordref)

            # Côte à côte : split horizontal (Détail | WordRef)
            self.splitDockWidget(
                self._dock_detail, self._dock_wordref, Qt.Horizontal
            )

        # ─── Dock droit-bas : Capture (sous Détail) ──────────────
        self._capture = CaptureWidget()
        self._capture.setMinimumWidth(220)

        self._dock_capture = QDockWidget("Capture", self)
        self._dock_capture.setWidget(self._capture)
        self._dock_capture.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )
        self.addDockWidget(Qt.RightDockWidgetArea, self._dock_capture)

        # Empiler Capture sous Détail (split vertical)
        self.splitDockWidget(
            self._dock_detail, self._dock_capture, Qt.Vertical
        )
        # Proportions appliquées au premier affichage (voir showEvent)
        self._initial_resize_done = False

        # ─── Dock bas : Références grammaticales ─────────────────
        self._panneau_refs = PanneauReferences()

        self._dock_refs = QDockWidget("Références", self)
        self._dock_refs.setWidget(self._panneau_refs)
        self._dock_refs.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )
        self.addDockWidget(Qt.BottomDockWidgetArea, self._dock_refs)
        self._dock_refs.hide()  # Caché par défaut, accessible via menu Vue

        # ─── Style des docks ─────────────────────────────────────
        self.setStyleSheet(self.styleSheet() + f"""
            QDockWidget {{
                font-size: 12px;
                font-weight: bold;
                color: {COULEUR_ACCENT.name()};
            }}
            QDockWidget::title {{
                background: {COULEUR_PANNEAU.name()};
                border-bottom: 1px solid {COULEUR_BORDURE.name()};
                padding: 4px 8px;
                text-align: left;
            }}
        """)

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()
        menu_bar.setStyleSheet(f"""
            QMenuBar {{
                background: {COULEUR_PANNEAU.name()};
                border-bottom: 1px solid {COULEUR_BORDURE.name()};
                padding: 2px 8px;
                font-size: 13px;
            }}
            QMenuBar::item:selected {{
                background: {COULEUR_ACCENT.name()};
                color: white;
                border-radius: 4px;
            }}
        """)

        menu_capture = menu_bar.addMenu("&Session")



        act_ouvrir_session = QAction("📖 Ouvrir…", self)
        act_ouvrir_session.triggered.connect(
            lambda: bus().ouverture_demandee.emit())
        menu_capture.addAction(act_ouvrir_session)

        menu_capture.addSeparator()

        act_fichier = QAction("📁 Ouvrir image…\tCtrl+O", self)
        act_fichier.triggered.connect(self._ouvrir_fichier)
        menu_capture.addAction(act_fichier)

        act_webcam = QAction("📷 Webcam\tF5", self)
        act_webcam.triggered.connect(lambda: bus().capture_webcam_demandee.emit())
        menu_capture.addAction(act_webcam)

        act_ecran = QAction("🖥 Capture écran\tF6", self)
        act_ecran.triggered.connect(lambda: bus().capture_ecran_demandee.emit())
        menu_capture.addAction(act_ecran)

        act_coller = QAction("📋 Coller\tF7", self)
        act_coller.triggered.connect(
            lambda: self._capture._coller_presse_papier())
        menu_capture.addAction(act_coller)

        menu_capture.addSeparator()

        act_sauvegarder = QAction("💾 Sauvegarder page\tCtrl+S", self)
        act_sauvegarder.triggered.connect(
            lambda: bus().sauvegarde_demandee.emit())
        menu_capture.addAction(act_sauvegarder)

        menu_config = menu_bar.addMenu("&Configuration")
        act_api = QAction("🔑 Clé API Anthropic…", self)
        act_api.triggered.connect(self._configurer_cle_api)
        menu_config.addAction(act_api)

        menu_config.addSeparator()

        # Choix du modèle
        import workers.analyse_worker as aw
        self._model_actions = {}
        for model_id, label in [
            ("claude-sonnet-4-20250514", "Sonnet 4 (rapide)"),
            ("claude-opus-4-20250514", "Opus 4 (précis)"),
        ]:
            act = QAction(f"{'✓ ' if aw.MODEL == model_id else '  '}{label}", self)
            act.setData(model_id)
            act.triggered.connect(lambda checked, m=model_id, a=act: self._changer_modele(m))
            menu_config.addAction(act)
            self._model_actions[model_id] = act

        # ─── Menu Vue (panneaux) ─────────────────────────────────
        menu_vue = menu_bar.addMenu("&Vue")
        menu_vue.addAction(self._dock_capture.toggleViewAction())
        menu_vue.addAction(self._dock_detail.toggleViewAction())
        if HAS_WEBENGINE:
            menu_vue.addAction(self._dock_wordref.toggleViewAction())
        menu_vue.addSeparator()
        menu_vue.addAction(self._dock_refs.toggleViewAction())

    def _build_statusbar(self) -> None:
        self._status = QStatusBar()
        self._status.setStyleSheet(f"""
            QStatusBar {{
                background: {COULEUR_PANNEAU.name()};
                border-top: 1px solid {COULEUR_BORDURE.name()};
                padding: 4px 12px;
                font-size: 12px;
                color: #5c5349;
            }}
        """)
        self.setStatusBar(self._status)

        self._progress = QProgressBar()
        self._progress.setMaximumWidth(160)
        self._progress.setMaximumHeight(14)
        self._progress.setRange(0, 0)
        self._progress.hide()
        self._progress.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {COULEUR_BORDURE.name()};
                border-radius: 7px;
                background: {COULEUR_FOND.name()};
            }}
            QProgressBar::chunk {{
                background: {COULEUR_ACCENT.name()};
                border-radius: 6px;
            }}
        """)
        self._status.addPermanentWidget(self._progress)

        # Bouton Annuler (visible uniquement pendant l'analyse)
        self._btn_annuler = QPushButton("✕ Annuler")
        self._btn_annuler.setFixedHeight(20)
        self._btn_annuler.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid #e74c3c;
                border-radius: 4px;
                padding: 1px 10px;
                font-size: 11px;
                color: #e74c3c;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: #e74c3c;
                color: white;
            }}
        """)
        self._btn_annuler.clicked.connect(self._annuler_analyse)
        self._btn_annuler.hide()
        self._status.addPermanentWidget(self._btn_annuler)

        hint = QLabel(
            "Tab: phrases  •  Clic: définition  •  Clic droit: traduction  "
            "•  Légende: références"
        )
        hint.setStyleSheet("color: #9b9084; font-size: 11px;")
        self._status.addPermanentWidget(hint)

    def _build_legende(self) -> None:
        # Catégories grammaticales (couleur du texte)
        categories_affichees = [
            "sustantivo", "verbo", "adjetivo", "adverbio",
            "pronombre", "preposición", "artículo", "conjunción",
        ]
        for cat in categories_affichees:
            couleur = COULEURS_CATEGORIES.get(cat, "#666")
            label_fr = LABELS_CATEGORIES.get(cat, cat)
            lbl = QLabel(f"● {label_fr}")
            lbl.setFont(police_texte(10))
            lbl.setStyleSheet(
                f"color: {couleur}; font-weight: 500; padding: 0 2px;"
            )
            lbl.setCursor(Qt.PointingHandCursor)
            # Clic → ouvrir la fiche de référence correspondante
            lbl.mousePressEvent = lambda ev, key=cat: (
                bus().reference_demandee.emit(key)
            )
            self._legende_layout.addWidget(lbl)

        # Séparateur visuel
        sep = QLabel("  │  ")
        sep.setStyleSheet("color: #c0b8ad;")
        self._legende_layout.addWidget(sep)

        # Groupes syntaxiques (couleur de fond)
        from core.config import COULEURS_GROUPES, LABELS_GROUPES
        for grp, hex_color in COULEURS_GROUPES.items():
            label_fr = LABELS_GROUPES.get(grp, grp)
            lbl = QLabel(f" {label_fr} ")
            lbl.setFont(police_texte(9))
            c = QColor(hex_color)
            bg_rgba = f"rgba({c.red()}, {c.green()}, {c.blue()}, 0.15)"
            lbl.setStyleSheet(
                f"background: {bg_rgba}; color: {hex_color}; "
                f"border-radius: 3px; padding: 1px 4px; font-weight: 500;"
            )
            lbl.setCursor(Qt.PointingHandCursor)
            lbl.mousePressEvent = lambda ev, key=grp: (
                bus().reference_demandee.emit(key)
            )
            self._legende_layout.addWidget(lbl)

        self._legende_layout.addStretch()

    def _connect_signals(self) -> None:
        b = bus()
        # Capture → OCR
        b.image_capturee.connect(self._on_image)
        # Texte collé → bypass OCR
        b.texte_colle.connect(self._on_texte_colle)
        # OCR termine → afficher texte brut
        b.ocr_termine.connect(self._on_ocr_termine)
        b.ocr_erreur.connect(self._on_erreur)
        # Analyse phrase par phrase
        b.analyse_phrase_terminee.connect(self._on_phrase_analysee)
        b.analyse_erreur.connect(self._on_erreur)
        # UI
        b.status_message.connect(self._status.showMessage)
        b.chargement_en_cours.connect(self._on_chargement)
        # WordReference intégré
        b.wordref_demandee.connect(self._on_wordref)
        # Sessions
        b.sauvegarde_demandee.connect(self._on_sauvegarder)
        b.ouverture_demandee.connect(self._on_ouvrir)
        b.page_precedente_demandee.connect(self._on_page_precedente)
        b.page_suivante_demandee.connect(self._on_page_suivante)
        # Références depuis légende
        b.reference_demandee.connect(self._on_reference_demandee)

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("F5"), self,
                  lambda: bus().capture_webcam_demandee.emit())
        QShortcut(QKeySequence("F6"), self,
                  lambda: bus().capture_ecran_demandee.emit())
        QShortcut(QKeySequence("F7"), self,
                  lambda: self._capture._coller_presse_papier())
        QShortcut(QKeySequence("Ctrl+O"), self, self._ouvrir_fichier)
        QShortcut(QKeySequence("Ctrl+S"), self,
                  lambda: bus().sauvegarde_demandee.emit())
        if HAS_WEBENGINE:
            QShortcut(QKeySequence("Ctrl+F"), self, self._wordref_toggle_search)
            QShortcut(QKeySequence("Escape"), self, self._on_escape)

    # ─── Proportions initiales des docks ────────────────────────────

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._initial_resize_done:
            self._initial_resize_done = True
            # Différer pour que Qt ait fini le layout
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._appliquer_proportions_docks)

    def _appliquer_proportions_docks(self) -> None:
        """Détail 3/4, Capture 1/4 de la hauteur disponible."""
        h = self.height()
        trois_quarts = int(h * 0.75)
        un_quart = h - trois_quarts
        self.resizeDocks(
            [self._dock_detail, self._dock_capture],
            [trois_quarts, un_quart],
            Qt.Vertical,
        )

    # ─── Ouvrir fichier image ────────────────────────────────────────

    @Slot()
    def _ouvrir_fichier(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir une image de texte espagnol", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp);;Tous (*)",
        )
        if not path:
            return
        image = cv2.imread(path)
        if image is None:
            self._on_erreur(f"Impossible de lire : {path}")
            return
        self._capture._preview.set_frame(image)
        self._capture._btn_capturer.setEnabled(True)
        bus().status_message.emit("Image chargée — ajustez le cadre, puis Capturer")

    # ─── Slots pipeline ──────────────────────────────────────────────

    @staticmethod
    def _assurer_resolution(image: np.ndarray) -> np.ndarray:
        """Upscale si nécessaire pour garantir assez de pixels pour l'OCR."""
        h, w = image.shape[:2]
        long_side = max(h, w)
        if long_side >= MIN_OCR_LONG_SIDE:
            return image
        scale = MIN_OCR_LONG_SIDE / long_side
        new_w = int(w * scale)
        new_h = int(h * scale)
        upscaled = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
        return upscaled

    @Slot(np.ndarray)
    def _on_image(self, image: np.ndarray) -> None:
        """Image capturée → validation résolution → Phase 1 OCR."""
        h, w = image.shape[:2]
        print(f"[Pipeline] Image reçue: {w}×{h} px")
        image = self._assurer_resolution(image)
        h2, w2 = image.shape[:2]
        if (h2, w2) != (h, w):
            print(f"[Pipeline] Upscale: {w}×{h} → {w2}×{h2}")
            bus().status_message.emit(
                f"Upscale {w}×{h} → {w2}×{h2} pour OCR"
            )
        print(f"[Pipeline] → Phase 1 : OCR ({w2}×{h2})")
        bus().ocr_lance.emit(image)

    @Slot(str)
    def _on_ocr_termine(self, texte: str) -> None:
        """OCR terminé → afficher le texte brut → lancer analyse batch."""
        print(f"[Pipeline] OCR ok ({len(texte)} chars) → affichage texte brut")
        self._charger_et_analyser(texte)

    @Slot(str)
    def _on_texte_colle(self, texte: str) -> None:
        """Texte collé → bypass OCR → lancer analyse batch."""
        print(f"[Pipeline] Texte collé ({len(texte)} chars) → affichage")
        self._charger_et_analyser(texte)

    def _charger_et_analyser(self, texte: str) -> None:
        """Charge le texte brut dans la scène, puis lance l'analyse
        de toutes les phrases en parallèle."""
        # Reset le worker pour le nouveau texte
        self._analyse_worker.reset()

        # Reset la navigation de session (c'est une nouvelle page, pas encore sauvegardée)
        self._current_session_id = None
        self._current_page_id = None
        self._clear_page_info()

        # Sanitizer : nettoyer le texte avant affichage et analyse
        texte_propre = sanitiser(texte)
        if texte_propre != texte:
            nb_avant = len(texte)
            nb_apres = len(texte_propre)
            print(f"[Sanitizer] {nb_avant} → {nb_apres} chars "
                  f"(-{nb_avant - nb_apres})")

        # Charger dans la vue
        self._vue_texte.scene.charger_texte_brut(texte_propre)
        self._vue_texte.setFocus()

        # Récupérer les phrases découpées et lancer le batch
        phrases = self._vue_texte.scene.phrases_texte()
        if phrases:
            batch = [(i, t) for i, t in enumerate(phrases)]
            print(f"[Pipeline] → Phase 2 : Analyse batch ({len(batch)} phrases)")
            bus().analyse_batch_demandee.emit(batch)

    @Slot(int, object)
    def _on_phrase_analysee(self, index: int, phrase: object) -> None:
        """Une phrase a été analysée → appliquer les couleurs en place."""
        if not isinstance(phrase, PhraseAnalysee):
            return
        print(f"[Pipeline] Phrase {index + 1} analysée: {len(phrase.mots)} mots")
        self._vue_texte.scene.appliquer_analyse(index, phrase)
        self._panneau.set_phrase(index, phrase)

    @Slot(str)
    def _on_erreur(self, message: str) -> None:
        self._status.showMessage(f"⚠ {message}", 10000)
        msg_lower = message.lower()
        if "auth" in msg_lower or "401" in msg_lower or "api key" in msg_lower:
            from core.settings import demander_cle_api
            demander_cle_api(self, message_erreur=message)

    @Slot(bool)
    def _on_chargement(self, en_cours: bool) -> None:
        self._progress.setVisible(en_cours)
        self._btn_annuler.setVisible(en_cours)

    def _set_page_info(self, session_nom: str, page_numero: int,
                       nb_pages: int) -> None:
        """Met à jour la barre de statut avec les infos de session/page."""
        self._session_name.setText(session_nom)
        self._lbl_session_page.setText(f"Page {page_numero}/{nb_pages}")
        self._btn_page_prec.setEnabled(page_numero > 1)
        self._btn_page_suiv.setEnabled(page_numero < nb_pages)

    def _clear_page_info(self) -> None:
        """Réinitialise l'affichage de session (nouvelle analyse)."""
        self._lbl_session_page.setText("")
        self._btn_page_prec.setEnabled(False)
        self._btn_page_suiv.setEnabled(False)

    @Slot(str)
    def _on_wordref(self, url: str) -> None:
        """Charge l'URL WordReference dans le navigateur intégré."""
        if self._webview is not None:
            self._webview.setUrl(QUrl(url))
        else:
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(url))

    @Slot(str)
    def _on_reference_demandee(self, hook: str) -> None:
        """Clic sur la légende → ouvrir le dock Références sur le bon thème."""
        if self._panneau_refs.afficher_par_hook(hook):
            # S'assurer que le dock est visible
            self._dock_refs.show()
            self._dock_refs.raise_()

    # ─── Annulation de l'analyse en cours ──────────────────────────

    def _on_escape(self) -> None:
        """Échap : ferme la recherche WordRef si visible, sinon annule l'analyse."""
        if (HAS_WEBENGINE
                and hasattr(self, '_wordref_search_bar')
                and self._wordref_search_bar.isVisible()):
            self._wordref_close_search()
        elif self._btn_annuler.isVisible():
            self._annuler_analyse()

    @Slot()
    def _annuler_analyse(self) -> None:
        """Annule l'OCR et/ou l'analyse en cours, nettoie la scène."""
        if hasattr(self._ocr_worker, 'reset'):
            self._ocr_worker.reset()
        self._analyse_worker.reset()
        bus().chargement_en_cours.emit(False)
        self._vue_texte.scene.clear()
        self._vue_texte.scene._textes_phrases = []
        self._vue_texte.scene._analyses = {}
        self._status.showMessage("⏹ Analyse annulée", 5000)
        print("[Pipeline] Analyse annulée par l'utilisateur")

    # ─── Recherche dans WordReference (Ctrl+F) ────────────────────────

    def _wordref_toggle_search(self) -> None:
        """Ctrl+F — ouvre/focus la barre de recherche WordReference."""
        if not HAS_WEBENGINE or not self._dock_wordref.isVisible():
            return
        if self._wordref_search_bar.isVisible():
            self._wordref_search_input.setFocus()
            self._wordref_search_input.selectAll()
        else:
            self._wordref_search_bar.show()
            self._wordref_search_input.setFocus()

    def _wordref_close_search(self) -> None:
        """Ferme la barre de recherche et efface le surlignage."""
        if not HAS_WEBENGINE:
            return
        self._wordref_search_bar.hide()
        self._wordref_search_input.clear()
        if self._webview is not None:
            self._webview.findText("")  # efface le surlignage

    def _wordref_find_live(self, text: str) -> None:
        """Recherche incrémentale à chaque frappe."""
        if self._webview is not None:
            self._webview.findText(text)

    def _wordref_find_next(self) -> None:
        """Occurrence suivante."""
        if self._webview is not None:
            text = self._wordref_search_input.text()
            self._webview.findText(text)

    def _wordref_find_prev(self) -> None:
        """Occurrence précédente."""
        if self._webview is not None:
            from PySide6.QtWebEngineWidgets import QWebEnginePage
            text = self._wordref_search_input.text()
            self._webview.findText(text, QWebEnginePage.FindBackward)

    # ─── Configuration ───────────────────────────────────────────────

    @Slot()
    def _configurer_cle_api(self) -> None:
        from core.settings import demander_cle_api
        cle = demander_cle_api(self)
        if cle:
            self._status.showMessage("Clé API mise à jour", 5000)

    def _changer_modele(self, model_id: str) -> None:
        import workers.analyse_worker as aw
        aw.MODEL = model_id
        # Mettre à jour les checkmarks
        for mid, act in self._model_actions.items():
            label = act.text().lstrip("✓ ").strip()
            act.setText(f"{'✓ ' if mid == model_id else '  '}{label}")
        self._status.showMessage(f"Modèle: {model_id}", 5000)
        print(f"[Config] Modèle changé: {model_id}")

    # ─── Sessions / Sauvegarde ───────────────────────────────────────

    @Slot()
    def _on_sauvegarder(self) -> None:
        """Sauvegarde la page courante dans la session active."""
        from core.db import db
        import json

        scene = self._vue_texte.scene
        texte_brut = scene.texte_brut()
        analyses = scene._analyses  # dict[int, PhraseAnalysee]

        if not texte_brut.strip():
            self._status.showMessage("⚠ Rien à sauvegarder", 5000)
            return

        if not analyses:
            self._status.showMessage("⚠ Aucune analyse à sauvegarder", 5000)
            return

        # Construire le JSON d'analyse (format compatible from_api_response)
        phrases_json = []
        for ip in sorted(analyses.keys()):
            phrase = analyses[ip]
            phrases_json.append({
                "texte_original": phrase.texte_original,
                "traduction": phrase.traduction,
                "mots": [
                    {
                        "mot": m.mot, "categorie": m.categorie,
                        "lemme": m.lemme, "genre": m.genre,
                        "nombre": m.nombre, "conjugaison": m.conjugaison,
                        "prononciation": m.prononciation,
                        "definition": m.definition, "groupe": m.groupe,
                    }
                    for m in phrase.mots
                ],
                "expressions": [
                    {"indices": e.indices, "texte": e.texte, "sens": e.sens}
                    for e in phrase.expressions
                ],
            })

        analyse_json = json.dumps({"phrases": phrases_json}, ensure_ascii=False)

        # Session : trouver ou créer
        nom_session = self._session_name.text().strip() or "Sans titre"
        database = db()
        sessions = database.lister_sessions()
        session = next((s for s in sessions if s.nom == nom_session), None)
        if session is None:
            session = database.creer_session(nom_session)
            print(f"[Session] Nouvelle session: {nom_session}")

        page = database.sauvegarder_page(session.id, texte_brut, analyse_json)
        self._status.showMessage(
            f"💾 Page {page.numero} sauvegardée dans « {nom_session} »", 5000
        )

    @Slot()
    def _on_ouvrir(self) -> None:
        """Ouvre le dialogue de sélection de session/page."""
        from ui.dialogue_sessions import DialogueSessions

        dlg = DialogueSessions(self)
        dlg.page_choisie.connect(self._charger_page)
        dlg.exec()

    @Slot(object)
    def _charger_page(self, page) -> None:
        """Charge une page sauvegardée sans appel à Claude."""
        from core.db import PageRecord, db as get_db
        from core.modeles import from_api_response
        import json

        if not isinstance(page, PageRecord):
            return

        print(f"[Session] Chargement page {page.numero}")

        database = get_db()
        session = database.session_par_id(page.session_id)
        pages = database.lister_pages(page.session_id)
        nb_pages = len(pages)

        # Tracker l'état courant
        self._current_session_id = page.session_id
        self._current_page_id = page.id

        # Mettre à jour la navigation dans le widget capture
        self._set_page_info(session.nom, page.numero, nb_pages)

        # Reset
        self._analyse_worker.reset()

        # Charger le texte brut SANS sélection auto
        self._vue_texte.scene.charger_texte_brut(page.texte_brut, auto_select=False)
        self._vue_texte.setFocus()

        # Charger les analyses sauvegardées (pas d'appel Claude !)
        try:
            data = json.loads(page.analyse_json)
            phrases = from_api_response(data)
            for i, phrase in enumerate(phrases):
                self._vue_texte.scene.appliquer_analyse(i, phrase)
                self._panneau.set_phrase(i, phrase)

            bus().phrase_selectionnee.emit(0)

            self._status.showMessage(
                f"📖 {session.nom} — Page {page.numero}/{nb_pages} "
                f"— {len(phrases)} phrases", 5000
            )
            print(f"[Session] {len(phrases)} phrases chargées depuis la base")
        except (json.JSONDecodeError, KeyError) as e:
            self._on_erreur(f"Erreur chargement analyse: {e}")

    @Slot()
    def _on_page_precedente(self) -> None:
        """Charge la page précédente dans la session courante."""
        self._naviguer_page(-1)

    @Slot()
    def _on_page_suivante(self) -> None:
        """Charge la page suivante dans la session courante."""
        self._naviguer_page(+1)

    def _naviguer_page(self, direction: int) -> None:
        """Charge la page précédente (-1) ou suivante (+1)."""
        if self._current_session_id is None or self._current_page_id is None:
            return

        from core.db import db as get_db
        pages = get_db().lister_pages(self._current_session_id)

        # Trouver l'index courant
        current_idx = None
        for i, p in enumerate(pages):
            if p.id == self._current_page_id:
                current_idx = i
                break

        if current_idx is None:
            return

        new_idx = current_idx + direction
        if 0 <= new_idx < len(pages):
            self._charger_page(pages[new_idx])