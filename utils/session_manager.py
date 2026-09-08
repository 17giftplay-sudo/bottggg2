import asyncio
import logging
import random
import re
import struct
from typing import Optional, Tuple
from datetime import datetime, timezone

from pyrogram import Client, filters
from pyrogram.errors import (
    AuthKeyUnregistered, UserDeactivated, SessionExpired,
    FloodWait, AuthKeyDuplicated, AuthKeyInvalid,
)

logger = logging.getLogger(__name__)

_PYROGRAM_V2_SESSION_BYTES = 271

async def _db_save(account_id, data):
    try:
        from database import save_pending_session
        await save_pending_session(account_id, data)
    except Exception as e:
        logger.warning("Could not persist session %s to DB: %s", account_id, e)

async def _db_update_refetch(account_id, count):
    try:
        from database import update_pending_session_refetch
        await update_pending_session_refetch(account_id, count)
    except Exception as e:
        logger.warning("Could not update refetch count for %s: %s", account_id, e)

async def _db_delete(account_id):
    try:
        from database import delete_pending_session
        await delete_pending_session(account_id)
    except Exception as e:
        logger.warning("Could not delete session %s from DB: %s", account_id, e)

CODE_WAIT_TIMEOUT = 120
TELEGRAM_OTP_ID   = 777000
MAX_REFETCH       = 2
LOGOUT_TIMEOUT    = 500
_CONNECT_RETRIES  = 3
_CONNECT_DELAY    = 5

_pending_sessions: dict[int, dict] = {}

_FATAL_AUTH_ERRORS = (
    AuthKeyUnregistered, UserDeactivated, SessionExpired,
    AuthKeyDuplicated, AuthKeyInvalid,
)
_NETWORK_ERRORS = (
    OSError, ConnectionError, ConnectionResetError,
    TimeoutError, asyncio.TimeoutError,
)

# ── أجهزة عشوائية لتنويع بصمة الاتصال ────────────────────────────────────────
_DEVICES = [
    # Samsung
    {"device_model": "Samsung Galaxy S23 Ultra", "system_version": "Android 14",   "app_version": "10.14.5"},
    {"device_model": "Samsung Galaxy A54",        "system_version": "Android 13",   "app_version": "10.12.2"},
    {"device_model": "Samsung Galaxy S21",         "system_version": "Android 12",   "app_version": "10.9.1"},
    # Xiaomi / Redmi
    {"device_model": "Xiaomi 13 Pro",             "system_version": "Android 13",   "app_version": "10.14.0"},
    {"device_model": "Redmi Note 12",              "system_version": "Android 12",   "app_version": "10.11.3"},
    {"device_model": "POCO X5 Pro",                "system_version": "Android 13",   "app_version": "10.13.1"},
    # Huawei
    {"device_model": "Huawei P60 Pro",             "system_version": "Android 11",   "app_version": "10.10.2"},
    {"device_model": "Huawei Nova 11",             "system_version": "Android 10",   "app_version": "10.8.4"},
    # Google Pixel
    {"device_model": "Pixel 7 Pro",                "system_version": "Android 14",   "app_version": "10.14.5"},
    {"device_model": "Pixel 6a",                   "system_version": "Android 13",   "app_version": "10.12.0"},
    # OnePlus
    {"device_model": "OnePlus 11",                 "system_version": "Android 13",   "app_version": "10.13.4"},
    # iPhone
    {"device_model": "iPhone 15 Pro Max",          "system_version": "iOS 17.4",     "app_version": "10.14.5"},
    {"device_model": "iPhone 14",                  "system_version": "iOS 16.6",     "app_version": "10.13.2"},
    {"device_model": "iPhone 13 mini",             "system_version": "iOS 16.2",     "app_version": "10.11.0"},
]

def _random_device() -> dict:
    return random.choice(_DEVICES)

