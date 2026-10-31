"""Jarvis 3D orb overlay: PyQt6 (โปร่งใสจริง) + numpy shader. set_state() เรียกได้จากทุก thread."""
import math, sys, time

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QImage, QPainter, QPen, QPolygonF, QRadialGradient
from PyQt6.QtWidgets import QApplication, QWidget

ACCENT = {"listening": (0.0, 0.85, 1.0), "thinking": (1.0, 0.62, 0.12), "speaking": (0.35, 1.0, 0.65)}
LABELS = {"listening": "กำลังฟัง...", "thinking": "กำลังคิด...", "speaking": ""}
SPIN = {"listening": 0.5, "thinking": 1.7, "speaking": 0.9}
W, H = 800, 420
ORB = 380          # ขนาดภาพ orb บนจอ (px)
BUBBLE_W = 380     # ความกว้างกล่องข้อความ
CX, CY = W - ORB / 2, H - ORB / 2  # ศูนย์กลาง orb (ชิดมุมขวาล่างของหน้าต่าง)
N = 300            # ความละเอียดที่คำนวณ
R = 0.45           # รัศมี orb (หน่วย: ครึ่งหนึ่งของภาพ)

_g = np.linspace(-1, 1, N, dtype=np.float32)
X, Y = np.meshgrid(_g, _g)
RAD = np.sqrt(X * X + Y * Y)
TH = np.arctan2(Y, X)
_L = np.array([-0.45, -0.55, 0.7], np.float32); _L /= np.linalg.norm(_L)
_Hh = _L + np.array([0, 0, 1], np.float32); _Hh /= np.linalg.norm(_Hh)
_rng = np.random.default_rng(7)
_pt = _rng.normal(size=(70, 3)); _pt /= np.linalg.norm(_pt, axis=1, keepdims=True)
PARTS = _pt * _rng.uniform(0.62, 1.0, (70, 1))

_app = None


def _qapp():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)
    return _app


def _rot_y(p, a):
    c, s = math.cos(a), math.sin(a)
    return np.stack([p[..., 0] * c + p[..., 2] * s, p[..., 1], -p[..., 0] * s + p[..., 2] * c], -1)


