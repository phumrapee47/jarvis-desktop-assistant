"""เครื่องมือสำหรับ programmer: ดูหน้าจอ, clipboard, สถานะ git/GitHub, ส่งงานให้ Claude Code (อ่านอย่างเดียว).

หลักความปลอดภัย: ทุกอย่างในไฟล์นี้ "อ่านอย่างเดียว" ยกเว้นเขียน clipboard
Claude Code ถูกจำกัดให้ใช้ได้แค่ Read/Grep/Glob (ห้าม Edit/Write/Bash)
"""
import base64, datetime, io, os, queue, re, shutil, subprocess, threading, time

from tools_pc import NO_WINDOW, _score

DOCS = os.path.join(os.path.expanduser("~"), "Documents")
HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "claude_code_results")
notify_queue = queue.Queue()  # ข้อความจากงานเบื้องหลัง รอให้ Jarvis พูดตอนว่าง
_client = _model = None
_job = {"running": False}


def setup(client, model):
    global _client, _model
    _client, _model = client, model


def _run(cmd, cwd=None, timeout=25, input_text=None, env=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, creationflags=NO_WINDOW, input=input_text, env=env)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


# ---------- ดูหน้าจอ / clipboard ----------
def look_at_screen(question=""):
    from PIL import ImageGrab
    im = ImageGrab.grab().convert("RGB")
    im.thumbnail((1568, 1568))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    img = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                       "data": base64.b64encode(buf.getvalue()).decode()}}
    return [img, {"type": "text", "text": "นี่คือภาพหน้าจอปัจจุบัน (จอหลัก) " + (f"คำถาม: {question}" if question else "")}]


def read_clipboard():
    _, out, _ = _run(["powershell", "-NoProfile", "-Command",
                      "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"])
    if not out:
        return "clipboard ว่างเปล่า (หรือไม่ใช่ข้อความ)"
    return out[:6000] + ("\n...(ตัดส่วนที่เกิน)" if len(out) > 6000 else "")


def write_clipboard(text):
    _run(["powershell", "-NoProfile", "-Command",
          "[Console]::InputEncoding=[Text.Encoding]::UTF8; $t=[Console]::In.ReadToEnd(); Set-Clipboard -Value $t"],
         input_text=text)
    return f"คัดลอกข้อความ {len(text)} ตัวอักษรลง clipboard แล้ว"


# ---------- โปรเจกต์ / git ----------
def _norm(s):
    return re.sub(r"[^a-z0-9ก-๙]", "", s.lower())


def _all_projects():
    return [d.name for d in os.scandir(DOCS) if d.is_dir() and not d.name.startswith(".")]


def find_project(name):
    """คืน (path, None) หรือ (None, ข้อความ error พร้อมตัวเลือกใกล้เคียง)"""
    names = _all_projects()
    ranked = sorted(((_score(_norm(name), _norm(n)), n) for n in names), reverse=True)
    if ranked and ranked[0][0] >= 0.75:
        return os.path.join(DOCS, ranked[0][1]), None
    return None, f"ไม่พบโปรเจกต์ '{name}' ใกล้เคียง: " + ", ".join(n for _, n in ranked[:5])


def git_status(project):
    path, err = find_project(project)
    if err:
        return err
    if not os.path.isdir(os.path.join(path, ".git")):
        return f"{os.path.basename(path)} ไม่ใช่ git repo"
    _, branch, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    _, status, _ = _run(["git", "status", "--porcelain"], cwd=path)
    rc, ab, _ = _run(["git", "rev-list", "--left-right", "--count", "@{u}...HEAD"], cwd=path)
    behind_ahead = f"ตามหลัง/นำหน้า remote: {ab.split()[0]}/{ab.split()[1]}" if rc == 0 and len(ab.split()) == 2 else "ไม่มี upstream"
    _, log, _ = _run(["git", "log", "-5", "--pretty=format:%h %s (%cr)"], cwd=path)
    n = len([l for l in status.splitlines() if l.strip()])
    return (f"โปรเจกต์ {os.path.basename(path)} branch {branch} | ไฟล์ที่ยังไม่ commit: {n} | {behind_ahead}\n"
            f"commit ล่าสุด:\n{log}")