# ── خريطة بادئات أرقام الهواتف → كود الدولة ISO ──────────────────────────────
_PHONE_PREFIXES: dict[str, str] = {
    # أمريكا الشمالية
    "+1":   "US",
    # أوروبا
    "+44":  "GB",
    "+49":  "DE",
    "+33":  "FR",
    "+34":  "ES",
    "+39":  "IT",
    "+31":  "NL",
    "+32":  "BE",
    "+41":  "CH",
    "+48":  "PL",
    "+46":  "SE",
    "+47":  "NO",
    "+45":  "DK",
    "+358": "FI",
    "+420": "CZ",
    "+40":  "RO",
    "+36":  "HU",
    "+351": "PT",
    "+30":  "GR",
    "+380": "UA",
    # روسيا / كازاخستان (نفس البادئة — نضعها كـ RU)
    "+7":   "RU",
    # الشرق الأوسط وشمال أفريقيا
    "+966": "SA",
    "+971": "AE",
    "+20":  "EG",
    "+964": "IQ",
    "+963": "SY",
    "+962": "JO",
    "+965": "KW",
    "+974": "QA",
    "+973": "BH",
    "+968": "OM",
    "+967": "YE",
    "+218": "LY",
    "+213": "DZ",
    "+212": "MA",
    "+216": "TN",
    "+249": "SD",
    "+961": "LB",
    "+972": "IL",
    # تركيا وإيران ومنطقة القوقاز
    "+90":  "TR",
    "+98":  "IR",
    "+994": "AZ",
    "+374": "AM",
    "+995": "GE",
    "+998": "UZ",
    "+93":  "AF",
    # جنوب ووسط آسيا
    "+92":  "PK",
    "+91":  "IN",
    "+880": "BD",
    # جنوب شرق آسيا
    "+62":  "ID",
    "+60":  "MY",
    "+63":  "PH",
    "+84":  "VN",
    "+66":  "TH",
    # شرق آسيا
    "+81":  "JP",
    "+82":  "KR",
    "+86":  "CN",
    # أفريقيا
    "+234": "NG",
    "+251": "ET",
    "+254": "KE",
    "+233": "GH",
    "+27":  "ZA",
    "+252": "SO",
    # أمريكا اللاتينية
    "+55":  "BR",
    "+52":  "MX",
    "+54":  "AR",
    "+57":  "CO",
    # أوقيانوسيا
    "+61":  "AU",
}
# رتّب البادئات من الأطول للأقصر حتى يُطابَق الأدق أولاً
_SORTED_PREFIXES = sorted(_PHONE_PREFIXES.keys(), key=len, reverse=True)


def _get_country_from_phone(phone: str) -> Optional[str]:
    """يعيد كود الدولة ISO من رقم الهاتف الدولي."""
    phone = phone.strip()
    if not phone.startswith("+"):
        phone = "+" + phone
    for prefix in _SORTED_PREFIXES:
        if phone.startswith(prefix):
            return _PHONE_PREFIXES[prefix]
    return None


def _get_proxy_for_phone(phone: str) -> Optional[dict]:
    """
    يختار أفضل بروكسي لدولة رقم الهاتف.
    - إذا وُجد بروكسي مُوسوم بنفس دولة الهاتف → يختاره عشوائياً من بروكسيات تلك الدولة.
    - إذا لم يوجد بروكسي للدولة → يختار بروكسياً عشوائياً من المجموعة الكاملة (Fallback).
    - إذا لم يوجد PROXY_POOL على الإطلاق → يُرجع None (لا بروكسي).
    """
    try:
        from config import PROXY_POOL
    except ImportError:
        return None
    if not PROXY_POOL:
        return None

    country = _get_country_from_phone(phone)
    if country:
        country_proxies = [p for p in PROXY_POOL if p.get("country") == country]
        if country_proxies:
            chosen = random.choice(country_proxies)
            logger.debug("Proxy selected for %s country=%s → %s:%s", phone, country, chosen["host"], chosen["port"])
            return chosen

    # Fallback عشوائي
    chosen = random.choice(PROXY_POOL)
    logger.debug("Proxy (random fallback) for %s → %s:%s", phone, chosen["host"], chosen["port"])
    return chosen


def _build_proxy_kwargs(phone: str) -> dict:
    """يبني معاملات البروكسي لتمريرها إلى Client()."""
    proxy = _get_proxy_for_phone(phone)
    if not proxy:
        return {}
    return {
        "proxy": {
            "scheme":   "socks5",
            "hostname": proxy["host"],
            "port":     proxy["port"],
            "username": proxy.get("username"),
            "password": proxy.get("password"),
        }
    }


def validate_session_string(session_string: str) -> bool:
    import base64
    try:
        padded = session_string + "=" * (-len(session_string) % 4)
        data   = base64.urlsafe_b64decode(padded)
        return len(data) == _PYROGRAM_V2_SESSION_BYTES
    except Exception:
        return False


