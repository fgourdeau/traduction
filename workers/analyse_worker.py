"""Workers : OCR Vision (Phase 1) + Analyse grammaticale (Phase 2).

Phase 1 — OcrWorker : image → Claude Vision → texte brut (~4 sec)
Phase 2 — AnalyseWorker : texte → Claude → JSON grammatical (pas d'image)

Optimisation v2 : format compact (tableaux au lieu d'objets par mot),
abréviations, prompt caching → ~50% moins de tokens en sortie.
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
Expert en linguistique espagnole. Texte espagnol → JSON grammatical.

Pour chaque phrase:
1. Découpe: une phrase = fin par . ? ! ou ... (sinon 1 ligne = 1 phrase).
   IMPORTANT: ne regroupe PAS tout en une seule phrase.
2. Analyse mot par mot (PAS la ponctuation), champs dans cet ORDRE FIXE:
   [mot, cat, lemme, genre, nombre, conj, pron, def, grp]
   - cat: S(ustantivo) V(erbo) Adj Adv Pro Pre Art Con Det Int Num
   - genre: m/f/n/x  (x = n/a)
   - nombre: s/p/x
   - conj: compact, ex "3s.pret.ind" = 3ª persona singular pretérito indicativo.
     Schéma: {personne}{nombre}.{temps}.{mode}
     personne: 1/2/3, nombre: s/p
     temps: pres/pret/imp/fut/cond/subpres/subimp/subfut/imper/ger/part
     mode: ind/sub/imp (omis si déjà dans temps: subpres, subimp, imper, ger, part)
     Null si pas verbe.
   - pron: prononciation approximative pour francophone
   - def: courte, en français
   - grp: suj/vrb/cpl/rel
     suj = sujet + déterminants/adjectifs du sujet
     vrb = verbe principal, auxiliaires, adverbes du verbe
     cpl = compléments (COD, COI, CC) + leurs déterminants
     rel = proposition relative entière (pronom relatif + verbe + compléments)
     défaut = cpl
3. Expressions: indices 0-based des mots formant expression idiomatique.
4. Traduction naturelle en français.

JSON UNIQUEMENT (pas de markdown, pas de ```):
{"p":[{"t":"texte original","tr":"traduction","m":[["mot","cat","lemme","g","n","conj","pron","def","grp"],...],"e":[{"i":[2,3],"t":"texte","s":"sens"}]}]}
"""

# System prompt sous forme de bloc avec cache_control pour prompt caching
ANALYSE_SYSTEM_BLOCK = [{
    "type": "text",
    "text": ANALYSE_PROMPT,
    "cache_control": {"type": "ephemeral"},
}]


# ─── Adaptateur format compact → format original ─────────────────────

_CAT_MAP = {
    "S": "sustantivo", "V": "verbo", "Adj": "adjetivo",
    "Adv": "adverbio", "Pro": "pronombre", "Pre": "preposición",
    "Art": "artículo", "Con": "conjunción", "Det": "determinante",
    "Int": "interjección", "Num": "numeral",
}
_GENRE_MAP = {"m": "masculino", "f": "femenino", "n": "neutro", "x": "n/a"}
_NOMBRE_MAP = {"s": "singular", "p": "plural", "x": "n/a"}
_GROUPE_MAP = {"suj": "sujeto", "vrb": "verbo", "cpl": "complemento", "rel": "relativa"}

# Champs dans l'ordre fixe du format compact
_KEYS = ("mot", "categorie", "lemme", "genre", "nombre",
         "conjugaison", "prononciation", "definition", "groupe")


def _expand_conj(conj: str | None) -> str | None:
    """Expand '3s.pret.ind' → '3ª persona singular, pretérito perfecto simple, indicativo'.

    Fait un best-effort — si le format n'est pas reconnu, retourne tel quel.
    """
    if not conj:
        return None

    _PERS = {"1": "1ª persona", "2": "2ª persona", "3": "3ª persona"}
    _NUM = {"s": "singular", "p": "plural"}
    _TEMPS = {
        "pres.ind": "presente de indicativo",
        "pret.ind": "pretérito perfecto simple de indicativo",
        "imp.ind": "pretérito imperfecto de indicativo",
        "fut.ind": "futuro de indicativo",
        "cond": "condicional",
        "subpres": "presente de subjuntivo",
        "subimp": "pretérito imperfecto de subjuntivo",
        "subfut": "futuro de subjuntivo",
        "imper": "imperativo",
        "ger": "gerundio",
        "part": "participio",
    }

    parts = conj.split(".", 1)
    if len(parts) < 2 or len(parts[0]) < 2:
        return conj  # format non reconnu, retourner tel quel

    pers_num = parts[0]  # ex: "3s"
    temps_mode = parts[1]  # ex: "pret.ind"

    pers = _PERS.get(pers_num[0], pers_num[0])
    num = _NUM.get(pers_num[1], pers_num[1])
    temps = _TEMPS.get(temps_mode, temps_mode)

    return f"{pers} {num}, {temps}"


