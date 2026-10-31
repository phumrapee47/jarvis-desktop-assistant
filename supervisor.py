"""รัน Jarvis และเปิดใหม่ให้เองถ้าโปรแกรมล้ม/ค้างแล้วถูกปิด
ถ้าปิดเองจากเมนูถาดระบบ "ออก" (Jarvis จะสร้าง quit.flag) จะไม่เปิดใหม่ ล้มซ้ำเกิน 6 ครั้งใน 10 นาทีจะเลิกพยายาม
เปิดด้วย pythonw (ไม่มีหน้าต่าง) ทางลัด Startup ชี้มาที่ไฟล์นี้
"""
import os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
FLAG = os.path.join(HERE, "quit.flag")
LOG = os.path.join(HERE, "supervisor.log")


def log(msg):
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 200_000:
            os.replace(LOG, LOG + ".1")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def main():
    # argv[1] = สคริปต์ที่จะรัน (ค่าเริ่มต้น jarvis.py ใช้ทดสอบ), argv[2] = วินาทีรอก่อนเปิดใหม่ (ค่าเริ่มต้น 5)
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "jarvis.py")
    delay = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
    if os.path.exists(FLAG):
        os.remove(FLAG)
    starts = []
    while True:
        t0 = time.time()
        p = subprocess.Popen([sys.executable, target], cwd=HERE)
        log(f"เริ่ม Jarvis pid={p.pid}")
        code = p.wait()
        if os.path.exists(FLAG):
            os.remove(FLAG)
            log("ผู้ใช้สั่งออก supervisor หยุด")
            return
        up = time.time() - t0
        if code == 0 and up < 20:
            log("มี Jarvis อีกตัวรันอยู่แล้ว supervisor หยุด")
            return
        log(f"Jarvis จบการทำงาน code={code} หลังรัน {up:.0f} วินาที -> เปิดใหม่ใน {delay:.0f} วินาที")
        starts = [s for s in starts if t0 - s < 600] + [t0]
        if len(starts) >= 6:
            log("ล้มซ้ำเกินไป (6 ครั้งใน 10 นาที) เลิกพยายาม")
            return
        time.sleep(delay)


if __name__ == "__main__":
    main()
