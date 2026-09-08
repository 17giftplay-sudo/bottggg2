"""
stars_rating_checker.py
─────────────────────────────────────────────────────────────────────────────
يستخدم حساب Pyrogram عادي للتحقق من تقييم نجوم مستخدم معين قبل قبول الدفع.

طريقة الفحص (بالترتيب):
  1. قائمة الحظر الداخلية (مستخدمون سبق وتسبّبوا في استرداد نجوم).
  2. علامات الحساب الصريحة: is_scam / is_fake / is_restricted.
  3. علامة disallow_higher_star_gifts في UserFull (تقييم سلبي للنجوم).
  4. stars_amount < 1 أو غير موجود أصلاً (None/0) → يُحجب (يُسمح فقط لمن ≥ 1).

السلوك عند عدم وجود حساب مراقبة (stars_checker_session فارغ):
  → (True, "no_checker") — يمنع الدفع تلقائياً حتى يُضبط الحساب.

السلوك عند timeout أو خطأ اتصال:
  → (False, "") — نقبل الدفع (fail-open) لتجنب منع جميع المستخدمين
     بسبب مشكلة مؤقتة في الاتصال.
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import logging
from typing import Optional, Tuple

from pyrogram import Client
from pyrogram.errors import (
    FloodWait, PeerIdInvalid, UserDeactivated,
    AuthKeyUnregistered, SessionExpired,
)
from pyrogram.raw.functions.users import GetFullUser

logger = logging.getLogger(__name__)

# ── Singleton client ───────────────────────────────────────────────────────────
_checker_client: Optional[Client] = None
_client_lock = asyncio.Lock()


def _parse_session(raw: str) -> Tuple[str, int, str, str]:
    """
    يقبل أحد الصيغتين:
      phone::api_id::api_hash::session_string   (صيغة كاملة)
      session_string                            (صيغة مختصرة — يستخدم DEFAULT_API_*)

    maxsplit=3 يضمن أن session_string يبقى كاملاً حتى لو احتوى على ::.
    """
    parts = raw.strip().split("::", maxsplit=3)
    if len(parts) == 4:
        phone, api_id_str, api_hash, session = parts
        return phone, int(api_id_str), api_hash, session
    if len(parts) == 1:
        from config import DEFAULT_API_ID, DEFAULT_API_HASH
        if not DEFAULT_API_ID or not DEFAULT_API_HASH:
            raise ValueError(
                "الصيغة المختصرة تتطلب DEFAULT_API_ID و DEFAULT_API_HASH في الإعدادات."
            )
        return "", DEFAULT_API_ID, DEFAULT_API_HASH, parts[0]
    raise ValueError(f"صيغة session غير صحيحة ({len(parts)} جزء).")


async def _build_client(session_data: str) -> Client:
    phone, api_id, api_hash, session = _parse_session(session_data)
    client = Client(
        name="stars_checker",
        api_id=api_id,
        api_hash=api_hash,
        session_string=session,
        in_memory=True,
        no_updates=True,
    )
    await client.start()
    me = await client.get_me()
    logger.info(
        "stars_checker: متصل كـ %s (id=%s)",
        me.first_name, me.id,
    )
    return client


async def get_checker_client() -> Optional[Client]:
    """يُرجع client جاهز أو None إذا لم يُضبط حساب الفحص."""
    global _checker_client
    async with _client_lock:
        if _checker_client is not None:
            try:
                if _checker_client.is_connected:
                    return _checker_client
            except Exception:
                pass
            _checker_client = None

        try:
            from database import get_setting
            raw = await get_setting("stars_checker_session")
            if not raw:
                logger.warning("stars_checker: stars_checker_session غير مضبوط في الإعدادات.")
                return None
            _checker_client = await _build_client(raw)
            return _checker_client
        except (AuthKeyUnregistered, SessionExpired) as e:
            logger.error("stars_checker: الجلسة منتهية أو غير صالحة — %s", e)
            _checker_client = None
            return None
        except Exception as e:
            logger.warning("stars_checker: فشل الاتصال — %s", e)
            _checker_client = None
            return None


async def reset_checker_client() -> None:
    """يُعاد الاستدعاء بعد تحديث بيانات الحساب في الإعدادات."""
    global _checker_client
    async with _client_lock:
        if _checker_client is not None:
            try:
                await _checker_client.stop()
            except Exception:
                pass
            _checker_client = None
    logger.info("stars_checker: تم إعادة تعيين client.")


async def check_user_stars_rating(user_id: int) -> Tuple[bool, str]:
    from database import is_stars_banned, is_trusted_stars_customer, get_setting

    # ── 0. فحص هل ميزة التحقق من تقييم النجوم مفعّلة أم معطّلة من الأدمن ──────
    check_enabled = await get_setting("stars_rating_check_enabled")
    if check_enabled == "0":
        logger.info("stars_checker: التحقق معطّل من لوحة التحكم → قبول الشحن للجميع")
        return False, ""

    # ── 1. قائمة الحظر المباشر (أولوية قصوى) ──────────────────────────────────
    if await is_stars_banned(user_id):
        logger.info("stars_checker: user %s محظور (refund_history)", user_id)
        return True, "refund_history"

    # ── 2. استثناء العملاء الموثوقين الذين شحنوا سابقاً دون استرداد ─────────────
    if await is_trusted_stars_customer(user_id):
        logger.info("stars_checker: user %s عميل موثوق شحن سابقاً دون مشاكل → مسموح", user_id)
        return False, ""

    # ── 3. فحص وجود حساب المراقبة للمستخدمين الجدد ─────────────────────────────
    client = await get_checker_client()
    if client is None:
        logger.warning(
            "stars_checker: user %s — لا يوجد حساب مراقبة مضبوط → يمنع المستخدمين الجدد",
            user_id,
        )
        return True, "no_checker"

    # ── 4. فحص عبر MTProto للحسابات الجديدة ───────────────────────────────────
    async def _do_mtproto_check() -> Tuple[bool, str]:
        try:
            # أ) فحص العلامات الصريحة
            try:
                user_obj = await client.get_users(user_id)
                if getattr(user_obj, "is_scam", False):
                    return True, "scam"
                if getattr(user_obj, "is_fake", False):
                    return True, "fake"
                if getattr(user_obj, "is_restricted", False):
                    return True, "restricted"
            except Exception as pe:
                logger.debug("stars_checker: get_users لم يتعرف على %s: %s", user_id, pe)

            # ب) فحص UserFull (تقييم النجوم ومستوى الحساب)
            peer = await client.resolve_peer(user_id)
            full_result = await client.invoke(GetFullUser(id=peer))
            user_full = full_result.full_user

            if getattr(user_full, "disallow_higher_star_gifts", False):
                logger.info("stars_checker: user %s — تقييم سلبي (disallow_higher_star_gifts)", user_id)
                return True, "negative_rating"

            stars_amount = getattr(user_full, "stars_amount", None)
            if stars_amount is None or int(stars_amount) < 1:
                logger.info(
                    "stars_checker: user %s — stars_amount=%s (لا يوجد تقييم أو سلبي → محجوب)",
                    user_id, stars_amount,
                )
                return True, "negative_rating"

            logger.info(
                "stars_checker: user %s — stars_amount=%s ≥ 1 ✅",
                user_id, stars_amount,
            )
            return False, ""

        except PeerIdInvalid:
            logger.warning("stars_checker: user %s — PeerIdInvalid حساب جديد غير محقق → محجوب", user_id)
            return True, "unverifiable_new_account"
        except UserDeactivated:
            logger.info("stars_checker: user %s — حساب معطل/محذوف", user_id)
            return True, "deactivated"
        except FloodWait as e:
            logger.warning("stars_checker: FloodWait %ds لـ user %s → محجوب للمستخدم الجديد", e.value, user_id)
            return True, "unverifiable_new_account"
        except Exception as e:
            logger.warning("stars_checker: خطأ فحص الحساب %s: %s → محجوب للمستخدم الجديد", user_id, e)
            return True, "unverifiable_new_account"

    try:
        return await asyncio.wait_for(_do_mtproto_check(), timeout=5.0)
    except asyncio.TimeoutError:
        logger.warning("stars_checker: timeout 5s للمستخدم الجديد %s → محجوب", user_id)
        return True, "unverifiable_new_account"