def recent_activity(days=1):
    """สรุปงานของผู้ใช้ทุก repo ใน Documents (ใช้ทำ standup)"""
    days = max(1, min(int(days), 30))
    _, email, _ = _run(["git", "config", "--global", "user.email"])
    lines = []
    for name in _all_projects():
        path = os.path.join(DOCS, name)
        if not os.path.isdir(os.path.join(path, ".git")):
            continue
        try:
            _, log, _ = _run(["git", "log", f"--since={days} days ago", f"--author={email}", "--no-merges",
                              "--pretty=format:%s"], cwd=path)
            _, st, _ = _run(["git", "status", "--porcelain"], cwd=path)
        except Exception:
            continue
        commits = [l for l in log.splitlines() if l.strip()]
        dirty = len([l for l in st.splitlines() if l.strip()])
        if commits or dirty:
            lines.append(f"- {name}: {len(commits)} commit" + (f" ({'; '.join(commits[:3])})" if commits else "")
                         + (f", ยังไม่ commit {dirty} ไฟล์" if dirty else ""))
    return (f"งานใน {days} วันที่ผ่านมา:\n" + "\n".join(lines[:25])) if lines else f"ไม่พบ commit หรือการแก้ไขใน {days} วันที่ผ่านมา"


def github_prs():
    if not shutil.which("gh"):
        return "ไม่ได้ติดตั้ง GitHub CLI (gh)"
    out = []
    for label, flag in (("PR ของฉันที่เปิดอยู่", "--author"), ("PR ที่รอฉัน review", "--review-requested")):
        rc, txt, err = _run(["gh", "search", "prs", flag, "@me", "--state", "open", "--limit", "10",
                             "--json", "title,repository,number"], timeout=30)
        if rc != 0:
            return f"เรียก gh ไม่สำเร็จ: {err[:150]}"
        import json
        items = json.loads(txt or "[]")
        out.append(f"{label}: " + ("ไม่มี" if not items else "; ".join(
            f"{i['repository']['nameWithOwner']}#{i['number']} {i['title']}" for i in items)))
    return "\n".join(out)


# ---------- ส่งงานให้ Claude Code (อ่านอย่างเดียว เบื้องหลัง) ----------
def ask_claude_code(project, task):
    path, err = find_project(project)
    if err:
        return err
    if _job["running"]:
        return "มีงาน Claude Code กำลังทำอยู่ รอให้เสร็จก่อน"
    exe = shutil.which("claude")
    if not exe:
        return "ไม่พบ Claude Code CLI (claude)"
    _job["running"] = True
    threading.Thread(target=_cc_worker, args=(exe, path, task, "read"), daemon=True).start()
    return f"รับงานแล้ว กำลังให้ Claude Code ดู {os.path.basename(path)} (โหมดอ่านอย่างเดียว) จะแจ้งเมื่อเสร็จ"


# ---------- ชั้นยืนยัน: การกระทำที่แก้ไฟล์/รันคำสั่ง ต้องให้ "ผู้ใช้พูดยืนยันเอง" ----------
# ยืนยันได้จากเสียงที่ถอดได้จริงเท่านั้น (handle_confirmation ถูกเรียกจาก jarvis.py) Claude เรียกยืนยันเองไม่ได้
_pending = {"fn": None, "desc": "", "expires": 0.0}
CONFIRM_RE = re.compile(r"ยืนยัน|ตกลง|ทำเลย|เริ่มเลย|\bconfirm\b|\byes\b", re.I)
# คำปฏิเสธชนะเสมอ ("ไม่ยืนยัน", "ยืนยันแต่ไม่ต้อง" ต้องถือเป็นยกเลิก)
CANCEL_RE = re.compile(r"ยกเลิก|ไม่|อย่า|หยุด|\bcancel\b|\bno\b|\bstop\b|don'?t", re.I)


