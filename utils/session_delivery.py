"""
تجهيز الجلسة للتسليم:
  1. اتصال بـ Telegram عبر Pyrogram (بـ semaphore لتجنب الـ flood)
  2. جلب معلومات الحساب (username / user_id / name)
  3. تغيير الباسوورد إلى new_password (أو إزالته إذا كان فارغاً)
  4. توليد ملف .session بصيغة Telethon v8 في thread منفصل

يُرجع dict مع كل المعلومات، أو dict مع ok=False إذا فشل الاتصال.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 30
_OP_TIMEOUT      = 25

# حد أقصى 5 اتصالات Pyrogram متزامنة لتجنب FloodWait وضغط الموارد
_SEMAPHORE = asyncio.Semaphore(5)


async def prepare_session_for_delivery(account_data: str, new_password: str = "") -> dict:
    """
    يجهّز حساباً واحداً للتسليم كجلسة.

    new_password: الباسوورد الجديد الذي سيُطبَّق.
                  إذا كان فارغاً → يُزال الباسوورد تماماً.

    يُرجع dict:
        ok              → bool
        phone           → str
        api_id          → int
        api_hash        → str
        session_string  → str
        session_bytes   → bytes   (ملف .session Telethon v8، b'' إذا فشل التوليد)
        username        → str
        full_name       → str
        user_id         → int
        new_password    → str
        password_changed → bool
        error           → str
    """
    from utils.session_manager import parse_account_data, _random_device, _build_proxy_kwargs
    from pyrogram import Client
    from pyrogram.errors import (
        AuthKeyUnregistered, UserDeactivated, SessionExpired,
        AuthKeyDuplicated, AuthKeyInvalid,
    )

    parsed = parse_account_data(account_data)
    if not parsed:
        return {"ok": False, "error": "parse_failed",
                "phone": account_data.split("::")[0],
                "new_password": new_password,
                "session_bytes": b""}

    phone       = parsed["phone"]
    api_id      = parsed["api_id"]
    api_hash    = parsed["api_hash"]
    session_str = parsed["session_string"]
    two_factor  = parsed.get("two_factor", "")

    device = _random_device()
    client = Client(
        name=f"delivery_{phone.replace('+', '')}",
        api_id=api_id,
        api_hash=api_hash,
        session_string=session_str,
        in_memory=True,
        no_updates=True,
        **{k: device[k] for k in device},
        **_build_proxy_kwargs(phone),
    )

    result = {
        "ok":              False,
        "phone":           phone,
        "api_id":          api_id,
        "api_hash":        api_hash,
        "session_string":  session_str,
        "session_bytes":   b"",
        "username":        "",
        "full_name":       "",
        "user_id":         0,
        "new_password":    new_password,
        "password_changed": False,
        "error":           "",
    }

    async with _SEMAPHORE:
        try:
            await asyncio.wait_for(client.start(), timeout=_CONNECT_TIMEOUT)

            # ── معلومات الحساب ────────────────────────────────────────────────
            try:
                me = await asyncio.wait_for(client.get_me(), timeout=_OP_TIMEOUT)
                result["user_id"]   = me.id
                result["full_name"] = f"{me.first_name or ''} {me.last_name or ''}".strip()
                result["username"]  = f"@{me.username}" if me.username else ""
            except Exception as e:
                logger.warning("get_me failed for %s: %s", phone, e)

            result["ok"] = True

        except (AuthKeyUnregistered, UserDeactivated, SessionExpired,
                AuthKeyDuplicated, AuthKeyInvalid) as e:
            result["error"] = f"dead_session:{type(e).__name__}"
            logger.warning("Dead session %s: %s", phone, e)
        except asyncio.TimeoutError:
            result["error"] = "connection_timeout"
            logger.warning("Timeout connecting %s", phone)
        except Exception as e:
            err_str = str(e).lower()
            # EOF = Telegram رفض auth_key (-404) → جلسة منتهية
            if "eof" in err_str or "-404" in err_str or "auth_key" in err_str:
                result["error"] = "dead_session:EOF"
                logger.warning("Dead session (EOF/auth_key rejected) %s: %s", phone, e)
            else:
                result["error"] = str(e)
                logger.error("prepare_session_for_delivery %s: %s", phone, e)
        finally:
            try:
                await client.stop()
            except Exception:
                pass

    # ── توليد ملف .session Telethon v8 في thread منفصل (blocking I/O) ────────
    if result["ok"] or result.get("session_string"):
        try:
            from utils.session_converter import session_string_to_telethon_sqlite
            result["session_bytes"] = await asyncio.to_thread(
                session_string_to_telethon_sqlite,
                result["session_string"],
                phone,
                result.get("user_id", 0),
                result.get("username", "").lstrip("@"),
                result.get("full_name", ""),
            )
        except Exception as e:
            logger.warning("telethon sqlite failed for %s: %s", phone, e)

    return result



