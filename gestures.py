"""ท่ามือควบคุมเครื่อง: เปิดกล้องผ่านโปรเซสแยก (gesture_worker) แล้วแปลท่าเป็นการกระทำ

ท่า (หลังแบมือค้าง 1 วินาทีเพื่อ "เปิดประตู"; ไม่มีมือ 5 วินาทีจะปิดเองกลับไปรอ):
  🤏 จีบโป้ง+ชี้ (นิ้วที่เหลือเหยียด)   จับหน้าต่างใต้ปลายนิ้วแล้วลาก ปล่อยนิ้ว = วาง
  👋 ปัดมือซ้าย/ขวา                      สลับหน้าต่าง (Alt+Tab / Alt+Shift+Tab)
  ✋ ปัดมือลง / ขึ้น                      ย่อหน้าต่างที่ใช้อยู่ / เปิด Task View
  👍 / 👎 ค้าง                           ยืนยัน / ยกเลิก งานที่ Jarvis รอ (เช่น ให้ Claude Code แก้ไฟล์)
  ✌️ ค้าง                                ให้ Jarvis ดูหน้าจอแล้วบอกว่ามีอะไรสำคัญ
  ✊ ค้าง                                 เล่น/หยุดเพลง

โหมดเมาส์ (เข้าด้วย ☝️ ชี้นิ้วเดียวค้าง 0.5 วินาที ออกด้วย ✋ แบมือค้าง 0.8 วินาที):
  ☝️ ชี้                                 เลื่อนเมาส์จริงตามปลายนิ้ว
  🤏 จีบโป้ง+ชี้                         กดเมาส์ซ้าย (แตะเร็ว = คลิก, จีบค้างแล้วขยับ = ลาก)
  🤏 จีบโป้ง+กลาง                        คลิกขวา
  ✌️ แล้วขยับมือขึ้น/ลง                  scroll
"""
import collections, ctypes, json, os, subprocess, sys, threading, time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.path.join(HERE, "gesture_env", "Scripts", "python.exe")
MODEL = os.path.join(HERE, "models", "hand_landmarker.task")
WORKER = os.path.join(HERE, "gesture_worker.py")

ARM_HOLD = 1.0        # แบมือค้างกี่วินาทีเพื่อเปิดโหมด
IDLE_TIMEOUT = 5.0    # ไม่มีมือกี่วินาทีถึงปิดโหมด
PINCH_ON, PINCH_OFF = 0.25, 0.40  # ratio เริ่มจับ / ปล่อย (hysteresis กันหลุด)
HOLD = {"thumbs_up": 0.6, "thumbs_down": 0.6, "peace": 0.7, "fist": 0.9}
COOLDOWN = 1.2
SMOOTH_WINDOW = 0.5   # วินาทีที่ใช้โหวตท่า
SWIPE_X, SWIPE_Y = 0.22, 0.20  # ระยะปัดขั้นต่ำ (สัดส่วนของภาพ) ผ่อนจากเดิม 0.30/0.25 หลังทดสอบกับมือจริง
MARGIN = 0.1          # ใช้กลางเฟรม 80% แมปเป็นทั้งจอ จะได้ไม่ต้องเอื้อมมือสุดขอบภาพ


MOUSE_ENTER = 0.5     # ชี้นิ้วเดียวค้างกี่วินาทีเพื่อเข้าโหมดเมาส์
MOUSE_EXIT = 0.8      # แบมือค้างกี่วินาทีเพื่อออกจากโหมดเมาส์
SCROLL_GAIN = 2400    # ขยับมือสุดความสูงภาพ ~ เลื่อน 20 ช่อง


def _lerp_map(v):
    return min(1.0, max(0.0, (v - MARGIN) / (1 - 2 * MARGIN)))


