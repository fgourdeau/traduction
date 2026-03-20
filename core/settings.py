"""Gestion de la configuration — clé API, préférences persistantes."""

import json
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QFrame,
)

from core.config import (
    COULEUR_ACCENT, COULEUR_FOND, COULEUR_PANNEAU, COULEUR_BORDURE,
    COULEUR_TEXTE_SECONDAIRE, COULEUR_TEXTE_MUET,
    police_texte, police_titre, police_mono,
)

CONFIG_DIR = Path.home() / ".config" / "analizador"
CONFIG_FILE = CONFIG_DIR / "config.json"


def charger_config() -> dict:
    """Charge la configuration depuis le fichier JSON."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def sauvegarder_config(config: dict) -> None:
    """Sauvegarde la configuration dans le fichier JSON."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def obtenir_cle_api() -> str | None:
    """Retourne la clé API depuis (par priorité):
    1. Variable d'environnement ANTHROPIC_API_KEY
    2. Fichier de configuration ~/.config/analizador/config.json
    """
    # Priorité 1 : variable d'environnement
    env_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if env_key:
        return env_key

    # Priorité 2 : fichier config
    config = charger_config()
    return config.get("api_key", "").strip() or None


def sauvegarder_cle_api(cle: str) -> None:
    """Persiste la clé API dans le fichier de configuration."""
    config = charger_config()
    config["api_key"] = cle.strip()
    sauvegarder_config(config)
    # Aussi la mettre dans l'environnement pour le process courant
    os.environ["ANTHROPIC_API_KEY"] = cle.strip()


class DialogueCleApi(QDialog):
    """Dialogue modal pour saisir la clé API Anthropic."""

    def __init__(self, parent=None, message_erreur: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Configuration — Clé API Anthropic")
        self.setFixedSize(520, 340)
        self.setModal(True)
        self._cle: str = ""

        self._build_ui(message_erreur)

    def _build_ui(self, message_erreur: str) -> None:
        self.setStyleSheet(f"""
            QDialog {{
                background: {COULEUR_FOND.name()};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(16)

        # Titre
        titre = QLabel("Analizador")
        titre.setFont(police_titre(24))
        titre.setStyleSheet(f"color: {COULEUR_ACCENT.name()};")
        layout.addWidget(titre)

        # Description
        desc = QLabel(
            "Pour fonctionner, l'application a besoin d'une clé API Anthropic.\n"
            "Vous pouvez en obtenir une sur console.anthropic.com"
        )
        desc.setFont(police_texte(12))
        desc.setStyleSheet(f"color: {COULEUR_TEXTE_SECONDAIRE.name()};")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Message d'erreur éventuel
        if message_erreur:
            err = QLabel(f"⚠ {message_erreur}")
            err.setFont(police_texte(11))
            err.setStyleSheet(
                "color: #dc2626; background: #fef2f2; "
                "padding: 8px 12px; border-radius: 6px;"
            )
            err.setWordWrap(True)
            layout.addWidget(err)

        # Séparateur
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {COULEUR_BORDURE.name()};")
        layout.addWidget(sep)

        # Champ de saisie
        lbl = QLabel("Clé API")
        lbl.setFont(police_texte(10))
        lbl.setStyleSheet(
            f"color: {COULEUR_TEXTE_MUET.name()}; "
            "letter-spacing: 1px; text-transform: uppercase;"
        )
        layout.addWidget(lbl)

        self._input = QLineEdit()
        self._input.setPlaceholderText("sk-ant-api03-...")
        self._input.setEchoMode(QLineEdit.Password)
        self._input.setFont(police_mono(13))
        self._input.setFixedHeight(40)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: {COULEUR_PANNEAU.name()};
                border: 1px solid {COULEUR_BORDURE.name()};
                border-radius: 6px;
                padding: 0 14px;
                color: {COULEUR_TEXTE_SECONDAIRE.name()};
            }}
            QLineEdit:focus {{
                border-color: {COULEUR_ACCENT.name()};
            }}
        """)
        self._input.returnPressed.connect(self._valider)
        layout.addWidget(self._input)

        # Toggle visibilité
        self._btn_voir = QPushButton("👁 Afficher")
        self._btn_voir.setFlat(True)
        self._btn_voir.setStyleSheet(
            f"color: {COULEUR_TEXTE_MUET.name()}; font-size: 11px;"
        )
        self._btn_voir.clicked.connect(self._toggle_visibilite)
        layout.addWidget(self._btn_voir, alignment=Qt.AlignLeft)

        layout.addStretch()

        # Boutons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self._btn_annuler = QPushButton("Quitter")
        self._btn_annuler.setFixedHeight(36)
        self._btn_annuler.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {COULEUR_BORDURE.name()};
                border-radius: 6px;
                padding: 0 20px;
                color: {COULEUR_TEXTE_SECONDAIRE.name()};
                font-size: 13px;
            }}
            QPushButton:hover {{
                background: {COULEUR_PANNEAU.name()};
            }}
        """)
        self._btn_annuler.clicked.connect(self.reject)
        btn_layout.addWidget(self._btn_annuler)

        btn_layout.addStretch()

        self._btn_ok = QPushButton("Enregistrer et continuer")
        self._btn_ok.setFixedHeight(36)
        self._btn_ok.setStyleSheet(f"""
            QPushButton {{
                background: {COULEUR_ACCENT.name()};
                border: none;
                border-radius: 6px;
                padding: 0 24px;
                color: white;
                font-size: 13px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background: #a84a22;
            }}
        """)
        self._btn_ok.clicked.connect(self._valider)
        btn_layout.addWidget(self._btn_ok)

        layout.addLayout(btn_layout)

        # Focus initial
        self._input.setFocus()

    def _toggle_visibilite(self) -> None:
        if self._input.echoMode() == QLineEdit.Password:
            self._input.setEchoMode(QLineEdit.Normal)
            self._btn_voir.setText("🔒 Masquer")
        else:
            self._input.setEchoMode(QLineEdit.Password)
            self._btn_voir.setText("👁 Afficher")

    def _valider(self) -> None:
        cle = self._input.text().strip()
        if not cle:
            return
        if not cle.startswith("sk-"):
            QMessageBox.warning(
                self, "Clé invalide",
                "La clé API Anthropic commence par 'sk-'.\n"
                "Vérifiez votre clé sur console.anthropic.com",
            )
            return
        self._cle = cle
        self.accept()

    def cle(self) -> str:
        return self._cle


def demander_cle_api(parent=None, message_erreur: str = "") -> str | None:
    """Affiche le dialogue et retourne la clé, ou None si annulé."""
    dlg = DialogueCleApi(parent, message_erreur)
    if dlg.exec() == QDialog.Accepted:
        cle = dlg.cle()
        sauvegarder_cle_api(cle)
        return cle
    return None
