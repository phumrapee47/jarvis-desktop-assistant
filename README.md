# Jarvis — ผู้ช่วยเสียงภาษาไทยบน Windows

ผู้ช่วยเสียงที่รันอยู่เบื้องหลังบน Windows: เรียกด้วย **"Hey Jarvis"** แล้วสั่งงานด้วยเสียง มี orb สามมิติและกล่องข้อความบนจอ
สมองคือ Claude (Haiku) ถอดเสียงด้วย Whisper บน GPU ควบคุมเครื่องด้วยเสียงและ **ท่ามือผ่านเว็บแคม**
ออกแบบให้เหมาะกับ programmer (ดู git/GitHub, ส่งงานให้ Claude Code, สรุปเช้า, ความจำ/เตือน)

> สถานะ: โปรเจกต์ส่วนตัวที่ยังพัฒนาอยู่ ทดสอบจริงบน Windows 11 เครื่องเดียว ยังไม่มี license (สงวนสิทธิ์ทั้งหมดโดยปริยาย)

## ความสามารถ

| กลุ่ม | ตัวอย่าง |
|---|---|
| คุยและควบคุมเครื่อง | เปิด/ปิดแอปใดก็ได้ที่ติดตั้ง (ค้นจาก Start Menu), เปิดเว็บ/ค้น Google, คุมเพลงและเสียง, ล็อกจอ, ถามเวลา |
| Gmail (อ่านอย่างเดียว) | "วันนี้มีเมลอะไรบ้าง" |
| สำหรับ programmer | ดูหน้าจอ/clipboard, สถานะ git ของโปรเจกต์, สรุปงานเมื่อวาน (standup), PR ที่รอ review, เฝ้าโปรเซส/รัน build-test แล้วแจ้งผล |
| Claude Code | ส่งคำถามให้ Claude Code อ่านโปรเจกต์ (อ่านอย่างเดียว) หรือให้แก้ไฟล์บน branch ใหม่ (ต้องพูด "ยืนยัน") |
| ความจำ/เตือน | "จดไว้ว่า...", "เตือนบ่ายสามให้ push", เตือนซ้ำรายวัน, สรุปเช้าอัตโนมัติ |
| ท่ามือ | ลากหน้าต่าง, ปัดสลับหน้าต่าง, 👍👎 ยืนยัน/ยกเลิก, ✌️ ดูหน้าจอ, ✊ เล่น/หยุดเพลง, **โหมดเมาส์ในอากาศ** |

## ติดตั้ง

ต้องมี: Windows 11, Python 3.11, ไมค์ (แนะนำ GPU NVIDIA สำหรับ Whisper medium), เว็บแคม (เฉพาะโหมดท่ามือ)

```powershell
pip install -r requirements.txt
copy .env.example .env      # แล้วใส่ ANTHROPIC_API_KEY (บังคับ)
python jarvis.py
```

ครั้งแรกจะดาวน์โหลดโมเดล Whisper และโมเดลคำปลุกอัตโนมัติ (ใช้เวลาโหลดราว 1–2 นาทีทุกครั้งที่เริ่ม)

### ไม่บังคับ

- **Gmail:** สร้าง OAuth client (ชนิด Desktop) ใน Google Cloud เปิด Gmail API เพิ่มอีเมลตัวเองเป็น Test user
  ดาวน์โหลด JSON เป็น `credentials.json` ในโฟลเดอร์นี้ แล้วรัน `python gmail_tool.py` ครั้งเดียวเพื่ออนุญาต (ขอสิทธิ์อ่านอย่างเดียว)
- **GPU (CUDA):** `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12==9.*` (อยู่ใน requirements แล้ว) ถ้าใช้ GPU ไม่ได้จะตกไปใช้ CPU รุ่น small เอง
- **โหมดท่ามือ:**
  ```powershell
  python -m venv gesture_env
  gesture_env\Scripts\python -m pip install -r gesture_requirements.txt
  mkdir models
  # ดาวน์โหลดโมเดลจับมือของ Google MediaPipe (~7.6 MB) วางที่ models\hand_landmarker.task
  Invoke-WebRequest https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task -OutFile models\hand_landmarker.task
  ```
  เปิดจากเมนูไอคอนถาดระบบ "โหมดท่ามือ (เปิดกล้อง)" หรือพูด "เปิดโหมดท่ามือ" แล้วแบมือค้าง 1 วินาที (รายละเอียดท่าอยู่ในหัวไฟล์ `gestures.py`)
