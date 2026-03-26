"""Workers mode Bounding Box — Détection bulles + OCR/Analyse par bulle.

Pipeline :
  0. Super-résolution RealSR-NCNN-Vulkan (×4, optionnel)
  1. Détection zones texte (Paddle TextDetection ou EasyOCR + DBSCAN)
  2. Pour chaque bulle : OCR Claude Vision → texte
  3. Pour chaque bulle : Analyse grammaticale Claude → JSON
     (le texte peut contenir plusieurs phrases → fusionnées pour la bbox)
  4. Retour progressif à la scène
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QThread, QObject, Signal, Slot
from sklearn.cluster import DBSCAN

import anthropic

from core.modeles import from_api_response

from workers.analyse_worker import (
    MODEL, OCR_PROMPT, ANALYSE_SYSTEM_BLOCK, _expand_response,
)


# ─────────────────────────────────────────────────────────────────
# Super-résolution RealSR
# ─────────────────────────────────────────────────────────────────

def _find_realsr_exe() -> Path | None:
    """Cherche l'exécutable RealSR dans le projet."""
    # Chercher dans tools/ relatif au projet
    candidates = [
        Path("tools/realsr-ncnn-vulkan-20220728-windows/realsr-ncnn-vulkan.exe"),
        Path("tools/realsr-ncnn-vulkan/realsr-ncnn-vulkan.exe"),
        Path("realsr-ncnn-vulkan.exe"),
    ]
    for p in candidates:
        if p.exists():
            return p.resolve()
    return None


