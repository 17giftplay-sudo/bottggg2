"""
zip_parser.py — تحليل ملفات ZIP الخاصة بجلسات Telethon وملفات Pyrogram النصية
               وتحويلها إلى أسطر جاهزة لإدخالها في قاعدة البيانات.

تحويل Telethon → Pyrogram v2 session string:
  تنسيق Pyrogram v2 (271 بايت، big-endian):
      B   – dc_id       (1 بايت)
      I   – api_id      (4 بايت)
      ?   – test_mode   (1 بايت، bool)
    256s  – auth_key    (256 بايت)
      Q   – user_id     (8 بايت، unsigned)
      ?   – is_bot      (1 بايت، bool)
"""

import base64
import logging
import os
import re
import shutil
import sqlite3
import struct
import zipfile
from typing import Optional

logger = logging.getLogger(__name__)

_PYROGRAM_V2_FMT  = ">BI?256sQ?"
_PYROGRAM_V2_SIZE = struct.calcsize(_PYROGRAM_V2_FMT)  # 271


# ─────────────────────────────────────────────────────────────────────────────
# تحويل الجلسة
# ─────────────────────────────────────────────────────────────────────────────

def _telethon_to_pyrogram(
    dc_id: int,
    auth_key: bytes,
    user_id: int,
    api_id: int,
    test_mode: bool = False,
    is_bot: bool = False,
) -> str:
    """يحوّل بيانات جلسة Telethon إلى session string بتنسيق Pyrogram v2."""
    if len(auth_key) != 256:
        raise ValueError(f"auth_key يجب أن يكون 256 بايت، المقدّم: {len(auth_key)}")
    packed = struct.pack(
        _PYROGRAM_V2_FMT,
        dc_id,
        api_id,
        test_mode,
        auth_key,
        user_id,
        is_bot,
    )
    return base64.urlsafe_b64encode(packed).decode().rstrip("=")


# ─────────────────────────────────────────────────────────────────────────────
# قراءة ملف .session
# ─────────────────────────────────────────────────────────────────────────────

def _read_telethon_session(session_path: str) -> Optional[dict]:
    """
    يستخرج dc_id وauth_key وuser_id من ملف SQLite الخاص بـ Telethon.
    يُعيد None إذا فشلت القراءة أو كان الملف غير صالح.
    """
    try:
        conn = sqlite3.connect(session_path)
        try:
            # ── قراءة بيانات جلسة الاتصال ─────────────────────────────────
            row = conn.execute(
                "SELECT dc_id, auth_key FROM sessions LIMIT 1"
            ).fetchone()
            if not row:
                logger.warning("جدول sessions فارغ في: %s", session_path)
                return None

            dc_id, auth_key = row
            auth_key = bytes(auth_key)
            if len(auth_key) != 256:
                logger.warning(
                    "auth_key غير صالح (%d بايت) في: %s", len(auth_key), session_path
                )
                return None

            # ── استخراج user_id من جدول entities ─────────────────────────
            # الصف المطابق لصاحب الحساب يحتوي على رقم الهاتف
            user_id = 0
            try:
                # ابحث عن الصف الذي يحتوي على رقم هاتف (عمود phone)
                ent = conn.execute(
                    "SELECT id FROM entities WHERE phone IS NOT NULL AND phone != '' LIMIT 1"
                ).fetchone()
                if ent:
                    user_id = abs(int(ent[0]))
                else:
                    # احتياطي: الصف ذو أقدم تاريخ (المستخدم نفسه عادةً)
                    ent = conn.execute(
                        "SELECT id FROM entities ORDER BY date ASC LIMIT 1"
                    ).fetchone()
                    if ent:
                        user_id = abs(int(ent[0]))
            except Exception as ue:
                logger.debug("لم يُتمكن من قراءة user_id من entities: %s", ue)

            return {
                "dc_id":    int(dc_id),
                "auth_key": auth_key,
                "user_id":  user_id,
            }
        finally:
            conn.close()
    except Exception as e:
        logger.warning("فشل قراءة ملف الجلسة %s: %s", session_path, e)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# تحليل ملف المعلومات
# ─────────────────────────────────────────────────────────────────────────────

