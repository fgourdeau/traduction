"""Widget de capture — webcam/écran avec cadre de visée 8.5×11 déplaçable."""

import cv2
import numpy as np
from PySide6.QtCore import Qt, QTimer, QRect, QPoint, QRectF, Slot, QSize
from PySide6.QtGui import (
    QImage, QPixmap, QScreen, QPainter, QColor, QPen, QBrush, QFont,
    QMouseEvent, QPaintEvent, QResizeEvent,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QApplication,
)

from core.event_bus import bus
from core.config import COULEUR_ACCENT


# Ratio 8.5 x 11 (portrait) = 11/8.5 ≈ 1.294
RATIO_PAGE = 11.0 / 8.5


class PreviewWidget(QWidget):
    """Widget de preview avec overlay de cadrage 8.5×11.

    Le cadre est déplaçable (drag) et redimensionnable (coins + bords).
    La zone sombre autour du cadre indique ce qui sera ignoré.
    """

    POIGNEE = 12  # taille des zones de redimensionnement en pixels

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._frame_bgr: np.ndarray | None = None

        # Cadre de visée (en coordonnées widget)
        self._cadre = QRect(40, 20, 200, int(200 * RATIO_PAGE))
        self._cadre_initialise = False

        # Drag state
        self._drag_mode: str | None = None  # 'move', 'n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'
        self._drag_origin = QPoint()
        self._cadre_origin = QRect()

        self.setMinimumSize(200, 180)
        self.setMouseTracking(True)
        self.setStyleSheet("background: #1a1613;")

    def sizeHint(self) -> QSize:
        """Préférer un format qui laisse de la place au cadre portrait."""
        return QSize(400, 320)

    def set_frame(self, frame_bgr: np.ndarray) -> None:
        """Met à jour la frame affichée (BGR numpy)."""
        self._frame_bgr = frame_bgr
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        rgb = np.ascontiguousarray(rgb)
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        self._pixmap = QPixmap.fromImage(qimg)

        # Initialiser le cadre au centre au premier frame
        if not self._cadre_initialise:
            self._init_cadre()
            self._cadre_initialise = True

        self.update()

    def set_pixmap(self, pixmap: QPixmap, frame_bgr: np.ndarray) -> None:
        """Met à jour depuis un QPixmap + frame BGR."""
        self._pixmap = pixmap
        self._frame_bgr = frame_bgr
        if not self._cadre_initialise:
            self._init_cadre()
            self._cadre_initialise = True
        self.update()

    def _init_cadre(self) -> None:
        """Place le cadre centré, occupant le maximum d'espace en ratio 8.5×11."""
        ww, wh = self.width(), self.height()
        # Essayer de remplir 85% de la hauteur
        cadre_h = int(wh * 0.85)
        cadre_w = int(cadre_h / RATIO_PAGE)
        # Si trop large, contraindre par la largeur
        if cadre_w > ww * 0.90:
            cadre_w = int(ww * 0.90)
            cadre_h = int(cadre_w * RATIO_PAGE)
        # Centrer
        cx = (ww - cadre_w) // 2
        cy = (wh - cadre_h) // 2
        self._cadre = QRect(cx, cy, cadre_w, cadre_h)

    def extraire_zone(self) -> np.ndarray | None:
        """Retourne la portion de l'image source correspondant au cadre."""
        if self._frame_bgr is None or self._pixmap is None:
            return None

        fh, fw = self._frame_bgr.shape[:2]
        ww, wh = self.width(), self.height()

        # Calculer la zone d'affichage du pixmap (aspect ratio maintenu)
        pix_w, pix_h = self._pixmap.width(), self._pixmap.height()
        scale = min(ww / pix_w, wh / pix_h)
        disp_w = int(pix_w * scale)
        disp_h = int(pix_h * scale)
        disp_x = (ww - disp_w) // 2
        disp_y = (wh - disp_h) // 2

        # Convertir le cadre widget → coordonnées image source
        # cadre widget → cadre dans l'espace pixmap affiché → cadre image
        cx = max(0, self._cadre.x() - disp_x)
        cy = max(0, self._cadre.y() - disp_y)
        cw = self._cadre.width()
        ch = self._cadre.height()

        # Ratio widget display → image source
        rx = fw / disp_w if disp_w > 0 else 1
        ry = fh / disp_h if disp_h > 0 else 1

        src_x = int(cx * rx)
        src_y = int(cy * ry)
        src_w = int(cw * rx)
        src_h = int(ch * ry)

        # Clamp
        src_x = max(0, min(src_x, fw - 1))
        src_y = max(0, min(src_y, fh - 1))
        src_w = min(src_w, fw - src_x)
        src_h = min(src_h, fh - src_y)

        if src_w < 10 or src_h < 10:
            return None

        return self._frame_bgr[src_y:src_y + src_h, src_x:src_x + src_w].copy()

    # ─── Dessin ──────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        ww, wh = self.width(), self.height()

        if self._pixmap is not None:
            # Afficher le pixmap centré, aspect ratio maintenu
            scaled = self._pixmap.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            dx = (ww - scaled.width()) // 2
            dy = (wh - scaled.height()) // 2
            p.drawPixmap(dx, dy, scaled)

            # Assombrir HORS du cadre (4 rectangles)
            overlay = QColor(0, 0, 0, 140)
            c = self._cadre
            # Haut
            p.fillRect(0, 0, ww, c.top(), overlay)
            # Bas
            p.fillRect(0, c.bottom() + 1, ww, wh - c.bottom() - 1, overlay)
            # Gauche
            p.fillRect(0, c.top(), c.left(), c.height(), overlay)
            # Droite
            p.fillRect(c.right() + 1, c.top(), ww - c.right() - 1, c.height(), overlay)

            # Cadre
            pen = QPen(COULEUR_ACCENT, 2.0)
            p.setPen(pen)
            p.drawRect(c)

            # Coins (petits carrés)
            coin_sz = 8
            p.setBrush(QBrush(COULEUR_ACCENT))
            for corner in self._coins():
                p.drawRect(
                    corner.x() - coin_sz // 2,
                    corner.y() - coin_sz // 2,
                    coin_sz, coin_sz,
                )

            # Label : ratio + résolution effective du crop
            p.setPen(QPen(QColor(255, 255, 255, 220)))
            p.setFont(QFont("JetBrains Mono", 8))
            # Calculer la résolution réelle du crop
            res_label = "8.5 × 11"
            if self._frame_bgr is not None:
                fh, fw = self._frame_bgr.shape[:2]
                disp_w = scaled.width()
                disp_h = scaled.height()
                if disp_w > 0 and disp_h > 0:
                    rx = fw / disp_w
                    ry = fh / disp_h
                    crop_w = int(c.width() * rx)
                    crop_h = int(c.height() * ry)
                    res_label = f"{crop_w}×{crop_h} px"
                    # Indicateur vert/rouge selon résolution suffisante
                    if max(crop_w, crop_h) >= 1500:
                        p.setPen(QPen(QColor(80, 220, 80, 220)))
                    elif max(crop_w, crop_h) >= 800:
                        p.setPen(QPen(QColor(255, 200, 60, 220)))
                    else:
                        p.setPen(QPen(QColor(255, 80, 80, 220)))
            p.drawText(c.adjusted(6, 4, 0, 0), Qt.AlignLeft | Qt.AlignTop, res_label)

        else:
            # Pas de frame — texte d'accueil
            p.setPen(QPen(QColor("#9b9084")))
            p.setFont(QFont("IBM Plex Sans", 13))
            p.drawText(
                QRectF(0, 0, ww, wh), Qt.AlignCenter,
                "F5 : Webcam  •  F6 : Écran  •  Ctrl+O : Fichier",
            )

        p.end()

    def _coins(self) -> list[QPoint]:
        c = self._cadre
        return [
            c.topLeft(), c.topRight(),
            c.bottomLeft(), c.bottomRight(),
        ]

    # ─── Drag & Resize ───────────────────────────────────────────────

    def _zone_sous_curseur(self, pos: QPoint) -> str | None:
        """Détermine la zone de drag sous le curseur."""
        c = self._cadre
        h = self.POIGNEE

        in_h = c.top() - h <= pos.y() <= c.bottom() + h
        in_v = c.left() - h <= pos.x() <= c.right() + h

        if not (in_h and in_v):
            return None

        near_top = abs(pos.y() - c.top()) < h
        near_bot = abs(pos.y() - c.bottom()) < h
        near_left = abs(pos.x() - c.left()) < h
        near_right = abs(pos.x() - c.right()) < h

        if near_top and near_left:
            return "nw"
        if near_top and near_right:
            return "ne"
        if near_bot and near_left:
            return "sw"
        if near_bot and near_right:
            return "se"
        if near_top:
            return "n"
        if near_bot:
            return "s"
        if near_left:
            return "w"
        if near_right:
            return "e"

        # À l'intérieur du cadre → déplacement
        if c.contains(pos):
            return "move"

        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_mode = self._zone_sous_curseur(event.pos())
            self._drag_origin = event.pos()
            self._cadre_origin = QRect(self._cadre)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.pos()

        if self._drag_mode is None:
            # Juste mettre à jour le curseur
            zone = self._zone_sous_curseur(pos)
            curseurs = {
                "move": Qt.SizeAllCursor,
                "n": Qt.SizeVerCursor, "s": Qt.SizeVerCursor,
                "e": Qt.SizeHorCursor, "w": Qt.SizeHorCursor,
                "nw": Qt.SizeFDiagCursor, "se": Qt.SizeFDiagCursor,
                "ne": Qt.SizeBDiagCursor, "sw": Qt.SizeBDiagCursor,
            }
            self.setCursor(curseurs.get(zone, Qt.ArrowCursor))
            return

        dx = pos.x() - self._drag_origin.x()
        dy = pos.y() - self._drag_origin.y()
        co = self._cadre_origin
        ww, wh = self.width(), self.height()
        MIN_SZ = 60

        if self._drag_mode == "move":
            nx = max(0, min(co.x() + dx, ww - co.width()))
            ny = max(0, min(co.y() + dy, wh - co.height()))
            self._cadre.moveTopLeft(QPoint(nx, ny))

        else:
            # Resize en conservant le ratio 8.5x11
            new_rect = QRect(co)

            if "e" in self._drag_mode:
                new_w = max(MIN_SZ, co.width() + dx)
                new_h = int(new_w * RATIO_PAGE)
                new_rect.setWidth(new_w)
                new_rect.setHeight(new_h)
            elif "w" in self._drag_mode:
                new_w = max(MIN_SZ, co.width() - dx)
                new_h = int(new_w * RATIO_PAGE)
                new_rect.setLeft(co.right() - new_w)
                new_rect.setHeight(new_h)

            if "s" in self._drag_mode and "e" not in self._drag_mode and "w" not in self._drag_mode:
                new_h = max(MIN_SZ, co.height() + dy)
                new_w = int(new_h / RATIO_PAGE)
                new_rect.setWidth(new_w)
                new_rect.setHeight(new_h)
            elif "n" in self._drag_mode and "e" not in self._drag_mode and "w" not in self._drag_mode:
                new_h = max(MIN_SZ, co.height() - dy)
                new_w = int(new_h / RATIO_PAGE)
                new_rect.setTop(co.bottom() - new_h)
                new_rect.setWidth(new_w)

            # Clamp dans le widget
            if new_rect.left() >= 0 and new_rect.top() >= 0 and \
               new_rect.right() < ww and new_rect.bottom() < wh:
                self._cadre = new_rect

        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_mode = None
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._cadre_initialise:
            # Garder le cadre dans les limites
            c = self._cadre
            ww, wh = event.size().width(), event.size().height()
            if c.right() >= ww:
                c.moveRight(ww - 1)
            if c.bottom() >= wh:
                c.moveBottom(wh - 1)
            if c.left() < 0:
                c.moveLeft(0)
            if c.top() < 0:
                c.moveTop(0)


