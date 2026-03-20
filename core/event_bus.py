"""EventBus — singleton de signaux pour communication inter-composants."""

from PySide6.QtCore import QObject, Signal
import numpy as np


class EventBus(QObject):
    """Centralise tous les signaux applicatifs. Singleton."""

    # ─── Capture ─────────────────────────────────────────────────────
    image_capturee = Signal(np.ndarray)          # image BGR numpy
    texte_colle = Signal(str)                    # texte collé (bypass OCR)
    capture_ecran_demandee = Signal()
    capture_webcam_demandee = Signal()

    # ─── Phase 1 : OCR (image → texte) ──────────────────────────────
    ocr_lance = Signal(np.ndarray)               # image → worker OCR
    ocr_termine = Signal(str)                    # texte extrait
    ocr_erreur = Signal(str)

    # ─── Phase 2 : Analyse grammaticale ──────────────────────────────
    analyse_phrase_demandee = Signal(int, str)    # (index, texte_phrase) — 1 phrase
    analyse_batch_demandee = Signal(list)         # list[(index, texte)] — toutes les phrases
    analyse_phrase_terminee = Signal(int, object) # (index, PhraseAnalysee)
    analyse_erreur = Signal(str)

    # ─── Navigation / sélection ──────────────────────────────────────
    phrase_selectionnee = Signal(int)             # index phrase
    mot_clique = Signal(int, int)                # (index_phrase, index_mot)
    expression_cliquee = Signal(int, int)        # (index_phrase, index_expression)
    traduction_demandee = Signal(int)            # index_phrase (clic droit)
    wordref_demandee = Signal(str)               # URL WordReference à charger

    # ─── UI ──────────────────────────────────────────────────────────
    status_message = Signal(str)
    chargement_en_cours = Signal(bool)


# Singleton
_instance: EventBus | None = None

def bus() -> EventBus:
    global _instance
    if _instance is None:
        _instance = EventBus()
    return _instance