def _parse_info_file(text: str) -> dict:
    """
    يستخرج رقم الهاتف وكلمة مرور 2FA و API ID و API HASH من ملف معلومات الجلسة النصي
    بدعم كامل للغات العربية والإنجليزية ومختلف صيغ التنسيق.
    """
    result = {"phone": "", "two_factor": "", "api_id": 0, "api_hash": ""}
    if not text:
        return result

    # 1. رقم الهاتف
    m_phone = re.search(
        r"(?:Phone|Mobile|رقم\s*الهاتف|الهاتف|رقم)[^:\n]*:\s*(\+?\d{7,15})",
        text, re.IGNORECASE
    )
    if m_phone:
        p = m_phone.group(1).strip()
        result["phone"] = p if p.startswith("+") else "+" + p
    else:
        m_fallback = re.search(r"(\+\d{7,15})", text)
        if m_fallback:
            result["phone"] = m_fallback.group(1).strip()
        else:
            m_digits = re.search(r"\b(\d{9,15})\b", text)
            if m_digits:
                result["phone"] = "+" + m_digits.group(1).strip()

    # 2. كلمة مرور 2FA / التحقق بخطوتين
    m_pw = re.search(
        r"(?:2FA|Verification|Password|كلمة\s*المرور|كلمة\s*السر|التحقق\s*بخطوتين)[^:\n]*:\s*[`'\"]?([^\n`'\"]+)[`'\"]?",
        text, re.IGNORECASE
    )
    if m_pw:
        pw = m_pw.group(1).strip()
        if pw and not any(k in pw.lower() for k in ("telethon", "client", "telegram", "تنبيه", "طريقة", "http")):
            result["two_factor"] = pw

    # 3. API ID
    m_api_id = re.search(r"(?:API\s*ID|app_id)[^:\n]*:\s*(\d+)", text, re.IGNORECASE)
    if m_api_id:
        try:
            result["api_id"] = int(m_api_id.group(1).strip())
        except ValueError:
            pass

    # 4. API HASH
    m_api_hash = re.search(r"(?:API\s*HASH|app_hash)[^:\n]*:\s*([a-fA-F0-9]{32})", text, re.IGNORECASE)
    if m_api_hash:
        result["api_hash"] = m_api_hash.group(1).strip()

    return result


def _parse_json_info(text: str) -> dict:
    """
    يستخرج بيانات الحساب من ملف JSON بمرونة عالية:
    { phone, api_id/app_id, api_hash/app_hash, 2fa/password/two_step, session_string/session, user_id/id }
    """
    import json as _json
    result = {
        "phone":          "",
        "api_id":         0,
        "api_hash":       "",
        "two_factor":     "",
        "session_string": "",
        "user_id":        0,
    }
    try:
        data = _json.loads(text)
    except Exception:
        return result

    # رقم الهاتف
    for key in ("phone", "phone_number", "number", "mobile", "Phone"):
        val = str(data.get(key) or "").strip()
        if val:
            if not val.startswith("+") and val.isdigit():
                val = "+" + val
            result["phone"] = val
            break

    # معرف المستخدم (user_id)
    for key in ("user_id", "id", "user"):
        try:
            val = int(data.get(key) or 0)
            if val > 0:
                result["user_id"] = val
                break
        except (ValueError, TypeError):
            pass

    # API credentials
    result["api_id"]   = int(data.get("api_id") or data.get("app_id") or 0)
    result["api_hash"] = str(data.get("api_hash") or data.get("app_hash") or "").strip()

    # كلمة مرور 2FA
    for key in ("two_step", "twoFA", "password", "2fa", "pass", "2FA", "p"):
        val = str(data.get(key) or "").strip()
        if val:
            result["two_factor"] = val
            break

    # session string (Pyrogram أو Telethon)
    for key in ("session_string", "session", "string_session", "pyrogram", "telethon"):
        val = str(data.get(key) or "").strip()
        if val:
            result["session_string"] = val
            break

    return result


def _is_pyrogram_v2(session_string: str) -> bool:
    """يتحقق إن كان session_string بصيغة Pyrogram v2 (271 بايت)."""
    try:
        padded = session_string + "=" * (-len(session_string) % 4)
        raw    = base64.urlsafe_b64decode(padded)
        return len(raw) == _PYROGRAM_V2_SIZE
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# الدالة الرئيسية: تحليل ملف ZIP
# ─────────────────────────────────────────────────────────────────────────────

