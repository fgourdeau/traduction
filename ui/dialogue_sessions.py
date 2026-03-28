"""Dialogue de sélection de session et page sauvegardée."""

from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QSplitter, QWidget, QMessageBox,
    QFileDialog,
)

from core.db import db, SessionRecord, PageRecord
from core.config import (
    COULEUR_ACCENT, COULEUR_PANNEAU, COULEUR_BORDURE,
    COULEUR_TEXTE_SECONDAIRE, COULEUR_TEXTE_MUET,
    police_texte, police_titre,
)


class DialogueSessions(QDialog):
    """Dialogue pour parcourir les sessions et charger une page."""

    page_choisie = Signal(PageRecord)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gestionnaire de sessions")
        self.setMinimumSize(700, 450)
        self.resize(800, 500)

        self._sessions: list[SessionRecord] = []
        self._pages: list[PageRecord] = []
        self._page_selectionnee: PageRecord | None = None

        self._build_ui()
        self._charger_sessions()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ─── Splitter : sessions | pages ─────────────────────────
        splitter = QSplitter(Qt.Horizontal)

        # Liste des sessions
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        lbl_sessions = QLabel("Sessions")
        lbl_sessions.setFont(police_titre(14))
        lbl_sessions.setStyleSheet(f"color: {COULEUR_ACCENT.name()};")
        left_layout.addWidget(lbl_sessions)

        self._list_sessions = QListWidget()
        self._list_sessions.setStyleSheet(f"""
            QListWidget {{
                border: 1px solid {COULEUR_BORDURE.name()};
                border-radius: 4px;
                background: white;
                font-size: 12px;
            }}
            QListWidget::item {{
                padding: 8px;
                border-bottom: 1px solid {COULEUR_BORDURE.name()};
            }}
            QListWidget::item:selected {{
                background: #fff3e0;
                color: {COULEUR_ACCENT.name()};
            }}
        """)
        self._list_sessions.currentRowChanged.connect(self._on_session_selectionnee)
        left_layout.addWidget(self._list_sessions)

        # Bouton supprimer session
        btn_suppr_session = QPushButton("🗑 Supprimer session")
        btn_suppr_session.clicked.connect(self._supprimer_session)
        left_layout.addWidget(btn_suppr_session)

        # ─── Boutons document ────────────────────────────────────
        btn_nouveau_doc = QPushButton("📄 Nouveau document")
        btn_nouveau_doc.setToolTip(
            "Exporter la session sélectionnée en document .anlz"
        )
        btn_nouveau_doc.clicked.connect(self._nouveau_document)
        left_layout.addWidget(btn_nouveau_doc)

        btn_ajout_doc = QPushButton("➕ Ajout à un document")
        btn_ajout_doc.setToolTip(
            "Ajouter les pages de la session à un document .anlz existant"
        )
        btn_ajout_doc.clicked.connect(self._ajout_a_document)
        left_layout.addWidget(btn_ajout_doc)

        splitter.addWidget(left)

        # Liste des pages
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        lbl_pages = QLabel("Pages")
        lbl_pages.setFont(police_titre(14))
        lbl_pages.setStyleSheet(f"color: {COULEUR_ACCENT.name()};")
        right_layout.addWidget(lbl_pages)

        self._list_pages = QListWidget()
        self._list_pages.setStyleSheet(self._list_sessions.styleSheet())
        self._list_pages.currentRowChanged.connect(self._on_page_selectionnee)
        self._list_pages.doubleClicked.connect(self._ouvrir)
        right_layout.addWidget(self._list_pages)

        # Aperçu du texte
        self._lbl_apercu = QLabel()
        self._lbl_apercu.setWordWrap(True)
        self._lbl_apercu.setMaximumHeight(80)
        self._lbl_apercu.setStyleSheet(
            f"color: {COULEUR_TEXTE_MUET.name()}; "
            f"background: #f6f1eb; padding: 8px; border-radius: 4px; "
            f"font-size: 11px;"
        )
        right_layout.addWidget(self._lbl_apercu)

        # Bouton supprimer page
        btn_suppr_page = QPushButton("🗑 Supprimer page")
        btn_suppr_page.clicked.connect(self._supprimer_page)
        right_layout.addWidget(btn_suppr_page)

        splitter.addWidget(right)
        splitter.setSizes([300, 500])
        layout.addWidget(splitter)

        # ─── Boutons bas ─────────────────────────────────────────
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._btn_ouvrir = QPushButton("📖 Ouvrir")
        self._btn_ouvrir.setEnabled(False)
        self._btn_ouvrir.setStyleSheet(f"""
            QPushButton {{
                background: {COULEUR_ACCENT.name()};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 24px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: #d4622e; }}
            QPushButton:disabled {{ background: #ccc; color: #999; }}
        """)
        self._btn_ouvrir.clicked.connect(self._ouvrir)
        btn_layout.addWidget(self._btn_ouvrir)

        btn_annuler = QPushButton("Annuler")
        btn_annuler.setStyleSheet("""
            QPushButton {
                padding: 8px 16px; font-size: 13px;
                border: 1px solid #ccc; border-radius: 6px;
            }
        """)
        btn_annuler.clicked.connect(self.reject)
        btn_layout.addWidget(btn_annuler)

        layout.addLayout(btn_layout)

    def _charger_sessions(self) -> None:
        self._list_sessions.clear()
        self._sessions = db().lister_sessions()
        for s in self._sessions:
            self._list_sessions.addItem(s.label)

    @Slot(int)
    def _on_session_selectionnee(self, row: int) -> None:
        self._list_pages.clear()
        self._lbl_apercu.clear()
        self._btn_ouvrir.setEnabled(False)
        self._page_selectionnee = None

        if row < 0 or row >= len(self._sessions):
            return

        session = self._sessions[row]
        self._pages = db().lister_pages(session.id)
        for p in self._pages:
            self._list_pages.addItem(p.label)

    @Slot(int)
    def _on_page_selectionnee(self, row: int) -> None:
        if row < 0 or row >= len(self._pages):
            self._btn_ouvrir.setEnabled(False)
            self._page_selectionnee = None
            self._lbl_apercu.clear()
            return

        page = self._pages[row]
        self._page_selectionnee = page
        self._btn_ouvrir.setEnabled(True)

        # Aperçu
        apercu = page.texte_brut[:300].replace("\n", " ")
        self._lbl_apercu.setText(apercu + ("…" if len(page.texte_brut) > 300 else ""))

    @Slot()
    def _ouvrir(self) -> None:
        if self._page_selectionnee:
            self.page_choisie.emit(self._page_selectionnee)
            self.accept()

    @Slot()
    def _supprimer_session(self) -> None:
        row = self._list_sessions.currentRow()
        if row < 0 or row >= len(self._sessions):
            return
        session = self._sessions[row]
        rep = QMessageBox.question(
            self, "Supprimer",
            f"Supprimer la session « {session.nom} » et toutes ses pages ?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if rep == QMessageBox.Yes:
            db().supprimer_session(session.id)
            self._charger_sessions()

    @Slot()
    def _supprimer_page(self) -> None:
        if not self._page_selectionnee:
            return
        rep = QMessageBox.question(
            self, "Supprimer",
            f"Supprimer la page {self._page_selectionnee.numero} ?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if rep == QMessageBox.Yes:
            db().supprimer_page(self._page_selectionnee.id)
            row = self._list_sessions.currentRow()
            self._on_session_selectionnee(row)

    # ─── Documents (.anlz) ───────────────────────────────────────

    def _session_selectionnee(self) -> SessionRecord | None:
        """Retourne la session sélectionnée, ou None."""
        row = self._list_sessions.currentRow()
        if row < 0 or row >= len(self._sessions):
            return None
        return self._sessions[row]

    @Slot()
    def _nouveau_document(self) -> None:
        """Exporte la session sélectionnée en nouveau document .anlz."""
        session = self._session_selectionnee()
        if session is None:
            QMessageBox.information(
                self, "Nouveau document",
                "Sélectionnez d'abord une session.",
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer le document",
            f"{session.nom}.anlz",
            "Documents Analizador (*.anlz)",
        )
        if not path:
            return

        try:
            from core.document import session_vers_document, sauvegarder_document

            doc = session_vers_document(session.id)
            chemin = sauvegarder_document(doc, path)

            QMessageBox.information(
                self, "Document créé",
                f"Document créé : {chemin.name}\n"
                f"{doc.nb_pages} pages exportées.",
            )
        except Exception as e:
            QMessageBox.critical(self, "Erreur", str(e))

    @Slot()
    def _ajout_a_document(self) -> None:
        """Ajoute les pages de la session à un document .anlz existant."""
        session = self._session_selectionnee()
        if session is None:
            QMessageBox.information(
                self, "Ajout à un document",
                "Sélectionnez d'abord une session.",
            )
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Choisir le document cible", "",
            "Documents Analizador (*.anlz);;Tous (*)",
        )
        if not path:
            return

        try:
            from core.document import (
                charger_document, sauvegarder_document,
                session_vers_document,
            )

            doc = charger_document(path)
            doc_source = session_vers_document(session.id)

            nb_avant = doc.nb_pages
            for page in doc_source.pages:
                doc.ajouter_page(page)
            doc._renumeroter()

            sauvegarder_document(doc, path)

            nb_ajoutees = doc.nb_pages - nb_avant
            QMessageBox.information(
                self, "Ajout terminé",
                f"{nb_ajoutees} pages ajoutées à « {doc.nom} ».\n"
                f"Total : {doc.nb_pages} pages.",
            )
        except Exception as e:
            QMessageBox.critical(self, "Erreur", str(e))