def request_confirmation(desc, fn):
    _pending.update(fn=fn, desc=desc, expires=time.time() + 90)
    return (f"ยังไม่ได้ทำ! รอผู้ใช้ยืนยัน: {desc} — บอกผู้ใช้ว่าจะทำอะไร แล้วให้ผู้ใช้พูดว่า 'ยืนยัน' หรือ 'ยกเลิก' "
            "(ระบบจะทำเองเมื่อผู้ใช้พูดยืนยัน ห้ามเรียกเครื่องมือนี้ซ้ำ)")


def has_pending():
    return bool(_pending["fn"]) and time.time() < _pending["expires"]


def handle_confirmation(text):
    """คืนข้อความตอบถ้าเป็นคำยืนยัน/ยกเลิกของคำขอที่ค้างอยู่ ไม่งั้นคืน None (และทิ้งคำขอที่ค้าง เพื่อกันยืนยันข้ามบริบท)"""
    fn, expires = _pending["fn"], _pending["expires"]
    _pending.update(fn=None, desc="", expires=0.0)  # ใช้ได้ครั้งเดียว
    if not fn or time.time() > expires:
        return None
    t = text.strip().lower()
    if len(t) <= 25 and CANCEL_RE.search(t):
        return "ยกเลิกแล้วครับ"
    if len(t) <= 25 and CONFIRM_RE.search(t):
        try:
            return fn()
        except Exception as e:
            return f"ทำไม่สำเร็จ: {e}"
    return None


def claude_code_edit(project, task):
    path, err = find_project(project)
    if err:
        return err
    name = os.path.basename(path)
    if not os.path.isdir(os.path.join(path, ".git")):
        return f"{name} ไม่ใช่ git repo ให้แก้ไฟล์ไม่ได้ เพราะย้อนกลับไม่ได้"
    _, st, _ = _run(["git", "status", "--porcelain"], cwd=path)
    if st.strip():
        return f"{name} มีไฟล์ที่ยังไม่ commit ({len(st.splitlines())} ไฟล์) ให้ผู้ใช้ commit หรือ stash ก่อน เพื่อไม่ให้งานเดิมปนกับที่ Claude Code แก้"
    exe = shutil.which("claude")
    if not exe:
        return "ไม่พบ Claude Code CLI (claude)"

    def go():
        if _job["running"]:
            return "มีงาน Claude Code กำลังทำอยู่ รอให้เสร็จก่อน"
        branch = "jarvis/" + datetime.datetime.now().strftime("%m%d-%H%M")
        rc, _, e = _run(["git", "switch", "-c", branch], cwd=path)
        if rc != 0:
            return f"สร้าง branch ไม่สำเร็จ: {e[:100]}"
        _job["running"] = True
        threading.Thread(target=_cc_worker, args=(exe, path, task, "edit", branch), daemon=True).start()
        return f"เริ่มแล้วครับ Claude Code กำลังแก้ {name} บน branch {branch} จะแจ้งเมื่อเสร็จ"

    return request_confirmation(f"ให้ Claude Code แก้ไฟล์ในโปรเจกต์ {name} ตามงาน '{task[:120]}' "
                                "ทำบน branch ใหม่ ไม่ commit ไม่ push", go)


_EDIT_TOOLS = ("Read,Grep,Glob,Edit,Write,Bash(git diff:*),Bash(git status:*),Bash(git log:*),"
               "Bash(npm test:*),Bash(npm run test:*),Bash(pytest:*),Bash(python -m pytest:*),Bash(flutter test:*)")
_EDIT_DENY = "Bash(git push:*),Bash(git commit:*),Bash(git reset:*),Bash(git checkout:*),Bash(rm:*),Bash(del:*),NotebookEdit"