def _realsr_upscale(image: np.ndarray, scale: int = 4) -> np.ndarray | None:
    """Upscale via RealSR-NCNN-Vulkan. Retourne None si indisponible."""
    exe = _find_realsr_exe()
    if exe is None:
        return None

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, "input.png")
            out_path = os.path.join(tmpdir, "output.png")

            cv2.imwrite(in_path, image)
            t0 = time.time()

            result = subprocess.run(
                [str(exe), "-i", in_path, "-o", out_path, "-s", str(scale)],
                capture_output=True, text=True, timeout=120,
            )

            # Afficher la sortie de RealSR dans la console Python
            if result.stdout.strip():
                for line in result.stdout.strip().splitlines():
                    print(f"[RealSR] {line}")
            if result.stderr.strip():
                for line in result.stderr.strip().splitlines():
                    print(f"[RealSR] {line}")

            if result.returncode != 0:
                print(f"[RealSR] Erreur: {result.stderr[:200]}")
                return None

            upscaled = cv2.imread(out_path)
            dt = time.time() - t0
            if upscaled is not None:
                h, w = upscaled.shape[:2]
                print(f"[RealSR] OK: {w}×{h} en {dt:.1f}s")
            return upscaled

    except subprocess.TimeoutExpired:
        print("[RealSR] Timeout (>120s)")
        return None
    except Exception as e:
        print(f"[RealSR] Erreur: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# Modèle de données
# ─────────────────────────────────────────────────────────────────

@dataclass
class BulleDetectee:
    """Une bulle détectée par le stage de détection."""
    id: int
    bbox_px: list[int]       # [x, y, w, h] dans l'image source
    bbox_pct: list[float]    # [x%, y%, w%, h%] relatif à l'image
    nb_segments: int
    texte_ocr: str | None = None
    phrase: object | None = None


# ─────────────────────────────────────────────────────────────────
# Fonctions de détection (Paddle / EasyOCR)
# ─────────────────────────────────────────────────────────────────

def _detect_paddle(img: np.ndarray, box_thresh: float = 0.3):
    """Détecte via PaddleOCR TextDetection (det-only, pas de rec)."""
    os.environ["FLAGS_use_mkldnn"] = "0"
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

    from paddleocr import TextDetection

    model = TextDetection(model_name="PP-OCRv5_server_det")
    output = model.predict(
        input=img,
        batch_size=1,
        box_thresh=box_thresh,
        limit_side_len=max(img.shape[:2]),
        limit_type="max",
    )

    h_img, w_img = img.shape[:2]
    img_area = w_img * h_img
    segments = []

    for res in output:
        polys = None
        try:
            j = res.json if hasattr(res, "json") else res
            if isinstance(j, dict):
                inner = j.get("res", j)
                polys = inner.get("dt_polys") if isinstance(inner, dict) else None
        except Exception:
            pass
        if polys is None:
            polys = getattr(res, "dt_polys", None)
        if polys is None:
            continue

        polys = np.array(polys)
        for poly in polys:
            poly_int = poly.astype(np.int32)
            x, y, w, h = cv2.boundingRect(poly_int)
            if (w * h) / img_area < 0.0005:
                continue
            segments.append({
                "bbox_px": [int(x), int(y), int(w), int(h)],
                "cx": x + w // 2,
                "cy": y + h // 2,
            })

    return segments


def _detect_easyocr(img: np.ndarray):
    """Détecte via EasyOCR (CRAFT). Fallback si Paddle indisponible."""
    import easyocr

    reader = easyocr.Reader(["es"], gpu=False)
    raw = reader.readtext(img)

    h_img, w_img = img.shape[:2]
    img_area = w_img * h_img
    segments = []

    for bbox_pts, text, conf in raw:
        xs = [p[0] for p in bbox_pts]
        ys = [p[1] for p in bbox_pts]
        x, y = int(min(xs)), int(min(ys))
        w, h = int(max(xs) - x), int(max(ys) - y)
        if (w * h) / img_area < 0.0005:
            continue
        segments.append({
            "bbox_px": [x, y, w, h],
            "cx": x + w // 2,
            "cy": y + h // 2,
        })

    return segments


# ─────────────────────────────────────────────────────────────────
# Stage 1 : Détection + DBSCAN
# ─────────────────────────────────────────────────────────────────

class _DetectionTask(QThread):
    termine = Signal(object, list)
    erreur = Signal(str)

    def __init__(self, image: np.ndarray, detector: str = "paddle",
                 eps: float = 0.03, y_stretch: float = 1.5,
                 box_thresh: float = 0.3, parent=None):
        super().__init__(parent)
        self._image = image
        self._detector = detector
        self._eps = eps
        self._y_stretch = y_stretch
        self._box_thresh = box_thresh

    def run(self) -> None:
        try:
            img = self._image
            h_img, w_img = img.shape[:2]
            print(f"[BBox] Détection {self._detector} sur {w_img}×{h_img}")

            t0 = time.time()
            if self._detector == "paddle":
                try:
                    segments = _detect_paddle(img, self._box_thresh)
                    print(f"[BBox] Paddle: {len(segments)} segments "
                          f"en {time.time() - t0:.1f}s")
                except Exception as e:
                    print(f"[BBox] Paddle échoué ({e}), fallback EasyOCR")
                    t0 = time.time()
                    segments = _detect_easyocr(img)
                    print(f"[BBox] EasyOCR fallback: {len(segments)} segments "
                          f"en {time.time() - t0:.1f}s")
            else:
                segments = _detect_easyocr(img)
                print(f"[BBox] EasyOCR: {len(segments)} segments "
                      f"en {time.time() - t0:.1f}s")

            if not segments:
                self.termine.emit(self._image, [])
                return

            # DBSCAN clustering
            centres = np.array([[s["cx"], s["cy"]] for s in segments],
                               dtype=float)
            centres_scaled = centres.copy()
            centres_scaled[:, 1] *= self._y_stretch

            eps_px = w_img * self._eps
            labels = DBSCAN(eps=eps_px, min_samples=1).fit_predict(
                centres_scaled)

            # Construire les bulles
            pad = 12
            bulles = []
            for cluster_id in range(max(labels) + 1):
                member_mask = labels == cluster_id
                indices = np.where(member_mask)[0]
                membres = [segments[i] for i in indices]

                x1 = min(m["bbox_px"][0] for m in membres)
                y1 = min(m["bbox_px"][1] for m in membres)
                x2 = max(m["bbox_px"][0] + m["bbox_px"][2] for m in membres)
                y2 = max(m["bbox_px"][1] + m["bbox_px"][3] for m in membres)

                bx = max(0, x1 - pad)
                by = max(0, y1 - pad)
                bw = min(w_img, x2 + pad) - bx
                bh = min(h_img, y2 + pad) - by

                bulles.append(BulleDetectee(
                    id=cluster_id,
                    bbox_px=[bx, by, bw, bh],
                    bbox_pct=[
                        round(bx / w_img * 100, 2),
                        round(by / h_img * 100, 2),
                        round(bw / w_img * 100, 2),
                        round(bh / h_img * 100, 2),
                    ],
                    nb_segments=len(membres),
                ))

            # Trier par position de lecture (haut→bas, gauche→droite)
            bulles.sort(key=lambda b: (b.bbox_px[1], b.bbox_px[0]))
            for i, b in enumerate(bulles):
                b.id = i

            print(f"[BBox] {len(bulles)} bulles détectées")
            self.termine.emit(self._image, bulles)

        except Exception as e:
            print(f"[BBox] ERREUR détection: {e}")
            traceback.print_exc()
            self.erreur.emit(f"Erreur détection bulles: {e}")


# ─────────────────────────────────────────────────────────────────
# Stage 2 : OCR Claude Vision sur un crop
# ─────────────────────────────────────────────────────────────────

class _BulleOcrTask(QThread):
    termine = Signal(int, str)
    erreur = Signal(int, str)

    def __init__(self, bulle_id: int, crop: np.ndarray, parent=None):
        super().__init__(parent)
        self._bulle_id = bulle_id
        self._crop = crop
        self._client = anthropic.Anthropic()

    def run(self) -> None:
        try:
            crop = self._crop
            h, w = crop.shape[:2]
            print(f"[BBox OCR B{self._bulle_id}] Crop {w}×{h}")

            ok, buf = cv2.imencode(".jpg", crop,
                                    [cv2.IMWRITE_JPEG_QUALITY, 92])
            if not ok:
                raise RuntimeError("Échec encodage JPEG")
            b64 = base64.b64encode(buf.tobytes()).decode("ascii")

            t0 = time.time()
            message = self._client.messages.create(
                model=MODEL,
                max_tokens=1000,
                system=OCR_PROMPT,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": b64,
                        }},
                        {"type": "text",
                         "text": "Extrais le texte espagnol de cette bulle de BD."},
                    ],
                }],
            )
            dt = time.time() - t0
            texte = message.content[0].text.strip()
            print(f"[BBox OCR B{self._bulle_id}] «{texte[:60]}» ({dt:.1f}s)")
            self.termine.emit(self._bulle_id, texte)

        except Exception as e:
            print(f"[BBox OCR B{self._bulle_id}] ERREUR: {e}")
            self.erreur.emit(self._bulle_id, str(e))


