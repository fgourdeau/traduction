#!/usr/bin/env python3
"""Analizador — Point d'entrée."""

import sys
import os


# --- Gestion des chemins (Interne vs Externe) ---
if hasattr(sys, '_MEIPASS'):
    # Dossier temporaire interne (lecture seule, pour certifi, icônes, etc.)
    base_path_internal = sys._MEIPASS
    # Dossier de l'exécutable (lecture/écriture, pour sessions et references)
    base_path_external = os.path.dirname(sys.executable)
else:
    # En mode développement (python main.py)
    base_path_internal = os.path.dirname(os.path.abspath(__file__))
    base_path_external = base_path_internal

# Configuration de Certifi pour le mode OneFile
import certifi
cert_path = os.path.join(base_path_internal, 'certifi', 'cacert.pem')
if not os.path.exists(cert_path):
    cert_path = certifi.where()

os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--log-level=3 --ignore-certificate-errors"

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # --- Initialisation des dossiers externes ---
    # On s'assure que les dossiers existent à côté du .exe
    for dossier in ['sessions', 'references']:
        chemin = os.path.join(base_path_external, dossier)
        if not os.path.exists(chemin):
            os.makedirs(chemin)
            # Optionnel : créer un fichier placeholder ou journal
            with open(os.path.join(chemin, ".keep"), "w") as f: f.write("")

    app.setStyleSheet("""
        QToolTip {
            background: #1a1613;
            color: #f6f1eb;
            border: none;
            padding: 6px 10px;
            border-radius: 4px;
            font-size: 12px;
        }
    """)

    from core.settings import obtenir_cle_api, demander_cle_api

    # Note : Assurez-vous que obtenir_cle_api() utilise base_path_external
    # pour stocker la clé dans un fichier local si nécessaire.
    cle = obtenir_cle_api()
    if not cle:
        cle = demander_cle_api()
        if not cle:
            sys.exit(0)

    os.environ["ANTHROPIC_API_KEY"] = cle

    from ui.fenetre_principale import FenetrePrincipale
    # Passez éventuellement base_path_external à votre fenêtre
    # pour qu'elle sache où charger les sessions.
    fenetre = FenetrePrincipale()
    fenetre.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()