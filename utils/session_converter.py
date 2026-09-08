"""
تحويل Pyrogram v2 StringSession → ملف .session بصيغة Telethon v8 (SQLite).
يعمل بدون اتصال بـ Telegram — تحويل محلي بحت.
"""
import base64
import os
import sqlite3
import struct
import tempfile
import logging
import time

logger = logging.getLogger(__name__)

# صيغة Pyrogram v2 StringSession (271 بايت بعد فك base64)
_SESSION_FMT  = ">BI?256sQ?"
_SESSION_SIZE = 271

# عناوين DC servers لـ Telethon
_DC_ADDRESSES = {
    1: "149.154.175.53",
    2: "149.154.167.51",
    3: "149.154.175.100",
    4: "149.154.167.92",
    5: "91.108.56.151",
}
_DC_PORT = 443


def _decode_session(session_string: str):
    """يفك ترميز session_string ويُرجع (dc_id, api_id, test_mode, auth_key, user_id, is_bot)."""
    padded = session_string + "=" * (-len(session_string) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded)
    except Exception as e:
        raise ValueError(f"base64 decode failed: {e}") from e
    if len(raw) != _SESSION_SIZE:
        raise ValueError(f"Session string size mismatch: {len(raw)} != {_SESSION_SIZE}")
    return struct.unpack(_SESSION_FMT, raw)


def session_string_to_sqlite_bytes(session_string: str) -> bytes:
    """
    (تُبقى للتوافق الخلفي)
    يُولّد ملف .session بصيغة Telethon v8.
    """
    return session_string_to_telethon_sqlite(session_string)


def session_string_to_telethon_sqlite(
    session_string: str,
    phone: str = "",
    user_id: int = 0,
    username: str = "",
    full_name: str = "",
    access_hash: int = 0,
) -> bytes:
    """
    يُولّد ملف .session بصيغة Telethon v8 من Pyrogram StringSession.

    المدخلات:
        session_string  — Pyrogram v2 StringSession
        phone           — رقم الهاتف (للـ entities)
        user_id         — معرف المستخدم (للـ entities، إن لم يُعطَ يُؤخذ من الجلسة)
        username        — يوزر الحساب (بدون @)
        full_name       — الاسم الكامل
        access_hash     — access hash (0 إذا لم يتوفر — Telethon يعيد جلبه)

    يُرجع bytes محتوى ملف .session.
    يُطلق ValueError إذا كانت الجلسة غير صالحة.
    """
    dc_id_b, api_id, test_mode, auth_key, uid_from_sess, is_bot = _decode_session(session_string)

    dc_id   = int(dc_id_b)
    uid     = int(user_id) if user_id else int(uid_from_sess)
    srv_addr = _DC_ADDRESSES.get(dc_id, _DC_ADDRESSES[4])
    now      = int(time.time())

    fd, tmp_path = tempfile.mkstemp(suffix=".session")
    os.close(fd)
    try:
        conn = sqlite3.connect(tmp_path)
        try:
            # ── مخطط Telethon v8 ─────────────────────────────────────────
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS version (version integer primary key);

                CREATE TABLE IF NOT EXISTS sessions (
                    dc_id          integer primary key,
                    server_address text,
                    port           integer,
                    auth_key       blob,
                    takeout_id     integer,
                    tmp_auth_key   blob
                );

                CREATE TABLE IF NOT EXISTS entities (
                    id       integer primary key,
                    hash     integer not null,
                    username text,
                    phone    integer,
                    name     text,
                    date     integer
                );

                CREATE TABLE IF NOT EXISTS sent_files (
                    md5_digest blob,
                    file_size  integer,
                    type       integer,
                    id         integer,
                    hash       integer,
                    primary key(md5_digest, file_size, type)
                );

                CREATE TABLE IF NOT EXISTS update_state (
                    id   integer primary key,
                    pts  integer,
                    qts  integer,
                    date integer,
                    seq  integer
                );
            """)

            # نسخة الملف
            conn.execute("INSERT OR REPLACE INTO version VALUES (8)")

            # بيانات الجلسة
            conn.execute(
                "INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?)",
                (dc_id, srv_addr, _DC_PORT, auth_key, None, None),
            )

            # كيان المستخدم (مع hash=0 إن لم يتوفر — Telethon يجلبه عند أول اتصال)
            if uid:
                phone_int = None
                if phone:
                    try:
                        phone_int = int(phone.lstrip("+"))
                    except ValueError:
                        pass
                conn.execute(
                    "INSERT OR REPLACE INTO entities VALUES (?,?,?,?,?,?)",
                    (uid, access_hash or 0, username or None, phone_int, full_name or None, now),
                )

            conn.commit()
        finally:
            conn.close()

        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def extract_phone_from_account_data(account_data: str) -> str:
    """يستخرج رقم الهاتف من account_data بصيغة phone::..."""
    return account_data.split("::")[0].strip()


def extract_session_string_from_account_data(account_data: str) -> str:
    """
    يستخرج session_string من account_data بصيغتيها:
      - phone::session_string
      - phone::api_id::api_hash::session_string[::2fa]
    """
    parts = [p.strip() for p in account_data.split("::")]
    if len(parts) == 2:
        return parts[1]
    if len(parts) >= 4:
        return parts[3]
    raise ValueError(f"Unrecognised account_data format: {account_data[:40]}...")