def parse_telethon_zip(
    zip_path: str,
    api_id: int = 0,
    api_hash: str = "",
) -> list[dict]:
    """
    يحلّل ملف ZIP يحتوي على جلسات Telethon (.session) وملفات معلومات اختيارية (.txt / .json)،
    ويحوّل كل جلسة إلى سطر Pyrogram v2.

    يُعيد قائمة من القواميس بالمفاتيح:
        line      — سطر الحساب الجاهز للإدخال في قاعدة البيانات
        phone     — رقم الهاتف
        error     — رسالة الخطأ إن وُجدت
    """
    # حاول استيراد بيانات API من الإعدادات إذا لم تُمرَّر
    if not api_id or not api_hash:
        try:
            from config import DEFAULT_API_ID, DEFAULT_API_HASH
            api_id   = api_id   or (DEFAULT_API_ID   or 0)
            api_hash = api_hash or (DEFAULT_API_HASH or "")
        except ImportError:
            pass

    # الاحتياطي الافتراضي الرسمي لـ Telegram إذا لم تتورّد أي بيانات API
    api_id   = api_id   or 2040
    api_hash = api_hash or "b18441a1260828d0ed5d60f4eb70e775"

    results: list[dict] = []
    import tempfile
    tmp_dir = tempfile.mkdtemp(prefix="zip_parse_")

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            all_names     = zf.namelist()
            session_files = [n for n in all_names if n.lower().endswith(".session")]

            # خرائط الملفات المرافقة (بدون مسار، lowercase → اسم كامل)
            txt_map: dict[str, str]  = {
                os.path.basename(n).lower(): n
                for n in all_names if n.lower().endswith(".txt")
            }
            json_map: dict[str, str] = {
                os.path.basename(n).lower(): n
                for n in all_names if n.lower().endswith(".json")
            }

            # ── دعم ZIP يحتوي فقط على .json (بدون .session) ───────────────
            if not session_files:
                json_only = list(json_map.values())
                if json_only:
                    logger.info("ZIP يحتوي على ملفات .json فقط — محاولة القراءة المباشرة")
                    for jn in json_only:
                        try:
                            jtext = zf.read(jn).decode("utf-8", errors="ignore")
                            info  = _parse_json_info(jtext)
                        except Exception as ex:
                            results.append({"phone": "", "line": "", "error": str(ex)})
                            continue

                        phone = info.get("phone", "")
                        ss    = info.get("session_string", "")
                        j_api_id   = info.get("api_id",   0) or api_id
                        j_api_hash = info.get("api_hash", "") or api_hash
                        two_factor = info.get("two_factor", "")

                        if not phone or not ss or not j_api_id or not j_api_hash:
                            results.append({"phone": phone, "line": "", "error": "بيانات JSON ناقصة"})
                            continue

                        if _is_pyrogram_v2(ss):
                            line = f"{phone}::{j_api_id}::{j_api_hash}::{ss}"
                            if two_factor:
                                line += f"::{two_factor}"
                            results.append({"phone": phone, "line": line, "error": ""})
                        else:
                            results.append({"phone": phone, "line": "", "error": "session_string بصيغة غير مدعومة"})
                else:
                    logger.warning("لا توجد ملفات .session أو .json داخل: %s", zip_path)
                return results

            os.makedirs(tmp_dir, exist_ok=True)

            for sf in session_files:
                basename = os.path.basename(sf)
                stem     = os.path.splitext(basename)[0]
                out_ses  = os.path.join(tmp_dir, basename)

                # ── استخراج ملف الجلسة مؤقتاً ──────────────────────────
                try:
                    with zf.open(sf) as src, open(out_ses, "wb") as dst:
                        dst.write(src.read())
                except Exception as ex:
                    results.append({"phone": stem, "line": "", "error": f"فشل استخراج الملف: {ex}"})
                    continue

                ses_data = _read_telethon_session(out_ses)
                try:
                    os.remove(out_ses)
                except Exception:
                    pass

                if not ses_data:
                    results.append({"phone": stem, "line": "", "error": "ملف الجلسة تالف أو غير صالح"})
                    continue

                # ── البحث عن ملف المعلومات المرافق: JSON أولاً ثم TXT ────
                info = {"phone": "", "api_id": 0, "api_hash": "", "two_factor": "", "session_string": "", "user_id": 0}
                found_info = False

                for candidate in [f"{stem}.json", f"info_{stem}.json", f"{stem}_info.json"]:
                    if candidate.lower() in json_map:
                        try:
                            jtext = zf.read(json_map[candidate.lower()]).decode("utf-8", errors="ignore")
                            info  = _parse_json_info(jtext)
                            found_info = True
                        except Exception:
                            pass
                        break

                if not found_info:
                    for candidate in [f"info_{stem}.txt", f"{stem}.txt", f"{stem}_info.txt"]:
                        if candidate.lower() in txt_map:
                            try:
                                ttext = zf.read(txt_map[candidate.lower()]).decode("utf-8", errors="ignore")
                                parsed_txt = _parse_info_file(ttext)
                                info["phone"]      = parsed_txt.get("phone", "")
                                info["two_factor"] = parsed_txt.get("two_factor", "")
                            except Exception:
                                pass
                            break

                # ── تحديد رقم الهاتف ──────────────────────────────────
                phone = info.get("phone", "")
                if not phone:
                    digits = re.sub(r"\D", "", stem)
                    if len(digits) >= 7:
                        phone = "+" + digits

                if not phone:
                    results.append({"phone": stem, "line": "", "error": "تعذّر تحديد رقم الهاتف"})
                    continue

                # ── تحديد API credentials: من JSON أو الإعدادات ──────────
                eff_api_id   = int(info.get("api_id",   0) or 0) or int(api_id or 2040)
                eff_api_hash = str(info.get("api_hash", "") or api_hash or "b18441a1260828d0ed5d60f4eb70e775").strip()

                # ── ضمان عدم كون user_id صفراً ─────────────────────────
                user_id = ses_data.get("user_id", 0)
                if not user_id:
                    user_id = info.get("user_id", 0)
                if not user_id:
                    digits = re.sub(r"\D", "", phone)
                    if digits.isdigit():
                        user_id = int(digits)

                # ── التحويل إلى Pyrogram v2 ──────────────────────────────
                try:
                    session_string = _telethon_to_pyrogram(
                        dc_id    = ses_data["dc_id"],
                        auth_key = ses_data["auth_key"],
                        user_id  = user_id,
                        api_id   = eff_api_id,
                    )
                except Exception as conv_err:
                    results.append({"phone": phone, "line": "", "error": f"خطأ في التحويل: {conv_err}"})
                    continue

                two_factor = info.get("two_factor", "")
                line = f"{phone}::{eff_api_id}::{eff_api_hash}::{session_string}"
                if two_factor:
                    line += f"::{two_factor}"

                results.append({"phone": phone, "line": line, "error": ""})
                logger.info(
                    "تم تحويل جلسة %s للرقم %s (dc=%s)",
                    "JSON+session" if found_info else "Telethon",
                    phone, ses_data["dc_id"],
                )

    except zipfile.BadZipFile as e:
        logger.error("ملف ZIP تالف %s: %s", zip_path, e)
    except Exception as e:
        logger.error("خطأ في parse_telethon_zip: %s", e)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# تحليل ملف Pyrogram النصي
# ─────────────────────────────────────────────────────────────────────────────

def parse_pyrogram_txt(txt_path: str) -> list[dict]:
    """
    يحلّل ملفاً نصياً حيث كل سطر هو إدخال جلسة Pyrogram بأحد الصيغ:
        phone::session_string
        phone::api_id::api_hash::session_string
        phone::api_id::api_hash::session_string::2fa_password

    يُعيد قائمة من القواميس بالمفاتيح: line, phone, error.
    """
    results: list[dict] = []
    try:
        with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("::")
                phone = parts[0].strip() if parts else ""
                results.append({"phone": phone, "line": line, "error": ""})
    except Exception as e:
        logger.error("خطأ في parse_pyrogram_txt: %s", e)
    return results