def _cc_worker(exe, path, task, mode="read", branch=""):
    name = os.path.basename(path)
    try:
        # ตัด API key ออกจาก environment เพื่อให้ Claude Code ใช้โควตา Pro ไม่ใช่คิดเงินตาม API
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        if mode == "edit":
            prompt = ("แก้ไฟล์ตามงานนี้ในโปรเจกต์ปัจจุบัน ห้าม commit/push รันเทสต์ได้ถ้ามี ตอบเป็นภาษาไทย "
                      "สรุปว่าแก้อะไรไปบ้าง\n\n" + task)
            cmd = [exe, "-p", "--permission-mode", "acceptEdits", "--allowedTools", _EDIT_TOOLS,
                   "--disallowedTools", _EDIT_DENY, "--max-turns", "40"]
            timeout = 900
        else:
            prompt = "โหมดอ่านอย่างเดียว ห้ามแก้ไฟล์ ตอบเป็นภาษาไทย กระชับ ตรงประเด็น\n\n" + task
            cmd = [exe, "-p", "--allowedTools", "Read,Grep,Glob", "--disallowedTools",
                   "Edit,Write,Bash,NotebookEdit", "--max-turns", "20"]
            timeout = 600
        rc, out, err = _run(cmd, cwd=path, timeout=timeout, input_text=prompt, env=env)
        if rc != 0 or not out:
            notify_queue.put(f"Claude Code ทำงานที่ {name} ไม่สำเร็จ: {(err or out or 'ไม่มีผลลัพธ์')[:150]}")
            return
        diff = ""
        if mode == "edit":
            _, diff, _ = _run(["git", "diff", "--stat"], cwd=path)
            _, new, _ = _run(["git", "status", "--short"], cwd=path)
            diff = (diff or "ไม่มีไฟล์เปลี่ยน") + ("\n" + new if new else "")
        os.makedirs(RESULTS, exist_ok=True)
        fpath = os.path.join(RESULTS, datetime.datetime.now().strftime("%Y%m%d_%H%M%S_") + re.sub(r"\W", "", name) + ".md")
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(f"# งาน ({mode}): {task}\nโปรเจกต์: {path}\n" + (f"branch: {branch}\n" if branch else "")
                    + f"\n{out}\n" + (f"\n## git diff --stat\n{diff}\n" if diff else ""))
        summary = out[:400]
        if _client:
            r = _client.messages.create(model=_model, max_tokens=300, messages=[{"role": "user", "content":
                "สรุปผลนี้เป็นภาษาไทย 2-3 ประโยค สำหรับอ่านออกเสียง ไม่ใช้ markdown/ลิสต์/อีโมจิ:\n\n" + out[:8000]
                + ("\n\nไฟล์ที่เปลี่ยน:\n" + diff if diff else "")}])
            summary = "".join(b.text for b in r.content if b.type == "text")
        tail = (f" แก้บน branch {branch} ยังไม่ commit ตรวจด้วย git diff ได้ ถ้าไม่เอาให้สลับกลับ branch เดิมแล้วลบ branch นี้"
                if mode == "edit" else " ผลเต็มบันทึกไว้ในโฟลเดอร์ claude_code_results")
        notify_queue.put(f"Claude Code ทำงานที่ {name} เสร็จแล้วครับ {summary}{tail}")
    except Exception as e:
        notify_queue.put(f"Claude Code ทำงานที่ {name} ไม่สำเร็จ: {e}")
    finally:
        _job["running"] = False


# ---------- แจ้งเมื่อเสร็จ: รันคำสั่ง build/test (ต้องยืนยัน) และเฝ้าโปรเซส ----------
ALLOWED_CMDS = [r"(npm|pnpm|yarn)( run)? (test|build|lint|typecheck|check)", r"npm ci", r"(python -m )?pytest( -q| -x)*",
                r"dotnet (build|test)", r"mvn (test|package|verify)", r"(\.\\)?gradlew?(\.bat)? (build|test)",
                r"flutter (test|analyze|build apk|build web)", r"cargo (build|test|check)", r"go (build|test)( \./\.\.\.)?",
                r"tsc( --noEmit)?"]


