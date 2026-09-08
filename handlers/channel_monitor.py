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
    يُستدعى عندما يغادر مستخدم القناة أو يُطرد منها.
    يبدأ فترة سماح 24 ساعة قبل تطبيق العقوبة.
    """
    force_sub_channel = await get_setting("force_sub_channel")
    if not force_sub_channel:
        return

    try:
        channel_id = (await bot.get_chat(force_sub_channel)).id
    except Exception:
        return

    if event.chat.id != channel_id:
        return

    user_id = event.new_chat_member.user.id

    if event.new_chat_member.user.is_bot:
        return

    user = await get_user(user_id)
    if not user:
        return

    existing = await get_pending_leave(user_id)
    if existing:
        return

    deadline = datetime.now(timezone.utc) + timedelta(hours=GRACE_HOURS)
    await add_pending_leave(user_id, deadline)

    logger.info(
        "User %s left channel %s — grace period until %s",
        user_id,
        force_sub_channel,
        deadline.isoformat(),
    )

    lang = user.get("language", "ar")
    try:
        await bot.send_message(
            user_id,
            (
                f"⚠️ <b>تنبيه: غادرت قناة الاشتراك الإجباري</b>\n\n"
                f"لديك <b>{GRACE_HOURS} ساعة</b> للعودة للاشتراك قبل أن يتم تعليق حسابك.\n\n"
                f"اضغط الزر أدناه للاشتراك مجدداً:"
            ) if lang == "ar" else (
                f"⚠️ <b>Warning: You left the required channel</b>\n\n"
                f"You have <b>{GRACE_HOURS} hours</b> to re-subscribe before your account is suspended.\n\n"
                f"Press the button below to re-subscribe:"
            ),
            reply_markup=_rejoin_keyboard(force_sub_channel, lang),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning("Could not notify user %s about leaving: %s", user_id, e)


@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def on_user_rejoin_channel(event: ChatMemberUpdated, bot: Bot):
    """
    يُستدعى عندما يعود المستخدم للاشتراك في القناة.
    يلغي فترة السماح المعلقة.
    """
    force_sub_channel = await get_setting("force_sub_channel")
    if not force_sub_channel:
        return

    try:
        channel_id = (await bot.get_chat(force_sub_channel)).id
    except Exception:
        return

    if event.chat.id != channel_id:
        return

    user_id = event.new_chat_member.user.id

    pending = await get_pending_leave(user_id)
    if not pending:
        return

    await delete_pending_leave(user_id)

    logger.info("User %s rejoined channel — pending leave cancelled.", user_id)

    user = await get_user(user_id)
    if not user:
        return
    lang = user.get("language", "ar")

    try:
        await bot.send_message(
            user_id,
            (
                "✅ <b>شكراً لإعادة الاشتراك!</b>\n\n"
                "تم إلغاء التحذير، حسابك بخير."
            ) if lang == "ar" else (
                "✅ <b>Thank you for re-subscribing!</b>\n\n"
                "The warning has been cancelled, your account is fine."
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning("Could not send rejoin confirmation to %s: %s", user_id, e)


# ─────────────────────────────────────────────────────────────────────────────
# مهمة الخلفية: فحص المغادرين بشكل دوري
# ─────────────────────────────────────────────────────────────────────────────

async def check_pending_leaves_loop(bot: Bot):
    """
    تعمل في الخلفية كل 10 دقائق.
    تفحص قائمة المغادرين وتطبق العقوبة على من انتهت مهلتهم.
    """
    while True:
        try:
            await _process_expired_leaves(bot)
        except Exception as e:
            logger.error("Error in check_pending_leaves_loop: %s", e)
        await asyncio.sleep(600)


def _normalize_datetime(dt) -> datetime:
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return datetime.now(timezone.utc)
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


async def _process_expired_leaves(bot: Bot):
    now     = datetime.now(timezone.utc)
    pending = await get_all_pending_leaves()

    for record in pending:
        user_id  = record["user_id"]
        deadline = _normalize_datetime(record["deadline"])

        if now < deadline:
            continue

        force_sub_channel = await get_setting("force_sub_channel")
        if not force_sub_channel:
            await delete_pending_leave(user_id)
            continue

        still_left = await _check_user_not_in_channel(bot, force_sub_channel, user_id)

        if not still_left:
            await delete_pending_leave(user_id)
            logger.info("User %s is back in channel — no penalty applied.", user_id)
            continue

        await _apply_penalty(bot, user_id)
        await delete_pending_leave(user_id)


async def _check_user_not_in_channel(bot: Bot, channel: str, user_id: int) -> bool:
    """
    يُرجع True إذا كان المستخدم لا يزال خارج القناة.
    """
    try:
        member = await bot.get_chat_member(channel, user_id)
        status = member.status
        if status in ("member", "administrator", "creator", "restricted"):
            return False
        return True
    except Exception:
        return True


async def _apply_penalty(bot: Bot, user_id: int):
    """
    يطبق العقوبة بعد انتهاء مهلة السماح.
    العقوبة: تعليق الحساب (منع الشراء) + إشعار المستخدم.
    """
    user = await get_user(user_id)
    if not user:
        return

    lang = user.get("language", "ar")

    await set_user_banned(user_id, banned=True, reason="left_channel")

    logger.info("User %s penalized for not rejoining channel.", user_id)

    try:
        await bot.send_message(
            user_id,
            (
                "🚫 <b>تم تعليق حسابك</b>\n\n"
                "لم تعد مشتركاً في القناة الإجبارية خلال المهلة المحددة.\n\n"
                "للرفع عن الحساب: أعد الاشتراك في القناة ثم تواصل مع الدعم."
            ) if lang == "ar" else (
                "🚫 <b>Your account has been suspended</b>\n\n"
                "You did not re-subscribe to the required channel within the grace period.\n\n"
                "To restore: re-subscribe to the channel then contact support."
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning("Could not send penalty notice to %s: %s", user_id, e)

    try:
        from config import ADMIN_IDS
        for admin_id in ADMIN_IDS:
            try:
                name = user.get("first_name") or str(user_id)
                uname = f"@{user.get('username')}" if user.get("username") else str(user_id)
                await bot.send_message(
                    admin_id,
                    f"🚫 <b>تعليق حساب تلقائي</b>\n\n"
                    f"👤 المستخدم: {name} ({uname})\n"
                    f"🆔 المعرف: <code>{user_id}</code>\n"
                    f"📋 السبب: مغادرة القناة الإجبارية",
                    parse_mode="HTML",
                )
            except Exception:
                pass
    except Exception:
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
