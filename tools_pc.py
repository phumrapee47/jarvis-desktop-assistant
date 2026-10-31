"""เครื่องมือควบคุมเครื่อง: เปิด/ปิดแอปด้วยการค้นหาอัตโนมัติ (ไม่ต้อง hard code), เว็บ, มีเดีย/เสียง, เวลา, ล็อกจอ.

ตั้งใจไม่ทำเครื่องมือ "รันคำสั่งอะไรก็ได้" เพราะคำสั่งเสียงที่ถอดผิด/ถูกหลอกอาจกลายเป็นคำสั่งอันตราย
"""
import ctypes, datetime, difflib, json, re, subprocess, urllib.parse, webbrowser

NO_WINDOW = 0x08000000  # ไม่ให้หน้าต่าง console โผล่ตอนรันด้วย pythonw
PROTECTED = {"explorer", "python", "pythonw", "dwm", "winlogon", "csrss", "svchost", "taskmgr"}
_apps = []  # [{"Name":..., "AppID":...}] จาก Start Menu (ทั้งแอป desktop และ Store)


def _ps(cmd, timeout=20):
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + cmd],
                       capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                       creationflags=NO_WINDOW)
    return r.stdout.strip()


def _json_list(text):
    if not text:
        return []
    data = json.loads(text)
    return data if isinstance(data, list) else [data]


def index_apps():
    """อ่านรายชื่อแอปทั้งหมดที่ติดตั้งในเครื่อง (เรียกตอนเริ่มโปรแกรม และเมื่อหาไม่เจอ)"""
    global _apps
    _apps = [a for a in _json_list(_ps("Get-StartApps | ConvertTo-Json -Compress")) if a.get("Name")]
    return len(_apps)


def _score(q, name):
    q, n = q.lower().strip(), name.lower().strip()
    if not q or not n:
        return 0.0
    if q == n:
        return 1.0
    # q อยู่ในชื่อแอป (พิมพ์ย่อ) หรือชื่อแอปเป็น "คำเต็ม" ในประโยค (กัน photoshop ไปตรงกับ Photos)
    if q in n or (len(n) >= 3 and re.search(r"\b" + re.escape(n) + r"\b", q)):
        return 0.9 + 0.1 * min(len(q), len(n)) / max(len(q), len(n))
    return difflib.SequenceMatcher(None, q, n).ratio()


def _rank(q, items, key):
    return sorted(((_score(q, key(i)), i) for i in items), key=lambda x: -x[0])


def open_app(name):
    for attempt in (1, 2):
        if not _apps or attempt == 2:
            index_apps()
        ranked = _rank(name, _apps, lambda a: a["Name"])
        if ranked and ranked[0][0] >= 0.85:  # เข้มไว้ กันเปิดแอปผิดตัว (photoshop vs Photos = 0.80)
            app = ranked[0][1]
            subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + app["AppID"]], creationflags=NO_WINDOW)
            return f"เปิด {app['Name']} แล้ว"
    near = ", ".join(a["Name"] for _, a in ranked[:5])
    return f"ไม่พบแอปชื่อ '{name}' แอปที่ใกล้เคียงที่สุด: {near} (ลองใช้ชื่อภาษาอังกฤษ หรือถามผู้ใช้ว่าหมายถึงอันไหน)"


def _windows():
    return _json_list(_ps("Get-Process | Where-Object {$_.MainWindowTitle} | "
                          "Select-Object Id,ProcessName,MainWindowTitle | ConvertTo-Json -Compress"))


def list_open_apps():
    rows = [f"{w['ProcessName']}: {w['MainWindowTitle']}" for w in _windows()
            if w["ProcessName"].lower() not in PROTECTED]
    return "แอปที่เปิดอยู่:\n" + "\n".join(rows) if rows else "ไม่มีแอปที่เปิดหน้าต่างอยู่"


