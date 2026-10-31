"""จัดประเภทท่ามือจากจุด landmark 21 จุดของ MediaPipe (พิกัด normalized, y ชี้ลง) ใช้ Python ล้วน ทดสอบได้โดยไม่ต้องมีกล้อง

ดัชนีจุด: 0 ข้อมือ | นิ้วโป้ง 1-4 | ชี้ 5-8 | กลาง 9-12 | นาง 13-16 | ก้อย 17-20 (ปลายนิ้ว = 4, 8, 12, 16, 20)
"""
import math

WRIST, THUMB_MCP, THUMB_IP, THUMB_TIP = 0, 2, 3, 4
FINGERS = {"index": (6, 8), "middle": (10, 12), "ring": (14, 16), "pinky": (18, 20)}  # (PIP, TIP)


def _d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def classify(lm):
    """lm: รายการ (x, y) 21 จุด -> dict(pose, ratio, others_ext, tip, wrist, size)

    pose: open | fist | peace | thumbs_up | thumbs_down | point | other
    ratio: ระยะปลายโป้ง-ปลายชี้ หารขนาดมือ (ยิ่งน้อยยิ่งจีบแน่น)
    others_ext: จำนวนนิ้วกลาง/นาง/ก้อยที่เหยียด (ใช้แยกท่าจีบจริงจากกำมือ)
    """
    wrist = lm[WRIST]
    size = max(_d(wrist, lm[9]), 1e-6)  # ข้อมือ -> โคนนิ้วกลาง
    ext = {n: _d(lm[t], wrist) > _d(lm[p], wrist) * 1.05 for n, (p, t) in FINGERS.items()}
    n_ext = sum(ext.values())
    thumb_ext = _d(lm[THUMB_TIP], lm[17]) > _d(lm[THUMB_IP], lm[17]) * 1.1
    thumb_dy = (lm[THUMB_MCP][1] - lm[THUMB_TIP][1]) / size  # บวก = ปลายโป้งอยู่สูงกว่าโคนโป้ง
    if n_ext == 0 and thumb_ext and thumb_dy > 0.6:
        pose = "thumbs_up"
    elif n_ext == 0 and thumb_ext and thumb_dy < -0.6:
        pose = "thumbs_down"
    elif n_ext == 0:
        pose = "fist"
    elif n_ext == 4:
        pose = "open"
    elif ext["index"] and ext["middle"] and not ext["ring"] and not ext["pinky"]:
        pose = "peace"
    elif ext["index"] and n_ext == 1:
        pose = "point"
    else:
        pose = "other"
    return {"pose": pose, "ratio": _d(lm[THUMB_TIP], lm[8]) / size,
            "others_ext": sum(ext[n] for n in ("middle", "ring", "pinky")),
            "tip": lm[8], "wrist": wrist, "size": size,
            # สำหรับโหมดเมาส์: ปลายโป้ง, ระยะที่ปลายชี้/กลางยื่นจากข้อมือ (เหยียด ~1.9 งอ <1.0), จีบโป้ง-กลาง (คลิกขวา)
            "thumb": lm[THUMB_TIP], "mcp": lm[5], "ir": _d(lm[8], wrist) / size, "mr": _d(lm[12], wrist) / size,
            "r2": _d(lm[THUMB_TIP], lm[12]) / size}