# ─────────────────────────────────────────────────────────────────
# Stage 3 : Analyse grammaticale (multi-phrases fusionnées)
# ─────────────────────────────────────────────────────────────────

class _BulleAnalyseTask(QThread):
    """Analyse le texte complet d'une bulle. Si plusieurs phrases,
    les fusionne en une seule PhraseAnalysee pour l'affichage bbox."""

    termine = Signal(int, list)   # (bulle_id, list[PhraseAnalysee])
    erreur = Signal(str)

    def __init__(self, bulle_id: int, texte: str, parent=None):
        super().__init__(parent)
        self._bulle_id = bulle_id
        self._texte = texte
        self._client = anthropic.Anthropic()

    def run(self) -> None:
        user_content = (
            "Analyse ce texte espagnol (découpe en phrases si nécessaire):\n\n"
            f"{self._texte}"
        )
        print(f"[BBox Analyse B{self._bulle_id}] «{self._texte[:60]}»")

        try:
            t0 = time.time()
            message = self._client.messages.create(
                model=MODEL,
                max_tokens=4000,
                system=ANALYSE_SYSTEM_BLOCK,
                messages=[{"role": "user", "content": user_content}],
            )
            dt = time.time() - t0
            raw = message.content[0].text.strip()

            usage = message.usage
            print(f"[BBox Analyse B{self._bulle_id}] {dt:.1f}s, "
                  f"in={usage.input_tokens} out={usage.output_tokens}")

            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            data = json.loads(raw)
            data = _expand_response(data)
            phrases = from_api_response(data)

            if phrases:
                print(f"[BBox Analyse B{self._bulle_id}] OK: "
                      f"{len(phrases)} phrases, "
                      f"{sum(len(p.mots) for p in phrases)} mots")
                self.termine.emit(self._bulle_id, phrases)
            else:
                self.erreur.emit(f"Bulle {self._bulle_id}: aucun résultat")

        except json.JSONDecodeError as e:
            self.erreur.emit(f"JSON invalide (bulle {self._bulle_id}): {e}")
        except Exception as e:
            traceback.print_exc()
            self.erreur.emit(f"Erreur analyse bulle {self._bulle_id}: {e}")