class OneEuro:
    """ตัวกรองให้เมาส์นิ่งตอนหยุดมือ แต่ไม่หน่วงตอนขยับเร็ว (One Euro filter) หน่วยเป็นสัดส่วนของจอ"""

    def __init__(self, min_cutoff=1.0, beta=6.0, dcutoff=1.0):
        self.mc, self.beta, self.dc = min_cutoff, beta, dcutoff
        self.x = self.dx = self.t = None

    @staticmethod
    def _alpha(cutoff, dt):
        return 1.0 / (1.0 + (1.0 / (2 * 3.141592653589793 * cutoff)) / dt)

    def __call__(self, x, t):
        if self.t is None:
            self.x, self.dx, self.t = x, 0.0, t
            return x
        dt = max(t - self.t, 1e-3)
        a_d = self._alpha(self.dc, dt)
        self.dx = a_d * ((x - self.x) / dt) + (1 - a_d) * self.dx
        a = self._alpha(self.mc + self.beta * abs(self.dx), dt)
        self.x, self.t = a * x + (1 - a) * self.x, t
        return self.x


class Controller:
    """ตัวตัดสินใจล้วนๆ (ไม่แตะกล้อง/Windows) รับ event ทีละอัน ส่ง action ผ่าน dict ที่ฉีดเข้ามา ทดสอบได้ด้วยเวลาจำลอง"""

    def __init__(self, actions, hud=None):
        self.a, self.hud = actions, hud if hud is not None else {}
        self.active = False
        self.palm_since = None
        self.last_hand = 0.0
        self.pose, self.pose_since, self.fired = None, 0.0, False
        self.cool = 0.0
        self.trail = collections.deque()  # (t, x, y) ข้อมือ ใช้จับการปัด
        self.grab = None                  # handle ของหน้าต่างที่กำลังลาก
        self.pinch_since = None
        self.sm = None                    # ตำแหน่งปลายนิ้วที่ทำให้เรียบแล้ว
        self._logged_pose = None
        self.win = collections.deque()    # (t, pose) ใช้ทำให้ท่าเรียบ
        self.stable = None                # ท่าที่เรียบแล้วล่าสุด
        # --- โหมดเมาส์ ---
        self.mouse, self.point_since, self.mouse_exit_since = False, None, None
        self.l_down = self.r_down = False
        self.lp_on = self.lp_off = self.rp_on = self.rp_off = 0   # ตัวนับเฟรมกันสั่นของจีบซ้าย/ขวา
        self.down_t, self.latch, self.ptr, self.prev_y = 0.0, None, (0.5, 0.5), None
        self.fx = self.fy = None
        self.v = (0.0, 0.0)

    def _set_hud(self, **kw):
        self.hud.update(kw)

    def feed(self, ev, now):
        if not ev.get("hand"):
            if self.grab is not None and now - self.last_hand > 0.5:
                self._release()
            if self.mouse and (self.l_down or self.r_down) and now - self.last_hand > 0.3:
                self._mouse_up_all()  # มือหายตอนกดค้าง: ปล่อยปุ่มทันที กันเมาส์ค้าง
            if self.active and now - self.last_hand > IDLE_TIMEOUT:
                self._deactivate()
            self.palm_since = None
            self.pose = None
            self.win.clear()
            self.stable = None
            self._set_hud(cursor=None)
            return
        self.last_hand = now
        # ท่ากะพริบระหว่างเฟรมได้ (เช่น fist<->thumbs_down, open<->other ตอนมือเบลอ): ตัดสินด้วยเสียงข้างมากใน 0.3 วินาทีล่าสุด
        self.win.append((now, ev["pose"]))
        while self.win and now - self.win[0][0] > SMOOTH_WINDOW:
            self.win.popleft()
        # 👍👎 ถ่วงน้ำหนัก 1.6 เท่า: นิ้วโป้งใกล้เส้นแบ่งกับ fist จะกะพริบสลับกัน ถ้าครึ่งหนึ่งเป็นท่านิ้วโป้งให้ถือว่าตั้งใจทำท่านั้น
        score = collections.Counter()
        for _, p in self.win:
            score[p] += 2.0 if p.startswith("thumbs") else 1.0
        top = score.most_common(1)[0][0]
        if len(self.win) < 3:
            pose = ev["pose"]
        elif self.stable in score and score[top] - score[self.stable] < 1.5:
            pose = self.stable  # กันสั่น: ท่าใหม่ต้องนำท่าปัจจุบันชัดเจนพอถึงจะเปลี่ยน
        else:
            pose = top
        self.stable = pose
        if pose != self._logged_pose:  # log เฉพาะตอนท่าเปลี่ยน ไว้ใช้ปรับความไวภายหลัง
            self._logged_pose = pose
            print(f"[gesture] pose={pose} ratio={ev.get('ratio')} others={ev.get('others')} active={self.active}")
        tx, ty = ev["tip"]
        sx, sy = _lerp_map(tx), _lerp_map(ty)
        self.sm = (sx, sy) if self.sm is None else (self.sm[0] * 0.5 + sx * 0.5, self.sm[1] * 0.5 + sy * 0.5)
        self._set_hud(cursor=self.sm, pose=pose, grab=self.grab is not None)

        if not self.active:  # ประตูปิด: รอแบมือค้าง
            if pose == "open":
                self.palm_since = self.palm_since or now
                if now - self.palm_since >= ARM_HOLD:
                    self.active, self.palm_since, self.cool = True, None, now + 1.0
                    self.trail.clear()
                    self._set_hud(mode="active")
                    self.a["toast"]("เปิดโหมดท่ามือแล้ว")
            else:
                self.palm_since = None
            return

        # ---- โหมดทำงาน ----
        if self.mouse:
            self._mouse_feed(ev, pose, now)
            return
        ratio, others = ev.get("ratio", 9), ev.get("others", 0)
        pinching = (ratio < PINCH_ON and others >= 2) or (self.grab is not None and ratio < PINCH_OFF and others >= 1)
        if self.grab is not None:
            if pinching:
                if not self.a["grab_move"](self.grab, *self.sm):
                    self.a["toast"]("ย้ายหน้าต่างนี้ไม่ได้ (อาจรันแบบ Administrator)")
                    self._release()
            else:
                self._release()
            return
        if pinching:
            self.pinch_since = self.pinch_since or now
            if now - self.pinch_since >= 0.15:
                self.grab = self.a["grab_start"](*self.sm)
                self.pinch_since = None
                if self.grab is None:
                    self.a["toast"]("ไม่มีหน้าต่างให้จับตรงนี้")
                    self.cool = now + 0.8
                else:
                    self._set_hud(grab=True)
            return
        self.pinch_since = None

        if pose == "point":  # ชี้นิ้วเดียวค้าง = เข้าโหมดเมาส์
            self.point_since = self.point_since or now
            if now - self.point_since >= MOUSE_ENTER and now >= self.cool:
                self._enter_mouse(ev, now)
                return
        else:
            self.point_since = None

        if now < self.cool:
            self.trail.clear()
            return
        # ท่านิ่งที่ต้องค้าง
        if pose != self.pose:
            self.pose, self.pose_since, self.fired = pose, now, False
        elif pose in HOLD and not self.fired and now - self.pose_since >= HOLD[pose]:
            self.fired, self.cool = True, now + COOLDOWN
            self._fire(pose)
            return
        # ปัดมือ: มือเปิดอยู่ (นิ้วกลาง/นาง/ก้อยเหยียด >= 2 ไม่สนว่าท่าจะกะพริบ open/other ตอนมือเบลอ) แล้วเคลื่อนเร็ว
        if others >= 2:
            wx, wy = ev["wrist"]
            self.trail.append((now, wx, wy))
            while self.trail and now - self.trail[0][0] > 0.5:
                self.trail.popleft()
            if len(self.trail) >= 4:
                t0, x0, y0 = self.trail[0]
                dx, dy, dt = wx - x0, wy - y0, max(now - t0, 1e-3)
                if abs(dx) > SWIPE_X and abs(dx) > 2 * abs(dy) and abs(dx) / dt > 0.8:
                    self._swipe("right" if dx > 0 else "left", dx, dy, dt)
                elif abs(dy) > SWIPE_Y and abs(dy) > 2 * abs(dx) and abs(dy) / dt > 0.7:
                    self._swipe("down" if dy > 0 else "up", dx, dy, dt)
        else:
            self.trail.clear()

    def _swipe(self, d, dx=0.0, dy=0.0, dt=0.0):
        print(f"[gesture] swipe {d} dx={dx:.2f} dy={dy:.2f} dt={dt:.2f}")
        self.trail.clear()
        self.cool = self.last_hand + 0.8  # ใช้เวลาของ event เอง (ทดสอบด้วยเวลาจำลองได้)
        {"right": lambda: self.a["alt_tab"](False), "left": lambda: self.a["alt_tab"](True),
         "down": self.a["minimize"], "up": self.a["task_view"]}[d]()

    def _fire(self, pose):
        {"thumbs_up": self.a["confirm_yes"], "thumbs_down": self.a["confirm_no"],
         "peace": self.a["look_screen"], "fist": self.a["play_pause"]}[pose]()

    def _release(self):
        if self.grab is not None:
            self.a["grab_end"](self.grab)
        self.grab, self.pinch_since = None, None
        if self.mouse:
            self._exit_mouse(None, 0.0)  # ปิดโหมด/หยุดกล้อง: ต้องปล่อยปุ่มเมาส์เสมอ
        self._set_hud(grab=False)

    # ---------- โหมดเมาส์ ----------
    def _enter_mouse(self, ev, now):
        self.mouse, self.point_since, self.mouse_exit_since = True, None, None
        self.latch, self.prev_y = None, None
        self.fx, self.fy = OneEuro(), OneEuro()
        tx, ty = ev["tip"]
        mx, my = ev.get("mcp", ev["tip"])
        self.v = (tx - mx, ty - my)  # เวกเตอร์ โคนนิ้ว -> ปลายนิ้ว ตอนกำลังชี้ ใช้คงที่ตลอดโหมดเมาส์
        self.ptr = (_lerp_map(tx), _lerp_map(ty))
        self._set_hud(mouse=True)
        self.a["toast"]("🖱 โหมดเมาส์: ชี้เพื่อเลื่อน จีบ=คลิก โป้ง+กลาง=คลิกขวา ✌️เลื่อนขึ้นลง=scroll แบมือค้าง=ออก")

    def _exit_mouse(self, msg, cool_for=1.0):
        self._mouse_up_all()
        self.mouse, self.latch = False, None
        self._set_hud(mouse=False)
        self.cool = self.last_hand + cool_for
        if msg:
            self.a["toast"](msg)

    def _mouse_up_all(self):
        if self.l_down:
            self.a["mouse_btn"]("left", False)
        if self.r_down:
            self.a["mouse_btn"]("right", False)
        self.l_down = self.r_down = False
        self.lp_on = self.lp_off = self.rp_on = self.rp_off = 0
        self._set_hud(grab=False)

    def _mouse_feed(self, ev, pose, now):
        a = self.a
        ratio, r2 = ev.get("ratio", 9), ev.get("r2", 9)
        ir, mr = ev.get("ir", 2.0), ev.get("mr", 2.0)
        tip, thumb = ev["tip"], ev.get("thumb", ev["tip"])
        self._set_hud(cursor=self.ptr)  # วงบนจอ = ตำแหน่งเมาส์จริง ไม่ใช่ปลายนิ้วดิบ
        # ออกจากโหมดเมาส์: แบมือค้าง (ท่าเดียวที่ไม่เกี่ยวกับการชี้/จีบ)
        if pose == "open" and not (self.l_down or self.r_down):
            self.mouse_exit_since = self.mouse_exit_since or now
            if now - self.mouse_exit_since >= MOUSE_EXIT:
                self._exit_mouse("กลับโหมดท่ามือ")
                return
        else:
            self.mouse_exit_since = None
        # ปุ่ม: จีบโป้ง+ชี้ = ซ้าย, โป้ง+กลาง = ขวา (ต้องนิ้วนั้นยื่นอยู่ กันกำมือถูกนับเป็นจีบ; มี hysteresis + กันสั่น 2 เฟรม)
        pinch_l = ratio < (0.42 if self.l_down else 0.28) and ir > (1.0 if self.l_down else 1.3)
        pinch_r = (not pinch_l) and r2 < (0.42 if self.r_down else 0.28) and mr > (1.0 if self.r_down else 1.3)
        for name, want, down_attr, on_attr, off_attr in (("left", pinch_l, "l_down", "lp_on", "lp_off"),
                                                          ("right", pinch_r, "r_down", "rp_on", "rp_off")):
            if not getattr(self, down_attr):
                setattr(self, on_attr, getattr(self, on_attr) + 1 if want else 0)
                if getattr(self, on_attr) >= 2:
                    setattr(self, down_attr, True); setattr(self, on_attr, 0); self.down_t = now
                    a["mouse_btn"](name, True)
            else:
                setattr(self, off_attr, getattr(self, off_attr) + 1 if not want else 0)
                if getattr(self, off_attr) >= 2 or now - self.down_t > 25:  # 25 วินาทีกันปุ่มค้าง
                    setattr(self, down_attr, False); setattr(self, off_attr, 0)
                    a["mouse_btn"](name, False)
        self._set_hud(grab=self.l_down or self.r_down)
        # scroll: ✌️ แล้วขยับมือขึ้น/ลง (เมาส์ไม่ขยับระหว่างนี้)
        if pose == "peace" and not (self.l_down or self.r_down):
            if self.prev_y is not None:
                wheel = int(-(tip[1] - self.prev_y) * SCROLL_GAIN)
                if abs(wheel) >= 20:
                    a["mouse_wheel"](wheel)
            self.prev_y = tip[1]
            return
        self.prev_y = None
        # ตำแหน่งเมาส์ = "โคนนิ้วชี้" (ข้อต่อที่ไม่ขยับตอนจีบ/งอนิ้ว) + เวกเตอร์ไปปลายนิ้วที่วัดไว้ตอนเข้าโหมด
        # เมาส์จึงไม่เลื่อนหนีตอนจีบคลิก และไม่ขยับตอนเปลี่ยนท่า (เช่น ☝️ -> ✌️ เพื่อ scroll)
        if ir <= 1.3 and not (self.l_down or self.r_down):
            return  # นิ้วชี้งออยู่ (ไม่ได้ชี้) ไม่ขยับเมาส์
        mcp = ev.get("mcp", tip)
        anchor = (mcp[0] + self.v[0], mcp[1] + self.v[1])
        raw = (_lerp_map(anchor[0]), _lerp_map(anchor[1]))
        x = min(1.0, max(0.0, self.fx(raw[0], now)))
        y = min(1.0, max(0.0, self.fy(raw[1], now)))
        self.ptr = (x, y)
        a["mouse_move"](x, y)
        self._set_hud(cursor=self.ptr)

    def _deactivate(self):
        self._release()
        self.active, self.palm_since = False, None
        self._set_hud(mode="armed", cursor=None)
        self.a["toast"]("ปิดโหมดท่ามือ (แบมือค้างเพื่อเริ่มใหม่)")