- **Claude Code bridge:** ติดตั้ง Claude Code CLI แล้ว `claude auth login` (Jarvis ตัด API key ออกจาก environment ก่อนเรียก เพื่อใช้โควตาแผนของคุณ)
- **เปิดอัตโนมัติ + เปิดใหม่เมื่อล้ม:** ให้ทางลัดใน Startup ชี้ `pythonw.exe supervisor.py` (ปิดเองได้จากเมนูถาดระบบ "ออก")

## โครงสร้าง

| ไฟล์ | หน้าที่ |
|---|---|
| `jarvis.py` | วนฟังคำปลุก → อัดเสียง → Whisper → Claude (tool use) → พูดตอบ, ไอคอนถาดระบบ |
| `overlay.py` | orb 3 มิติ + กล่องข้อความมุมขวาล่าง (PyQt6 + numpy shader) |
| `tools_pc.py` / `tools_dev.py` / `tools_memory.py` / `tools_brief.py` | เครื่องมือที่ Claude เรียกได้: ควบคุมเครื่อง / สำหรับ programmer + ชั้นยืนยัน / ความจำ+เตือน / สรุปเช้า |
| `gmail_tool.py` | อ่าน Gmail (read-only) |
| `gestures.py`, `gesture_logic.py`, `gesture_worker.py` | ท่ามือ: ตัวตัดสินใจ, จัดประเภทท่า, โปรเซสกล้อง (รันใน venv แยก) |
| `supervisor.py`, `watchdog.py` | เปิดใหม่เมื่อล้ม, ตรวจจับการค้างแล้วบันทึก stack |
| `tts_fallback.ps1` | เสียงไทยสำรองออฟไลน์ (Windows OneCore) เมื่อ edge-tts ล้ม |

## หลักความปลอดภัย

- **ไม่มีเครื่องมือ "รันคำสั่งอะไรก็ได้"** (คำสั่งเสียงถอดผิดได้) เพิ่มความสามารถเป็นเครื่องมือเฉพาะเรื่องเท่านั้น
- งานที่แก้ไฟล์/รันคำสั่ง **ต้องให้ผู้ใช้พูด "ยืนยัน" (หรือทำท่า 👍) เอง** ตรวจจากเสียง/ท่าจริง Claude ยืนยันแทนไม่ได้ ใช้ได้ครั้งเดียว หมดอายุใน 90 วินาที และ "ไม่ยืนยัน" ถือเป็นยกเลิก
- Claude Code แก้ไฟล์ได้เฉพาะ git repo ที่ไม่มีไฟล์ค้าง ทำบน branch ใหม่ ไม่ commit/push
- ความจำปฏิเสธข้อมูลลับ (คีย์/รหัสผ่าน/เลขบัตร) และไม่จดข้อความที่มาจากเมล/เว็บ/หน้าจอ เว้นแต่ผู้ใช้สั่งเอง
- กล้องปิดอยู่เสมอจนกว่าจะสั่ง ประมวลผลในเครื่อง ไม่บันทึกหรือส่งภาพออก (ภาพหน้าจอส่งไป API เฉพาะตอนสั่ง "ดูหน้าจอ")
- ความลับ/ข้อมูลส่วนตัว (`.env`, `credentials.json`, `token.json`, `memory.json`, log) ถูก `.gitignore` ไว้ทั้งหมด

## ค่าใช้จ่ายโดยประมาณ

Claude Haiku ผ่าน API ราว 0.05–0.25 บาทต่อคำสั่ง (ประมาณการ) ส่วน Whisper, คำปลุก, เสียงพูด (edge-tts) และ Gmail API ไม่มีค่าใช้จ่าย
งานที่ส่งให้ Claude Code ใช้โควตาแผน Pro/Max ของคุณ