def close_app(name, force=False):
    wins = [w for w in _windows() if w["ProcessName"].lower() not in PROTECTED]
    hits = [w for s, w in _rank(name, wins, lambda w: w["ProcessName"]) if s >= 0.85]
    hits += [w for w in wins if w not in hits and name.lower() in w["MainWindowTitle"].lower()]
    if not hits:
        return f"ไม่พบแอป '{name}' ที่เปิดอยู่ (ใช้ list_open_apps เพื่อดูรายการ)"
    pids = sorted({w["Id"] for w in hits})
    for pid in pids:  # ปิดแบบสุภาพก่อน (แอปอาจถามให้เซฟงาน) force=True ถึงจะบังคับ
        subprocess.run(["taskkill", "/PID", str(pid)] + (["/F"] if force else []),
                       capture_output=True, creationflags=NO_WINDOW)
    names = ", ".join(sorted({w["ProcessName"] for w in hits}))
    return f"สั่งปิด {names} แล้ว" + ("" if force else " (ถ้าแอปถามให้เซฟงาน ผู้ใช้ต้องตอบเอง)")


def open_url(url):
    if not re.match(r"^https?://", url):
        url = "https://" + url
    webbrowser.open(url)
    return f"เปิด {url} แล้ว"


def web_search(query):
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(query))
    return f"เปิดผลค้นหา Google สำหรับ '{query}' แล้ว"


_KEYS = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1,
         "volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD}


def media_control(action, times=1):
    vk = _KEYS.get(action)
    if vk is None:
        return f"ไม่รู้จักคำสั่ง {action} ที่ใช้ได้: {', '.join(_KEYS)}"
    for _ in range(max(1, min(int(times), 25))):  # ปุ่มเสียงขยับทีละ ~2%
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
    return f"ทำ {action} x{times} แล้ว"


def get_datetime():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S, %A")


def lock_screen():
    ctypes.windll.user32.LockWorkStation()
    return "ล็อกหน้าจอแล้ว"


def _tool(name, desc, props=None, required=()):
    return {"name": name, "description": desc,
            "input_schema": {"type": "object", "properties": props or {}, "required": list(required)}}


S = {"type": "string"}
TOOLS = [
    _tool("open_app", "เปิดแอปใดก็ได้ที่ติดตั้งในเครื่อง โดยค้นหาจากชื่อ ควรส่งชื่อทางการภาษาอังกฤษ (เช่น Notepad, Google Chrome, "
          "Spotify, Calculator) ถ้าไม่พบ ผลลัพธ์จะบอกแอปใกล้เคียงให้ลองใหม่หรือถามผู้ใช้", {"name": S}, ["name"]),
    _tool("close_app", "ปิดแอปที่เปิดอยู่ (ปิดแบบสุภาพ) force=true เฉพาะเมื่อผู้ใช้สั่งให้บังคับปิดเท่านั้น",
          {"name": S, "force": {"type": "boolean"}}, ["name"]),
    _tool("list_open_apps", "ดูรายชื่อแอปที่เปิดหน้าต่างอยู่ตอนนี้"),
    _tool("open_url", "เปิดเว็บไซต์ในเบราว์เซอร์", {"url": S}, ["url"]),
    _tool("web_search", "ค้นหาบน Google ในเบราว์เซอร์", {"query": S}, ["query"]),
    _tool("media_control", "ควบคุมเพลง/วิดีโอและเสียงของเครื่อง action: play_pause, next, previous, "
          "volume_up, volume_down, mute (เสียงขยับทีละ ~2% ใช้ times ปรับหลายขั้น เช่น 5 = ~10%)",
          {"action": {"type": "string", "enum": list(_KEYS)}, "times": {"type": "integer"}}, ["action"]),
    _tool("get_datetime", "ดูวันที่และเวลาปัจจุบัน"),
    _tool("lock_screen", "ล็อกหน้าจอ Windows"),
]
HANDLERS = {"open_app": open_app, "close_app": close_app, "list_open_apps": list_open_apps, "open_url": open_url,
            "web_search": web_search, "media_control": media_control, "get_datetime": get_datetime,
            "lock_screen": lock_screen}


def run(name, args):
    try:
        return str(HANDLERS[name](**args))
    except Exception as e:
        return f"ทำไม่สำเร็จ: {e}"


if __name__ == "__main__":  # ทดสอบ: python tools_pc.py
    print("indexed apps:", index_apps())
    print(open_app("notepad"))
    print(list_open_apps())
