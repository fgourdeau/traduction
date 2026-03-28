"""Dialogue de gestion des documents Analizador (.anlz).

Fonctionnalités :
- Exporter une session en document .anlz
- Ouvrir un document .anlz (importer en session)
- Ajouter des pages d'une session dans un document existant
- Trier / supprimer des pages dans un document
"""

from pathlib import Path

from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QSplitter, QWidget, QMessageBox,
    QFileDialog, QInputDialog, QAbstractItemView,
)

from core.config import (
    COULEUR_ACCENT, COULEUR_PANNEAU, COULEUR_BORDURE,
    COULEUR_TEXTE_SECONDAIRE, COULEUR_TEXTE_MUET,
    police_texte, police_titre,
)


class DialogueDocuments(QDialog):
    """Dialogue pour gérer les documents .anlz."""

    # Émis quand l'utilisateur importe un document en session
    document_importe = Signal(int)  # session_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gestionnaire de documents")
        self.setMinimumSize(850, 550)
        self.resize(950, 600)

        self._doc = None           # Document chargé
        self._doc_path = None      # Chemin du fichier .anlz
        self._modified = False     # Suivi des modifications

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ─── Barre d'actions principales ─────────────────────────
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        btn_style = f"""
            QPushButton {{
                background: {COULEUR_PANNEAU.name()};
                border: 1px solid {COULEUR_BORDURE.name()};
                border-radius: 5px;
                padding: 6px 14px;
                font-size: 12px;
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

        self._lbl_titre = QLabel("Aucun document ouvert")
        self._lbl_titre.setFont(police_titre(14))
        self._lbl_titre.setStyleSheet(f"color: {COULEUR_ACCENT.name()};")
        top_bar.addWidget(self._lbl_titre)

        top_bar.addStretch()

        btn_ouvrir = QPushButton("📂 Ouvrir .anlz")
        btn_ouvrir.setStyleSheet(btn_style)
        btn_ouvrir.clicked.connect(self._ouvrir_document)
        top_bar.addWidget(btn_ouvrir)

        layout.addLayout(top_bar)

        # ─── Liste des pages (drag & drop pour réordonner) ───────
        self._list_pages = QListWidget()
        self._list_pages.setDragDropMode(QAbstractItemView.InternalMove)
        self._list_pages.setDefaultDropAction(Qt.MoveAction)
        self._list_pages.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._list_pages.model().rowsMoved.connect(self._on_pages_reordonnees)
        self._list_pages.setStyleSheet(f"""
            QListWidget {{
                border: 1px solid {COULEUR_BORDURE.name()};
                border-radius: 4px;
                background: white;
                font-size: 12px;
            }}
            QListWidget::item {{
                padding: 10px 12px;
                border-bottom: 1px solid {COULEUR_BORDURE.name()};
            }}
            QListWidget::item:selected {{
                background: #fff3e0;
                color: {COULEUR_ACCENT.name()};
            }}
        """)
        self._list_pages.currentRowChanged.connect(self._on_page_selectionnee)
        layout.addWidget(self._list_pages, stretch=1)

        # ─── Aperçu ──────────────────────────────────────────────
        self._lbl_apercu = QLabel()
        self._lbl_apercu.setWordWrap(True)
        self._lbl_apercu.setMaximumHeight(60)
        self._lbl_apercu.setStyleSheet(
            f"color: {COULEUR_TEXTE_MUET.name()}; "
            f"background: #f6f1eb; padding: 8px; border-radius: 4px; "
            f"font-size: 11px;"
        )
        layout.addWidget(self._lbl_apercu)

        # ─── Barre de gestion des pages ──────────────────────────
        page_bar = QHBoxLayout()
        page_bar.setSpacing(8)

        btn_monter = QPushButton("▲ Monter")
        btn_monter.setStyleSheet(btn_style)
        btn_monter.clicked.connect(self._monter_page)
        page_bar.addWidget(btn_monter)

        btn_descendre = QPushButton("▼ Descendre")
        btn_descendre.setStyleSheet(btn_style)
        btn_descendre.clicked.connect(self._descendre_page)
        page_bar.addWidget(btn_descendre)

        btn_suppr = QPushButton("🗑 Supprimer")
        btn_suppr.setStyleSheet(btn_style)
        btn_suppr.clicked.connect(self._supprimer_pages)
        page_bar.addWidget(btn_suppr)

        page_bar.addStretch()

        self._lbl_info = QLabel()
        self._lbl_info.setStyleSheet(
            f"color: {COULEUR_TEXTE_MUET.name()}; font-size: 11px;"
        )
        page_bar.addWidget(self._lbl_info)

        layout.addLayout(page_bar)

        # ─── Boutons bas ─────────────────────────────────────────
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self._btn_sauver = QPushButton("💾 Sauvegarder le document")
        self._btn_sauver.setEnabled(False)
        self._btn_sauver.setStyleSheet(f"""
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
        self._btn_sauver.clicked.connect(self._sauvegarder)
        btn_layout.addWidget(self._btn_sauver)

        self._btn_importer = QPushButton("📥 Lire / importer en session")
        self._btn_importer.setEnabled(False)
        self._btn_importer.setStyleSheet(f"""
            QPushButton {{
                background: #2e7d32;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 24px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: #1b5e20; }}
            QPushButton:disabled {{ background: #ccc; color: #999; }}
        """)
        self._btn_importer.clicked.connect(self._importer_en_session)
        btn_layout.addWidget(self._btn_importer)

        btn_layout.addStretch()

        btn_fermer = QPushButton("Fermer")
        btn_fermer.setStyleSheet("""
            QPushButton {
                padding: 8px 16px; font-size: 13px;
                border: 1px solid #ccc; border-radius: 6px;
            }
        """)
        btn_fermer.clicked.connect(self._fermer)
        btn_layout.addWidget(btn_fermer)

        layout.addLayout(btn_layout)

        # État initial
        self._maj_etat()

    # ─── Actions principales ─────────────────────────────────────

    @Slot()
    def _ouvrir_document(self) -> None:
        """Ouvre un fichier .anlz existant."""
        if self._confirmer_perte():
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir un document Analizador", "",
            "Documents Analizador (*.anlz);;Tous (*)",
        )
        if not path:
            return

        try:
            from core.document import charger_document
            self._doc = charger_document(path)
            self._doc_path = Path(path)
            self._modified = False
            self._rafraichir_liste()
            self._maj_etat()
        except (FileNotFoundError, ValueError) as e:
            QMessageBox.critical(self, "Erreur", str(e))

    # ─── Gestion des pages ───────────────────────────────────────

    @Slot()
    def _monter_page(self) -> None:
        row = self._list_pages.currentRow()
        if self._doc and 0 < row < self._doc.nb_pages:
            self._doc.deplacer_page(row, row - 1)
            self._modified = True
            self._rafraichir_liste()
            self._list_pages.setCurrentRow(row - 1)
            self._maj_etat()

    @Slot()
    def _descendre_page(self) -> None:
        row = self._list_pages.currentRow()
        if self._doc and 0 <= row < self._doc.nb_pages - 1:
            self._doc.deplacer_page(row, row + 1)
            self._modified = True
            self._rafraichir_liste()
            self._list_pages.setCurrentRow(row + 1)
            self._maj_etat()

    @Slot()
    def _supprimer_pages(self) -> None:
        if not self._doc:
            return

        indices = sorted(
            {idx.row() for idx in self._list_pages.selectedIndexes()},
            reverse=True,
        )
        if not indices:
            return

        n = len(indices)
        rep = QMessageBox.question(
            self, "Supprimer",
            f"Supprimer {n} page{'s' if n > 1 else ''} du document ?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if rep != QMessageBox.Yes:
            return

        for idx in indices:
            self._doc.supprimer_page(idx)

        self._modified = True
        self._rafraichir_liste()
        self._maj_etat()

    @Slot()
    def _on_pages_reordonnees(self) -> None:
        """Appelé après un drag & drop dans la liste."""
        if not self._doc:
            return

        # Reconstruire l'ordre depuis la liste
        new_order = []
        for i in range(self._list_pages.count()):
            item = self._list_pages.item(i)
            old_idx = item.data(Qt.UserRole)
            if old_idx is not None:
                new_order.append(old_idx)

        if new_order and new_order != list(range(len(self._doc.pages))):
            pages_reordonnees = [self._doc.pages[i] for i in new_order]
            self._doc.pages = pages_reordonnees
            self._doc._renumeroter()
            self._modified = True
            self._rafraichir_liste()
            self._maj_etat()

    @Slot(int)
    def _on_page_selectionnee(self, row: int) -> None:
        if not self._doc or row < 0 or row >= self._doc.nb_pages:
            self._lbl_apercu.clear()
            return

        page = self._doc.pages[row]
        apercu = page.texte_brut[:300].replace("\n", " ")
        suffix = "…" if len(page.texte_brut) > 300 else ""
        img_info = " 🖼 (avec image)" if page.has_image else ""
        self._lbl_apercu.setText(f"{apercu}{suffix}{img_info}")

    # ─── Sauvegarde / Import ─────────────────────────────────────

    @Slot()
    def _sauvegarder(self) -> None:
        if not self._doc:
            return

        # Si pas de chemin, demander
        if not self._doc_path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Enregistrer le document",
                f"{self._doc.nom}.anlz",
                "Documents Analizador (*.anlz)",
            )
            if not path:
                return
            self._doc_path = Path(path)

        try:
            from core.document import sauvegarder_document
            sauvegarder_document(self._doc, self._doc_path)
            self._modified = False
            self._maj_etat()
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Erreur sauvegarde: {e}")

    @Slot()
    def _importer_en_session(self) -> None:
        """Importe le document en session et charge la première page."""
        if not self._doc:
            return

        nom, ok = QInputDialog.getText(
            self, "Lire / importer en session",
            "Nom de la session :",
            text=self._doc.nom,
        )
        if not ok or not nom.strip():
            return

        try:
            from core.document import document_vers_session
            session_id = document_vers_session(self._doc, nom.strip())
            self.document_importe.emit(session_id)
            self._modified = False  # Éviter la confirmation de perte
            self.accept()           # Fermer et passer à la session
        except Exception as e:
            QMessageBox.critical(self, "Erreur import", str(e))

    # ─── Helpers ─────────────────────────────────────────────────

    def _rafraichir_liste(self) -> None:
        self._list_pages.clear()
        if not self._doc:
            return

        for i, page in enumerate(self._doc.pages):
            icone = "🖼" if page.has_image else "📝"
            apercu = page.texte_brut[:80].replace("\n", " ").strip()
            dt = page.cree_le[:16].replace("T", " ") if page.cree_le else ""
            label = f"{icone} Page {page.numero} — {dt} — {apercu}…"

            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, i)
            self._list_pages.addItem(item)

    def _maj_etat(self) -> None:
        """Met à jour les labels et boutons selon l'état."""
        has_doc = self._doc is not None

        self._btn_sauver.setEnabled(has_doc and self._modified)
        self._btn_importer.setEnabled(has_doc and self._doc.nb_pages > 0)

        if has_doc:
            modif = " *" if self._modified else ""
            nom_fichier = self._doc_path.name if self._doc_path else "(nouveau)"
            self._lbl_titre.setText(
                f"📄 {self._doc.nom}{modif} — {self._doc.nb_pages} pages"
            )
            self._lbl_info.setText(nom_fichier)
        else:
            self._lbl_titre.setText("Aucun document ouvert")
            self._lbl_info.setText("")

    def _confirmer_perte(self) -> bool:
        """Retourne True si l'utilisateur annule (modifications non sauvegardées)."""
        if not self._modified:
            return False
        rep = QMessageBox.question(
            self, "Modifications non sauvegardées",
            "Le document a été modifié. Continuer sans sauvegarder ?",
            QMessageBox.Yes | QMessageBox.No,
        )
        return rep != QMessageBox.Yes

    def _fermer(self) -> None:
        if not self._confirmer_perte():
            self.accept()

    def closeEvent(self, event) -> None:
        if self._confirmer_perte():
            event.ignore()
        else:
            event.accept()