def _expand_mot(row: list) -> dict:
    """Convertit une ligne compacte [mot, cat, lemme, g, n, conj, pron, def, grp]
    en dict compatible from_api_response."""
    d = dict(zip(_KEYS, row))
    d["categorie"] = _CAT_MAP.get(d["categorie"], d["categorie"])
    d["genre"] = _GENRE_MAP.get(d["genre"], d["genre"])
    d["nombre"] = _NOMBRE_MAP.get(d["nombre"], d["nombre"])
    d["groupe"] = _GROUPE_MAP.get(d["groupe"], d["groupe"])
    d["conjugaison"] = _expand_conj(d.get("conjugaison"))
    return d


def _expand_response(data: dict) -> dict:
    """Convertit la réponse compacte {"p":[...]} en format original {"phrases":[...]}."""
    phrases = []
    for p in data["p"]:
        phrases.append({
            "texte_original": p["t"],
            "traduction": p["tr"],
            "mots": [_expand_mot(row) for row in p["m"]],
            "expressions": [
                {"indices": e["i"], "texte": e["t"], "sens": e["s"]}
                for e in p.get("e", [])
            ],
        })
    return {"phrases": phrases}


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
            usage = message.usage
            tok_per_s = usage.output_tokens / dt if dt > 0 else 0
            print(f"\n┌─ OCR ────────────────────────────────────")
            print(f"│ Temps API : {dt:.1f}s")
            print(f"│ Tokens    : in={usage.input_tokens}  out={usage.output_tokens}  ({tok_per_s:.0f} tok/s)")
            print(f"│ Résultat  : {len(texte)} chars, stop={message.stop_reason}")
            print(f"└──────────────────────────────────────────")
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
# Phase 2 — Analyse grammaticale (parallèle, affichage progressif)
# ═════════════════════════════════════════════════════════════════════

