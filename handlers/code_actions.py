import asyncio
import logging

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery

from database import add_rating, get_user
from keyboards import code_actions_keyboard, rating_keyboard
from utils.session_manager import (
    do_refetch_code,
    do_logout_account,
    get_refetch_remaining,
    get_session_buyer_id,
    is_session_timed_out,
    LOGOUT_TIMEOUT,
)

router = Router()
logger = logging.getLogger(__name__)

MAX_REFETCH = 2


def _timeout_text(lang: str) -> str:
    if lang == "ar":
        return f"⏰ لقد مرّ الوقت المحدد ({LOGOUT_TIMEOUT} ثانية). لا تستطيع فعل هذا الإجراء."
    return f"⏰ The allowed time ({LOGOUT_TIMEOUT}s) has passed. You can no longer perform this action."


@router.callback_query(F.data.startswith("code_refetch:"))
async def handle_code_refetch(callback: CallbackQuery, bot: Bot):
    try:
        account_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("❌", show_alert=True)
        return

    user  = await get_user(callback.from_user.id)
    lang  = user.get("language", "ar") if user else "ar"

    # ── تحقق من الملكية: فقط المشتري الحقيقي يستطيع استخدام هذه الجلسة ─────
    buyer_id = get_session_buyer_id(account_id)
    if buyer_id is not None and buyer_id != callback.from_user.id:
        logger.warning(
            "Unauthorized refetch attempt: user=%s tried account_id=%s (owner=%s)",
            callback.from_user.id, account_id, buyer_id,
        )
        await callback.answer("⛔ غير مصرح.", show_alert=True)
        return

    # تحقق من المؤقت أولاً
    if is_session_timed_out(account_id):
        await callback.answer(_timeout_text(lang), show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    remaining = get_refetch_remaining(account_id)

    if remaining <= 0:
        await callback.answer(
            "⛔ لا يمكنك إعادة الجلب أكثر من مرتين." if lang == "ar"
            else "⛔ You cannot re-fetch more than twice.",
            show_alert=True,
        )
        return

    await callback.answer(
        "⏳ جاري جلب الكود..." if lang == "ar" else "⏳ Fetching code...",
        show_alert=False,
    )

    code, new_remaining = await do_refetch_code(account_id)

    # قد تنتهي الجلسة أثناء الجلب
    if new_remaining == -1:
        await callback.message.answer(
            _timeout_text(lang),
            parse_mode="HTML",
        )
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    if code is None:
        kb = code_actions_keyboard(account_id, lang, refetch_remaining=new_remaining)
        await callback.message.answer(
            (
                "❌ لم يتم العثور على كود بعد. إذا طلبت الكود، انتظر لحظة ثم أعد المحاولة."
                if lang == "ar" else
                "❌ No code found yet. If you requested a login code, wait a moment and try again."
            ),
            parse_mode="HTML",
            reply_markup=kb,
        )
    else:
        from database import get_account_status_and_data
        _acc = await get_account_status_and_data(account_id)
        two_factor = ""
        if _acc and _acc.get("account_data"):
            _pts = [p.strip() for p in _acc["account_data"].split("::")]
            two_factor = _pts[2] if len(_pts) == 3 else (_pts[4] if len(_pts) >= 5 else "")

        code_text = f"🔑 <b>الكود:</b> <code>{code}</code>" if lang == "ar" else f"🔑 <b>Code:</b> <code>{code}</code>"
        if two_factor:
            if lang == "ar":
                code_text += f"\n🔐 <b>باسوورد التحقق (2FA):</b> <code>{two_factor}</code>"
            elif lang == "fa":
                code_text += f"\n🔐 <b>رمز عبور دومرحله‌ای (2FA):</b> <code>{two_factor}</code>"
            else:
                code_text += f"\n🔐 <b>2FA Password:</b> <code>{two_factor}</code>"

        kb = code_actions_keyboard(account_id, lang, refetch_remaining=new_remaining)
        await callback.message.answer(
            code_text,
            parse_mode="HTML",
            reply_markup=kb,
        )

    # تحديث لوحة مفاتيح الرسالة الأصلية
    try:
        await callback.message.edit_reply_markup(
            reply_markup=code_actions_keyboard(account_id, lang, refetch_remaining=new_remaining)
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("code_logout:"))
async def handle_code_logout(callback: CallbackQuery):
    """يعرض رسالة تأكيد قبل تسجيل الخروج — لمنع الضغط العرضي."""
    try:
        account_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("❌", show_alert=True)
        return

    user = await get_user(callback.from_user.id)
    lang = user.get("language", "ar") if user else "ar"

    # ── تحقق من الملكية ───────────────────────────────────────────────────
    buyer_id = get_session_buyer_id(account_id)
    if buyer_id is not None and buyer_id != callback.from_user.id:
        logger.warning(
            "Unauthorized logout attempt: user=%s tried account_id=%s (owner=%s)",
            callback.from_user.id, account_id, buyer_id,
        )
        await callback.answer("⛔ غير مصرح.", show_alert=True)
        return

    # تحقق من المؤقت
    if is_session_timed_out(account_id):
        await callback.answer(_timeout_text(lang), show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    # ── عرض نافذة تأكيد بدلاً من التنفيذ الفوري ─────────────────────────
    from aiogram.utils.keyboard import InlineKeyboardBuilder as _IKB
    confirm_kb = _IKB()
    if lang == "ar":
        confirm_kb.button(text="✅ نعم، سجّل الخروج", callback_data=f"code_logout_confirm:{account_id}")
        confirm_kb.button(text="❌ إلغاء",              callback_data=f"code_logout_cancel:{account_id}")
        confirm_text = (
            "⚠️ <b>تأكيد تسجيل الخروج</b>\n\n"
            "هل أنت متأكد؟ بعد تسجيل الخروج لن تتمكن من الدخول للحساب مجدداً."
        )
    else:
        confirm_kb.button(text="✅ Yes, log out", callback_data=f"code_logout_confirm:{account_id}")
        confirm_kb.button(text="❌ Cancel",        callback_data=f"code_logout_cancel:{account_id}")
        confirm_text = (
            "⚠️ <b>Confirm Logout</b>\n\n"
            "Are you sure? After logging out you won't be able to access this account again."
        )
    confirm_kb.adjust(1)

    await callback.answer()
    await callback.message.answer(
        confirm_text,
        reply_markup=confirm_kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("code_logout_cancel:"))
async def handle_code_logout_cancel(callback: CallbackQuery):
    """يلغي طلب تسجيل الخروج."""
    user = await get_user(callback.from_user.id)
    lang = user.get("language", "ar") if user else "ar"
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer(
        "تم الإلغاء." if lang == "ar" else "Cancelled.",
        show_alert=False,
    )


@router.callback_query(F.data.startswith("code_logout_confirm:"))
async def handle_code_logout_confirm(callback: CallbackQuery):
    """ينفّذ تسجيل الخروج بعد تأكيد المستخدم."""
    try:
        account_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("❌", show_alert=True)
        return

    user = await get_user(callback.from_user.id)
    lang = user.get("language", "ar") if user else "ar"

    # تحقق من الملكية مجدداً
    buyer_id = get_session_buyer_id(account_id)
    if buyer_id is not None and buyer_id != callback.from_user.id:
        await callback.answer("⛔ غير مصرح.", show_alert=True)
        return

    # تحقق من المؤقت
    if is_session_timed_out(account_id):
        await callback.answer(_timeout_text(lang), show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    await callback.answer(
        "⏳ جاري تسجيل الخروج..." if lang == "ar" else "⏳ Logging out...",
        show_alert=False,
    )

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    success = await do_logout_account(account_id)

    if success:
        await callback.message.answer(
            "✅ <b>تم تسجيل الخروج من الحساب بنجاح.</b>" if lang == "ar"
            else "✅ <b>Account logged out successfully.</b>",
            parse_mode="HTML",
        )
    else:
        await callback.message.answer(
            "⚠️ تعذّر تسجيل الخروج. ربما انتهت صلاحية الجلسة." if lang == "ar"
            else "⚠️ Could not log out — session may have expired.",
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("rate:"))
async def handle_rating(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return

    try:
        account_id = int(parts[1])
        stars      = int(parts[2])
    except ValueError:
        await callback.answer()
        return

    user    = await get_user(callback.from_user.id)
    lang    = user.get("language", "ar") if user else "ar"
    user_id = callback.from_user.id

    if stars == 0:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.answer(
            "⏭ تم التخطي." if lang == "ar" else "⏭ Skipped.", show_alert=False
        )
        return

    from database import get_pool
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            "SELECT country_code, sold_to_user_id FROM accounts_inventory WHERE id = $1",
            account_id,
        )

    # ── تحقق من الملكية: فقط من اشترى الحساب يستطيع تقييمه ──────────────────
    if not row or row["sold_to_user_id"] != user_id:
        logger.warning(
            "Unauthorized rating attempt: user=%s tried account_id=%s",
            user_id, account_id,
        )
        await callback.answer("⛔ غير مصرح.", show_alert=True)
        return

    country_code = row["country_code"]
    await add_rating(account_id, user_id, country_code, stars)

    star_line = "⭐" * stars
    await callback.answer(
        f"{star_line} شكراً لتقييمك!" if lang == "ar"
        else f"{star_line} Thanks for your rating!",
        show_alert=True,
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
  
