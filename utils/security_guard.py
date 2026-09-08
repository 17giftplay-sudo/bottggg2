import logging
import asyncio
from typing import Optional
from aiogram import Bot

from config import ADMIN_IDS

logger = logging.getLogger(__name__)

# Global threshold for balance additions that trigger instant admin alerts (e.g. $50.00)
LARGE_BALANCE_ALERT_THRESHOLD = 50.0


async def notify_admin_security_alert(
    bot: Optional[Bot],
    title: str,
    details: str,
    user_id: Optional[int] = None,
    amount: Optional[float] = None
):
    """
    Sends an immediate red-alert notification to all bot admins when a large balance transaction,
    suspicious operation, or system anomaly occurs.
    """
    try:
        msg = f"🚨 <b>[تنبيه أمان ونظام البوت]</b>\n" \
              f"<b>{title}</b>\n\n" \
              f"━━━━━━━━━━━━━━━━━━━━━\n"
        if user_id:
            msg += f"👤 مستخدم (ID): <code>{user_id}</code>\n"
        if amount is not None:
            msg += f"💰 المبلغ: <b>${amount:.2f}</b>\n"
        msg += f"📝 التفاصيل: {details}\n" \
               f"━━━━━━━━━━━━━━━━━━━━━\n" \
               f"⏱️ الوقت: <code>فوري</code>"

        logger.warning("SECURITY ALERT: %s - User: %s, Amount: %s, Details: %s", title, user_id, amount, details)

        if bot is None:
            try:
                from payments.webhook_server import get_bot
                bot = get_bot()
            except Exception:
                bot = None

        if bot:
            admin_ids_list = ADMIN_IDS if isinstance(ADMIN_IDS, (list, tuple, set)) else [ADMIN_IDS]
            for admin_id in admin_ids_list:
                try:
                    await bot.send_message(chat_id=admin_id, text=msg, parse_mode="HTML")
                except Exception as ex:
                    logger.error("Failed to send security alert to admin %s: %s", admin_id, ex)
    except Exception as e:
        logger.error("Failed in notify_admin_security_alert: %s", e)


async def check_balance_addition_security(user_id: int, amount: float, source: str, bot: Optional[Bot] = None):
    """
    Sentinel check called whenever balance is added or refunded.
    If amount is abnormally large (> $50), triggers an instant admin security alert.
    """
    if amount <= 0:
        logger.error("Security violation: Attempted non-positive balance addition: user %s, amount %s, source %s", user_id, amount, source)
        return False
        
    if amount >= LARGE_BALANCE_ALERT_THRESHOLD:
        asyncio.create_task(
            notify_admin_security_alert(
                bot=bot,
                title="إضافة رصيد كبيرة مجرى فحصها",
                details=f"تم إضافة مبلغ <b>${amount:.2f}</b> لحساب العميل من المصدر (<code>{source}</code>).",
                user_id=user_id,
                amount=amount
            )
        )
    return True
