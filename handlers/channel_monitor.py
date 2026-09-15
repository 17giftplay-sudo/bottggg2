import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Router, Bot, F
from aiogram.types import ChatMemberUpdated
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER

from database import (
    get_user,
    get_setting,
    add_pending_leave,
    remove_pending_leave,
    get_pending_leave,
    get_all_pending_leaves,
    delete_pending_leave,
    deduct_balance,
    deduct_points,
    set_user_banned,
)

router = Router()
logger = logging.getLogger(__name__)

GRACE_HOURS = 24


# ─────────────────────────────────────────────────────────────────────────────
# مراقبة مغادرة القناة
# ─────────────────────────────────────────────────────────────────────────────

@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def on_user_leave_channel(event: ChatMemberUpdated, bot: Bot):
    """
    عند مغادرة المستخدم للقناة، لا يتم حظره أو معاقبته بناءً على رغبة الإدارة.
    """
    user_id = event.new_chat_member.user.id
    logger.info("User %s left channel — no ban or penalty applied.", user_id)
    return


@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def on_user_rejoin_channel(event: ChatMemberUpdated, bot: Bot):
    """
    يُستدعى عندما يعود المستخدم للاشتراك في القناة.
    """
    user_id = event.new_chat_member.user.id
    await delete_pending_leave(user_id)
    logger.info("User %s rejoined channel.", user_id)


# ─────────────────────────────────────────────────────────────────────────────
# مهمة الخلفية: فحص المغادرين
# ─────────────────────────────────────────────────────────────────────────────

async def check_pending_leaves_loop(bot: Bot):
    """
    معطلة — لا يتم حظر المستخدمين المغادرين للقناة.
    """
    while True:
        await asyncio.sleep(3600)


async def _process_expired_leaves(bot: Bot):
    pass


async def _apply_penalty(bot: Bot, user_id: int):
    pass



# ─────────────────────────────────────────────────────────────────────────────
# لوحة مفاتيح إعادة الانضمام
# ─────────────────────────────────────────────────────────────────────────────

def _rejoin_keyboard(channel: str, lang: str):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    link = channel if channel.startswith("http") else f"https://t.me/{channel.lstrip('@')}"
    builder.button(
        text="📢 اشترك الآن" if lang == "ar" else "📢 Subscribe Now",
        url=link,
    )
    builder.button(
        text="✅ تحققت من الاشتراك" if lang == "ar" else "✅ I re-subscribed",
        callback_data="check:rejoin",
    )
    builder.adjust(1)
    return builder.as_markup()


@router.callback_query(F.data == "check:rejoin")
async def check_rejoin(callback, bot: Bot):
    user_id           = callback.from_user.id
    force_sub_channel = await get_setting("force_sub_channel")
    user              = await get_user(user_id)
    lang              = user.get("language", "ar") if user else "ar"

    if not force_sub_channel:
        await callback.answer()
        return

    still_left = await _check_user_not_in_channel(bot, force_sub_channel, user_id)

    if still_left:
        pending = await get_pending_leave(user_id)
        if pending:
            deadline = _normalize_datetime(pending["deadline"])
            remaining = deadline - datetime.now(timezone.utc)
            hours_left = max(0, int(remaining.total_seconds() // 3600))
            mins_left  = max(0, int((remaining.total_seconds() % 3600) // 60))
            await callback.answer(
                (
                    f"⚠️ لم تشترك بعد!\n"
                    f"المتبقي: {hours_left}س {mins_left}د"
                ) if lang == "ar" else (
                    f"⚠️ Not subscribed yet!\n"
                    f"Remaining: {hours_left}h {mins_left}m"
                ),
                show_alert=True,
            )
        else:
            await callback.answer(
                "⚠️ لست مشتركاً في القناة." if lang == "ar" else "⚠️ You are not in the channel.",
                show_alert=True,
            )
    else:
        await delete_pending_leave(user_id)
        await set_user_banned(user_id, banned=False, reason=None)
        await callback.answer(
            "✅ تم التحقق! حسابك بخير." if lang == "ar" else "✅ Verified! Your account is fine.",
            show_alert=True,
        )
        try:
            await callback.message.delete()
        except Exception:
            pass
