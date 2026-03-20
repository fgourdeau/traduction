"""Workers : OCR Vision (Phase 1) + Analyse grammaticale (Phase 2).

Phase 1 — OcrWorker : image → Claude Vision → texte brut (~4 sec)
Phase 2 — AnalyseWorker : texte → Claude → JSON grammatical (pas d'image)
"""

import base64
import json
import traceback
import time

import cv2
import numpy as np
from PySide6.QtCore import QThread, QObject, Signal, Slot

import anthropic

from core.modeles import from_api_response

# Modèle à utiliser — configurable
MODEL = "claude-sonnet-4-20250514"

# ─── Prompts séparés ─────────────────────────────────────────────────

OCR_PROMPT = """\
Tu es un expert en OCR. On te donne une IMAGE contenant du texte en espagnol.
Extrais et retranscris EXACTEMENT tout le texte visible, en respectant:
- L'orthographe exacte (accents, ñ, ¿, ¡)
- La ponctuation
- Les sauts de ligne entre paragraphes (ligne vide)
- Les retours à la ligne au sein d'un paragraphe (un simple retour)

Ne commente pas, ne traduis pas. Retourne UNIQUEMENT le texte extrait.
"""

ANALYSE_PROMPT = """\
Tu es un expert en linguistique espagnole. On te donne du texte en espagnol.

**Tâche 1 — Découpage en phrases:**
Découpe le texte en phrases individuelles:
- Chaque phrase se termine par . ? ! ou ...
- Si un fragment n'a pas de ponctuation finale, traite chaque ligne comme phrase
- IMPORTANT: ne regroupe PAS tout en une seule phrase

**Tâche 2 — Analyse grammaticale mot par mot:**
Pour chaque mot:
- mot: le mot exact
- categorie: sustantivo, verbo, adjetivo, adverbio, pronombre, preposición, \
artículo, conjunción, determinante, interjección, numeral
- lemme: forme de base / infinitif
- genre: masculino/femenino/neutro/n/a
- nombre: singular/plural/n/a
- conjugaison: "3ª persona singular, presente de indicativo" pour un verbe, sinon null
- prononciation: approximative pour un francophone
- definition: courte, en français
- groupe: le groupe syntaxique auquel appartient le mot dans la phrase. \
Valeurs possibles EXACTES: "sujeto", "verbo", "complemento", "relativa". \
Règles: le sujet et ses déterminants/adjectifs → "sujeto". \
Le verbe principal, auxiliaires et adverbes modifiant le verbe → "verbo". \
Compléments d'objet (direct, indirect, circonstanciel) et leurs déterminants → "complemento". \
Propositions relatives (pronom relatif + verbe + compléments) → "relativa". \
Si un mot n'entre dans aucun groupe, utiliser "complemento" par défaut.

**Tâche 3 — Expressions idiomatiques:**
Indices (0-based) des mots formant une expression dont le sens diffère du littéral.

**Tâche 4 — Traduction par phrase:**
Traduction naturelle en français.

Réponds UNIQUEMENT en JSON valide (pas de markdown, pas de ```), schéma:
{
  "phrases": [
    {
      "texte_original": "...",
      "traduction": "...",
      "mots": [{"mot":"...", "categorie":"...", "lemme":"...", "genre":"...", \
"nombre":"...", "conjugaison":null, "prononciation":"...", "definition":"...", \
"groupe":"sujeto"}],
      "expressions": [{"indices":[2,3], "texte":"...", "sens":"..."}]
    }
  ]
}

Les signes de ponctuation ne sont pas des mots.
Le tableau "phrases" doit contenir PLUSIEURS objets si le texte contient plusieurs phrases.
"""


# ═════════════════════════════════════════════════════════════════════
# Phase 1 — OCR Vision
# ═════════════════════════════════════════════════════════════════════

class _OcrTask(QThread):
    """Thread éphémère — envoie l'image à Claude Vision pour OCR pur."""

    termine = Signal(str)
    erreur = Signal(str)

    def __init__(self, image: np.ndarray, parent=None):
        super().__init__(parent)
        self._image = image
        self._client = anthropic.Anthropic()

    def run(self) -> None:
        h, w = self._image.shape[:2]
        print(f"[OCR] Image {w}×{h}, modèle={MODEL}")

        try:
            ok, buf = cv2.imencode(".jpg", self._image, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if not ok:
                raise RuntimeError("Échec encodage JPEG")
            b64 = base64.b64encode(buf.tobytes()).decode("ascii")
            b64_kb = len(b64) * 3 // 4 // 1024
            print(f"[OCR] JPEG: ~{b64_kb} Ko")

            t0 = time.time()
            message = self._client.messages.create(
                model=MODEL,
                max_tokens=4000,
                system=OCR_PROMPT,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": "Extrais le texte espagnol."},
                    ],
                }],
            )
            dt = time.time() - t0

            texte = message.content[0].text.strip()
            print(f"[OCR] {dt:.1f}s, {len(texte)} chars, "
                  f"stop={message.stop_reason}, "
                  f"tokens in={message.usage.input_tokens} "
                  f"out={message.usage.output_tokens}")
            print(f"[OCR] Texte:\n{texte[:300]}...")

            if not texte:
                self.erreur.emit("Aucun texte détecté")
            else:
                self.termine.emit(texte)

        except anthropic.APIError as e:
            print(f"[OCR] ERREUR API: {e}")
            self.erreur.emit(f"Erreur API (OCR): {e}")
        except Exception as e:
            print(f"[OCR] ERREUR: {e}")
            traceback.print_exc()
            self.erreur.emit(f"Erreur OCR: {e}")