# ---------------- การกระทำจริงบน Windows ----------------
user32 = ctypes.WinDLL("user32", use_last_error=True)
# กำหนดชนิดให้ครบ: บน Windows 64 บิต HWND เป็น 64 บิต ถ้าไม่กำหนดจะถูกตัดเป็น 32 บิตแล้วเรียก API พังได้
user32.WindowFromPoint.argtypes, user32.WindowFromPoint.restype = [wintypes.POINT], wintypes.HWND
user32.GetAncestor.argtypes, user32.GetAncestor.restype = [wintypes.HWND, wintypes.UINT], wintypes.HWND
user32.IsWindowVisible.argtypes, user32.IsWindowVisible.restype = [wintypes.HWND], wintypes.BOOL
user32.IsZoomed.argtypes, user32.IsZoomed.restype = [wintypes.HWND], wintypes.BOOL
user32.ShowWindow.argtypes, user32.ShowWindow.restype = [wintypes.HWND, ctypes.c_int], wintypes.BOOL
user32.GetClassNameW.argtypes, user32.GetClassNameW.restype = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int
user32.GetWindowTextW.argtypes, user32.GetWindowTextW.restype = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowRect.argtypes, user32.GetWindowRect.restype = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL
user32.GetForegroundWindow.argtypes, user32.GetForegroundWindow.restype = [], wintypes.HWND
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
user32.GetSystemMetrics.argtypes, user32.GetSystemMetrics.restype = [ctypes.c_int], ctypes.c_int
user32.SetCursorPos.argtypes, user32.SetCursorPos.restype = [ctypes.c_int, ctypes.c_int], wintypes.BOOL
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
SW_RESTORE, SW_MINIMIZE = 9, 6
SWP_NOSIZE, SWP_NOACTIVATE = 0x1, 0x10
_SKIP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}


