"""
التقرير اليومي التلقائي — يُرسَل لجميع الأدمن كل يوم في الوقت المحدد
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# الوقت الذي يُرسل فيه التقرير (بتوقيت UTC) — يمكن تغييره
REPORT_HOUR_UTC = 8   # 8 صباحاً UTC
REPORT_MINUTE   = 0


async def send_daily_report(bot) -> None:
    """يبني ويرسل التقرير اليومي لكل الأدمن."""
    from config import ADMIN_IDS
    from database import get_daily_stats, get_all_sub_admins

    try:
        stats = await get_daily_stats()
    except Exception as e:
        logger.error("daily_report: failed to fetch stats: %s", e)
        return

    now_str = datetime.now(timezone.utc).strftime("%d-%m-%Y")

    # ── بناء التقرير ──────────────────────────────────────────────────────────
    report = (
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>التقرير اليومي — {now_str}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥  <b>مستخدمون جدد اليوم:</b>  {stats['new_users']}\n"
        f"👤  <b>إجمالي المستخدمين:</b>  {stats['total_users']}\n\n"
        f"💵  <b>إيداعات اليوم:</b>  ${stats['daily_deposits']:.2f}\n"
        f"💰  <b>إجمالي الإيداعات:</b>  ${stats['total_deposits']:.2f}\n\n"
        f"📦  <b>حسابات مباعة اليوم:</b>  {stats['daily_sold']}\n"
        f"🗂  <b>المخزون المتبقي:</b>  {stats['total_available']}\n"
    )

    if stats["country_sales"]:
        report += "\n🏆 <b>أكثر الدول مبيعاً اليوم:</b>\n"
        for i, row in enumerate(stats["country_sales"], 1):
            report += f"  {i}. {row['country_name']} — {row['cnt']} حساب\n"

    report += "\n━━━━━━━━━━━━━━━━━━━━━"

    # ── إرسال للأدمن الرئيسي ─────────────────────────────────────────────────
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, report, parse_mode="HTML")
        except Exception as e:
            logger.warning("daily_report: could not send to admin %s: %s", admin_id, e)

    # ── إرسال للأدمن الفرعيين الذين لديهم صلاحية الإحصائيات ──────────────────
    try:
        from database import get_sub_admins_with_perm
        sub_admins = await get_sub_admins_with_perm("stats")
        for sa in sub_admins:
            try:
                await bot.send_message(sa["user_id"], report, parse_mode="HTML")
            except Exception:
                pass
    except Exception as e:
        logger.warning("daily_report: sub-admins fetch failed: %s", e)

    logger.info("Daily report sent successfully.")


def _seconds_until_next_report() -> float:
    """يحسب عدد الثواني حتى التقرير التالي."""
    now = datetime.now(timezone.utc)
    target = now.replace(hour=REPORT_HOUR_UTC, minute=REPORT_MINUTE, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def daily_report_loop(bot) -> None:
    """حلقة لا نهائية تنتظر الوقت المناسب وترسل التقرير كل يوم."""
    while True:
        wait_secs = _seconds_until_next_report()
        logger.info(
            "Daily report scheduled in %.0f seconds (next: %s UTC)",
            wait_secs,
            (datetime.now(timezone.utc) + timedelta(seconds=wait_secs)).strftime("%H:%M %d-%m-%Y"),
        )
        await asyncio.sleep(wait_secs)
        await send_daily_report(bot)