def run_command_notify(project, command):
    command = command.strip()
    if re.search(r"[&|;<>`$\n\r]", command) or not any(re.fullmatch(p, command, re.I) for p in ALLOWED_CMDS):
        return ("คำสั่งนี้ไม่อยู่ในรายการที่อนุญาต (อนุญาตเฉพาะ build/test เช่น npm test, npm run build, pytest, "
                "flutter test, dotnet build, cargo test, go test) ให้ผู้ใช้รันเอง")
    path, err = find_project(project)
    if err:
        return err
    name = os.path.basename(path)

    def go():
        threading.Thread(target=_cmd_worker, args=(path, command), daemon=True).start()
        return f"เริ่มรัน {command} ที่ {name} แล้วครับ จะแจ้งเมื่อเสร็จ"
    return request_confirmation(f"รันคำสั่ง '{command}' ในโปรเจกต์ {name} แล้วแจ้งผลเมื่อเสร็จ", go)


def _cmd_worker(path, command):
    name, t0 = os.path.basename(path), time.time()
    try:
        r = subprocess.run(command, shell=True, cwd=path, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=1800, creationflags=NO_WINDOW)
        mins = (time.time() - t0) / 60
        log = (r.stdout or "") + "\n" + (r.stderr or "")
        logdir = os.path.join(HERE, "command_logs")
        os.makedirs(logdir, exist_ok=True)
        with open(os.path.join(logdir, datetime.datetime.now().strftime("%Y%m%d_%H%M%S_") + re.sub(r"\W", "", name) + ".log"),
                  "w", encoding="utf-8") as f:
            f.write(f"$ {command}\n(exit {r.returncode})\n{log}")
        if r.returncode == 0:
            notify_queue.put(f"{command} ที่ {name} สำเร็จแล้วครับ ใช้เวลา {mins:.1f} นาที")
            return
        why = log[-600:]
        if _client:
            m = _client.messages.create(model=_model, max_tokens=200, messages=[{"role": "user", "content":
                "สรุปสาเหตุที่คำสั่งล้มเหลวเป็นภาษาไทย 1-2 ประโยค สำหรับอ่านออกเสียง ไม่ใช้ markdown:\n\n" + log[-4000:]}])
            why = "".join(b.text for b in m.content if b.type == "text")
        notify_queue.put(f"{command} ที่ {name} ล้มเหลวครับ (exit {r.returncode}) {why}")
    except Exception as e:
        notify_queue.put(f"{command} ที่ {name} ทำไม่สำเร็จ: {e}")


def watch_process(name):
    from tools_pc import PROTECTED, _json_list, _ps
    safe = re.sub(r"[^\w.-]", "", name)
    procs = [p for p in _json_list(_ps(f"Get-Process | Where-Object {{$_.ProcessName -like '*{safe}*'}} | "
                                       "Select-Object Id,ProcessName | ConvertTo-Json -Compress"))
             if p["ProcessName"].lower() not in PROTECTED]
    if not procs:
        return f"ไม่พบโปรเซสที่ชื่อมี '{name}' กำลังทำงานอยู่"
    ids = ",".join(str(p["Id"]) for p in procs)
    label = ", ".join(sorted({p["ProcessName"] for p in procs}))

    def watch():
        deadline = time.time() + 3 * 3600
        while time.time() < deadline:
            time.sleep(8)
            if _ps(f"(Get-Process -Id {ids} -ErrorAction SilentlyContinue | Measure-Object).Count").strip() == "0":
                notify_queue.put(f"{label} หยุดทำงานแล้วครับ")
                return
    threading.Thread(target=watch, daemon=True).start()
    return f"กำลังเฝ้า {label} ({len(procs)} โปรเซส) จะแจ้งเมื่อหยุดทำงาน (สูงสุด 3 ชั่วโมง)"


def _tool(name, desc, props=None, required=()):
    return {"name": name, "description": desc,
            "input_schema": {"type": "object", "properties": props or {}, "required": list(required)}}