class Overlay(QWidget):
    def __init__(self):
        _qapp()
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput |
                         Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.resize(W, H)
        geo = QApplication.primaryScreen().availableGeometry()
        self.move(geo.x() + geo.width() - W - 8, geo.y() + geo.height() - H - 8)  # มุมขวาล่าง
        self.st, self.cur, self.text = None, "listening", ""
        self.fade, self.amp, self.t = 0.0, 0.03, 0.0
        self.col = np.array(ACCENT["listening"], np.float32)
        self.t0 = time.time()
        self._buf = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_state(self, state, text=None):
        """state: listening | thinking | speaking | None(ซ่อน)"""
        if text is not None:
            self.text = text
        self.st = state

    def run(self):
        _app.exec()

    def _tick(self):
        self.t = time.time() - self.t0
        self.fade += ((1.0 if self.st else 0.0) - self.fade) * 0.16
        if self.st:
            self.cur = self.st
            if not self.isVisible():
                self.show()
        elif self.fade < 0.02:
            if self.isVisible():
                self.hide()
            return
        self.col += (np.array(ACCENT[self.cur], np.float32) - self.col) * 0.12
        if self.cur == "speaking":  # เต้นเหมือนคลื่นเสียง
            target = 0.05 + 0.045 * abs(math.sin(self.t * 7.3) * math.sin(self.t * 2.1 + 1))
        else:
            target = 0.025 if self.cur == "listening" else 0.035
        self.amp += (target - self.amp) * 0.25
        self.update()

    # ---------- shader ----------
    def _shade(self, t):
        acc, amp = self.col, self.amp
        Rr = R * (1 + amp * (np.sin(3 * TH + 1.7 * t) + 0.6 * np.sin(5 * TH - 2.3 * t)))
        cov = np.clip((Rr - RAD) / 0.012 + 0.5, 0, 1)
        z = np.sqrt(1 - np.minimum(RAD / Rr, 1) ** 2)
        nx, ny = X / Rr, Y / Rr
        a = t * SPIN[self.cur]
        ca, sa = math.cos(a), math.sin(a)
        nxr, nzr = nx * ca + z * sa, -nx * sa + z * ca
        p = (np.sin(3.1 * nxr + t) + np.sin(3.7 * ny - 0.8 * t) + np.sin(4.3 * nzr + 0.6 * t)
             + 0.5 * np.sin(7 * (nxr + ny + nzr) + 1.5 * t)) / 3.5
        p = (0.5 + 0.5 * p) ** 1.6
        dark = acc * 0.08
        base = dark + (acc * 0.95 - dark) * p[..., None]
        diff = np.clip(nx * _L[0] + ny * _L[1] + z * _L[2], 0, 1)
        spec = np.clip(nx * _Hh[0] + ny * _Hh[1] + z * _Hh[2], 0, 1) ** 48
        fres = (1 - z) ** 2.5
        rgb = (base * (0.28 + 0.9 * diff)[..., None] + (spec * 0.95)[..., None]
               + (fres * 1.1)[..., None] * acc + ((z ** 3) * 0.22)[..., None] * acc)
        rgb = np.clip(rgb, 0, 1)
        glow = np.where(RAD > Rr, np.exp(-np.maximum(RAD - Rr, 0) / 0.11), 0) * (0.5 + amp * 3)
        alpha = np.clip(cov + glow * (1 - cov), 0, 1)
        c = np.minimum(rgb * cov[..., None] + acc * glow[..., None], alpha[..., None])  # กัน uint8 ล้น
        out = np.empty((N, N, 4), np.uint8)
        k = 255 * self.fade
        out[..., 0], out[..., 1], out[..., 2] = c[..., 2] * k, c[..., 1] * k, c[..., 0] * k
        out[..., 3] = alpha * k
        self._buf = out
        return QImage(out.data, N, N, N * 4, QImage.Format.Format_ARGB32_Premultiplied)

    # ---------- วงแหวน/อนุภาค ----------
    def _items(self, p, t, front):
        S, cx, cy = ORB / 2, CX, CY
        acc = QColor.fromRgbF(*[float(v) for v in self.col])
        sp = SPIN[self.cur]
        phi = np.linspace(0, 2 * math.pi, 121)
        for rr, tilt, speed in ((0.70, 1.15, 0.5), (0.84, -0.65, -0.35)):
            pts = np.stack([np.cos(phi), np.zeros_like(phi), np.sin(phi)], -1) * rr
            ct, st = math.cos(tilt), math.sin(tilt)
            pts = np.stack([pts[:, 0], pts[:, 1] * ct - pts[:, 2] * st, pts[:, 1] * st + pts[:, 2] * ct], -1)
            pts = _rot_y(pts, t * speed * (0.5 + sp))
            head = (t * (1.2 + sp)) % (2 * math.pi)
            for i in range(len(phi) - 1):
                zm = (pts[i, 2] + pts[i + 1, 2]) / 2
                if (zm >= 0) != front:
                    continue
                w = ((phi[i] - head) % (2 * math.pi)) / (2 * math.pi)
                al = (0.10 + 0.9 * (1 - w) ** 3) * (0.45 + 0.55 * (zm / rr + 1) / 2) * self.fade
                col = QColor(acc); col.setAlphaF(min(1.0, al))
                pen = QPen(col, 2.2 if front else 1.2); pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                f1, f2 = 1 + 0.12 * pts[i, 2], 1 + 0.12 * pts[i + 1, 2]
                p.drawLine(QPointF(cx + pts[i, 0] * S * f1, cy + pts[i, 1] * S * f1),
                           QPointF(cx + pts[i + 1, 0] * S * f2, cy + pts[i + 1, 1] * S * f2))
        q = _rot_y(PARTS, t * 0.22 * (0.6 + sp))
        q[:, 1] += 0.03 * np.sin(t * 1.5 + np.arange(len(q)))
        p.setPen(Qt.PenStyle.NoPen)
        for x, y, z in q:
            if (z >= 0) != front:
                continue
            col = QColor(acc.lighter(130)); col.setAlphaF(min(1.0, (0.25 + 0.6 * (z + 1) / 2) * self.fade))
            p.setBrush(col)
            s = 1.1 + 1.7 * (z + 1) / 2
            p.drawEllipse(QPointF(cx + x * S, cy + y * S), s, s)

    def paintEvent(self, _):
        t, S, cx, cy = self.t, ORB / 2, CX, CY
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform |
                         QPainter.RenderHint.TextAntialiasing)
        acc = QColor.fromRgbF(*[float(v) for v in self.col])
        # เงาบนพื้น
        p.save()
        p.translate(cx, cy + R * S + 32)
        p.scale(1, 0.18)
        g = QRadialGradient(QPointF(0, 0), 140)
        c0 = QColor(acc); c0.setAlphaF(0.55 * self.fade); c1 = QColor(acc); c1.setAlphaF(0)
        g.setColorAt(0, c0); g.setColorAt(1, c1)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(0, 0), 140, 140)
        p.restore()
        self._items(p, t, front=False)
        p.drawImage(QRectF(cx - S, cy - S, ORB, ORB), self._shade(t))
        self._items(p, t, front=True)
        self._bubble(p, acc, cx, cy)
        p.end()

    def _bubble(self, p, acc, cx, cy):
        """กล่องข้อความอยู่ซ้ายของ orb ขอบล่างตรึงไว้ ยาวขึ้นไปด้านบนตามความยาวข้อความ"""
        f = self.fade
        title = QFont("Consolas", 10, QFont.Weight.Bold)
        title.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4)
        body = QFont("Segoe UI", 13)
        txt = self.text or LABELS[self.cur]
        pad, bw = 16, BUBBLE_W
        flags = Qt.TextFlag.TextWordWrap.value | Qt.AlignmentFlag.AlignLeft.value | Qt.AlignmentFlag.AlignTop.value
        th = QFontMetricsF(body).boundingRect(QRectF(0, 0, bw - 2 * pad, 2000), flags, txt).height()
        bh = min(pad * 2 + 24 + th, H - 20)
        right, bottom = cx - ORB * 0.32, cy + 55
        box = QRectF(right - bw, bottom - bh, bw, bh)
        fill = QColor(10, 14, 20); fill.setAlphaF(0.82 * f)
        edge = QColor(acc); edge.setAlphaF(0.55 * f)
        p.setBrush(fill); p.setPen(QPen(edge, 1.4))
        p.drawRoundedRect(box, 16, 16)
        tail = QPolygonF([QPointF(right - 1, bottom - 34), QPointF(right + 14, bottom - 22), QPointF(right - 1, bottom - 12)])
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(fill)
        p.drawPolygon(tail)
        c = QColor(acc.lighter(150)); c.setAlphaF(f)
        p.setPen(c); p.setFont(title)
        p.drawText(QRectF(box.x() + pad, box.y() + pad - 2, bw - 2 * pad, 20), Qt.AlignmentFlag.AlignLeft, "J.A.R.V.I.S")
        c = QColor(255, 255, 255); c.setAlphaF(f)
        p.setPen(c); p.setFont(body)
        p.drawText(QRectF(box.x() + pad, box.y() + pad + 22, bw - 2 * pad, bh - 2 * pad - 22), flags, txt)


if __name__ == "__main__":  # ทดสอบ: python overlay.py
    o = Overlay()
    seq = [("listening", ""), ("thinking", "วันนี้มีเมลอะไรบ้าง"), ("speaking", "วันนี้มีเมลที่ยังไม่อ่าน 10 ฉบับครับ ส่วนใหญ่เป็นแจ้งเตือนจาก GitHub และ Claude "
                                  "ที่น่าสนใจคือมีเมลชำระเงินจากธนาคารกสิกรไทย 1 ฉบับ"), (None, "")]
    for i, s in enumerate(seq):
        QTimer.singleShot(i * 3000 + 100, lambda s=s: o.set_state(*s))
    QTimer.singleShot(len(seq) * 3000 + 500, _app.quit)
    o.run()