# Nombre max de requêtes API simultanées
MAX_PARALLEL = 3


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
        print(f"[Analyse #{self._index}] USER:")
        print(user_content)
        print(f"{'='*70}")

        try:
            t0 = time.time()
            message = self._client.messages.create(
                model=MODEL,
                max_tokens=4000,
                system=ANALYSE_SYSTEM_BLOCK,
                messages=[{
                    "role": "user",
                    "content": user_content,
                }],
            )
            dt = time.time() - t0

            raw = message.content[0].text.strip()

            # Afficher les infos de timing et cache
            usage = message.usage
            tok_per_s = usage.output_tokens / dt if dt > 0 else 0
            cache_info = ""
            if hasattr(usage, "cache_creation_input_tokens"):
                cc = usage.cache_creation_input_tokens
                cr = usage.cache_read_input_tokens
                cache_info = f"│ Cache     : create={cc}  read={cr}\n"

            print(f"\n┌─ Analyse #{self._index} ──────────────────────────────")
            print(f"│ Temps API : {dt:.1f}s")
            print(f"│ Tokens    : in={usage.input_tokens}  out={usage.output_tokens}  ({tok_per_s:.0f} tok/s)")
            print(f"{cache_info}"
                  f"│ Résultat  : {len(raw)} chars, stop={message.stop_reason}")
            print(f"└──────────────────────────────────────────")
            print(f"[Analyse #{self._index}] JSON:")
            print(raw[:500] + ("…" if len(raw) > 500 else ""))
            print(f"{'='*70}\n")

            if message.stop_reason == "max_tokens":
                print(f"[Analyse #{self._index}] ⚠ TRONQUÉ")

            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            data = json.loads(raw)

            # Expand format compact → format original compatible from_api_response
            data = _expand_response(data)

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
    """Gestionnaire — analyse plusieurs phrases en parallèle.

    Supporte deux modes :
    - analyse_phrase_demandee(index, texte) : une phrase à la fois (clic/tab)
    - analyse_batch_demandee(list[tuple[int, str]]) : toutes les phrases d'un coup

    Les résultats arrivent progressivement via analyse_phrase_terminee.
    MAX_PARALLEL requêtes API tournent simultanément.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._actives: dict[int, _AnalysePhraseTask] = {}  # index → task
        self._queue: list[tuple[int, str]] = []  # phrases en attente
        self._deja_analyses: set[int] = set()  # éviter les doublons
        self._t0_batch: float | None = None  # chrono global du batch
        self._nb_batch: int = 0  # nombre total de phrases dans le batch

        from core.event_bus import bus
        bus().analyse_phrase_demandee.connect(self._on_demande)
        bus().analyse_batch_demandee.connect(self._on_batch)

    @Slot(int, str)
    def _on_demande(self, index: int, texte: str) -> None:
        """Une seule phrase demandée (navigation utilisateur)."""
        if not texte.strip() or index in self._deja_analyses:
            return
        if index in self._actives:
            return  # déjà en cours
        self._enqueue([(index, texte)])

    @Slot(list)
    def _on_batch(self, phrases: list) -> None:
        """Batch de phrases demandé (après OCR ou collage)."""
        # Filtrer celles déjà analysées ou en cours
        nouvelles = [
            (i, t) for i, t in phrases
            if i not in self._deja_analyses
            and i not in self._actives
            and t.strip()
        ]
        if not nouvelles:
            return
        self._t0_batch = time.time()
        self._nb_batch = len(nouvelles)
        print(f"\n[Analyse] Batch de {self._nb_batch} phrases, "
              f"parallélisme={MAX_PARALLEL}")
        self._enqueue(nouvelles)

    def _enqueue(self, phrases: list[tuple[int, str]]) -> None:
        """Ajoute des phrases à la queue et lance les slots libres."""
        self._queue.extend(phrases)
        self._lancer_suivantes()

    def _lancer_suivantes(self) -> None:
        """Lance des tasks tant qu'il y a des slots libres et des phrases en attente."""
        from core.event_bus import bus

        while self._queue and len(self._actives) < MAX_PARALLEL:
            index, texte = self._queue.pop(0)

            # Skip si déjà fait entre-temps
            if index in self._deja_analyses or index in self._actives:
                continue

            n_en_cours = len(self._actives) + 1
            n_restant = len(self._queue)
            bus().status_message.emit(
                f"Analyse phrase {index + 1}… "
                f"({n_en_cours} en cours, {n_restant} en attente)"
            )
            bus().chargement_en_cours.emit(True)

            task = _AnalysePhraseTask(index, texte, parent=self)
            task.termine.connect(self._on_termine)
            task.erreur.connect(self._on_erreur)
            task.finished.connect(lambda idx=index: self._on_task_finie(idx))
            self._actives[index] = task
            task.start()

    def _on_task_finie(self, index: int) -> None:
        """Nettoyage quand une task se termine (succès ou erreur)."""
        self._actives.pop(index, None)

        # Lancer les suivantes dans la queue
        self._lancer_suivantes()

        # Si plus rien en cours ni en attente, fin du batch
        if not self._actives and not self._queue:
            from core.event_bus import bus
            bus().chargement_en_cours.emit(False)
            if self._t0_batch is not None:
                dt = time.time() - self._t0_batch
                print(f"\n┌─ Batch terminé ───────────────────────────")
                print(f"│ {self._nb_batch} phrases en {dt:.1f}s "
                      f"({dt / self._nb_batch:.1f}s/phrase)")
                print(f"└──────────────────────────────────────────\n")
                self._t0_batch = None
                bus().status_message.emit(
                    f"Analyse terminée — {self._nb_batch} phrases en {dt:.1f}s"
                )

    def _on_termine(self, index: int, phrase: object) -> None:
        from core.event_bus import bus
        self._deja_analyses.add(index)
        bus().analyse_phrase_terminee.emit(index, phrase)

    def _on_erreur(self, msg: str) -> None:
        from core.event_bus import bus
        bus().analyse_erreur.emit(msg)

    def reset(self) -> None:
        """Réinitialise l'état (nouveau texte chargé)."""
        self._deja_analyses.clear()
        self._queue.clear()
        self._t0_batch = None
        self._nb_batch = 0
        # Les tasks actives finiront d'elles-mêmes