S = {"type": "string"}
TOOLS = [
    _tool("look_at_screen", "แคปหน้าจอปัจจุบันให้ดู ใช้เมื่อผู้ใช้ขอให้ดูจอ/error/สิ่งที่เปิดอยู่เท่านั้น (ภาพถูกส่งไปยัง API)",
          {"question": S}),
    _tool("read_clipboard", "อ่านข้อความที่ผู้ใช้ copy ไว้ ใช้เมื่อผู้ใช้พูดถึงสิ่งที่ copy/โค้ดที่ copy ไว้"),
    _tool("write_clipboard", "คัดลอกข้อความลง clipboard เช่น commit message ที่เขียนให้", {"text": S}, ["text"]),
    _tool("git_status", "ดูสถานะ git ของโปรเจกต์ (branch, ไฟล์ที่ยังไม่ commit, commit ล่าสุด) ชื่อโปรเจกต์คือชื่อโฟลเดอร์ใน Documents",
          {"project": S}, ["project"]),
    _tool("recent_activity", "สรุปงานที่ผู้ใช้ทำในทุก git repo ย้อนหลัง N วัน ใช้ตอบ 'เมื่อวานทำอะไรไป' หรือเตรียม standup",
          {"days": {"type": "integer"}}),
    _tool("github_prs", "ดู Pull Request ของผู้ใช้ที่เปิดอยู่ และที่รอ review (GitHub)"),
    _tool("ask_claude_code", "ส่งคำถามเกี่ยวกับโค้ดในโปรเจกต์ให้ Claude Code วิเคราะห์เบื้องหลัง (อ่านอย่างเดียว แก้ไฟล์ไม่ได้) "
          "ห้ามใช้เมื่อผู้ใช้สั่งให้เขียน/แก้/เพิ่ม/ลบโค้ด ให้ใช้ claude_code_edit แทน "
          "ใช้กับคำถามเช่น โปรเจกต์นี้ทำงานยังไง, หา bug, อธิบายโมดูล ใช้เวลาหลายนาที คืนสถานะ 'รับงานแล้ว' ทันที "
          "แล้ว Jarvis จะแจ้งผลเองเมื่อเสร็จ ให้บอกผู้ใช้สั้นๆ ว่ารับงานแล้ว", {"project": S, "task": S}, ["project", "task"]),
    _tool("claude_code_edit", "ให้ Claude Code แก้ไฟล์/เขียนโค้ดในโปรเจกต์ตามงานที่ผู้ใช้สั่ง ทำบน branch ใหม่ ไม่ commit ไม่ push "
          "เครื่องมือนี้ยังไม่ทำจริง แต่จะรอให้ผู้ใช้พูดว่า 'ยืนยัน' เอง ให้บอกผู้ใช้ว่าจะแก้อะไรที่ไหนแล้วขอให้ยืนยัน "
          "ห้ามเรียกซ้ำเพื่อยืนยันแทนผู้ใช้", {"project": S, "task": S}, ["project", "task"]),
    _tool("run_command_notify", "รันคำสั่ง build/test ในโปรเจกต์เบื้องหลัง แล้วแจ้งผลเมื่อเสร็จ (อนุญาตเฉพาะ npm test/build, pytest, "
          "flutter test, dotnet build, cargo test, go test ฯลฯ) ต้องรอผู้ใช้พูด 'ยืนยัน' เองก่อนรัน", {"project": S, "command": S},
          ["project", "command"]),
    _tool("watch_process", "เฝ้าโปรเซสที่กำลังรันอยู่ (เช่น node, docker, python, dotnet ที่ผู้ใช้รันเองใน terminal) "
          "แล้วแจ้งเมื่อมันหยุดทำงาน ใช้กับ 'บอกด้วยเมื่อ build/เทรนเสร็จ'", {"name": S}, ["name"]),
]
HANDLERS = {"look_at_screen": look_at_screen, "read_clipboard": read_clipboard, "write_clipboard": write_clipboard,
            "git_status": git_status, "recent_activity": recent_activity, "github_prs": github_prs,
            "ask_claude_code": ask_claude_code, "claude_code_edit": claude_code_edit,
            "run_command_notify": run_command_notify, "watch_process": watch_process}


def run(name, args):
    try:
        return HANDLERS[name](**args)
    except Exception as e:
        return f"ทำไม่สำเร็จ: {e}"