def parse_account_data(raw: str) -> Optional[dict]:
    from config import DEFAULT_API_ID, DEFAULT_API_HASH, API_POOL

    parts = [p.strip() for p in raw.split("::")]

    if len(parts) == 2 or len(parts) == 3:
        phone          = parts[0]
        session_string = parts[1]
        two_factor     = parts[2] if len(parts) == 3 else ""
        # اختيار عشوائي من API_POOL إذا كان متاحاً
        if API_POOL:
            api_id, api_hash = random.choice(API_POOL)
        else:
            api_id   = DEFAULT_API_ID
            api_hash = DEFAULT_API_HASH
        if not api_id or not api_hash:
            logger.error("parse_account_data: short format used but DEFAULT_API_ID/HASH not set.")
            return None

    elif len(parts) >= 4:
        phone          = parts[0]
        api_id_str     = parts[1]
        api_hash       = parts[2]
        session_string = parts[3]
        two_factor     = parts[4] if len(parts) >= 5 else ""
        try:
            api_id = int(api_id_str)
        except ValueError:
            return None
        if not api_id:
            api_id = DEFAULT_API_ID
        if not api_hash:
            api_hash = DEFAULT_API_HASH

    else:
        return None

    if not api_id or not api_hash:
        logger.error(
            "parse_account_data: api_id/api_hash missing for %s and no DEFAULT set.",
            parts[0] if parts else "?",
        )
        return None

    if not validate_session_string(session_string):
        logger.error(
            "parse_account_data: session_string for %s is NOT valid Pyrogram v2 "
            "(must decode to %d bytes). Likely Pyrogram v1 or Telethon format.",
            phone, _PYROGRAM_V2_SESSION_BYTES,
        )
        return None

    return {
        "phone":          phone,
        "api_id":         api_id,
        "api_hash":       api_hash,
        "session_string": session_string,
        "two_factor":     two_factor,
        "session_valid":  True,
    }


def extract_code_from_message(text: str) -> Optional[str]:
    """
    يستخرج كود OTP من رسالة تيليجرام بدعم كامل للغات المتعددة:
    - العربية: الرمز هو / الكود هو
    - الروسية: код / ваш код
    - الإنجليزية: code / login code / your code
    - الصيغة العامة: أي رقم مؤلف من 5 أرقام في السياق الصحيح
    """
    if not text:
        return None

    # ── 1. بحث صريح بكلمات مفتاحية متعددة اللغة ──────────────────────────────
    patterns = [
        # إنجليزي
        r"(?:login\s+code|your\s+code|code)[:\s]+(\d{5})\b",
        # روسي — Код: XXXXX / ваш код: XXXXX / код для входа XXXXX
        r"(?:ваш\s+код|код\s+для\s+входа|код)[:\s]+(\d{5})\b",
        # عربي
        r"(?:الرمز|كود|الكود)[:\s]+(\d{5})\b",
        # صيغة عامة: رقم 5 أرقام مسبوق بـ : أو مسافة بعد كلمة
        r"\b(\d{5})\b",
    ]

    for pattern in patterns[:-1]:
        match = re.search(pattern, text, re.IGNORECASE | re.UNICODE)
        if match:
            return match.group(1)

    # ── 2. إذا لم تنجح الصيغ الصريحة، استخرج كل الأرقام وحلّل ───────────────
    all_numbers = re.findall(r"\b\d+\b", text)
    five_digit  = [n for n in all_numbers if len(n) == 5]

    if len(five_digit) == 1:
        return five_digit[0]

    if len(five_digit) >= 1 and len(text) < 200:
        candidate = five_digit[0]
        escaped = re.escape(candidate)
        if re.search(rf"(?<!\d){escaped}(?!\d)", text):
            return candidate

    return None


def get_session_buyer_id(account_id: int) -> Optional[int]:
    session = _pending_sessions.get(account_id)
    if not session:
        return None
    return session.get("buyer_id")


def get_refetch_remaining(account_id: int) -> int:
    session = _pending_sessions.get(account_id)
    if not session:
        return -1
    return MAX_REFETCH - session.get("refetch_count", 0)


async def _collect_history(client: Client, chat_id: int, limit: int = 10) -> list:
    """دالة مساعدة: تجمع سجل الرسائل في قائمة بدلاً من استخدام async for مباشرة."""
    return [m async for m in client.get_chat_history(chat_id, limit=limit)]