class OcrWorker(QObject):
    """Gestionnaire OCR — lance un _OcrTask éphémère par image."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._task: _OcrTask | None = None

        from core.event_bus import bus
        bus().ocr_lance.connect(self._on_lancement)

    @Slot(np.ndarray)
    def _on_lancement(self, image: np.ndarray) -> None:
        from core.event_bus import bus

        if self._task is not None and self._task.isRunning():
            self._task.terminate()
            self._task.wait(2000)

        bus().status_message.emit("Phase 1 : OCR Claude Vision…")
        bus().chargement_en_cours.emit(True)

        self._task = _OcrTask(image, parent=self)
        self._task.termine.connect(self._on_termine)
        self._task.erreur.connect(self._on_erreur)
        self._task.finished.connect(lambda: bus().chargement_en_cours.emit(False))
        self._task.start()

    def _on_termine(self, texte: str) -> None:
        from core.event_bus import bus
        bus().status_message.emit(f"OCR terminé — {len(texte)} chars")
        bus().ocr_termine.emit(texte)

    def _on_erreur(self, msg: str) -> None:
        from core.event_bus import bus
        bus().ocr_erreur.emit(msg)


# ═════════════════════════════════════════════════════════════════════
# Phase 2 — Analyse grammaticale (phrase par phrase, à la demande)
# ═════════════════════════════════════════════════════════════════════

class _AnalysePhraseTask(QThread):
    """Thread éphémère — analyse UNE phrase."""

    termine = Signal(int, object)   # (index, PhraseAnalysee)
    erreur = Signal(str)

    def __init__(self, index: int, texte: str, parent=None):
        super().__init__(parent)
        self._index = index
        self._texte = texte
        self._client = anthropic.Anthropic()

    def run(self) -> None:
        user_content = (
            "Analyse cette UNIQUE phrase espagnole:\n\n"
            f"{self._texte}"
        )

        print(f"\n{'='*70}")
        print(f"[Analyse #{self._index}] modèle={MODEL}")
        print(f"[Analyse #{self._index}] SYSTEM PROMPT:")
        print(ANALYSE_PROMPT)
        print(f"[Analyse #{self._index}] USER:")
        print(user_content)
        print(f"{'='*70}")

        try:
            t0 = time.time()
            message = self._client.messages.create(
                model=MODEL,
                max_tokens=4000,
                system=ANALYSE_PROMPT,
                messages=[{
                    "role": "user",
                    "content": user_content,
                }],
            )
            dt = time.time() - t0

            raw = message.content[0].text.strip()
            print(f"\n[Analyse #{self._index}] {dt:.1f}s, {len(raw)} chars, "
                  f"stop={message.stop_reason}, "
                  f"tokens in={message.usage.input_tokens} "
                  f"out={message.usage.output_tokens}")
            print(f"[Analyse #{self._index}] JSON RETOUR:")
            print(raw)
            print(f"{'='*70}\n")

            if message.stop_reason == "max_tokens":
                print(f"[Analyse #{self._index}] ⚠ TRONQUÉ")

            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            data = json.loads(raw)
            phrases = from_api_response(data)
            if phrases:
                phrase = phrases[0]
                nb = len(phrase.mots)
                print(f"[Analyse #{self._index}] OK: {nb} mots")
                self.termine.emit(self._index, phrase)
            else:
                self.erreur.emit(f"Phrase #{self._index}: aucun résultat")

        except json.JSONDecodeError as e:
            print(f"[Analyse #{self._index}] ERREUR JSON: {e}")
            self.erreur.emit(f"JSON invalide (phrase {self._index}): {e}")
        except anthropic.APIError as e:
            print(f"[Analyse #{self._index}] ERREUR API: {e}")
            self.erreur.emit(f"Erreur API: {e}")
        except Exception as e:
            print(f"[Analyse #{self._index}] ERREUR: {e}")
            traceback.print_exc()
            self.erreur.emit(f"Erreur: {e}")


class AnalyseWorker(QObject):
    """Gestionnaire — analyse une phrase à la fois, à la demande."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._task: _AnalysePhraseTask | None = None

        from core.event_bus import bus
        bus().analyse_phrase_demandee.connect(self._on_demande)

    @Slot(int, str)
    def _on_demande(self, index: int, texte: str) -> None:
        from core.event_bus import bus

        if not texte.strip():
            return

        # Si une analyse est en cours, on la laisse finir
        # (pas de terminate — on queue implicitement)
        if self._task is not None and self._task.isRunning():
            # Reconnecter quand elle finit pour traiter la nouvelle
            self._task.finished.connect(
                lambda: self._lancer(index, texte))
            return

        self._lancer(index, texte)

    def _lancer(self, index: int, texte: str) -> None:
        from core.event_bus import bus

        bus().status_message.emit(f"Analyse phrase {index + 1}…")
        bus().chargement_en_cours.emit(True)

        self._task = _AnalysePhraseTask(index, texte, parent=self)
        self._task.termine.connect(self._on_termine)
        self._task.erreur.connect(self._on_erreur)
        self._task.finished.connect(
            lambda: bus().chargement_en_cours.emit(False))
        self._task.start()

    def _on_termine(self, index: int, phrase: object) -> None:
        from core.event_bus import bus
        bus().status_message.emit(f"Phrase {index + 1} analysée")
        bus().analyse_phrase_terminee.emit(index, phrase)

    def _on_erreur(self, msg: str) -> None:
        from core.event_bus import bus
        bus().analyse_erreur.emit(msg)