# ─────────────────────────────────────────────────────────────────
# Orchestrateur
# ─────────────────────────────────────────────────────────────────

MAX_PARALLEL_BBOX = 3


class BBoxWorker(QObject):
    """Orchestre détection → OCR → analyse par bulle.

    Paddle par défaut (eps=0.03), fallback EasyOCR si Paddle échoue.
    Multi-phrases par bulle fusionnées en une PhraseAnalysee.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._detection_task: _DetectionTask | None = None
        self._image: np.ndarray | None = None
        self._image_hires: np.ndarray | None = None
        self._hires_scale: float = 1.0
        self._bulles: list[BulleDetectee] = []

        self._ocr_actives: dict[int, _BulleOcrTask] = {}
        self._ocr_queue: list[int] = []

        self._analyse_actives: dict[int, _BulleAnalyseTask] = {}
        self._analyse_queue: list[tuple[int, str]] = []

        from core.event_bus import bus
        bus().bbox_capture_demandee.connect(self._on_capture)

    @Slot(np.ndarray)
    def _on_capture(self, image: np.ndarray) -> None:
        from core.event_bus import bus
        self.reset()

        h, w = image.shape[:2]
        print(f"[BBox] Image reçue: {w}×{h}")

        # Stocker l'image native pour la détection ET l'affichage
        self._image = image
        # L'image upscalée sera stockée séparément pour les crops OCR
        self._image_hires: np.ndarray | None = None

        bus().status_message.emit("Détection des bulles (Paddle+DBSCAN)…")
        bus().chargement_en_cours.emit(True)

        # Détection sur l'image NATIVE (pas upscalée) — meilleures bbox
        self._detection_task = _DetectionTask(
            image, detector="paddle", eps=0.05,
            y_stretch=1.5, box_thresh=0.3, parent=self)
        self._detection_task.termine.connect(self._on_detection_ok)
        self._detection_task.erreur.connect(self._on_erreur)
        self._detection_task.start()

    def _on_detection_ok(self, image: np.ndarray, bulles: list) -> None:
        from core.event_bus import bus
        self._bulles = bulles
        # Émettre l'image native pour l'affichage dans la scène
        bus().bbox_detection_terminee.emit(image, bulles)

        if not bulles:
            bus().status_message.emit("Aucune bulle détectée")
            bus().chargement_en_cours.emit(False)
            return

        bus().status_message.emit(
            f"{len(bulles)} bulles → super-résolution RealSR…")

        # Upscale l'image complète pour avoir des crops haute-res
        upscaled = _realsr_upscale(self._image)
        if upscaled is not None:
            h2, w2 = upscaled.shape[:2]
            h1, w1 = self._image.shape[:2]
            self._hires_scale = w2 / w1
            self._image_hires = upscaled
            print(f"[BBox] RealSR: {w1}×{h1} → {w2}×{h2} (×{self._hires_scale:.1f})")
        else:
            self._hires_scale = 1.0
            self._image_hires = self._image
            print(f"[BBox] RealSR indisponible, crops natifs")

        bus().status_message.emit(
            f"{len(bulles)} bulles détectées → OCR en cours…")
        self._ocr_queue = [b.id for b in bulles]
        self._lancer_ocr_suivantes()

    # ─── OCR ─────────────────────────────────────────────────────

    def _lancer_ocr_suivantes(self) -> None:
        while (self._ocr_queue
               and len(self._ocr_actives) < MAX_PARALLEL_BBOX):
            bid = self._ocr_queue.pop(0)
            bulle = self._bulles[bid]
            bx, by, bw, bh = bulle.bbox_px

            # Crop depuis l'image haute-res (coordonnées scalées)
            s = self._hires_scale
            hx, hy = int(bx * s), int(by * s)
            hw, hh = int(bw * s), int(bh * s)
            crop = self._image_hires[hy:hy + hh, hx:hx + hw]

            task = _BulleOcrTask(bid, crop, parent=self)
            task.termine.connect(self._on_ocr_bulle_ok)
            task.erreur.connect(self._on_ocr_bulle_erreur)
            task.finished.connect(lambda b=bid: self._on_ocr_task_finie(b))
            self._ocr_actives[bid] = task
            task.start()

    def _on_ocr_bulle_ok(self, bulle_id: int, texte: str) -> None:
        from core.event_bus import bus
        self._bulles[bulle_id].texte_ocr = texte
        bus().bbox_ocr_terminee.emit(bulle_id, texte)

        if texte.strip():
            self._analyse_queue.append((bulle_id, texte))
            self._lancer_analyse_suivantes()

    def _on_ocr_bulle_erreur(self, bulle_id: int, msg: str) -> None:
        from core.event_bus import bus
        bus().status_message.emit(f"⚠ OCR bulle {bulle_id}: {msg}")

    def _on_ocr_task_finie(self, bulle_id: int) -> None:
        self._ocr_actives.pop(bulle_id, None)
        self._lancer_ocr_suivantes()
        if not self._ocr_actives and not self._ocr_queue:
            from core.event_bus import bus
            n_ok = sum(1 for b in self._bulles if b.texte_ocr)
            bus().status_message.emit(
                f"OCR terminé ({n_ok}/{len(self._bulles)}) → analyse…")

    # ─── Analyse ─────────────────────────────────────────────────

    def _lancer_analyse_suivantes(self) -> None:
        while (self._analyse_queue
               and len(self._analyse_actives) < MAX_PARALLEL_BBOX):
            bulle_id, texte = self._analyse_queue.pop(0)
            task = _BulleAnalyseTask(bulle_id, texte, parent=self)
            task.termine.connect(self._on_analyse_ok)
            task.erreur.connect(self._on_analyse_erreur)
            task.finished.connect(
                lambda b=bulle_id: self._on_analyse_task_finie(b))
            self._analyse_actives[bulle_id] = task
            task.start()

    def _on_analyse_ok(self, bulle_id: int, phrases: list) -> None:
        from core.event_bus import bus

        if not phrases:
            return

        # Fusionner toutes les phrases en une seule pour l'affichage bbox
        merged = phrases[0]
        for extra in phrases[1:]:
            merged.mots.extend(extra.mots)
            merged.expressions.extend(extra.expressions)
            if extra.traduction:
                merged.traduction = (
                    (merged.traduction or "") + " " + extra.traduction
                ).strip()

        self._bulles[bulle_id].phrase = merged
        bus().analyse_phrase_terminee.emit(bulle_id, merged)

    def _on_analyse_erreur(self, msg: str) -> None:
        from core.event_bus import bus
        bus().analyse_erreur.emit(msg)

    def _on_analyse_task_finie(self, bulle_id: int) -> None:
        self._analyse_actives.pop(bulle_id, None)
        self._lancer_analyse_suivantes()

        if (not self._analyse_actives and not self._analyse_queue
                and not self._ocr_actives and not self._ocr_queue):
            from core.event_bus import bus
            bus().chargement_en_cours.emit(False)
            bus().status_message.emit(
                f"Analyse terminée — {len(self._bulles)} bulles")

    # ─── Erreur / Reset ──────────────────────────────────────────

    def _on_erreur(self, msg: str) -> None:
        from core.event_bus import bus
        bus().chargement_en_cours.emit(False)
        bus().status_message.emit(f"⚠ {msg}")

    def reset(self) -> None:
        self._bulles = []
        self._ocr_queue.clear()
        self._analyse_queue.clear()
        self._image = None
        self._image_hires = None
        self._hires_scale = 1.0