async def do_refetch_code(account_id: int) -> Tuple[Optional[str], int]:
    session = _pending_sessions.get(account_id)
    if not session:
        return None, -1
    if session.get("refetch_count", 0) >= MAX_REFETCH:
        return None, 0

    parsed = session["parsed"]
    client = None
    try:
        device = _random_device()
        client = Client(
            name=f"refetch_{parsed['phone'].replace('+', '')}",
            api_id=parsed["api_id"],
            api_hash=parsed["api_hash"],
            session_string=parsed["session_string"],
            in_memory=True,
            **{k: device[k] for k in device},
            **_build_proxy_kwargs(parsed["phone"]),
        )
        await asyncio.sleep(random.uniform(1.0, 3.0))
        # إصلاح التجميد: أضف timeout لكل خطوة شبكية
        _REFETCH_START_TIMEOUT   = 30   # ثانية لبدء الاتصال
        _REFETCH_HISTORY_TIMEOUT = 20   # ثانية لجلب سجل الرسائل
        try:
            await asyncio.wait_for(client.start(), timeout=_REFETCH_START_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("do_refetch_code: client.start() timed out for account %s", account_id)
            remaining = MAX_REFETCH - session.get("refetch_count", 0)
            return None, remaining

        try:
            messages = await asyncio.wait_for(
                _collect_history(client, TELEGRAM_OTP_ID, limit=10),
                timeout=_REFETCH_HISTORY_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("do_refetch_code: get_chat_history timed out for account %s", account_id)
            remaining = MAX_REFETCH - session.get("refetch_count", 0)
            return None, remaining

        found_code = None
        msgs = messages if isinstance(messages, list) else [messages]
        for msg in msgs:
            code = extract_code_from_message(getattr(msg, "text", "") or "")
            if code:
                found_code = code
                break

        if found_code:
            session["refetch_count"] = session.get("refetch_count", 0) + 1
            asyncio.ensure_future(_db_update_refetch(account_id, session["refetch_count"]))

        remaining = MAX_REFETCH - session.get("refetch_count", 0)
        return found_code, remaining

    except Exception as e:
        logger.error("do_refetch_code error for account %s: %s", account_id, e)
        remaining = MAX_REFETCH - session.get("refetch_count", 0)
        return None, remaining
    finally:
        if client is not None:
            try:
                await asyncio.wait_for(client.stop(), timeout=10)
            except Exception:
                pass


def is_session_timed_out(account_id: int) -> bool:
    session = _pending_sessions.get(account_id)
    if not session:
        return True
    sent_at = session.get("sent_at")
    if not sent_at:
        return False
    elapsed = (datetime.now(timezone.utc) - sent_at).total_seconds()
    return elapsed >= LOGOUT_TIMEOUT


async def do_logout_account(account_id: int) -> bool:
    session = _pending_sessions.get(account_id)
    if not session:
        return False
    parsed = session["parsed"]
    logged_out = False
    client = None
    try:
        device = _random_device()
        client = Client(
            name=f"logout_{parsed['phone'].replace('+', '')}",
            api_id=parsed["api_id"],
            api_hash=parsed["api_hash"],
            session_string=parsed["session_string"],
            in_memory=True,
            **{k: device[k] for k in device},
            **_build_proxy_kwargs(parsed["phone"]),
        )
        # إصلاح التجميد: أضف timeout لكل خطوة شبكية
        _LOGOUT_START_TIMEOUT  = 30   # ثانية لبدء الاتصال
        _LOGOUT_ACTION_TIMEOUT = 20   # ثانية لتنفيذ تسجيل الخروج
        try:
            await asyncio.wait_for(client.start(), timeout=_LOGOUT_START_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("do_logout_account: client.start() timed out for account %s", account_id)
        else:
            try:
                await asyncio.wait_for(client.log_out(), timeout=_LOGOUT_ACTION_TIMEOUT)
                logged_out = True
            except asyncio.TimeoutError:
                logger.warning("do_logout_account: client.log_out() timed out for account %s", account_id)
            except Exception as lo_err:
                logger.error("do_logout_account: log_out error for account %s: %s", account_id, lo_err)
    except Exception as e:
        logger.error("do_logout_account error for account %s: %s", account_id, e)
    finally:
        if client is not None:
            try:
                await asyncio.wait_for(client.stop(), timeout=10)
            except Exception:
                pass
        _pending_sessions.pop(account_id, None)
        await _db_delete(account_id)
    return logged_out


async def _auto_expire_session(account_id: int, delay: int = LOGOUT_TIMEOUT):
    await asyncio.sleep(delay)
    _pending_sessions.pop(account_id, None)
    await _db_delete(account_id)


async def restore_sessions_from_db():
    """
    يستعيد الجلسات المعلّقة من قاعدة البيانات بعد إعادة التشغيل.
    
    الإصلاح: كان يُعطي كل جلسة LOGOUT_TIMEOUT كاملاً بغض النظر عن متى أُنشئت،
    مما يجعل جلسة عمرها 490 ثانية تبقى 500 ثانية إضافية بدلاً من أن تُلغى فوراً.
    الآن نحسب الوقت المتبقي الفعلي ونتجاهل الجلسات المنتهية.
    """
    try:
        from database import load_all_pending_sessions
        rows = await load_all_pending_sessions()
        count   = 0
        expired = 0
        now_utc = datetime.now(timezone.utc)

        # احذف جميع الجلسات المنتهية من DB دفعة واحدة قبل المعالجة
        # (load_all_pending_sessions يُفلتر expires_at > now، لكن قد يكون هناك
        #  صفوف منتهية لم تُحذف بعد من استدعاءات سابقة فشلت)
        try:
            from database import get_pool
            pool = await get_pool()
            async with pool.acquire() as db:
                # إصلاح: DELETE...RETURNING COUNT(*) غير صحيح في PostgreSQL
                # نستخدم execute() ونقرأ العدد من نص النتيجة ("DELETE N")
                # PostgreSQL يخزن expires_at بدون timezone — نرسل naive datetime
                result = await db.execute(
                    "DELETE FROM pending_otp_sessions WHERE expires_at <= $1",
                    now_utc.replace(tzinfo=None),
                )
                deleted_count = 0
                if result and result.startswith("DELETE "):
                    try:
                        deleted_count = int(result.split()[-1])
                    except (ValueError, IndexError):
                        pass
                if deleted_count:
                    logger.info("Cleaned up %s already-expired OTP session(s) from DB at startup.", deleted_count)
        except Exception as cleanup_err:
            logger.warning("restore_sessions_from_db: startup cleanup failed: %s", cleanup_err)

        for row in rows:
            try:
                sent_at = row["sent_at"]
                if sent_at.tzinfo is None:
                    sent_at = sent_at.replace(tzinfo=timezone.utc)

                elapsed   = (now_utc - sent_at).total_seconds()
                remaining = LOGOUT_TIMEOUT - elapsed

                # الجلسة منتهية (وصلت هنا رغم الفلتر) — تجاهلها
                if remaining <= 0:
                    expired += 1
                    continue

                parsed = __import__('json').loads(row["parsed_json"])
                _pending_sessions[row["account_id"]] = {
                    "parsed":        parsed,
                    "buyer_id":      row["buyer_id"],
                    "lang":          row.get("lang", "ar"),
                    "country_name":  row.get("country_name", ""),
                    "refetch_count": row.get("refetch_count", 0),
                    "sent_at":       sent_at,
                }
                # استخدم الوقت المتبقي الفعلي لا LOGOUT_TIMEOUT الكامل
                asyncio.create_task(
                    _auto_expire_session(row["account_id"], delay=int(remaining))
                )
                count += 1
            except Exception as ex:
                logger.warning("Could not restore session %s: %s", row.get("account_id"), ex)

        if count:
            logger.info("Restored %s OTP session(s) from database.", count)
        if expired:
            logger.info("Cleaned up %s expired OTP session(s) from database.", expired)
    except Exception as e:
        logger.error("restore_sessions_from_db failed: %s", e)


_CLIENT_START_TIMEOUT = 30   # ثوانٍ — timeout لكل محاولة اتصال واحدة
_FLOODWAIT_MAX        = 60   # ثانية — الحد الأقصى للانتظار عند FloodWait


async def _start_client_with_retry(client: Client, phone: str) -> None:
    """
    يحاول الاتصال بالحساب مع إعادة المحاولة عند الأخطاء المؤقتة.

    إصلاح 1: كل محاولة محاطة بـ asyncio.wait_for بمهلة _CLIENT_START_TIMEOUT.
               قبل الإصلاح كان client.start() قد يتجمد للأبد عند مشكلة شبكة
               وبالتالي لا يصل البوت أبداً لكود إرجاع الأموال.

    إصلاح 2: FloodWait محدود بـ _FLOODWAIT_MAX ثانية.
               قبل الإصلاح كان قد ينتظر أياماً كاملة.
    """
    last_exc: Exception = RuntimeError("Unknown error")
    for attempt in range(1, _CONNECT_RETRIES + 1):
        try:
            await asyncio.wait_for(client.start(), timeout=_CLIENT_START_TIMEOUT)
            return
        except _FATAL_AUTH_ERRORS:
            raise
        except asyncio.TimeoutError:
            last_exc = asyncio.TimeoutError(
                f"client.start() timed out after {_CLIENT_START_TIMEOUT}s for {phone}"
            )
            logger.warning(
                "client.start() timed out (%ds) for %s (attempt %d/%d)",
                _CLIENT_START_TIMEOUT, phone, attempt, _CONNECT_RETRIES,
            )
            if attempt < _CONNECT_RETRIES:
                await asyncio.sleep(_CONNECT_DELAY)
        except struct.error as e:
            raise ValueError(f"Invalid session string format (not Pyrogram v2): {e}") from e
        except FloodWait as fw:
            # نحد الانتظار بـ _FLOODWAIT_MAX لمنع التجميد الطويل
            wait_time = min(fw.value, _FLOODWAIT_MAX)
            logger.warning(
                "FloodWait %ss (capped to %ss) for %s (attempt %d/%d)",
                fw.value, wait_time, phone, attempt, _CONNECT_RETRIES,
            )
            await asyncio.sleep(wait_time)
            last_exc = fw
        except _NETWORK_ERRORS as e:
            last_exc = e
            logger.warning(
                "Network error for %s (attempt %d/%d): %s — retrying in %ds",
                phone, attempt, _CONNECT_RETRIES, e, _CONNECT_DELAY,
            )
            if attempt < _CONNECT_RETRIES:
                await asyncio.sleep(_CONNECT_DELAY)
        except Exception as e:
            last_exc = e
            logger.warning(
                "Unexpected error for %s (attempt %d/%d): %s — retrying in %ds",
                phone, attempt, _CONNECT_RETRIES, e, _CONNECT_DELAY,
            )
            if attempt < _CONNECT_RETRIES:
                await asyncio.sleep(_CONNECT_DELAY)
    raise last_exc


async def wait_for_login_code(
    account_id: int,
    account_data_raw: str,
    buyer_id: int,
    bot,
    lang: str = "en",
    country_name: str = "",
    price: float = 0.0,
    flag: str = "🌍",
) -> bool:
    from database import (
        refund_account_purchase, get_setting, get_user
    )
    from translations import t
    from keyboards import code_actions_keyboard, rating_keyboard

    parsed = parse_account_data(account_data_raw)
    if not parsed:
        await refund_account_purchase(account_id, buyer_id, mark_invalid=True)
        await bot.send_message(
            buyer_id,
            t(lang, "session_format_error"),
            parse_mode="HTML",
        )
        return False

    await bot.send_message(
        buyer_id,
        t(lang, "session_waiting", phone=parsed["phone"], timeout=CODE_WAIT_TIMEOUT),
        parse_mode="HTML",
    )

    code_delivered = asyncio.Event()
    received_code: list[str] = []
    client: Optional[Client] = None

    try:
        device = _random_device()
        # تأخير عشوائي قبل الاتصال لتجنب الأنماط المنتظمة
        await asyncio.sleep(random.uniform(1.5, 4.0))

        client = Client(
            name=f"account_{parsed['phone'].replace('+', '')}",
            api_id=parsed["api_id"],
            api_hash=parsed["api_hash"],
            session_string=parsed["session_string"],
            in_memory=True,
            **{k: device[k] for k in device},
            **_build_proxy_kwargs(parsed["phone"]),
        )

        # نضع connect_time قبل بدء الاتصال بفارق أمان 10 ثوانٍ
        # لالتقاط أي كود وصل أثناء فترة الاتصال نفسها
        from datetime import timedelta as _td
        connect_time = datetime.now(timezone.utc) - _td(seconds=10)

        @client.on_message(filters.user(TELEGRAM_OTP_ID) & filters.private)
        async def on_code_message(_, message):
            msg_date = message.date
            if msg_date:
                if not msg_date.tzinfo:
                    msg_date = msg_date.replace(tzinfo=timezone.utc)
                # نقبل الرسائل الواصلة بعد connect_time - 10 ثوانٍ (هامش أمان)
                if msg_date < connect_time:
                    return
            code = extract_code_from_message(message.text or "")
            if code and not received_code:
                received_code.append(code)
                code_delivered.set()

        # إصلاح: نحيط مرحلة الاتصال الكاملة بـ timeout خارجي.
        # بدون هذا، لو تجمدت _start_client_with_retry بعد استنفاد كل محاولاتها
        # أو وقع خطأ غير متوقع، لا يصل البوت لكود إرجاع الأموال أبداً.
        _CONNECT_TOTAL_TIMEOUT = (_CLIENT_START_TIMEOUT + _CONNECT_DELAY) * _CONNECT_RETRIES + 10
        try:
            await asyncio.wait_for(
                _start_client_with_retry(client, parsed["phone"]),
                timeout=_CONNECT_TOTAL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error(
                "Total connection timeout (%ds) reached for %s — refunding buyer %s",
                _CONNECT_TOTAL_TIMEOUT, parsed["phone"], buyer_id,
            )
            await refund_account_purchase(account_id, buyer_id, mark_invalid=False)
            await bot.send_message(
                buyer_id,
                t(lang, "session_timeout"),
                parse_mode="HTML",
            )
            return False
        logger.info("Userbot connected for %s via device=%s", parsed["phone"], device.get("device_model"))

        # ── فحص فوري للسجل التاريخي بعد الاتصال ────────────────────────────────
        # قد يكون الكود وصل أثناء الاتصال أو قبله بقليل (هامش 10 ثوانٍ في connect_time)
        async def _check_history_once() -> bool:
            """يبحث في آخر 10 رسائل من 777000 — يُعيد True إذا وجد كوداً."""
            try:
                msgs = await asyncio.wait_for(
                    _collect_history(client, TELEGRAM_OTP_ID, limit=10),
                    timeout=15,
                )
                for msg in msgs:
                    msg_date = getattr(msg, "date", None)
                    if msg_date:
                        if not msg_date.tzinfo:
                            msg_date = msg_date.replace(tzinfo=timezone.utc)
                        if msg_date < connect_time:
                            continue
                    code = extract_code_from_message(getattr(msg, "text", "") or "")
                    if code and not received_code:
                        received_code.append(code)
                        code_delivered.set()
                        return True
            except Exception as hist_err:
                logger.warning("_check_history_once error: %s", hist_err)
            return False

        if not code_delivered.is_set():
            await _check_history_once()

        # ── Polling fallback: كل 15 ثانية نتحقق من السجل التاريخي ───────────────
        # السبب: أحياناً الـ event handler لا يُطلَق (انقطاع مؤقت، مشكلة Pyrogram)
        # حتى لو وصل الكود إلى حساب تيليجرام، يكتشفه الـ polling عند استطلاعه التالي.
        async def _poll_history():
            """يستطلع السجل التاريخي كل 15 ثانية طوال فترة الانتظار."""
            poll_interval = 15
            while not code_delivered.is_set():
                await asyncio.sleep(poll_interval)
                if code_delivered.is_set():
                    break
                await _check_history_once()

        poll_task = asyncio.create_task(_poll_history())

        try:
            await asyncio.wait_for(code_delivered.wait(), timeout=CODE_WAIT_TIMEOUT)
        except asyncio.TimeoutError:
            # أوقف مهمة الـ polling حتى لا تستمر بعد إيقاف الـ client
            poll_task.cancel()
            # عند انتهاء الوقت: نُعيد الحساب لـ 'available' مباشرةً
            # حتى يبقى في قائمة المخزون ويُعرض للبيع مجدداً بدلاً من حجبه في الصيانة
            await refund_account_purchase(account_id, buyer_id, mark_invalid=False)
            await bot.send_message(
                buyer_id,
                t(lang, "session_timeout"),
                parse_mode="HTML",
            )
            return False
        finally:
            poll_task.cancel()

        code = received_code[0]

        _sent_at   = datetime.now(timezone.utc)
        _expires_at = _sent_at + __import__('datetime').timedelta(seconds=LOGOUT_TIMEOUT)
        _pending_sessions[account_id] = {
            "parsed":        parsed,
            "buyer_id":      buyer_id,
            "lang":          lang,
            "country_name":  country_name,
            "refetch_count": 0,
            "sent_at":       _sent_at,
        }
        asyncio.create_task(_auto_expire_session(account_id, delay=LOGOUT_TIMEOUT))
        # نحفظ الجلسة في DB بشكل متزامن (await لا create_task)
        # السبب: لو حُفظت كـ background task وانهار البوت قبل تنفيذها،
        # الجلسة تكون في الذاكرة فقط وتضيع عند إعادة التشغيل مما يؤدي
        # لخسارة المستخدم لمشتراه بدون إمكانية استرداد تلقائي.
        await _db_save(account_id, {
            "parsed":        parsed,
            "buyer_id":      buyer_id,
            "lang":          lang,
            "country_name":  country_name,
            "refetch_count": 0,
            "sent_at":       _sent_at,
            "expires_at":    _expires_at,
        })

        if lang == "ar":
            code_msg = f"🔑 <b>كود تسجيل الدخول:</b>\n\n<code>{code}</code>"
        else:
            code_msg = f"🔑 <b>Login Code:</b>\n\n<code>{code}</code>"

        # نعيد قراءة account_data من DB لضمان الباسوورد الأحدث
        # (قد يكون تغيّر بعد الشراء بسبب عملية تغيير جماعي)
        try:
            from database import get_account_status_and_data
            _fresh = await get_account_status_and_data(account_id)
            if _fresh and _fresh.get("account_data"):
                _fresh_parts = [p.strip() for p in _fresh["account_data"].split("::")]
                if len(_fresh_parts) == 3:
                    _fresh_2fa = _fresh_parts[2]
                elif len(_fresh_parts) >= 5:
                    _fresh_2fa = _fresh_parts[4]
                else:
                    _fresh_2fa = ""
                if _fresh_2fa:
                    parsed = dict(parsed)
                    parsed["two_factor"] = _fresh_2fa
        except Exception as _rf_err:
            logger.debug("Could not refresh account_data before code send: %s", _rf_err)

        if parsed.get("two_factor"):
            if lang == "ar":
                code_msg += (
                    f"\n\n🔐 <b>باسوورد التحقق (2FA):</b>\n"
                    f"<code>{parsed['two_factor']}</code>\n"
                    f"<i>(انسخ الباسوورد واستخدمه إذا طلبه تيليجرام أثناء تسجيل الدخول)</i>"
                )
            elif lang == "fa":
                code_msg += (
                    f"\n\n🔐 <b>رمز عبور دومرحله‌ای (2FA):</b>\n"
                    f"<code>{parsed['two_factor']}</code>"
                )
            else:
                code_msg += (
                    f"\n\n🔐 <b>2FA Password:</b>\n"
                    f"<code>{parsed['two_factor']}</code>\n"
                    f"<i>(Copy and use if requested by Telegram)</i>"
                )

        await bot.send_message(
            buyer_id,
            code_msg,
            parse_mode="HTML",
            reply_markup=code_actions_keyboard(account_id, lang, refetch_remaining=MAX_REFETCH),
        )

        try:
            notif_channel = await get_setting("notification_channel")
            if notif_channel:
                now_str      = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
                phone_raw    = parsed["phone"]
                masked_phone = "*****" + phone_raw[-6:] if len(phone_raw) > 6 else phone_raw
                masked_buyer = "*****" + str(buyer_id)[-5:]
                notif_msg = (
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    "✅  <b>عملية شراء ناجحة</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"🌍  <b>الدولة :</b>  {flag} {country_name}\n"
                    f"📱  <b>المنصة :</b>  تليجرام\n"
                    f"📞  <b>الرقم :</b>  <code>{masked_phone}</code>\n"
                    f"💰  <b>السعر :</b>  {price:.2f} $\n"
                    f"👤  <b>العميل :</b>  <code>{masked_buyer}</code>\n"
                    f"🔑  <b>الكود :</b>  <code>{code}</code>\n"
                    f"🟢  <b>الحالة :</b>  تم التفعيل\n\n"
                    f"🗓  <b>التاريخ :</b>  {now_str}\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━"
                )
                from aiogram.utils.keyboard import InlineKeyboardBuilder as _NIK
                bot_info = await bot.get_me()
                notif_kb = _NIK()
                notif_kb.button(
                    text="🔗  ـ  رابط البوت  ـ  🔗",
                    url=f"https://t.me/{bot_info.username}",
                )
                await bot.send_message(
                    chat_id=notif_channel,
                    text=notif_msg,
                    parse_mode="HTML",
                    reply_markup=notif_kb.as_markup(),
                )
        except Exception as e:
            logger.error("Failed to send notification to channel: %s", e)

        return True

    except _FATAL_AUTH_ERRORS as e:
        logger.error("Fatal auth error for %s: %s", parsed["phone"], e)
        await refund_account_purchase(account_id, buyer_id, mark_invalid=True)
        await bot.send_message(
            buyer_id,
            t(lang, "session_error"),
            parse_mode="HTML",
        )
        return False

    except _NETWORK_ERRORS as e:
        logger.error(
            "Network error (after %d retries) for %s: %s — refunding without marking invalid",
            _CONNECT_RETRIES, parsed["phone"], e,
        )
        await refund_account_purchase(account_id, buyer_id, mark_invalid=False)
        await bot.send_message(
            buyer_id,
            t(lang, "session_network_error"),
            parse_mode="HTML",
        )
        return False

    except Exception as e:
        logger.error("Unexpected session error for %s: %s", parsed["phone"], e)
        await refund_account_purchase(account_id, buyer_id, mark_invalid=False)
        await bot.send_message(
            buyer_id,
            t(lang, "session_error"),
            parse_mode="HTML",
        )
        return False

    finally:
        if client is not None:
            try:
                await client.stop()
            except Exception:
                pass