def _screen():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def _cls(hwnd):
    b = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, b, 256)
    return b.value


def _movable(hwnd):
    if not hwnd or not user32.IsWindowVisible(hwnd) or _cls(hwnd) in _SKIP_CLASSES:
        return False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value != os.getpid()


def _key(*vks):
    for vk in vks:
        user32.keybd_event(vk, 0, 0, 0)
    for vk in reversed(vks):
        user32.keybd_event(vk, 0, 2, 0)


class Actions:
    def __init__(self, hud, notify_put, ask_fn, media_fn, confirm_fn):
        self.hud, self.notify_put, self.ask_fn, self.media_fn, self.confirm_fn = hud, notify_put, ask_fn, media_fn, confirm_fn

    def dict(self):
        return {"toast": self.toast, "grab_start": self.grab_start, "grab_move": self.grab_move, "grab_end": lambda h: None,
                "mouse_move": self.mouse_move, "mouse_btn": self.mouse_btn, "mouse_wheel": self.mouse_wheel,
                "alt_tab": self.alt_tab, "minimize": self.minimize, "task_view": lambda: _key(0x5B, 0x09),
                "confirm_yes": lambda: self._confirm("ยืนยัน"), "confirm_no": lambda: self._confirm("ยกเลิก"),
                "look_screen": self.look_screen, "play_pause": self.play_pause}

    def toast(self, text):
        print("[gesture] action:", text)
        self.hud["toast"] = (text, time.time() + 2.5)

    def grab_start(self, nx, ny):
        w, h = _screen()
        x, y = int(nx * w), int(ny * h)
        root = user32.GetAncestor(user32.WindowFromPoint(wintypes.POINT(x, y)), 2)
        if not _movable(root):
            return None
        zoomed = bool(user32.IsZoomed(root))
        if zoomed:
            user32.ShowWindow(root, SW_RESTORE)  # ลากหน้าต่างที่ขยายเต็มจอ = คืนขนาดก่อน (เหมือนลากแถบชื่อปกติ)
        r = wintypes.RECT()
        user32.GetWindowRect(root, ctypes.byref(r))
        w_, h_ = r.right - r.left, r.bottom - r.top
        if zoomed:  # ขนาดเปลี่ยนแล้ว: ให้นิ้วอยู่แถบชื่อ กึ่งกลางความกว้าง
            off = (w_ // 2, min(20, h_ // 2))
        else:  # หน้าต่างปกติ: คงตำแหน่งที่จับไว้ตามจริง ไม่ให้กระโดด
            off = (min(max(x - r.left, 0), w_), min(max(y - r.top, 0), h_))
        user32.SetWindowPos(root, 0, r.left, r.top, 0, 0, SWP_NOSIZE)  # ยกขึ้นบนสุด
        b = ctypes.create_unicode_buffer(80)
        user32.GetWindowTextW(root, b, 80)
        print(f"[gesture] grab: {_cls(root)!r} {b.value[:40]!r} zoomed={zoomed}")
        return (root, off)

    def grab_move(self, handle, nx, ny):
        root, (ox, oy) = handle
        w, h = _screen()
        return bool(user32.SetWindowPos(root, 0, int(nx * w) - ox, int(ny * h) - oy, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE))

    # --- เมาส์จริง (โหมดเมาส์เท่านั้น) ---
    def mouse_move(self, nx, ny):
        w, h = _screen()
        user32.SetCursorPos(min(max(int(nx * w), 0), w - 1), min(max(int(ny * h), 0), h - 1))

    def mouse_btn(self, which, down):
        flag = {("left", True): 0x2, ("left", False): 0x4, ("right", True): 0x8, ("right", False): 0x10}[(which, down)]
        print(f"[gesture] mouse {which} {'down' if down else 'up'}")
        user32.mouse_event(flag, 0, 0, 0, 0)

    def mouse_wheel(self, delta):
        user32.mouse_event(0x800, 0, 0, ctypes.c_uint32(delta & 0xFFFFFFFF).value, 0)

    def alt_tab(self, reverse):
        _key(0x12, 0x10, 0x09) if reverse else _key(0x12, 0x09)

    def minimize(self):
        hwnd = user32.GetForegroundWindow()
        if _movable(hwnd):
            user32.ShowWindow(hwnd, SW_MINIMIZE)
        else:
            self.toast("ไม่มีหน้าต่างให้ย่อ")

    def _confirm(self, word):
        msg = self.confirm_fn(word)
        if msg is None:
            self.toast("ไม่มีอะไรรอยืนยัน")
        else:
            self.toast("👍 ยืนยัน" if word == "ยืนยัน" else "👎 ยกเลิก")
            self.notify_put(msg)

    def look_screen(self):
        self.toast("✌️ ให้ Jarvis ดูหน้าจอ")
        self.notify_put(lambda: self.ask_fn("[ท่ามือ ✌️] ดูหน้าจอให้หน่อย แล้วบอกสั้นๆ ว่ามีอะไรสำคัญหรือ error อะไรไหม"))

    def play_pause(self):
        self.toast("✊ เล่น/หยุดเพลง")
        self.media_fn("play_pause")


# ---------------- ตัวจัดการโปรเซสกล้อง ----------------
class GestureService:
    def __init__(self, actions_obj, hud):
        self.hud = hud
        self.ctrl = Controller(actions_obj.dict(), hud)
        self.proc = None
        self.enabled = False
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self.enabled:
                return "โหมดท่ามือเปิดอยู่แล้ว"
            if not os.path.exists(VENV_PY):
                return "ยังไม่ได้ติดตั้งสภาพแวดล้อมท่ามือ (gesture_env)"
            if not os.path.exists(MODEL):
                return "ยังไม่มีไฟล์โมเดลจับมือ (models/hand_landmarker.task)"
            self.proc = subprocess.Popen([VENV_PY, WORKER, "--model", MODEL, "--parent-pid", str(os.getpid())],
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                         creationflags=0x08000000)
            self.enabled = True
            self.ctrl = Controller(self.ctrl.a, self.hud)
            self.hud.update(mode="armed", cursor=None, grab=False)
            threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()
        return "เปิดโหมดท่ามือแล้ว กล้องกำลังทำงาน แบมือค้าง 1 วินาทีเพื่อเริ่มใช้งาน"

    def stop(self):
        with self._lock:
            if not self.enabled:
                return "โหมดท่ามือปิดอยู่แล้ว"
            self.enabled = False
            try:
                self.ctrl._release()
            except Exception:
                pass
            if self.proc:
                self.proc.terminate()
                self.proc = None
            self.hud.update(mode="off", cursor=None, grab=False)
        return "ปิดโหมดท่ามือแล้ว กล้องปิดแล้ว"

    def _reader(self, proc):
        for line in proc.stdout:
            if proc is not self.proc:
                return
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if "error" in ev:
                self.hud["toast"] = (ev["error"], time.time() + 6)
                print("gesture error:", ev["error"])
                self.stop()
                return
            if ev.get("hand") is not None:
                try:
                    self.ctrl.feed(ev, time.time())
                except Exception as e:
                    print("gesture feed error:", e)
        if self.enabled and proc is self.proc:  # โปรเซสตายเอง
            self.stop()


# ---------------- HUD: วงกลมตามปลายนิ้ว + ข้อความสถานะ (เต็มจอ โปร่งใส คลิกทะลุ) ----------------
def make_hud_widget(hud):
    from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
    from PyQt6.QtGui import QColor, QFont, QPainter, QPen
    from PyQt6.QtWidgets import QApplication, QWidget

    class HandHUD(QWidget):
        def __init__(self):
            super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                             Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput |
                             Qt.WindowType.WindowDoesNotAcceptFocus)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.setGeometry(QApplication.primaryScreen().geometry())
            self.t = QTimer(self)
            self.t.timeout.connect(self._tick)
            self.t.start(33)

        def _tick(self):
            on = hud.get("mode", "off") != "off" or time.time() < hud.get("toast", ("", 0))[1]
            if on and not self.isVisible():
                self.show()
            elif not on and self.isVisible():
                self.hide()
            if on:
                self.update()

        def paintEvent(self, _):
            p = QPainter(self)
            p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
            W, H = self.width(), self.height()
            mode, cur, grab = hud.get("mode"), hud.get("cursor"), hud.get("grab")
            if mode == "active" and cur:
                c = QColor("#69f0ae" if grab else ("#ffb300" if hud.get("mouse") else "#00e5ff"))  # เมาส์ = ส้ม, กดอยู่ = เขียว
                pos = QPointF(cur[0] * W, cur[1] * H)
                p.setPen(QPen(c, 3)); p.setBrush(QColor(c.red(), c.green(), c.blue(), 90 if grab else 25))
                r = 16 if grab else 26
                p.drawEllipse(pos, r, r)
                p.setPen(c); p.setFont(QFont("Segoe UI", 10))
                p.drawText(QRectF(pos.x() + 30, pos.y() - 12, 220, 24), Qt.AlignmentFlag.AlignLeft, "จับอยู่" if grab else "")
            text, until = hud.get("toast", ("", 0))
            if time.time() >= until:
                text = {"armed": "🖐 โหมดท่ามือ: แบมือค้าง 1 วินาทีเพื่อเริ่ม", "active": ""}.get(mode, "")
            if text:
                p.setFont(QFont("Segoe UI", 13))
                w = p.fontMetrics().horizontalAdvance(text) + 40
                box = QRectF((W - w) / 2, 28, w, 40)
                p.setPen(QPen(QColor(0, 229, 255, 150), 1.2)); p.setBrush(QColor(10, 14, 20, 215))
                p.drawRoundedRect(box, 20, 20)
                p.setPen(QColor("white")); p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
            p.end()

    return HandHUD()


_service = None


def setup(notify_put, ask_fn, media_fn, confirm_fn):
    global _service
    hud = {"mode": "off", "cursor": None, "grab": False, "pose": None, "toast": ("", 0)}
    _service = GestureService(Actions(hud, notify_put, ask_fn, media_fn, confirm_fn), hud)
    return _service


def set_gesture_mode(enabled=True):
    return _service.start() if enabled else _service.stop()


TOOLS = [{"name": "set_gesture_mode",
          "description": "เปิด/ปิดโหมดท่ามือ (เปิดกล้องเว็บแคมจับมือเพื่อควบคุมหน้าต่าง/ยืนยัน/ดูจอ) ใช้เมื่อผู้ใช้สั่งเปิดหรือปิดท่ามือ "
                         "เปิดกล้องจริงๆ ให้บอกผู้ใช้ว่ากล้องกำลังทำงาน",
          "input_schema": {"type": "object", "properties": {"enabled": {"type": "boolean"}}, "required": ["enabled"]}}]
HANDLERS = {"set_gesture_mode": set_gesture_mode}


def run(name, args):
    try:
        return str(HANDLERS[name](**args))
    except Exception as e:
        return f"ทำไม่สำเร็จ: {e}"
