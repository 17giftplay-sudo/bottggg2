import asyncio
import sys
import logging
from typing import Callable, Dict, Any, Awaitable

# Cross-platform single instance locking
if sys.platform != "win32":
    try:
        import fcntl
        _lock_file = open("/tmp/bot.lock", "w")
        try:
            fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError:
            sys.exit("FATAL: Another bot instance is already running. Exiting.")
    except (ImportError, OSError):
        pass

from aiohttp import web
from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.types import Update
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import os as _os

from config import BOT_TOKEN, WEBHOOK_PORT, ADMIN_IDS
from utils.session_manager import restore_sessions_from_db
from database import init_db, get_setting, get_user
from handlers import start, buy, top_up_final, profile, admin, channel_monitor
from handlers import sessions_buy, admin_sessions
from handlers import sub_admin
from handlers.daily_report import daily_report_loop
from handlers import code_actions
from handlers.channel_monitor import check_pending_leaves_loop
from payments.webhook_server import create_app, set_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

MAINTENANCE_TEXT = (
    "🔧 <b>البوت متوقف مؤقتاً للصيانة</b>\n\n"
    "عذراً، البوت تحت الصيانة حالياً، سنعود قريباً 🙏"
)


class ThrottlingMiddleware(BaseMiddleware):
    """يمنع إغراق البوت بالرسائل مع استجابة فائقة السرعة للأزرار."""
    def __init__(self, limit: float = 0.2):
        self.limit = limit
        self.cache = {}
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        user_id = None
        if event.message and event.message.from_user:
            user_id = event.message.from_user.id
        elif event.callback_query and event.callback_query.from_user:
            user_id = event.callback_query.from_user.id

        from handlers.admin import is_admin
        if user_id and not is_admin(user_id):
            now = asyncio.get_event_loop().time()
            if user_id in self.cache:
                delta = now - self.cache[user_id]
                if delta < self.limit:
                    if event.callback_query:
                        try:
                            await event.callback_query.answer()
                        except Exception:
                            pass
                    return
            self.cache[user_id] = now
            
            if len(self.cache) > 5000:
                self.cache = {uid: t for uid, t in self.cache.items() if now - t < 10.0}

        return await handler(event, data)


class MaintenanceMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        user_id = None
        if event.message and event.message.from_user:
            user_id = event.message.from_user.id
        elif event.callback_query and event.callback_query.from_user:
            user_id = event.callback_query.from_user.id

        from handlers.admin import is_admin
        if user_id and not is_admin(user_id):
            try:
                maintenance = await get_setting("maintenance_mode")
                if maintenance == "1":
                    bot: Bot = data.get("bot")
                    if bot:
                        if event.message:
                            await event.message.answer(MAINTENANCE_TEXT, parse_mode="HTML")
                        elif event.callback_query:
                            await event.callback_query.answer(
                                "🔧 البوت متوقف مؤقتاً للصيانة. سنعود قريباً!",
                                show_alert=True,
                            )
                    return
            except Exception as e:
                # لا نُسكت الخطأ — نسجّله ونستمر (الأمان أهم من الصمت)
                logger.warning("MaintenanceMiddleware: DB error checking maintenance: %s", e)

        return await handler(event, data)


class BanMiddleware(BaseMiddleware):
    """يمنع المستخدمين المحظورين من استخدام البوت نهائياً."""
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        user_id = None
        if event.message and event.message.from_user:
            user_id = event.message.from_user.id
        elif event.callback_query and event.callback_query.from_user:
            user_id = event.callback_query.from_user.id

        from handlers.admin import is_admin
        if user_id and not is_admin(user_id):
            try:
                user = await get_user(user_id)
                if user and user.get("is_banned"):
                    ban_reason = user.get("ban_reason") or ""
                    msg = "🚫 <b>حسابك محظور.</b>"
                    if ban_reason:
                        msg += f"\n<i>{ban_reason}</i>"
                    bot: Bot = data.get("bot")
                    if bot:
                        if event.message:
                            await event.message.answer(msg, parse_mode="HTML")
                        elif event.callback_query:
                            await event.callback_query.answer(
                                f"🚫 حسابك محظور.{(' — ' + ban_reason) if ban_reason else ''}",
                                show_alert=True,
                            )
                    return
            except Exception as e:
                # فشل قاعدة البيانات → نسمح بالمرور (fail-open) لتجنب حجب جميع المستخدمين
                # عند انقطاع DB مؤقت. الحالات المحظورة نادرة جداً مقارنةً بالضرر الكلي.
                logger.warning("BanMiddleware: DB error for user %s — allowing through: %s", user_id, e)

        return await handler(event, data)


async def main():
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized.")
    from database import init_sub_admins_table
    await init_sub_admins_table()
    logger.info("Sub-admins table ready.")
    logger.info("Restoring OTP sessions from database...")
    await restore_sessions_from_db()
    logger.info("OTP sessions restored.")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    set_bot(bot)

    # ── FSM Storage: Redis إذا توفر REDIS_URL وإلا MemoryStorage ──────────
    _redis_url = _os.getenv("REDIS_URL", "").strip()
    if _redis_url:
        try:
            from aiogram.fsm.storage.redis import RedisStorage
            _storage = RedisStorage.from_url(_redis_url)
            logger.info("FSM: Redis storage enabled — states survive restarts")
        except ImportError:
            from aiogram.fsm.storage.memory import MemoryStorage
            _storage = MemoryStorage()
            logger.warning("FSM: aiogram-redis not installed — using MemoryStorage")
    else:
        from aiogram.fsm.storage.memory import MemoryStorage
        _storage = MemoryStorage()
        logger.warning("FSM: MemoryStorage in use — set REDIS_URL for persistence")

    dp = Dispatcher(storage=_storage)
    dp.update.middleware(ThrottlingMiddleware())
    dp.update.middleware(BanMiddleware())
    dp.update.middleware(MaintenanceMiddleware())

    @dp.error()
    async def global_error_handler(event):
        logger.error("Global Aiogram Error: %s", event.exception, exc_info=event.exception)
        return True

    dp.include_router(admin.router)
    dp.include_router(start.router)
    dp.include_router(buy.router)
    dp.include_router(top_up_final.router)
    dp.include_router(profile.router)
    dp.include_router(channel_monitor.router)
    dp.include_router(code_actions.router)
    dp.include_router(sub_admin.router)
    dp.include_router(sessions_buy.router)
    dp.include_router(admin_sessions.router)

    app = create_app()

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=WEBHOOK_PORT)
    await site.start()
    logger.info("Webhook server listening on port %s", WEBHOOK_PORT)

    # نحتفظ بمرجع كل task في مجموعة لمنع garbage collector من حذفها
    _background_tasks: set = set()

    def _track(coro):
        t = asyncio.create_task(coro)
        _background_tasks.add(t)
        t.add_done_callback(_background_tasks.discard)
        return t

    logger.info("Starting bot polling...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logger.warning("Could not delete webhook: %s", e)
    _track(check_pending_leaves_loop(bot))
    logger.info("Pending leaves background task started.")
    _track(daily_report_loop(bot))
    logger.info("Daily report background task started.")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), drop_pending_updates=True)
    finally:
        await runner.cleanup()
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
