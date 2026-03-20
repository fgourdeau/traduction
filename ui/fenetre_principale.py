"""Fenêtre principale — orchestre capture → analyse Vision → affichage.

Layout 4 colonnes : Capture | Texte analysé + légende | Panneau détail | WordReference
"""

from PySide6.QtCore import Qt, Slot, QUrl
from PySide6.QtGui import QKeySequence, QShortcut, QAction, QColor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QStatusBar, QLabel, QProgressBar, QFrame,
    QMenuBar, QFileDialog, QDockWidget,
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
from core.config import (
    COULEUR_FOND, COULEUR_PANNEAU, COULEUR_BORDURE, COULEUR_ACCENT,
    COULEURS_CATEGORIES, LABELS_CATEGORIES, police_texte, police_mono,
)
from ui.capture_widget import CaptureWidget
from ui.scene_texte import VueTexte
from ui.panneau_detail import PanneauDetail
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

        self.setCentralWidget(centre)

        # ─── Dock gauche : Capture ───────────────────────────────
        self._capture = CaptureWidget()
        self._capture.setMinimumWidth(220)

        self._dock_capture = QDockWidget("Capture", self)
        self._dock_capture.setWidget(self._capture)
        self._dock_capture.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
        )
        self.addDockWidget(Qt.LeftDockWidgetArea, self._dock_capture)

        # ─── Dock droit : Panneau détail ─────────────────────────
        self._panneau = PanneauDetail()

        self._dock_detail = QDockWidget("Détail", self)
        self._dock_detail.setWidget(self._panneau)
        self._dock_detail.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
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

            self._dock_wordref = QDockWidget("WordReference", self)
            self._dock_wordref.setWidget(self._webview)
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

        menu_capture = menu_bar.addMenu("&Capture")

        act_fichier = QAction("📁 Ouvrir image…\tCtrl+O", self)
        act_fichier.triggered.connect(self._ouvrir_fichier)
        menu_capture.addAction(act_fichier)
        menu_capture.addSeparator()

        act_webcam = QAction("📷 Webcam\tF5", self)
        act_webcam.triggered.connect(lambda: bus().capture_webcam_demandee.emit())
        menu_capture.addAction(act_webcam)

        act_ecran = QAction("🖥 Capture écran\tF6", self)
        act_ecran.triggered.connect(lambda: bus().capture_ecran_demandee.emit())
        menu_capture.addAction(act_ecran)

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

        hint = QLabel(
            "Tab/Shift+Tab: phrases  •  Clic: définition  "
            "•  Clic droit: traduction  •  F5: webcam  •  F6: écran  •  F7: coller"
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
            lbl.setStyleSheet(f"color: {couleur}; font-weight: 500;")
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
            # Convertir hex → rgb pour rgba() dans le stylesheet
            c = QColor(hex_color)
            bg_rgba = f"rgba({c.red()}, {c.green()}, {c.blue()}, 0.15)"
            lbl.setStyleSheet(
                f"background: {bg_rgba}; color: {hex_color}; "
                f"border-radius: 3px; padding: 1px 4px; font-weight: 500;"
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

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("F5"), self,
                  lambda: bus().capture_webcam_demandee.emit())
        QShortcut(QKeySequence("F6"), self,
                  lambda: bus().capture_ecran_demandee.emit())
        QShortcut(QKeySequence("F7"), self,
                  lambda: self._capture._coller_presse_papier())
        QShortcut(QKeySequence("Ctrl+O"), self, self._ouvrir_fichier)

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

        # Charger dans la vue
        self._vue_texte.scene.charger_texte_brut(texte)
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

    @Slot(str)
    def _on_wordref(self, url: str) -> None:
        """Charge l'URL WordReference dans le navigateur intégré."""
        if self._webview is not None:
            self._webview.setUrl(QUrl(url))
        else:
            # Fallback : ouvrir dans le navigateur système
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(url))

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