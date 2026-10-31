"""Gmail แบบอ่านอย่างเดียว (scope gmail.readonly). ต้องมี credentials.json ข้างไฟล์นี้ (ดู README)."""
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

HERE = os.path.dirname(os.path.abspath(__file__))
CRED = os.path.join(HERE, "credentials.json")
TOKEN = os.path.join(HERE, "token.json")
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _service():
    creds = Credentials.from_authorized_user_file(TOKEN, SCOPES) if os.path.exists(TOKEN) else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CRED):
                raise FileNotFoundError("ไม่พบ credentials.json")
            creds = InstalledAppFlow.from_client_secrets_file(CRED, SCOPES).run_local_server(port=0)
        with open(TOKEN, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def check_email(max_results=10, query="is:unread in:inbox"):
    """คืนข้อความสรุปเมลให้ Claude อ่าน (ผู้ส่ง/หัวเรื่อง/ตัวอย่างเนื้อหาสั้นๆ)"""
    try:
        svc = _service()
    except FileNotFoundError:
        return "ยังไม่ได้ตั้งค่า Gmail: ไม่พบไฟล์ credentials.json"
    max_results = max(1, min(int(max_results), 15))
    res = svc.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    ids = [m["id"] for m in res.get("messages", [])]
    if not ids:
        return "ไม่มีเมลที่ตรงเงื่อนไข"
    msgs = {}
    batch = svc.new_batch_http_request(callback=lambda rid, resp, exc: msgs.update({rid: resp}) if exc is None else None)
    for mid in ids:  # ดึงทุกฉบับในคำขอเดียว เร็วกว่าดึงทีละฉบับมาก
        batch.add(svc.users().messages().get(userId="me", id=mid, format="metadata",
                                             metadataHeaders=["From", "Subject"]), request_id=mid)
    batch.execute()
    lines = []
    for mid in ids:
        m = msgs.get(mid)
        if not m:
            continue
        h = {x["name"]: x["value"] for x in m["payload"]["headers"]}
        lines.append(f"- จาก: {h.get('From', '?')} | เรื่อง: {h.get('Subject', '(ไม่มีหัวเรื่อง)')} "
                     f"| ตัวอย่าง: {m.get('snippet', '')[:150]}")
    return f"พบ {len(ids)} ฉบับ (สูงสุด {max_results}):\n" + "\n".join(lines)


if __name__ == "__main__":  # ทดสอบ/ขออนุญาตครั้งแรก: python gmail_tool.py
    print(check_email(5))