class CaptureWidget(QWidget):
    """Zone de capture : preview avec cadre 8.5×11 + boutons."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cap: cv2.VideoCapture | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_frame)

        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Preview (prend tout l'espace vertical)
        self._preview = PreviewWidget()
        layout.addWidget(self._preview, stretch=1)

        # Boutons empilés en 2×2 pour la colonne étroite
        btn_grid = QVBoxLayout()
        btn_grid.setSpacing(4)

        row1 = QHBoxLayout()
        row1.setSpacing(4)
        row2 = QHBoxLayout()
        row2.setSpacing(4)

        self._btn_webcam = QPushButton("📷 Webcam")
        self._btn_ecran = QPushButton("🖥 Écran")
        self._btn_coller = QPushButton("📋 Coller")
        self._btn_capturer = QPushButton("⏎ Capturer")
        self._btn_capturer.setEnabled(False)
        self._btn_stop = QPushButton("⏹ Stop")
        self._btn_stop.setEnabled(False)

        btn_style = f"""
            QPushButton {{
                background: #fffdf9;
                border: 1px solid #e0d6c8;
                border-radius: 6px;
                padding: 6px 8px;
                font-size: 12px;
                color: #1a1613;
            }}
            QPushButton:hover {{
                background: #fff3e0;
                border-color: {COULEUR_ACCENT.name()};
            }}
            QPushButton:pressed {{
                background: #ffe0c0;
            }}
            QPushButton:disabled {{
                color: #c4b5a2;
                background: #f0ebe5;
            }}
        """
        for btn in (self._btn_webcam, self._btn_ecran, self._btn_coller,
                    self._btn_capturer, self._btn_stop):
            btn.setFixedHeight(32)
            btn.setStyleSheet(btn_style)

        row1.addWidget(self._btn_webcam)
        row1.addWidget(self._btn_ecran)
        row1.addWidget(self._btn_coller)
        row2.addWidget(self._btn_capturer)
        row2.addWidget(self._btn_stop)

        btn_grid.addLayout(row1)
        btn_grid.addLayout(row2)
        layout.addLayout(btn_grid)

        self._btn_webcam.clicked.connect(self._demarrer_webcam)
        self._btn_ecran.clicked.connect(self._capturer_ecran)
        self._btn_coller.clicked.connect(self._coller_presse_papier)
        self._btn_capturer.clicked.connect(self._envoyer_capture)
        self._btn_stop.clicked.connect(self._arreter_webcam)

    def _connect_signals(self) -> None:
        bus().capture_webcam_demandee.connect(self._demarrer_webcam)
        bus().capture_ecran_demandee.connect(self._capturer_ecran)

    # ─── Webcam ──────────────────────────────────────────────────────

    @Slot()
    def _demarrer_webcam(self) -> None:
        if self._cap is not None:
            return
        self._cap = cv2.VideoCapture(0)
        if not self._cap.isOpened():
            bus().status_message.emit("Erreur : impossible d'ouvrir la webcam")
            self._cap = None
            return

        self._btn_capturer.setEnabled(True)
        self._btn_stop.setEnabled(True)
        self._btn_webcam.setEnabled(False)
        self._timer.start(33)
        bus().status_message.emit(
            "Webcam active — positionnez le cadre sur le texte, puis Capturer"
        )

    @Slot()
    def _arreter_webcam(self) -> None:
        self._timer.stop()
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._btn_capturer.setEnabled(False)
        self._btn_stop.setEnabled(False)
        self._btn_webcam.setEnabled(True)

    def _update_frame(self) -> None:
        if self._cap is None:
            return
        ret, frame = self._cap.read()
        if not ret:
            return
        self._preview.set_frame(frame)

    # ─── Capture écran ───────────────────────────────────────────────

    @Slot()
    def _capturer_ecran(self) -> None:
        screen: QScreen = QApplication.primaryScreen()
        if screen is None:
            bus().status_message.emit("Erreur : pas d'écran détecté")
            return

        pixmap = screen.grabWindow(0)
        qimg = pixmap.toImage().convertToFormat(QImage.Format_RGB888)

        w, h = qimg.width(), qimg.height()
        stride = qimg.bytesPerLine()
        raw_bytes = bytes(qimg.bits())
        arr = np.frombuffer(raw_bytes, dtype=np.uint8).reshape(h, stride)
        arr = arr[:, :w * 3].reshape(h, w, 3)
        frame = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

        self._preview.set_frame(frame)
        self._btn_capturer.setEnabled(True)
        bus().status_message.emit(
            "Capture écran — ajustez le cadre sur le texte, puis Capturer"
        )

    # ─── Presse-papier ──────────────────────────────────────────────

    @Slot()
    def _coller_presse_papier(self) -> None:
        """Colle le contenu du presse-papier : image → preview, texte → direct."""
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()

        if mime.hasImage():
            qimg = clipboard.image()
            if qimg.isNull():
                bus().status_message.emit("⚠ Image du presse-papier invalide")
                return
            qimg = qimg.convertToFormat(QImage.Format_RGB888)
            w, h = qimg.width(), qimg.height()
            stride = qimg.bytesPerLine()
            raw_bytes = bytes(qimg.bits())
            arr = np.frombuffer(raw_bytes, dtype=np.uint8).reshape(h, stride)
            arr = arr[:, :w * 3].reshape(h, w, 3)
            frame = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

            self._arreter_webcam()
            self._preview.set_frame(frame)
            self._btn_capturer.setEnabled(True)
            bus().status_message.emit(
                f"Image collée ({w}×{h}) — ajustez le cadre, puis Capturer"
            )
            print(f"[Coller] Image {w}×{h}")

        elif mime.hasText():
            texte = mime.text().strip()
            if not texte:
                bus().status_message.emit("⚠ Presse-papier vide")
                return
            self._arreter_webcam()
            bus().texte_colle.emit(texte)
            bus().status_message.emit(
                f"Texte collé ({len(texte)} chars) → affichage"
            )
            print(f"[Coller] Texte: {len(texte)} chars")

        else:
            bus().status_message.emit(
                "⚠ Presse-papier ne contient ni image ni texte"
            )

    # ─── Envoi ───────────────────────────────────────────────────────

    @Slot()
    def _envoyer_capture(self) -> None:
        zone = self._preview.extraire_zone()
        if zone is None:
            bus().status_message.emit("⚠ Impossible d'extraire la zone")
            return

        h, w = zone.shape[:2]
        print(f"[Capture] Zone extraite: {w}×{h} px")

        # Log aussi la frame source pour comparaison
        if self._preview._frame_bgr is not None:
            sh, sw = self._preview._frame_bgr.shape[:2]
            print(f"[Capture] Frame source: {sw}×{sh} px")

        self._arreter_webcam()
        bus().image_capturee.emit(zone)
        bus().status_message.emit(
            f"Zone capturée ({w}×{h} px) → analyse"
        )

    def closeEvent(self, event) -> None:
        self._arreter_webcam()
        super().closeEvent(event)