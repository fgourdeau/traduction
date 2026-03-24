import sys
from pathlib import Path

def get_base_path():
    """Retourne le dossier où se trouve l'exécutable (ou le script)."""
    if getattr(sys, 'frozen', False):
        # Mode compilé (.exe)
        return Path(sys.executable).parent
    # Mode développement (Python)
    return Path(__file__).parent.parent

# Définition des dossiers constants
BASE_DIR = get_base_path()
SESSIONS_DIR = BASE_DIR / "sessions"
REFERENCES_DIR = BASE_DIR / "references"