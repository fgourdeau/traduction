#!/usr/bin/env python3
"""Analizador — Point d'entrée."""

import sys
import os

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
import logging
#logging.basicConfig(
#    level=logging.DEBUG,
#    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
#)

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

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

    # ─── Configuration clé API ───────────────────────────────────
    from core.settings import obtenir_cle_api, demander_cle_api

    cle = obtenir_cle_api()
    if not cle:
        cle = demander_cle_api()
        if not cle:
            sys.exit(0)  # Annulé par l'utilisateur

    # S'assurer que la clé est dans l'environnement pour anthropic SDK
    os.environ["ANTHROPIC_API_KEY"] = cle

    # ─── Lancement ───────────────────────────────────────────────
    from ui.fenetre_principale import FenetrePrincipale

    fenetre = FenetrePrincipale()
    fenetre.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()