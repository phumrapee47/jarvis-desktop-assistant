"""สรุปเช้า: รวมเมลที่ยังไม่อ่าน + งานใน git + PR + เตือนวันนี้ ให้ Claude สรุปเป็นเสียง
ตั้งเวลาอัตโนมัติได้ (เก็บใน memory.json) ถ้าตั้งไว้ จะสรุปให้เองครั้งแรกของวันหลังถึงเวลา (ภายใน 4 ชั่วโมง)
"""
import datetime as dt, threading, time
from concurrent.futures import ThreadPoolExecutor

import gmail_tool
import tools_dev
import tools_memory

_ask = None  # ฟังก์ชันถาม Claude (ใส่โดย jarvis.py) ใช้ตอนสรุปเช้าอัตโนมัติ


def setup(ask_fn):
    global _ask
    _ask = ask_fn


def morning_brief():
    jobs = {
        "เมลที่ยังไม่อ่าน (2 วันล่าสุด)": lambda: gmail_tool.check_email(8, "is:unread in:inbox newer_than:2d"),
        "งานใน git (เมื่อวานถึงวันนี้)": lambda: tools_dev.recent_activity(1),
        "GitHub PR": tools_dev.github_prs,
        "เตือนที่ตั้งไว้": tools_memory.list_reminders,
    }
    with ThreadPoolExecutor(len(jobs)) as ex:  # ดึงพร้อมกัน ไม่ต้องรอทีละอย่าง
        futs = {k: ex.submit(f) for k, f in jobs.items()}
    parts = [f"วันนี้ {dt.datetime.now():%A %d/%m/%Y %H:%M}"]
    for k, fu in futs.items():
        try:
            parts.append(f"## {k}\n{fu.result()}")
        except Exception as e:
            parts.append(f"## {k}\nดึงข้อมูลไม่ได้: {e}")
    return "\n\n".join(parts)


def schedule_morning_brief(time_hhmm="09:00", weekdays_only=True, enabled=True):
    h, m = map(int, time_hhmm.split(":"))
    if not (0 <= h < 24 and 0 <= m < 60):
        return "เวลาไม่ถูกต้อง"
    with tools_memory._lock:
        d = tools_memory._load()
        d["brief"] = {"enabled": bool(enabled), "time": f"{h:02d}:{m:02d}", "weekdays_only": bool(weekdays_only), "last": ""}
        tools_memory._save(d)
    if not enabled:
        return "ปิดสรุปเช้าอัตโนมัติแล้ว"
    return f"ตั้งสรุปเช้าอัตโนมัติเวลา {h:02d}:{m:02d}" + (" ทุกวันทำงาน" if weekdays_only else " ทุกวัน") + " แล้ว"


def _spoken():
    return _ask("[ระบบ: ถึงเวลาสรุปเช้าอัตโนมัติ] เรียก morning_brief แล้วสรุปให้ผู้ใช้ 4-5 ประโยค เริ่มด้วยทักทายตอนเช้า "
                "เน้นเมลสำคัญ งานค้างใน git และเตือนวันนี้ ถ้าไม่มีอะไรก็บอกสั้นๆ")


def _check():
    with tools_memory._lock:
        d = tools_memory._load()
        b = d.get("brief")
        now = dt.datetime.now()
        if not b or not b.get("enabled") or (b.get("weekdays_only") and now.weekday() >= 5):
            return
        h, m = map(int, b["time"].split(":"))
        due = now.replace(hour=h, minute=m, second=0, microsecond=0)
        today = now.strftime("%Y-%m-%d")
        if now < due or b.get("last") == today:
            return
        b["last"] = today  # ทำเครื่องหมายก่อน กันซ้ำแม้รอบนี้จะพลาด
        tools_memory._save(d)
        if now > due + dt.timedelta(hours=4):
            return  # เปิดเครื่องสายเกินไป ข้ามของวันนี้
    tools_dev.notify_queue.put(_spoken)  # ใส่เป็นฟังก์ชัน: jarvis.py จะเรียกตอนว่างแล้วพูดผลลัพธ์


def start_scheduler():
    def loop():
        while True:
            try:
                _check()
            except Exception as e:
                print("brief error:", e)
            time.sleep(30)
    threading.Thread(target=loop, daemon=True).start()


def _tool(name, desc, props=None, required=()):
    return {"name": name, "description": desc,
            "input_schema": {"type": "object", "properties": props or {}, "required": list(required)}}


TOOLS = [
    _tool("morning_brief", "รวบรวมข้อมูลสำหรับสรุปเช้า (เมลที่ยังไม่อ่าน งานใน git PR เตือน) แล้วสรุปให้ผู้ใช้ 4-5 ประโยค "
          "ใช้เมื่อผู้ใช้ขอ 'สรุปเช้า/วันนี้มีอะไรบ้าง'"),
    _tool("schedule_morning_brief", "เปิด/ตั้งเวลาการสรุปเช้าอัตโนมัติ (Jarvis จะพูดสรุปเองครั้งแรกของวันหลังถึงเวลา ภายใน 4 ชั่วโมง) "
          "time_hhmm รูปแบบ HH:MM ค่าเริ่มต้น 09:00 weekdays_only ค่าเริ่มต้น true (เฉพาะจันทร์-ศุกร์)",
          {"time_hhmm": {"type": "string"}, "weekdays_only": {"type": "boolean"}}),
    _tool("disable_morning_brief", "ปิดการสรุปเช้าอัตโนมัติ ใช้เฉพาะเมื่อผู้ใช้พูดชัดเจนว่าให้ปิด/เลิก/ไม่ต้องสรุปเช้าอีก "
          "ห้ามใช้กับประโยคจบบทสนทนา เช่น 'ไม่มีอะไรแล้ว' 'พอแล้ว' 'ขอบคุณ'"),
]
HANDLERS = {"morning_brief": morning_brief, "schedule_morning_brief": lambda **kw: schedule_morning_brief(enabled=True, **kw),
            "disable_morning_brief": lambda: schedule_morning_brief(enabled=False)}


def run(name, args):
    try:
        return str(HANDLERS[name](**args))
    except Exception as e:
        return f"ทำไม่สำเร็จ: {e}"
