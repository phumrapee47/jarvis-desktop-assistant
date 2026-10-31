"""ตัวเฝ้าการค้างของ Qt main thread: ถ้านิ่งเกิน limit วินาที บันทึก stack ทุก thread แล้วออก (ให้ supervisor เปิดใหม่)
ดีกว่าปล่อยค้างเงียบๆ จน Windows ปิดให้เอง (Application Hang) โดยไม่มีหลักฐานว่าค้างเพราะอะไร
"""
import faulthandler, os, threading, time


def start(parent_qobject, log_path, limit=60.0, on_hang=lambda: os._exit(3)):
    from PyQt6.QtCore import QTimer
    f = open(log_path, "a", encoding="utf-8")
    faulthandler.enable(file=f, all_threads=True)  # พังระดับ native (เช่น CUDA) ก็ได้ stack
    beat = {"t": time.time()}
    timer = QTimer(parent_qobject)
    timer.timeout.connect(lambda: beat.update(t=time.time()))
    timer.start(1000)

    def watch():
        while True:
            t0 = time.time()
            time.sleep(min(5.0, limit / 3))
            if time.time() - t0 > max(20.0, limit / 3 * 2):  # ทั้งเครื่องหยุดนิ่ง (เช่น sleep) ไม่ใช่ Jarvis ค้าง
                beat["t"] = time.time()
                continue
            if time.time() - beat["t"] > limit:
                f.write(f"\n=== {time.ctime()} Qt main thread ไม่ตอบสนองเกิน {limit:.0f} วินาที ===\n")
                faulthandler.dump_traceback(file=f, all_threads=True)
                f.flush()
                print(f"watchdog: โปรแกรมค้างเกิน {limit:.0f} วินาที ออกเพื่อให้เปิดใหม่ (ดู hang_trace.log)")
                on_hang()
                return
    threading.Thread(target=watch, daemon=True).start()
    return timer  # ผู้เรียกต้องถือ reference ไว้
