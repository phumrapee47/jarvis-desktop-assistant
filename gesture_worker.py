"""โปรเซสแยกสำหรับกล้อง + MediaPipe (รันด้วย python ใน gesture_env) ส่งผลเป็น JSON ทีละบรรทัดทาง stdout

แยกโปรเซสเพื่อ: ไม่ให้ไลบรารีชนกับ Jarvis, ปิดกล้องได้แน่นอนเมื่อสั่งหยุด, และถ้าพังก็ไม่ลาก Jarvis ไปด้วย
ภาพจากกล้องไม่ถูกบันทึกหรือส่งออกที่ไหน ใช้ประมวลผลในหน่วยความจำแล้วทิ้ง
"""
import argparse, ctypes, json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gesture_logic import classify


def emit(obj):
    print(json.dumps(obj, separators=(",", ":")), flush=True)


def parent_alive(pid):
    h = ctypes.windll.kernel32.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
    if not h:
        return False
    alive = ctypes.windll.kernel32.WaitForSingleObject(h, 0) == 0x102  # WAIT_TIMEOUT = ยังรันอยู่
    ctypes.windll.kernel32.CloseHandle(h)
    return alive


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--parent-pid", type=int, required=True)
    ap.add_argument("--camera", type=int, default=0)
    a = ap.parse_args()
    try:
        import cv2
        import mediapipe as mp
        opts = mp.tasks.vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=a.model),
            running_mode=mp.tasks.vision.RunningMode.VIDEO, num_hands=1,
            min_hand_detection_confidence=0.6, min_hand_presence_confidence=0.5, min_tracking_confidence=0.5)
        det = mp.tasks.vision.HandLandmarker.create_from_options(opts)
        cap = cv2.VideoCapture(a.camera, cv2.CAP_DSHOW)
        cap.set(3, 640); cap.set(4, 480)
        if not cap.isOpened():
            emit({"error": "เปิดกล้องไม่ได้ (อาจมีแอปอื่นใช้อยู่ หรือยังไม่อนุญาตให้แอปเข้าถึงกล้อง)"})
            return
    except Exception as e:
        emit({"error": f"เริ่มระบบจับมือไม่ได้: {e}"})
        return
    emit({"status": "ready"})
    t0, last_hand, last_check = time.time(), 0.0, 0.0
    while True:
        now = time.time()
        if now - last_check > 1.0:  # ถ้า Jarvis หายไป (ถูกปิดกะทันหัน) ให้ปิดกล้องตัวเอง
            last_check = now
            if not parent_alive(a.parent_pid):
                break
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.05)
            continue
        frame = cv2.flip(frame, 1)  # กลับซ้ายขวาเหมือนกระจก ให้ "ขวาของผู้ใช้" = ขวาในภาพ
        img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        res = det.detect_for_video(img, int((now - t0) * 1000))
        if res.hand_landmarks:
            last_hand = now
            info = classify([(p.x, p.y) for p in res.hand_landmarks[0]])
            emit({"hand": True, "pose": info["pose"], "ratio": round(info["ratio"], 3), "others": info["others_ext"],
                  "tip": [round(info["tip"][0], 4), round(info["tip"][1], 4)],
                  "wrist": [round(info["wrist"][0], 4), round(info["wrist"][1], 4)],
                  "thumb": [round(info["thumb"][0], 4), round(info["thumb"][1], 4)],
                  "mcp": [round(info["mcp"][0], 4), round(info["mcp"][1], 4)],
                  "ir": round(info["ir"], 2), "mr": round(info["mr"], 2), "r2": round(info["r2"], 3)})
        else:
            emit({"hand": False})
        if now - last_hand > 3.0:  # ไม่มีมือสักพัก: ลดเหลือ ~8 เฟรม/วินาที ประหยัดแรงเครื่อง
            time.sleep(0.12)
    cap.release()


if __name__ == "__main__":
    try:
        main()
    except (BrokenPipeError, KeyboardInterrupt):
        pass
