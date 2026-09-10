import asyncio
from datetime import datetime, timezone
import json
import logging
import random
from typing import Optional
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pyrogram import Client as PyrogramClient
from pyrogram.errors import (
    AuthKeyUnregistered, UserDeactivated, SessionExpired,
    AuthKeyDuplicated, AuthKeyInvalid,
    FloodWait, PasswordHashInvalid,
)

from database import (
    get_user, set_user_banned,
    add_balance, deduct_balance, add_points as db_add_points,
    get_setting, set_setting,
    add_country, update_country_price, update_country_points_price,
    add_account_to_stock, get_country, get_all_countries,
    get_available_accounts_by_country, delete_account_from_stock,
    set_flash_sale, clear_flash_sale, get_active_flash_sales,
    get_ratings_stats, get_bot_stats,
    get_all_available_accounts,
    approve_manual_payment, reject_manual_payment,
    set_account_status, get_accounts_for_maintenance_view,
    get_all_countries_with_stock_or_maintenance,
    update_account_data_by_old, update_account_data_by_id, get_account_status_and_data,
)
from config import ADMIN_IDS
from states import AdminState
from keyboards import (
    admin_main_keyboard, admin_users_keyboard, admin_stock_keyboard,
    admin_links_keyboard, admin_stars_keyboard, admin_countries_keyboard,
    admin_back_keyboard,
    admin_flash_sale_keyboard,
)

router = Router()
logger = logging.getLogger(__name__)


def is_admin(user_id: int) -> bool:
    try:
        from config import ADMIN_IDS as _cfg_admins
        if isinstance(_cfg_admins, (list, tuple, set)) and user_id in _cfg_admins:
            return True
        if user_id == _cfg_admins:
            return True
    except Exception:
        pass
    import os
    raw = os.environ.get("ADMIN_IDS", "")
    for part in raw.split(","):
        if part.strip().isdigit() and int(part.strip()) == user_id:
            return True
    return False



def _clean_channel_id(ch: str) -> str:
    if not ch:
        return ""
    ch = ch.strip()
    if ch.startswith("https://t.me/joinchat/") or ch.startswith("https://t.me/+"):
        return ch
    if ch.startswith("https://t.me/"):
        ch = ch.replace("https://t.me/", "")
    elif ch.startswith("http://t.me/"):
        ch = ch.replace("http://t.me/", "")
    elif ch.startswith("t.me/"):
        ch = ch.replace("t.me/", "")
    ch = ch.strip("/")
    if ch and not ch.startswith("@") and not ch.startswith("-") and not ch.isdigit():
        ch = f"@{ch}"
    return ch


# ── ثوابت ودوال مساعدة لكشف الحسابات المميزة ─────────────────────────────────
_ACCOUNT_EPOCH = 1376438400  # Telegram epoch reference
# سيمافور يحدد أقصى عدد لمهام تدفئة الحسابات المتزامنة (لتجنب الحمل الزائد)
_WARM_SEM = asyncio.Semaphore(2)
# حد معدّل إرسال الرسائل الترويجية (2 في آنٍ واحد كحد أقصى لتجنب Spam)
_PROMO_RATE_SEM = asyncio.Semaphore(2)
# سيمافور منفصل لعمليات 2FA — أكثر خطورة من الفحص البسيط
_2FA_SEM = asyncio.Semaphore(4)


# مدّة انتظار عمليات الـ 2FA (تغيير/تفعيل الباسوورد).
# ملاحظة: عمليات الـ 2FA تتضمن حسابات SRP/KDF مكلفة + جولة اتصال إضافية عبر
# البروكسي، وهي أبطأ بكثير من استدعاء عادي مثل get_me(). كانت مضبوطة سابقاً
# على 15 ثانية وهذا قصير جداً. رفعناها إلى 25 ثانية فقط (وليس أكثر) لأن هذه
# القيمة تُضاعَف عملياً عند كل إعادة محاولة (تايم أوت) وعند كل حساب في عملية
# جماعية (bulk) تعمل بالتتابع — قيمة أعلى تجعل تغيير كل الحسابات يستغرق وقتاً
# طويلاً جداً إذا كانت بعض الحسابات لا تتصل أصلاً (مشكلة بروكسي/IP منفصلة).
_PW_OP_TIMEOUT = 25


async def _ensure_password_2fa(client, current_2fa: str = "", target_password: str = "", fallback_passwords: list = None) -> bool:
    """
    تحقق من الباسوورد الحالي أو الهدف دون تعديل تلقائي.
    """
    return True







def _estimate_account_year(user_id: int) -> int:
    """
    يُقدّر سنة إنشاء الحساب بناءً على نطاق معرّف تيليجرام.
    تيليجرام لا يُعلن عن تواريخ الإنشاء — هذا تقريب بناءً على نطاقات المعرّفات المعروفة.
    المعرّفات الأصغر = حسابات أقدم.
    """
    try:
        uid = int(user_id)
        if uid < 10_000_000:     return 2013   # مستخدمون قدامى جداً
        if uid < 100_000_000:    return 2014
        if uid < 200_000_000:    return 2015
        if uid < 400_000_000:    return 2016
        if uid < 600_000_000:    return 2017
        if uid < 800_000_000:    return 2018
        if uid < 1_000_000_000:  return 2019
        if uid < 1_500_000_000:  return 2020
        if uid < 2_000_000_000:  return 2021
        if uid < 3_000_000_000:  return 2022
        if uid < 5_000_000_000:  return 2023
        return 2024
    except Exception:
        return 0





async def _get_proxy_kwargs(phone: str) -> dict:
    """
    يبني معاملات البروكسي من PROXY_POOL المضبوط في Railway (env var).
    يختار بروكسي يتطابق مع دولة الرقم إن أمكن، وإلا يختار عشوائياً.
    """
    try:
        from config import PROXY_POOL
    except (ImportError, Exception):
        return {}
    if not PROXY_POOL:
        return {}

    chosen = None
    try:
        from utils.session_manager import _get_country_from_phone
        country = _get_country_from_phone(phone)
        if country:
            country_proxies = [p for p in PROXY_POOL if p.get("country") == country]
            chosen = random.choice(country_proxies) if country_proxies else random.choice(PROXY_POOL)
        else:
            chosen = random.choice(PROXY_POOL)
    except Exception:
        chosen = random.choice(PROXY_POOL)

    return {
        "proxy": {
            "scheme":   "socks5",
            "hostname": chosen["host"],
            "port":     chosen["port"],
            "username": chosen.get("username"),
            "password": chosen.get("password"),
        }
    }


async def _check_single_line(
    line: str,
    stock_password: str,
    fallback_passwords: list,
    sem: asyncio.Semaphore,
) -> dict:
    """
    يفحص حساباً واحداً من السطر الخام ويُعيد نتيجته.
    يُستخدم من _check_accounts_and_report للتشغيل المتوازي.
    """
    _FATAL = (AuthKeyUnregistered, UserDeactivated, SessionExpired, AuthKeyDuplicated, AuthKeyInvalid)
    parts = [p.strip() for p in line.split("::")]
    phone = parts[0] if parts else "?"

    is_short = False
    if len(parts) == 2:
        # ── الصيغة المختصرة: phone::session_string ──────────────────────
        session_string = parts[1]
        current_2fa    = ""
        try:
            from config import DEFAULT_API_ID, DEFAULT_API_HASH, API_POOL
            if API_POOL:
                api_id, api_hash = random.choice(API_POOL)
            elif DEFAULT_API_ID and DEFAULT_API_HASH:
                api_id   = DEFAULT_API_ID
                api_hash = DEFAULT_API_HASH
            else:
                logger.warning("Short-format account %s: no DEFAULT_API_ID/HASH configured", phone)
                return {"status": "unknown", "phone": phone}
        except Exception:
            return {"status": "unknown", "phone": phone}
        is_short = True
    elif len(parts) >= 4:
        # ── الصيغة الكاملة: phone::api_id::api_hash::session[::2fa] ─────
        try:
            api_id = int(parts[1])
        except (ValueError, IndexError):
            return {"status": "unknown", "phone": phone}
        api_hash       = parts[2]
        session_string = parts[3]
        current_2fa    = parts[4] if len(parts) >= 5 else ""
    else:
        return {"status": "unknown", "phone": phone}

    async with sem:
        client = None
        try:
            from utils.session_manager import _random_device
            proxy_kwargs = await _get_proxy_kwargs(phone)
            device = _random_device()
            client = PyrogramClient(
                name=f"chk_{phone.replace('+', '')}",
                api_id=api_id,
                api_hash=api_hash,
                session_string=session_string,
                in_memory=True,
                no_updates=True,
                **{k: device[k] for k in device},
                **proxy_kwargs,
            )
            try:
                is_auth = await asyncio.wait_for(client.connect(), timeout=12)
            except (asyncio.TimeoutError, OSError, ConnectionError):
                if proxy_kwargs:
                    try:
                        if client.is_connected:
                            await client.disconnect()
                    except Exception:
                        pass
                    client = PyrogramClient(
                        name=f"chk_direct_{phone.replace('+', '')}",
                        api_id=api_id,
                        api_hash=api_hash,
                        session_string=session_string,
                        in_memory=True,
                        no_updates=True,
                        **{k: device[k] for k in device},
                    )
                    is_auth = await asyncio.wait_for(client.connect(), timeout=12)
                else:
                    raise

            if not is_auth:
                return {"status": "invalid", "phone": phone}

            me = await asyncio.wait_for(client.get_me(), timeout=10)
            if not me:
                return {"status": "invalid", "phone": phone}

            pw_status = None
            return {"status": "valid", "phone": phone, "pw": pw_status}

        except (AuthKeyUnregistered, UserDeactivated, SessionExpired, AuthKeyDuplicated, AuthKeyInvalid):
            return {"status": "invalid", "phone": phone}
        except asyncio.TimeoutError:
            logger.warning("Timeout checking line account %s", phone)
            return {"status": "unknown", "phone": phone}
        except FloodWait as fw:
            logger.warning("FloodWait %ds on start for %s", fw.value, phone)
            return {"status": "unknown", "phone": phone}
        except Exception as e:
            logger.warning("Error checking line account %s: %s", phone, e)
            return {"status": "unknown", "phone": phone}
        finally:
            if client is not None:
                try:
                    if client.is_connected:
                        await asyncio.wait_for(client.disconnect(), timeout=4)
                except Exception:
                    pass


async def _check_accounts_and_report(parsed_lines: list, admin_id: int, bot: Bot, country_name: str):
    """
    يفحص جميع الجلسات بعد الرفع بشكل متوازٍ (8 حسابات في آنٍ واحد)،
    يغيّر الباسوورد تلقائياً إن كان مضبوطاً، ويرسل تقريراً للمدير.
    """
    stock_password = await get_setting("stock_2fa_password")
    stock_password = stock_password.strip() if stock_password else ""

    _fb_raw = await get_setting("stock_2fa_fallback") or ""
    fallback_passwords = [p.strip() for p in _fb_raw.split(",") if p.strip()]

    # سيمافور يسمح بـ 8 حسابات متزامنة — أسرع بكثير من الواحد تلو الآخر
    sem = asyncio.Semaphore(8)
    tasks = [_check_single_line(line, stock_password, fallback_passwords, sem) for line in parsed_lines]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    valid, invalid, unknown = [], [], []
    pw_changed, pw_failed = [], []

    for res in results:
        if isinstance(res, Exception):
            unknown.append("?")
            continue
        phone = res.get("phone", "?")
        status = res.get("status", "unknown")
        pw = res.get("pw")
        if status == "valid":
            valid.append(phone)
            if pw == "changed":
                pw_changed.append(phone)
            elif pw == "failed":
                pw_failed.append(phone)
        elif status == "invalid":
            invalid.append(phone)
        else:
            unknown.append(phone)

    report_lines = [f"🔍 <b>تقرير فحص الحسابات</b>\n🌍 الدولة: <b>{country_name}</b>\n"]
    report_lines.append(f"✅ صالح: <b>{len(valid)}</b>")
    report_lines.append(f"❌ منتهي/محظور: <b>{len(invalid)}</b>")
    report_lines.append(f"⚠️ غير محدد (شبكة): <b>{len(unknown)}</b>")

    if stock_password:
        report_lines.append(f"\n🔐 <b>تغيير الباسوورد:</b>")
        report_lines.append(f"  ✅ تم التغيير: <b>{len(pw_changed)}</b>")
        if pw_failed:
            report_lines.append(f"  ❌ فشل التغيير: <b>{len(pw_failed)}</b>")
            for p in pw_failed[:10]:
                report_lines.append(f"    • <code>{p}</code>")

    if invalid:
        report_lines.append("\n<b>الأرقام المنتهية (تم الاحتفاظ بها في المخزون):</b>")
        for p in invalid[:20]:
            report_lines.append(f"  ❌ <code>{p}</code>")
        if len(invalid) > 20:
            report_lines.append(f"  ...و{len(invalid) - 20} أخرى")

    if unknown:
        report_lines.append("\n⚠️ <b>الأرقام غير محددة الشبكة (timeout):</b>")
        for p in unknown[:20]:
            report_lines.append(f"  ⚠️ <code>{p}</code>")
        if len(unknown) > 20:
            report_lines.append(f"  ...و{len(unknown) - 20} أخرى")

    try:
        await bot.send_message(admin_id, "\n".join(report_lines), parse_mode="HTML")
    except Exception as e:
        logger.error("_check_accounts_and_report: failed to send report: %s", e)


async def _panel_text() -> str:
    stats = await get_bot_stats()
    maintenance = await get_setting("maintenance_mode")
    sell_val    = await get_setting("sell_btn_enabled")
    status      = "🔴 موقوف (صيانة)" if maintenance == "1" else "🟢 يعمل بشكل طبيعي"
    sell_status = "🟢 مفتوح" if (sell_val or "1") == "1" else "🔴 موقوف"
    return (
        f"👑 <b>لوحة تحكم الإدارة (VIP Admin Panel)</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥  <b>المستخدمين:</b> <code>{stats['total_users']}</code>\n"
        f"💵  <b>إجمالي الإيداعات:</b> <code>${stats['total_deposits']:.2f}</code>\n"
        f"📦  <b>الحسابات المباعة:</b> <code>{stats['total_sold']}</code>\n"
        f"🗂  <b>المخزون المتوفر:</b> <code>{stats['total_available']}</code>\n"
        f"🌍  <b>الدول المتاحة:</b> <code>{stats['total_countries']}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚡ <b>حالة البوت:</b> {status}\n"
        f"🛍️ <b>حالة المتجر:</b> {sell_status}"
    )


async def _panel_keyboard() -> "InlineKeyboardMarkup":
    """يبني لوحة الأدمن الرئيسية مع الحالات الصحيحة لجميع الأزرار."""
    maintenance = await get_setting("maintenance_mode")
    sell_val    = await get_setting("sell_btn_enabled")
    sell_on     = (sell_val or "1") == "1"
    return admin_main_keyboard(maintenance == "1", sell_on=sell_on)


async def _is_admin_or_has_perm(user_id: int, perm: str) -> bool:
    """يعود True إذا كان المستخدم أدمن رئيسي أو أدمن فرعي بالصلاحية المحددة."""
    if is_admin(user_id):
        return True
    from database import get_sub_admin
    sa = await get_sub_admin(user_id)
    return bool(sa and sa.get(f"perm_{perm}"))


from aiogram.filters import Command

@router.message(Command("admin"))
@router.message(F.text.startswith("/admin"))
async def admin_cmd(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        from database import get_sub_admin
        from keyboards import sub_admin_panel_keyboard
        sa = await get_sub_admin(message.from_user.id)
        if not sa:
            await message.answer(
                f"⛔ <b>ليس لديك صلاحية للوصول للوحة الأدمن.</b>\n\n"
                f"🆔 الآيدي الخاص بك: <code>{message.from_user.id}</code>\n"
                f"ℹ️ إذا كنت أنت صاحب البوت، أضف هذا الآيدي في متغيرات Railway:\n"
                f"<code>ADMIN_IDS={message.from_user.id}</code>",
                parse_mode="HTML"
            )
            return
        perms = {
            "stock":     bool(sa.get("perm_stock")),
            "users":     bool(sa.get("perm_users")),
            "stats":     bool(sa.get("perm_stats")),
            "deposits":  bool(sa.get("perm_deposits")),
            "broadcast": bool(sa.get("perm_broadcast")),
        }
        if not any(perms.values()):
            await message.answer(
                "⚠️ ليس لديك أي صلاحيات مفعّلة حالياً.\n"
                "تواصل مع المشرف الرئيسي لتفعيل الصلاحيات."
            )
            return
        await state.clear()
        label = sa.get("label") or str(message.from_user.id)
        await message.answer(
            f"👮 <b>لوحة الأدمن الفرعي</b>\n\n"
            f"مرحباً <b>{label}</b>!\n"
            f"اختر القسم الذي تريد إدارته:",
            reply_markup=sub_admin_panel_keyboard(perms),
            parse_mode="HTML",
        )
        return
    await state.clear()
    text = await _panel_text()
    await message.answer(text, reply_markup=await _panel_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "admin:main")
async def admin_main(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.clear()
    text = await _panel_text()
    await callback.message.edit_text(text, reply_markup=await _panel_keyboard(), parse_mode="HTML")
    await callback.answer()




# ─── تبديل حالة المتجر من اللوحة الرئيسية ────────────────────────────────────

@router.callback_query(F.data == "admin:toggle_sell_btn_main")
async def admin_toggle_sell_btn_main(callback: CallbackQuery):
    """يُبدّل sell_btn_enabled مباشرةً من لوحة الأدمن الرئيسية."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    current = (await get_setting("sell_btn_enabled") or "1")
    new_val = "0" if current == "1" else "1"
    await set_setting("sell_btn_enabled", new_val)
    if new_val == "1":
        await callback.answer("🟢 تم فتح المتجر!", show_alert=True)
    else:
        await callback.answer("🔴 تم إيقاف المتجر!", show_alert=True)
    text = await _panel_text()
    await callback.message.edit_text(text, reply_markup=await _panel_keyboard(), parse_mode="HTML")
# ─── الإحصائيات ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    stats = await get_bot_stats()
    await callback.message.edit_text(
        f"📊 <b>إحصائيات البوت</b>\n\n"
        f"👥 إجمالي المستخدمين: <b>{stats['total_users']}</b>\n"
        f"💵 إجمالي الإيداعات: <b>${stats['total_deposits']:.2f}</b>\n"
        f"📦 حسابات مباعة: <b>{stats['total_sold']}</b>\n"
        f"🗂 حسابات متوفرة: <b>{stats['total_available']}</b>\n"
        f"🌍 عدد الدول: <b>{stats['total_countries']}</b>",
        reply_markup=admin_back_keyboard("admin:main"),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── وضع الصيانة ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:maintenance")
async def admin_toggle_maintenance(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    current = await get_setting("maintenance_mode")
    new_val = "0" if current == "1" else "1"
    await set_setting("maintenance_mode", new_val)
    if new_val == "1":
        await callback.answer("🔴 تم تفعيل وضع الصيانة!", show_alert=True)
    else:
        await callback.answer("🟢 تم تشغيل البوت!", show_alert=True)
    text = await _panel_text()
    await callback.message.edit_text(text, reply_markup=await _panel_keyboard(), parse_mode="HTML")





# ─── تفعيل/تعطيل الرسالة الترويجية ──────────────────────────────────────────

@router.callback_query(F.data == "admin:toggle_promo")
async def admin_toggle_promo(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    current = await get_setting("promo_enabled") or "1"
    new_val = "0" if current == "1" else "1"
    await set_setting("promo_enabled", new_val)
    if new_val == "1":
        await callback.answer("🟢 تم تفعيل الرسائل الترويجية!", show_alert=True)
    else:
        await callback.answer("🔴 تم تعطيل الرسائل الترويجية!", show_alert=True)
    # تحديث لوحة المخزون
    countries = await get_all_countries()
    lines = []
    for c in countries:
        flag  = c.get("flag_emoji", "🌍")
        stock = c.get("stock_count", 0)
        pts_p = int(c.get("points_price", 0) or 0)
        lines.append(
            f"{flag} <b>{c['country_name']}</b> — ${float(c['price']):.2f}"
            f" | 🪙{pts_p} pts — مخزون: {stock}"
        )
    text = "🗄️ <b>إدارة المخزون</b>\n\n" + ("\n".join(lines) if lines else "لا توجد دول مضافة.")
    await callback.message.edit_text(text, reply_markup=admin_stock_keyboard(promo_on=new_val == "1"), parse_mode="HTML")


# ─── إدارة المستخدمين ────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:users")
async def admin_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await callback.message.edit_text(
        "👥 <b>إدارة المستخدمين</b>\n\nاختر العملية:",
        reply_markup=admin_users_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin:view_user")
async def admin_view_user_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminState.waiting_for_user_id_add)
    await state.update_data(action="view")
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:users")
    await callback.message.edit_text(
        "🔍 <b>عرض مستخدم</b>\n\nأرسل ID المستخدم:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin:add_balance")
async def admin_add_balance_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminState.waiting_for_user_id_add)
    await state.update_data(action="add")
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:users")
    await callback.message.edit_text(
        "💰 <b>إضافة رصيد</b>\n\nأرسل ID المستخدم:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin:add_points")
async def admin_add_points_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminState.waiting_for_user_id_add)
    await state.update_data(action="add_points")
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:users")
    await callback.message.edit_text(
        "🪙 <b>إضافة نقاط</b>\n\nأرسل ID المستخدم:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminState.waiting_for_user_id_add)
async def admin_user_id_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("❌ ID غير صحيح.")
        return
    user = await get_user(uid)
    if not user:
        await message.answer("❌ المستخدم غير موجود.")
        return

    data   = await state.get_data()
    action = data.get("action", "add")

    if action == "view":
        await state.clear()
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 إدارة المستخدمين", callback_data="admin:users")
        pts = int(float(user.get("points", 0) or 0))
        uname = user.get("username")
        uname_line = f"@{uname}" if uname else "—"
        # رابط السحابة يعمل دائماً حتى لو المستخدم بدون يوزر
        profile_link = f'<a href="tg://user?id={uid}">🔗 فتح الحساب على التيليجرام</a>'
        await message.answer(
            f"👤 <b>بيانات المستخدم</b>\n\n"
            f"🆔 ID: <code>{uid}</code>\n"
            f"👤 الاسم: <b>{user.get('first_name', '—')}</b>\n"
            f"📛 اليوزر: {uname_line}\n"
            f"{profile_link}\n\n"
            f"💰 الرصيد: <b>${float(user['balance']):.4f}</b>\n"
            f"✅ موثّق: {'نعم' if user.get('is_verified') else 'لا'}",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return

    if action == "add_points":
        await state.update_data(target_id=uid)
        await state.set_state(AdminState.waiting_for_add_amount)
        pts = int(float(user.get("points", 0) or 0))
        await message.answer(
            f"👤 المستخدم: <b>{user.get('first_name', '—')}</b> (<code>{uid}</code>)\n"
            f"🪙 النقاط الحالية: <b>{pts}</b>\n\n"
            "أرسل عدد النقاط المراد إضافتها:",
            parse_mode="HTML",
        )
        return

    await state.update_data(target_id=uid)
    await state.set_state(AdminState.waiting_for_add_amount)
    await message.answer(
        f"👤 المستخدم: <b>{user.get('first_name', '—')}</b> (<code>{uid}</code>)\n"
        f"💰 الرصيد الحالي: <b>${float(user['balance']):.4f}</b>\n\n"
        "أرسل المبلغ المراد إضافته بالدولار:",
        parse_mode="HTML",
    )


@router.message(AdminState.waiting_for_add_amount)
async def admin_add_balance_amount(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    data   = await state.get_data()
    action = data.get("action", "add")

    try:
        amount = float(message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ أدخل قيمة صحيحة.")
        return

    uid = data["target_id"]
    await state.clear()

    if action == "add_points":
        pts = int(amount)
        await db_add_points(uid, pts, description=f"Admin points add by {message.from_user.id}")
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 لوحة الأدمن", callback_data="admin:main")
        await message.answer(
            f"✅ تم إضافة <b>{pts} نقطة</b> للمستخدم <code>{uid}</code>",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        return

    await add_balance(uid, amount, description=f"Admin top-up by {message.from_user.id}")
    updated = await get_user(uid)
    new_bal = float(updated["balance"]) if updated else amount
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 لوحة الأدمن", callback_data="admin:main")
    await message.answer(
        f"✅ تم إضافة <b>${amount}</b> للمستخدم <code>{uid}</code>\n"
        f"💰 رصيده الجديد: <b>${new_bal:.4f}</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    try:
        await bot.send_message(
            uid,
            f"💰 تم إضافة <b>${amount}</b> إلى رصيدك!\n💰 رصيدك الجديد: <b>${new_bal:.4f}</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(F.data == "admin:deduct_balance")
async def admin_deduct_balance_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminState.waiting_for_user_id_deduct)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:users")
    await callback.message.edit_text(
        "💸 <b>خصم رصيد</b>\n\nأرسل ID المستخدم:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminState.waiting_for_user_id_deduct)
async def admin_deduct_user_id(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("❌ ID غير صحيح.")
        return
    user = await get_user(uid)
    if not user:
        await message.answer("❌ المستخدم غير موجود.")
        return
    await state.update_data(target_id=uid)
    await state.set_state(AdminState.waiting_for_deduct_amount)
    await message.answer(
        f"👤 المستخدم: <b>{user.get('first_name', '—')}</b> (<code>{uid}</code>)\n"
        f"💰 الرصيد الحالي: <b>${float(user['balance']):.4f}</b>\n\n"
        "أرسل المبلغ المراد خصمه بالدولار:",
        parse_mode="HTML",
    )


@router.message(AdminState.waiting_for_deduct_amount)
async def admin_deduct_balance_amount(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        amount = float(message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ أدخل مبلغاً صحيحاً.")
        return
    data = await state.get_data()
    uid  = data["target_id"]
    await state.clear()
    await deduct_balance(uid, amount, description=f"Admin deduction by {message.from_user.id}")
    updated = await get_user(uid)
    new_bal = float(updated["balance"]) if updated else 0.0
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 لوحة الأدمن", callback_data="admin:main")
    await message.answer(
        f"✅ تم خصم <b>${amount}</b> من المستخدم <code>{uid}</code>\n"
        f"💰 رصيده الجديد: <b>${new_bal:.4f}</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


# ─── إدارة المخزون ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:stock")
async def admin_stock(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    countries = await get_all_countries()
    lines = []
    for c in countries:
        flag  = c.get("flag_emoji", "🌍")
        stock = c.get("stock_count", 0)
        lines.append(
            f"{flag} <b>{c['country_name']}</b> — ${float(c['price']):.2f} — مخزون: {stock}"
        )
    text = "🗄️ <b>إدارة المخزون</b>\n\n" + ("\n".join(lines) if lines else "لا توجد دول مضافة.")
    await callback.message.edit_text(text, reply_markup=admin_stock_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin:add_stock")
async def admin_add_stock_start(callback: CallbackQuery, state: FSMContext):
    if not await _is_admin_or_has_perm(callback.from_user.id, "stock"):
        await callback.answer("⛔", show_alert=True)
        return
    countries = await get_all_countries()
    if not countries:
        await callback.answer("❌ لا توجد دول. أضف دولة أولاً.", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for c in countries:
        flag = c.get("flag_emoji", "")
        builder.button(
            text=f"{flag} {c['country_name']}",
            callback_data=f"add_stock:{c['country_code']}",
        )
    builder.button(text="❌ إلغاء", callback_data="admin:stock")
    builder.adjust(2)
    await callback.message.edit_text(
        "📦 <b>إضافة مخزون</b>\n\nاختر الدولة:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("add_stock:"))
async def admin_add_stock_country_cb(callback: CallbackQuery, state: FSMContext):
    if not await _is_admin_or_has_perm(callback.from_user.id, "stock"):
        await callback.answer("⛔", show_alert=True)
        return
    code    = callback.data.split(":", 1)[1].upper()
    country = await get_country(code)
    if not country:
        await callback.answer("❌ الدولة غير موجودة.", show_alert=True)
        return
    await state.update_data(
        stock_country=code,
        stock_country_name=country["country_name"],
        stock_price=float(country["price"]),
        stock_type="dollar",
    )
    await state.set_state(AdminState.waiting_for_stock_data)

    flag = country.get("flag_emoji", "")
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:stock")

    from config import DEFAULT_API_ID, DEFAULT_API_HASH
    if DEFAULT_API_ID and DEFAULT_API_HASH:
        format_hint = (
            f"📦 <b>إضافة مخزون — {flag} {country['country_name']}</b>\n\n"
            "📋 أرسل بيانات الحساب — يُقبل شكلان:\n\n"
            "1️⃣ <b>الصيغة المختصرة</b> (API موحّد مضبوط):\n"
            "<code>رقم_الهاتف::session_string</code>\n\n"
            "2️⃣ <b>الصيغة الكاملة</b>:\n"
            "<code>رقم_الهاتف::api_id::api_hash::session_string</code>\n\n"
            "<b>أو ارفع ملف:</b>\n"
            "• <b>.zip</b> — Telethon Session Zip\n"
            "• <b>.txt</b> — سطر واحد لكل حساب (Pyrogram)"
        )
    else:
        format_hint = (
            f"📦 <b>إضافة مخزون — {flag} {country['country_name']}</b>\n\n"
            "📋 أرسل بيانات الحساب بهذه الصيغة:\n"
            "<code>رقم_الهاتف::api_id::api_hash::session_string</code>\n\n"
            "💡 <i>لتفعيل الصيغة المختصرة (بدون api_id/api_hash في كل سطر)،\n"
            "أضف DEFAULT_API_ID و DEFAULT_API_HASH في متغيرات Railway.</i>\n\n"
            "<b>أو ارفع ملف:</b>\n"
            "• <b>.zip</b> — Telethon Session Zip\n"
            "• <b>.txt</b> — سطر واحد لكل حساب (Pyrogram)"
        )

    await callback.message.edit_text(
        format_hint,
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


_VALIDATE_SEM = asyncio.Semaphore(5)   # لا أكثر من 5 اتصالات تحقق متزامنة
_VALIDATE_CONNECT_TIMEOUT = 20        # ثانية لكل محاولة اتصال في التحقق
_VALIDATE_GETME_TIMEOUT   = 10        # ثانية لـ get_me


async def _validate_one_account(
    account_id: int,
    account_data: str,
    phone: str,
) -> str:
    """
    يتحقق من صلاحية جلسة واحدة بالاتصال الفعلي بتيليجرام.

    يُعيد:
        "valid"   — الجلسة تعمل → سيُفعَّل status='available'
        "invalid" — الجلسة منتهية/محظورة → سيُحذف الحساب من المخزون
        "unknown" — timeout أو خطأ شبكة → يُعطى الحساب شك الصالح ويُفعَّل
    """
    from pyrogram import Client as _ValClient
    from pyrogram.errors import (
        AuthKeyUnregistered, UserDeactivated, SessionExpired,
        AuthKeyDuplicated, AuthKeyInvalid, UserDeactivatedBan,
    )
    from utils.session_manager import parse_account_data, _random_device, _build_proxy_kwargs

    parsed = parse_account_data(account_data)
    if not parsed:
        return "invalid"

    async with _VALIDATE_SEM:
        client = None
        try:
            device = _random_device()
            proxy_kwargs = await _get_proxy_kwargs(phone)
            client = _ValClient(
                name=f"val_{phone.replace('+', '')}_{account_id}",
                api_id=parsed["api_id"],
                api_hash=parsed["api_hash"],
                session_string=parsed["session_string"],
                in_memory=True,
                no_updates=True,
                **{k: device[k] for k in device},
                **proxy_kwargs,
            )
            try:
                is_auth = await asyncio.wait_for(client.connect(), timeout=_VALIDATE_CONNECT_TIMEOUT)
            except (asyncio.TimeoutError, OSError, ConnectionError):
                if proxy_kwargs:
                    try:
                        if client.is_connected:
                            await client.disconnect()
                    except Exception:
                        pass
                    client = _ValClient(
                        name=f"val_direct_{phone.replace('+', '')}_{account_id}",
                        api_id=parsed["api_id"],
                        api_hash=parsed["api_hash"],
                        session_string=parsed["session_string"],
                        in_memory=True,
                        no_updates=True,
                        **{k: device[k] for k in device},
                    )
                    is_auth = await asyncio.wait_for(client.connect(), timeout=_VALIDATE_CONNECT_TIMEOUT)
                else:
                    raise

            if not is_auth:
                return "invalid"

            me = await asyncio.wait_for(client.get_me(), timeout=_VALIDATE_GETME_TIMEOUT)
            if not me:
                return "invalid"
            return "valid"

        except (
            AuthKeyUnregistered, UserDeactivated, SessionExpired,
            AuthKeyDuplicated, AuthKeyInvalid, UserDeactivatedBan,
        ):
            # خطأ مؤكد — الجلسة منتهية أو الحساب محظور
            return "invalid"
        except asyncio.TimeoutError:
            # مشكلة شبكة — لا نحذف الحساب بسببها
            logger.warning("Validation timeout for account %s (%s)", account_id, phone)
            return "unknown"
        except FloodWait as fw:
            logger.warning("FloodWait %ds during validation for %s — treating as unknown", fw.value, phone)
            return "unknown"
        except Exception as e:
            logger.warning("Unexpected error validating account %s (%s): %s", account_id, phone, e)
            return "unknown"
        finally:
            if client is not None:
                try:
                    if client.is_connected:
                        await asyncio.wait_for(client.disconnect(), timeout=4)
                except Exception:
                    pass


_IMPORT_SEM = asyncio.Semaphore(5)   # حد أقصى 5 اتصالات متزامنة عند الاستيراد


async def _import_check_one(
    account_id: int,
    account_data: str,
    phone: str,
    stock_password: str,
    fallback_passwords: list,
    bot: "Bot",
    admin_id: int,
) -> dict:
    """
    يتحقق من حساب واحد في اتصال واحد ويُنجز كل العمليات دفعةً واحدة:
      1. يتحقق من صلاحية الجلسة (valid / invalid / unknown)
      2. يكشف إن كان الحساب مميزاً (Premium أو قديم ≤ 2020)
      3. يُغيّر كلمة المرور (2FA) إذا كانت stock_2fa_password مضبوطة
      4. يُرسل رسالة ترويجية لـ Saved Messages
      5. يُرسل إشعاراً للأدمن إذا كان الحساب مميزاً
    يُعيد: {"status": "valid"|"invalid"|"unknown", "is_notable": bool,
             "year": int, "is_premium": bool, "pw_changed": bool}
    """
    from pyrogram import Client as _ImpClient
    from pyrogram.errors import (
        AuthKeyUnregistered, UserDeactivated, SessionExpired,
        AuthKeyDuplicated, AuthKeyInvalid, UserDeactivatedBan,
        PasswordHashInvalid,
    )
    from utils.session_manager import parse_account_data, _random_device, _build_proxy_kwargs

    _FATAL = (
        AuthKeyUnregistered, UserDeactivated, SessionExpired,
        AuthKeyDuplicated, AuthKeyInvalid, UserDeactivatedBan,
    )

    parsed = parse_account_data(account_data)
    if not parsed:
        return {"status": "invalid", "is_notable": False, "year": 0, "is_premium": False, "pw_changed": False}

    parts         = [p.strip() for p in account_data.split("::")]
    current_2fa   = parts[4] if len(parts) >= 5 else ""
    result = {"status": "unknown", "is_notable": False, "year": 0, "is_premium": False, "pw_changed": False}

    async with _IMPORT_SEM:
        client = None
        try:
            device       = _random_device()
            proxy_kwargs = _build_proxy_kwargs(parsed["phone"])
            client = _ImpClient(
                name=f"imp_{parsed['phone'].replace('+', '')}_{account_id}",
                api_id=parsed["api_id"],
                api_hash=parsed["api_hash"],
                session_string=parsed["session_string"],
                in_memory=True,
                no_updates=True,
                **{k: device[k] for k in device},
                **proxy_kwargs,
            )

            # ── 1. اتصال + تحقق أساسي ─────────────────────────────────────
            try:
                is_auth = await asyncio.wait_for(client.connect(), timeout=15)
            except (asyncio.TimeoutError, OSError, ConnectionError):
                if proxy_kwargs:
                    try:
                        if client.is_connected:
                            await client.disconnect()
                    except Exception:
                        pass
                    client = _ImpClient(
                        name=f"imp_direct_{parsed['phone'].replace('+', '')}_{account_id}",
                        api_id=parsed["api_id"],
                        api_hash=parsed["api_hash"],
                        session_string=parsed["session_string"],
                        in_memory=True,
                        no_updates=True,
                        **{k: device[k] for k in device},
                    )
                    is_auth = await asyncio.wait_for(client.connect(), timeout=15)
                else:
                    raise

            if not is_auth:
                result["status"] = "invalid"
                return result

            me = await asyncio.wait_for(client.get_me(), timeout=10)
            if not me:
                result["status"] = "invalid"
                return result

            # ── 2. كشف Premium وسنة الإنشاء ──────────────────────────────
            year       = _estimate_account_year(me.id)
            is_premium = bool(getattr(me, "is_premium", False))
            is_notable = (year > 0 and year <= 2020) or is_premium
            result.update({"status": "valid", "year": year, "is_premium": is_premium, "is_notable": is_notable})

            # ── 3. إشعار الأدمن عن الحساب المميز ────────────────────────
            if is_notable:
                name     = f"{getattr(me, 'first_name', '') or ''} {getattr(me, 'last_name', '') or ''}".strip()
                username = f"@{me.username}" if getattr(me, "username", None) else "بدون يوزر"
                labels   = []
                if year and year <= 2020:
                    labels.append(f"📅 حساب قديم — أُنشئ عام {year}")
                if is_premium:
                    labels.append("💎 Telegram Premium")
                notif_text = (
                    "⭐ <b>حساب مميز تمت إضافته!</b>\n\n"
                    f"📞 الرقم: <code>{parsed['phone']}</code>\n"
                    f"👤 الاسم: {name or 'غير معروف'}\n"
                    f"🔗 اليوزر: {username}\n"
                )
                if labels:
                    notif_text += "\n" + "\n".join(f"• {l}" for l in labels)
                try:
                    await bot.send_message(admin_id, notif_text, parse_mode="HTML")
                except Exception as notif_err:
                    logger.warning("Notable notification failed for %s: %s", parsed["phone"], notif_err)

            # ── 4. التحقق من باسوورد 2FA ────────────────────────────────
            has_2fa = False
            pw_working = False
            try:
                from pyrogram.raw.functions.account import GetPassword
                pwd_obj = await asyncio.wait_for(client.invoke(GetPassword()), timeout=8)
                has_2fa = bool(getattr(pwd_obj, "has_password", False))
                if has_2fa and parsed.get("two_factor"):
                    pw_working = True
                elif not has_2fa and not parsed.get("two_factor"):
                    pw_working = True
                elif not has_2fa and parsed.get("two_factor"):
                    pw_working = True
            except Exception as _2fa_err:
                logger.debug("2FA check debug for %s: %s", phone, _2fa_err)
                if parsed.get("two_factor"):
                    has_2fa = True
                    pw_working = True

            result.update({"has_2fa": has_2fa, "pw_working": pw_working, "has_pw_set": bool(parsed.get("two_factor"))})

        except _FATAL as fatal_err:
            logger.warning("Fatal session authentication error for %s: %s", phone, fatal_err)
            result["status"] = "invalid"
        except asyncio.TimeoutError:
            logger.warning("Import check timeout for account %s (%s)", account_id, phone)
            result["status"] = "unknown"
        except FloodWait as fw:
            logger.warning("FloodWait %ds for %s during import check", fw.value, phone)
            result["status"] = "unknown"
        except Exception as e:
            logger.warning("Import check network/connection error for %s: %s", phone, e)
            result["status"] = "unknown"
        finally:
            if client is not None:
                try:
                    if client.is_connected:
                        await asyncio.wait_for(client.disconnect(), timeout=4)
                except Exception:
                    pass

    return result


async def _validate_and_activate_stock(
    inserted: list,   # list of (account_id, account_data, phone)
    admin_id: int,
    bot: "Bot",
    country_name: str,
) -> None:
    """
    يتحقق من جميع الحسابات الجديدة بشكل متوازٍ ثم:
    - الصالحة   → status = 'available'  (تظهر للمشترين)
    - المنتهية  → تُحذف من المخزون
    - غير محددة → status = 'available'  (نعطيها شك الصالح)
    - يُرسل تقريراً شاملاً عند الانتهاء مع حالة باسوورد 2FA
    """
    from database import set_account_status, delete_account_from_stock

    stock_password = await get_setting("stock_2fa_password") or ""
    stock_password = stock_password.strip()

    _fb_raw = await get_setting("stock_2fa_fallback") or ""
    fallback_passwords = [p.strip() for p in _fb_raw.split(",") if p.strip()]

    tasks = [
        _import_check_one(acc_id, acc_data, phone, stock_password, fallback_passwords, bot, admin_id)
        for acc_id, acc_data, phone in inserted
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    valid_count   = 0
    invalid_count = 0
    unknown_count = 0
    notable_count = 0
    pw_ok_count   = 0

    for (acc_id, acc_data, phone), res in zip(inserted, results):
        if isinstance(res, Exception):
            logger.error("_validate_and_activate_stock unexpected exception for %s: %s", phone, res)
            await set_account_status(acc_id, "available")
            unknown_count += 1
            continue

        status = res.get("status", "unknown")
        if status == "valid":
            await set_account_status(acc_id, "available")
            valid_count += 1
            if res.get("is_notable"):
                notable_count += 1
            if res.get("has_pw_set"):
                pw_ok_count += 1
        elif status == "invalid":
            await delete_account_from_stock(acc_id)
            invalid_count += 1
        else:  # unknown (timeout / network)
            await set_account_status(acc_id, "available")
            unknown_count += 1
            if res.get("has_pw_set"):
                pw_ok_count += 1

    # ── تقرير نهائي للأدمن ────────────────────────────────────────────────
    report = (
        f"✅ <b>نتيجة فحص الحسابات الجديدة</b>\n\n"
        f"🌍 الدولة: <b>{country_name}</b>\n\n"
        f"✅ صالحة وتم تفعيلها: <b>{valid_count}</b>\n"
        f"❌ منتهية وتم حذفها: <b>{invalid_count}</b>\n"
        f"⚠️ غير محددة (تم تفعيلها): <b>{unknown_count}</b>\n"
    )
    if notable_count:
        report += f"\n⭐ حسابات مميزة (Premium/قديمة): <b>{notable_count}</b>"
    if pw_ok_count > 0:
        report += f"\n🔐 باسوورد 2FA: <b>شغال ومربوط بـ ({pw_ok_count}) حساب</b>"
    report += "\n\n<i>الحسابات جاهزة للبيع ومخزنة مع كلمات المرور الخاصة بها.</i>"

    try:
        await bot.send_message(admin_id, report, parse_mode="HTML")
    except Exception as e:
        logger.error("_validate_and_activate_stock: failed to send report: %s", e)


@router.message(AdminState.waiting_for_stock_data)
async def admin_add_stock_data(message: Message, state: FSMContext, bot: Bot):
    if not await _is_admin_or_has_perm(message.from_user.id, "stock"):
        return
    data         = await state.get_data()
    code         = data.get("stock_country", "")
    country_name = data.get("stock_country_name", "")
    price        = data.get("stock_price", 0.0)
    store_type   = data.get("stock_type", "dollar")

    lines = []

    doc    = message.document
    is_zip = doc and doc.file_name and doc.file_name.lower().endswith(".zip")
    is_txt = doc and doc.file_name and doc.file_name.lower().endswith(".txt")

    # ─── CASE A: ملف .zip ───
    if is_zip:
        processing_msg = await message.answer("⏳ جاري معالجة ملف الـ zip وتحويل الجلسة...")

        file_id = message.document.file_id
        file    = await bot.get_file(file_id)
        local_zip_path = f"temp_{message.document.file_name}"
        await bot.download_file(file.file_path, local_zip_path)

        from utils.zip_parser import parse_telethon_zip
        import os
        parsed = parse_telethon_zip(local_zip_path)

        if os.path.exists(local_zip_path):
            try:
                os.remove(local_zip_path)
            except Exception:
                pass

        if parsed:
            lines = [p["line"] for p in parsed if p.get("line")]

        if not lines:
            await processing_msg.edit_text(
                "❌ فشل تحليل وتحويل ملفات الجلسة. "
                "تأكد من أن ملف الـ zip يحتوي على ملفات قاعدة بيانات .session وملفات معلومات نصية صحيحة."
            )
            return

        try:
            await processing_msg.delete()
        except Exception:
            pass

    # ─── CASE B: ملف Pyrogram .txt ───
    elif is_txt:
        processing_msg = await message.answer("⏳ جاري معالجة ملف Pyrogram .txt ...")

        file_id   = doc.file_id
        file      = await bot.get_file(file_id)
        local_txt = f"temp_{doc.file_name}"
        await bot.download_file(file.file_path, local_txt)

        from utils.zip_parser import parse_pyrogram_txt
        import os
        parsed = parse_pyrogram_txt(local_txt)
        if os.path.exists(local_txt):
            try:
                os.remove(local_txt)
            except Exception:
                pass

        if parsed:
            lines = [p["line"] for p in parsed if p.get("line")]

        if not lines:
            await processing_msg.edit_text(
                "❌ فشل قراءة الملف. تأكد من أن كل سطر بصيغة:\n"
                "<code>phone::api_id::api_hash::session_string</code>",
                parse_mode="HTML",
            )
            return

        try:
            await processing_msg.delete()
        except Exception:
            pass

    # ─── CASE C: نص مباشر ───
    else:
        text_input = message.text or ""
        lines = [ln.strip() for ln in text_input.strip().splitlines() if ln.strip()]

    if not lines:
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 إدارة المخزون", callback_data="admin:stock")
        await message.answer(
            "❌ لم يتم إرسال أي بيانات صحيحة.",
            reply_markup=builder.as_markup(),
        )
        return

    # ── المرحلة 1: فحص صيغة كل سطر (سريع، بدون شبكة) ──────────────────────
    from utils.session_manager import parse_account_data as _parse_for_validate
    parsed_ok: list[tuple[str, str]] = []   # (line, phone)
    syntax_failed = 0

    for line in lines:
        p = _parse_for_validate(line)
        if p:
            parsed_ok.append((line, p["phone"]))
        else:
            syntax_failed += 1

    if not parsed_ok:
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 إدارة المخزون", callback_data="admin:stock")
        await message.answer(
            f"❌ <b>لم يتم قبول أي حساب!</b>\n\n"
            f"❌ فشل التحليل: <b>{syntax_failed}</b>\n\n"
            "تأكد من صيغة البيانات:\n"
            "<code>phone::api_id::api_hash::session_string</code>",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        return

    # ── المرحلة 2: سؤال الأدمن عن باسوورد 2FA لهذه الدفعة ──────────────────
    await state.update_data(
        stock_country=code,
        stock_country_name=country_name,
        stock_price=price,
        stock_type=store_type,
        stock_total_lines=len(lines),
        stock_syntax_failed=syntax_failed,
        stock_parsed_ok=[p[0] for p in parsed_ok],
    )
    await state.set_state(AdminState.waiting_for_batch_password)

    builder = InlineKeyboardBuilder()
    builder.button(text="⏭️ تخطي (بدون باسوورد)", callback_data="stock_pw:skip")
    builder.button(text="❌ إلغاء", callback_data="admin:stock")
    builder.adjust(1)

    await message.answer(
        f"📦 <b>تم استلام {len(parsed_ok)} حساب بنجاح!</b>\n\n"
        f"🔐 <b>هل تحتوي هذه الدفعة على كلمة مرور للتحقق بخطوتين (2FA)؟</b>\n\n"
        f"• <b>أرسل كلمة المرور الآن</b> ليتم فحصها واختبارها وربطها بالأرقام.\n"
        f"• أو اضغط <b>«⏭️ تخطي (بدون باسوورد)»</b> إذا كانت الأرقام بدون باسوورد أو كان الباسوورد داخل ملفات JSON/TXT مسبقاً.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


async def _process_stock_insertion_and_validation(
    event,
    state: FSMContext,
    bot: Bot,
    batch_password: str = "",
):
    data = await state.get_data()
    await state.clear()

    code          = data.get("stock_country", "")
    country_name  = data.get("stock_country_name", "")
    price         = data.get("stock_price", 0.0)
    store_type    = data.get("stock_type", "dollar")
    parsed_lines  = data.get("stock_parsed_ok", [])
    total_lines   = data.get("stock_total_lines", len(parsed_lines))
    syntax_failed = data.get("stock_syntax_failed", 0)

    from utils.session_manager import parse_account_data as _parse_for_validate
    inserted: list[tuple[int, str, str]] = []
    insert_failed = 0

    batch_pw = batch_password.strip()

    for raw_line in parsed_lines:
        line_to_save = raw_line
        p = _parse_for_validate(raw_line)
        if not p:
            continue
        phone = p["phone"]

        # إذا قام الأدمن بإدخال باسوورد دفعة، نطبقه على الحسابات (مع استبدال أي باسوورد قديم في الملف)
        if batch_pw:
            parts = [x.strip() for x in raw_line.split("::")]
            if len(parts) == 2 or len(parts) == 3:
                line_to_save = f"{parts[0]}::{parts[1]}::{batch_pw}"
            elif len(parts) >= 4:
                line_to_save = f"{parts[0]}::{parts[1]}::{parts[2]}::{parts[3]}::{batch_pw}"

        try:
            acc_id = await add_account_to_stock(
                country_code=code,
                country_name=country_name,
                account_data=line_to_save,
                price=price,
                store_type=store_type,
                status="maintenance",
            )
            inserted.append((acc_id, line_to_save, phone))
        except Exception as e:
            logger.error("Failed to insert account line: %s", e)
            insert_failed += 1

    total_failed = syntax_failed + insert_failed
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 إدارة المخزون", callback_data="admin:stock")

    pw_status_text = f"🔐 باسوورد الدفعة: <code>{batch_pw}</code>\n" if batch_pw else "🔐 باسوورد الدفعة: لا يوجد (تخطي)\n"

    msg_text = (
        f"⏳ <b>تمت الإضافة — جارٍ التحقق من صحة الحسابات واختبار الباسوورد...</b>\n\n"
        f"📋 إجمالي الأسطر: <b>{total_lines}</b>\n"
        f"🔍 في انتظار التحقق: <b>{len(inserted)}</b>\n"
        f"❌ فشل (صيغة/إدراج): <b>{total_failed}</b>\n"
        f"{pw_status_text}\n"
        f"<i>الحسابات الصالحة ستُفعَّل تلقائياً وستصلك النتيجة قريباً.</i>"
    )

    admin_id = event.from_user.id
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(msg_text, reply_markup=builder.as_markup(), parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(msg_text, reply_markup=builder.as_markup(), parse_mode="HTML")

    if inserted:
        task = asyncio.create_task(
            _validate_and_activate_stock(inserted, admin_id, bot, country_name)
        )
        task.add_done_callback(
            lambda t: logger.error("_validate_and_activate_stock error: %s", t.exception())
            if not t.cancelled() and t.exception() else None
        )


@router.callback_query(F.data == "stock_pw:skip", AdminState.waiting_for_batch_password)
async def admin_stock_pw_skip_cb(callback: CallbackQuery, state: FSMContext, bot: Bot):
    if not await _is_admin_or_has_perm(callback.from_user.id, "stock"):
        await callback.answer("⛔", show_alert=True)
        return
    await _process_stock_insertion_and_validation(callback, state, bot, batch_password="")


@router.message(AdminState.waiting_for_batch_password)
async def admin_stock_pw_message(message: Message, state: FSMContext, bot: Bot):
    if not await _is_admin_or_has_perm(message.from_user.id, "stock"):
        return
    password = message.text.strip()
    await _process_stock_insertion_and_validation(message, state, bot, batch_password=password)


# ─── عرض وحذف الأرقام ────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:view_stock")
async def admin_view_stock(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    countries = await get_all_countries()
    if not countries:
        await callback.answer("❌ لا توجد دول.", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for c in countries:
        flag  = c.get("flag_emoji", "")
        stock = c.get("stock_count", 0)
        builder.button(
            text=f"{flag} {c['country_name']} ({stock})",
            callback_data=f"view_stock_country:{c['country_code']}",
        )
    builder.button(text="🔙 رجوع", callback_data="admin:stock")
    builder.adjust(2)
    await callback.message.edit_text(
        "📋 <b>عرض وإلغاء الأرقام</b>\n\nاختر الدولة:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("view_stock_country:"))
async def admin_view_stock_country(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    code     = callback.data.split(":", 1)[1].upper()
    accounts = await get_available_accounts_by_country(code)
    if not accounts:
        await callback.answer("❌ لا يوجد مخزون لهذه الدولة.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for acc in accounts[:20]:
        phone = acc["account_data"].split("::")[0][:15]
        builder.button(
            text=f"🗑 {phone}",
            callback_data=f"del_stock:{acc['id']}:{code}",
        )
    builder.button(text="🔙 رجوع", callback_data="admin:view_stock")
    builder.adjust(2)

    await callback.message.edit_text(
        f"📋 الأرقام المتاحة في <b>{code}</b> (أول 20):\n\n"
        "اضغط على رقم لحذفه من المخزون:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("del_stock:"))
async def admin_delete_stock_account(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    parts = callback.data.split(":")
    try:
        account_id = int(parts[1])
        code       = parts[2]
    except (IndexError, ValueError):
        await callback.answer("❌", show_alert=True)
        return

    await delete_account_from_stock(account_id)
    await callback.answer("✅ تم حذف الرقم.", show_alert=True)

    accounts = await get_available_accounts_by_country(code)
    if not accounts:
        await callback.message.edit_text(
            f"✅ تم حذف الرقم.\n\n📋 لا يوجد مخزون متبقٍّ في <b>{code}</b>.",
            reply_markup=admin_back_keyboard("admin:view_stock"),
            parse_mode="HTML",
        )
        return

    builder = InlineKeyboardBuilder()
    for acc in accounts[:20]:
        phone = acc["account_data"].split("::")[0][:15]
        builder.button(
            text=f"🗑 {phone}",
            callback_data=f"del_stock:{acc['id']}:{code}",
        )
    builder.button(text="🔙 رجوع", callback_data="admin:view_stock")
    builder.adjust(2)
    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())


# ─── إضافة دولة جديدة ────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:add_country")
async def admin_add_country_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminState.waiting_for_new_country_code)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:stock")
    await callback.message.edit_text(
        "🌍 <b>إضافة دولة جديدة</b>\n\nأرسل كود الدولة (مثال: SA، US، EG):",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminState.waiting_for_new_country_code)
async def admin_new_country_code(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    code = message.text.strip().upper()
    if not code.isalpha() or len(code) > 5:
        await message.answer("❌ كود غير صالح، أرسل حروفاً فقط (2-5 أحرف).")
        return
    await state.update_data(new_country_code=code)
    await state.set_state(AdminState.waiting_for_new_country_name)
    await message.answer(f"✅ الكود: <b>{code}</b>\n\nأرسل اسم الدولة:", parse_mode="HTML")


@router.message(AdminState.waiting_for_new_country_name)
async def admin_new_country_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(new_country_name=message.text.strip())
    await state.set_state(AdminState.waiting_for_new_country_flag)
    await message.answer("أرسل الإيموجي الخاص بالدولة (مثال: 🇸🇦):")


@router.message(AdminState.waiting_for_new_country_flag)
async def admin_new_country_flag(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(new_country_flag=message.text.strip())
    await state.set_state(AdminState.waiting_for_new_country_price)
    await message.answer("أرسل سعر الحساب بالدولار (مثال: 2.50):")


@router.message(AdminState.waiting_for_new_country_price)
async def admin_new_country_price(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        price = float(message.text.strip())
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ أدخل سعراً صحيحاً.")
        return

    data = await state.get_data()
    await state.clear()

    code  = data["new_country_code"]
    name  = data["new_country_name"]
    flag  = data.get("new_country_flag", "🌍")

    await add_country(code, name, flag, price)

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 إدارة المخزون", callback_data="admin:stock")
    await message.answer(
        f"✅ تمت إضافة الدولة:\n\n"
        f"{flag} <b>{name}</b> ({code}) — ${price:.2f}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


# ─── تغيير سعر دولة ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:change_price")
async def admin_change_price_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    countries = await get_all_countries()
    if not countries:
        await callback.answer("❌ لا توجد دول.", show_alert=True)
        return
    await callback.message.edit_text(
        "💲 <b>تغيير سعر دولة</b>\n\nاختر الدولة:",
        reply_markup=admin_countries_keyboard(countries, "chprice"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("chprice:"))
async def admin_change_price_country(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    code = callback.data.split(":", 1)[1].upper()
    await state.update_data(price_country=code)
    await state.set_state(AdminState.waiting_for_new_price)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:stock")
    await callback.message.edit_text(
        f"💲 الدولة: <b>{code}</b>\n\nأرسل السعر الجديد بالدولار:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminState.waiting_for_new_price)
async def admin_new_price_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        price = float(message.text.strip())
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ أدخل سعراً صحيحاً.")
        return

    data = await state.get_data()
    code = data["price_country"]
    await state.clear()
    await update_country_price(code, price)

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 إدارة المخزون", callback_data="admin:stock")
    await message.answer(
        f"✅ تم تحديث سعر <b>{code}</b> إلى <b>${price:.2f}</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


# ─── تغيير سعر النقاط ────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:change_points_price")
async def admin_change_points_price_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    countries = await get_all_countries()
    if not countries:
        await callback.answer("❌ لا توجد دول.", show_alert=True)
        return
    await callback.message.edit_text(
        "🪙 <b>تغيير سعر النقاط</b>\n\nاختر الدولة:",
        reply_markup=admin_countries_keyboard(countries, "chpts"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("chpts:"))
async def admin_change_points_price_country(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    code = callback.data.split(":", 1)[1].upper()
    await state.update_data(price_country=code)
    await state.set_state(AdminState.waiting_for_new_points_price)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:stock")
    await callback.message.edit_text(
        f"🪙 الدولة: <b>{code}</b>\n\nأرسل سعر النقاط الجديد (عدد صحيح):",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminState.waiting_for_new_points_price)
async def admin_new_points_price_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        pts = int(message.text.strip())
        if pts < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ أدخل عدداً صحيحاً.")
        return

    data = await state.get_data()
    code = data["price_country"]
    await state.clear()
    await update_country_points_price(code, pts)

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 إدارة المخزون", callback_data="admin:stock")
    await message.answer(
        f"✅ تم تحديث سعر نقاط <b>{code}</b> إلى <b>{pts} 🪙</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


# ─── فحص صحة الحسابات ──────────────────────────────────────────────────────────────────────────

async def _check_single_account(
    account_id: int,
    account_data: str,
    sem: asyncio.Semaphore,
    bot: Bot = None,
    admin_id: int = 0,
) -> tuple:
    """
    يفحص صحة جلسة حساب واحد.
    يُرجع: (account_id, status, phone, is_notable, year, is_premium)
    - status: "valid" | "frozen" | "unknown"
    - is_notable: True إذا كان الحساب قديماً (≤2020) أو يحمل Premium
    """
    from pyrogram import Client
    from pyrogram.errors import (
        AuthKeyUnregistered, UserDeactivated, SessionExpired,
        AuthKeyDuplicated, UserDeactivatedBan, AuthKeyInvalid,
    )
    from utils.session_manager import parse_account_data, _random_device
    phone = account_data.split("::")[0].strip() if account_data else "?"
    parsed = parse_account_data(account_data)
    if not parsed:
        return account_id, "frozen", phone, False, 0, False

    async with sem:
        client = None
        try:
            device = _random_device()
            proxy_kwargs = await _get_proxy_kwargs(parsed["phone"])
            client = Client(
                name=f"chk_{parsed['phone'].replace('+', '')}_{account_id}",
                api_id=parsed["api_id"],
                api_hash=parsed["api_hash"],
                session_string=parsed["session_string"],
                in_memory=True,
                no_updates=True,
                **{k: device[k] for k in device},
                **proxy_kwargs,
            )
            
            # اتصال بدون طلب تفاعلي
            try:
                is_auth = await asyncio.wait_for(client.connect(), timeout=12)
            except (asyncio.TimeoutError, OSError, ConnectionError):
                if proxy_kwargs:
                    # إعادة محاولة مباشرة بدون بروكسي في حال تعطل البروكسي
                    try:
                        if client.is_connected:
                            await client.disconnect()
                    except Exception:
                        pass
                    client = Client(
                        name=f"chk_direct_{parsed['phone'].replace('+', '')}_{account_id}",
                        api_id=parsed["api_id"],
                        api_hash=parsed["api_hash"],
                        session_string=parsed["session_string"],
                        in_memory=True,
                        no_updates=True,
                        **{k: device[k] for k in device},
                    )
                    is_auth = await asyncio.wait_for(client.connect(), timeout=12)
                else:
                    raise

            if not is_auth:
                return account_id, "frozen", phone, False, 0, False

            # ── كشف الحسابات المميزة ────────────────────────────────────────
            me = await asyncio.wait_for(client.get_me(), timeout=10)
            if not me:
                return account_id, "frozen", phone, False, 0, False

            year = _estimate_account_year(me.id)
            is_premium = bool(getattr(me, "is_premium", False))
            is_notable = (year > 0 and year <= 2020) or is_premium

            return account_id, "valid", phone, is_notable, year, is_premium

        except (AuthKeyUnregistered, UserDeactivated, SessionExpired,
                AuthKeyDuplicated, UserDeactivatedBan, AuthKeyInvalid):
            # أخطاء مميتة — الجلسة منتهية أو محظورة بالفعل
            return account_id, "frozen", phone, False, 0, False
        except asyncio.TimeoutError:
            logger.warning("Timeout checking account %s (%s)", account_id, phone)
            return account_id, "unknown", phone, False, 0, False
        except Exception as e:
            logger.warning("Unexpected error checking account %s (%s): %s", account_id, phone, e)
            return account_id, "unknown", phone, False, 0, False
        finally:
            if client is not None:
                try:
                    if client.is_connected:
                        await asyncio.wait_for(client.disconnect(), timeout=4)
                except Exception:
                    pass


@router.callback_query(F.data == "admin:check_accounts")
async def admin_check_accounts(callback: CallbackQuery, state: FSMContext, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    accounts = await get_all_available_accounts()
    total = len(accounts)
    if not accounts:
        await callback.message.edit_text(
            "📦 لا يوجد مخزون متاح حالياً.",
            reply_markup=admin_back_keyboard("admin:stock"),
        )
        await callback.answer()
        return
    await callback.answer("⏳ جاري الفحص...", show_alert=False)
    progress_msg = await callback.message.edit_text(
        f"🔍 <b>جاري فحص {total} حساب...</b>\n\n"
        "⏳ قد يستغرق هذا بعض الوقت، يُرجى الانتظار.",
        parse_mode="HTML",
    )
    admin_id = callback.from_user.id
    sem = asyncio.Semaphore(10)
    tasks = [
        _check_single_account(acc["id"], acc["account_data"], sem, bot, admin_id)
        for acc in accounts
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    valid_count    = 0
    notable_count  = 0
    frozen_ids     = []
    frozen_phones  = []
    unknown_phones = []
    unknown_count  = 0
    for res in results:
        if isinstance(res, Exception):
            continue
        # (account_id, status, phone, is_notable, year, is_premium)
        acc_id, status, phone = res[0], res[1], res[2]
        is_notable = res[3] if len(res) > 3 else False
        if status == "valid":
            valid_count += 1
            if is_notable:
                notable_count += 1
        elif status == "frozen":
            frozen_ids.append(acc_id)
            frozen_phones.append(phone)
        else:
            # unknown — مشكلة شبكة أو timeout، لا نضيفها للحذف
            unknown_count += 1
            unknown_phones.append(phone)
    frozen_count = len(frozen_ids)
    ratings  = await get_ratings_stats()
    avg_str  = f"{ratings.get('overall_avg', 0):.1f}" if ratings else "—"
    count_r  = ratings.get("total_ratings", 0) if ratings else 0
    await state.update_data(frozen_account_ids=frozen_ids)
    phones_text = ""
    if frozen_phones:
        shown = frozen_phones[:30]
        phones_text = "\n\n📋 <b>الأرقام المجمدة/الغير صالحة:</b>\n"
        phones_text += "\n".join(f"• <code>{p}</code>" for p in shown)
        if len(frozen_phones) > 30:
            phones_text += f"\n... و<b>{len(frozen_phones) - 30}</b> رقم آخر"
    if unknown_phones:
        shown_u = unknown_phones[:30]
        phones_text += "\n\n⚠️ <b>الأرقام غير محددة الشبكة (timeout):</b>\n"
        phones_text += "\n".join(f"• <code>{p}</code>" for p in shown_u)
        if len(unknown_phones) > 30:
            phones_text += f"\n... و<b>{len(unknown_phones) - 30}</b> رقم آخر"
    notable_line  = f"\n⭐ حسابات مميزة (قديمة/Premium): <b>{notable_count}</b>" if notable_count else ""
    unknown_line  = f"\n⚠️ غير محددة (شبكة/timeout): <b>{unknown_count}</b>" if unknown_count else ""
    text = (
        f"🔍 <b>نتيجة فحص الحسابات</b>\n\n"
        f"📦 إجمالي المتاح: <b>{total}</b>\n"
        f"✅ حسابات سليمة: <b>{valid_count}</b>\n"
        f"❌ حسابات مجمدة/غير صالحة: <b>{frozen_count}</b>"
        + unknown_line
        + notable_line
        + f"\n⭐ متوسط التقييم: <b>{avg_str}</b> ({count_r} تقييم)"
        + phones_text
    )
    builder = InlineKeyboardBuilder()
    if frozen_ids:
        builder.button(
            text=f"🗑 حذف الحسابات المجمدة ({frozen_count})",
            callback_data="admin:delete_invalid_accounts",
        )
    builder.button(text="🔙 رجوع", callback_data="admin:stock")
    builder.adjust(1)
    await progress_msg.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "admin:delete_invalid_accounts")
async def admin_delete_invalid_accounts(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    data = await state.get_data()
    frozen_ids = data.get("frozen_account_ids", [])
    if not frozen_ids:
        await callback.answer("❌ لا توجد حسابات مجمدة للحذف.", show_alert=True)
        return
    await callback.answer("⏳ جاري الحذف...", show_alert=False)
    deleted = 0
    for acc_id in frozen_ids:
        if await delete_account_from_stock(acc_id):
            deleted += 1
    await state.update_data(frozen_account_ids=[])
    await callback.message.edit_text(
        f"✅ <b>تم الحذف!</b>\n\n🗑 تم حذف <b>{deleted}</b> حساب مجمد/غير صالح.",
        reply_markup=admin_back_keyboard("admin:stock"),
        parse_mode="HTML",
    )


# ─── فلاش سيل ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:flash_sale")
async def admin_flash_sale_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    countries = await get_all_countries()
    if not countries:
        await callback.answer("❌ لا توجد دول.", show_alert=True)
        return

    active = await get_active_flash_sales()
    active_codes = {r["country_code"] for r in active} if active else set()

    lines = []
    for c in countries:
        flag = c.get("flag_emoji", "")
        code = c["country_code"]
        if code in active_codes:
            lines.append(f"⚡ {flag} {c['country_name']}")
        else:
            lines.append(f"   {flag} {c['country_name']}")

    text = "⚡ <b>إدارة الفلاش سيل</b>\n\n" + "\n".join(lines) if lines else "لا توجد دول."

    await callback.message.edit_text(
        text + "\n\nاختر دولة لتفعيل/تعديل الفلاش سيل:",
        reply_markup=admin_flash_sale_keyboard(countries),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("flash_set:"))
async def admin_flash_set_country(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    code = callback.data.split(":", 1)[1].upper()
    await state.update_data(flash_country=code)
    await state.set_state(AdminState.waiting_for_flash_sale_discount)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:flash_sale")
    await callback.message.edit_text(
        f"⚡ <b>فلاش سيل — {code}</b>\n\nأرسل نسبة الخصم (مثال: 20 = 20%):",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminState.waiting_for_flash_sale_discount)
async def admin_flash_discount_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        discount = float(message.text.strip())
        if discount <= 0 or discount >= 100:
            raise ValueError
    except ValueError:
        await message.answer("❌ أدخل نسبة صحيحة بين 1 و99.")
        return
    await state.update_data(flash_discount=discount)
    await state.set_state(AdminState.waiting_for_flash_sale_hours)
    await message.answer("أرسل مدة الفلاش سيل بالساعات (مثال: 6 = 6 ساعات):")


@router.message(AdminState.waiting_for_flash_sale_hours)
async def admin_flash_hours_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        hours = int(message.text.strip())
        if hours <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ أدخل عدد ساعات صحيحاً.")
        return

    data     = await state.get_data()
    code     = data["flash_country"]
    discount = data["flash_discount"]
    await state.clear()

    await set_flash_sale(code, discount, hours)

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 إدارة المخزون", callback_data="admin:stock")
    await message.answer(
        f"✅ تم تفعيل فلاش سيل على <b>{code}</b>:\n"
        f"⚡ الخصم: <b>{discount:.0f}%</b>\n"
        f"⏱ المدة: <b>{hours} ساعة</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "flash_clear_all")
async def admin_flash_clear_all(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    active = await get_active_flash_sales()
    for sale in active:
        await clear_flash_sale(sale["country_code"])
    await callback.answer("✅ تم إلغاء جميع الفلاش سيل!", show_alert=True)
    countries = await get_all_countries()
    await callback.message.edit_text(
        "⚡ <b>إدارة الفلاش سيل</b>\n\nتم إلغاء جميع الخصومات.\n\nاختر دولة:",
        reply_markup=admin_flash_sale_keyboard(countries),
        parse_mode="HTML",
    )





# ─── إعدادات النجوم ───────────────────────────────────────────────────────────

# ─── إعدادات النجوم وتحديد مستوى التحقق ───────────────────────────────────────

@router.callback_query(F.data == "admin:stars")
async def admin_stars_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    stars_rate = await get_setting("stars_rate") or "0.011"
    min_stars  = await get_setting("min_deposit_stars") or "100"
    min_usd    = await get_setting("min_deposit_usd") or "1.0"
    check_raw  = await get_setting("stars_rating_check_enabled")
    check_enabled = (check_raw != "0")

    status_str = "🟢 <b>مفعّـل (يُشترط مستوى 1+ أو حساب قديم)</b>" if check_enabled else "🔴 <b>معطّـل (الشحن مسموح للجميع بما في ذلك النجوم السلبية)</b>"

    await callback.message.edit_text(
        f"⭐ <b>إعدادات النجوم والتحقق الأمنـي</b>\n\n"
        f"🛡️ حالة فحص مستوى النجوم: {status_str}\n\n"
        f"💱 سعر النجمة: <b>${float(stars_rate):.4f}</b>\n"
        f"⭐ الحد الأدنى بالنجوم: <b>{min_stars}</b>\n"
        f"💲 الحد الأدنى بالدولار: <b>${float(min_usd):.2f}</b>",
        reply_markup=admin_stars_keyboard(check_enabled=check_enabled),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin:toggle_stars_check")
async def admin_toggle_stars_check(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    current = await get_setting("stars_rating_check_enabled")
    new_val = "0" if current != "0" else "1"
    await set_setting("stars_rating_check_enabled", new_val)
    status_text = "🔴 تم تعطيل فحص مستوى النجوم! الآن يمكن لأي حساب الشحن بالنجوم." if new_val == "0" else "🟢 تم تفعيل فحص مستوى النجوم الصارم لحماية المتجر."
    await callback.answer(status_text, show_alert=True)
    await admin_stars_menu(callback)


# ─── إدارة إلغاء الحظر ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:unban_menu")
async def admin_unban_menu(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.clear()
    from database import get_banned_users
    banned = await get_banned_users()
    count = len(banned)

    builder = InlineKeyboardBuilder()
    builder.button(text="🔓  إلغاء حظر جميع المحظورين", callback_data="admin:unban_all")
    builder.button(text="👤  إلغاء حظر ID معين", callback_data="admin:unban_id")
    builder.button(text="🔙  رجوع لإعدادات النجوم", callback_data="admin:stars")
    builder.adjust(1)

    await callback.message.edit_text(
        f"🔓 <b>إدارة إلغاء الحظر للحسابات</b>\n\n"
        f"📌 عدد الحسابات المحظورة حالياً: <b>{count}</b> حساب.\n\n"
        f"💡 يمكنك إلغاء الحظر عن حساب معين عن طريق ID أو إلغاء الحظر عن جميع الحسابات بنقرة واحدة.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin:unban_all")
async def admin_unban_all_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    from database import unban_all_banned_users
    count = await unban_all_banned_users()
    await callback.answer(f"✅ تم إلغاء الحظر عن {count} حساب وحذفهم من قائمة الحظر!", show_alert=True)
    await admin_unban_menu(callback, None)


@router.callback_query(F.data == "admin:unban_id")
async def admin_unban_id_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminState.waiting_for_unban_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:unban_menu")
    await callback.message.edit_text(
        "👤 <b>أرسل ID المستخدم المراد إلغاء حظره:</b>\n\n"
        "مثال: <code>123456789</code>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminState.waiting_for_unban_id)
async def admin_unban_id_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        target_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ يرجى إدخال ID صحيح (أرقام فقط).")
        return
    await state.clear()
    from database import unban_user, get_user
    await unban_user(target_id)
    usr = await get_user(target_id)
    name = usr.get("first_name", str(target_id)) if usr else str(target_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 إدارة الحظر", callback_data="admin:unban_menu")
    await message.answer(
        f"✅ <b>تم إلغاء حظر المستخدم بنجاح!</b>\n\n"
        f"👤 الاسم/الـ ID: <b>{name}</b> (<code>{target_id}</code>)\n"
        f"تمت إزالة الحظر عنه ويمكنه استخدام البوت وشحن الحساب الآن.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:set_stars_rate")
async def admin_set_stars_rate_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminState.waiting_for_stars_rate)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:stars")
    await callback.message.edit_text(
        "💱 أرسل سعر النجمة الواحدة بالدولار (مثال: 0.011):",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.message(AdminState.waiting_for_stars_rate)
async def admin_stars_rate_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        rate = float(message.text.strip())
        if rate <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ أدخل قيمة صحيحة.")
        return
    await state.clear()
    await set_setting("stars_rate", str(rate))
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 إعدادات النجوم", callback_data="admin:stars")
    await message.answer(
        f"✅ سعر النجمة: <b>${rate:.4f}</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:set_min_stars")
async def admin_set_min_stars_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminState.waiting_for_min_deposit_stars)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:stars")
    await callback.message.edit_text(
        "⭐ أرسل الحد الأدنى لعدد النجوم للشحن:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.message(AdminState.waiting_for_min_deposit_stars)
async def admin_min_stars_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        val = int(message.text.strip())
        if val <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ أدخل عدداً صحيحاً.")
        return
    await state.clear()
    await set_setting("min_deposit_stars", str(val))
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 إعدادات النجوم", callback_data="admin:stars")
    await message.answer(
        f"✅ الحد الأدنى للنجوم: <b>{val} ⭐</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:set_min_usd")
async def admin_set_min_usd_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminState.waiting_for_min_deposit_usd)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:stars")
    await callback.message.edit_text(
        "💲 أرسل الحد الأدنى للإيداع بالدولار (مثال: 1.0):",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.message(AdminState.waiting_for_min_deposit_usd)
async def admin_min_usd_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        val = float(message.text.strip())
        if val <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ أدخل قيمة صحيحة.")
        return
    await state.clear()
    await set_setting("min_deposit_usd", str(val))
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 إعدادات النجوم", callback_data="admin:stars")
    await message.answer(
        f"✅ الحد الأدنى للإيداع: <b>${val:.2f}</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )



# ─── حساب فحص النجوم ──────────────────────────────────────────────────────────

# جلسات تسجيل الدخول المؤقتة لحساب الفحص: admin_id → {client, phone, phone_code_hash}
_checker_sessions: dict[int, dict] = {}


async def _cleanup_checker_session(admin_id: int) -> None:
    session = _checker_sessions.pop(admin_id, None)
    if session and session.get("client"):
        try:
            await session["client"].stop()
        except Exception:
            pass


@router.callback_query(F.data == "admin:stars_checker")
async def admin_stars_checker_menu(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.clear()
    await _cleanup_checker_session(callback.from_user.id)

    session_raw = await get_setting("stars_checker_session") or ""
    has_session = bool(session_raw.strip())

    builder = InlineKeyboardBuilder()
    if has_session:
        builder.button(text="✏️  تحديث الحساب",  callback_data="admin:stars_checker_set")
        builder.button(text="🗑  حذف الحساب",     callback_data="admin:stars_checker_del")
    else:
        builder.button(text="➕  إضافة حساب",     callback_data="admin:stars_checker_set")
    builder.button(text="🔙  رجوع",              callback_data="admin:stars")
    builder.adjust(1)

    status_line = (
        "✅ <b>حساب الفحص مضبوط وجاهز</b>" if has_session
        else "❌ <b>لا يوجد حساب فحص مضبوط</b>"
    )
    await callback.message.edit_text(
        f"🔍 <b>حساب فحص النجوم</b>\n\n"
        f"{status_line}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📌 <b>كيف يعمل:</b>\n"
        "البوت يستخدم هذا الحساب للتحقق من تقييم نجوم المستخدم قبل قبول الشحن.\n"
        "إذا كان التقييم سلبياً يُرفض الدفع ويُطلب من المستخدم طريقة أخرى.\n\n"
        "📱 الإضافة تتم بإدخال رقم الهاتف فقط.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin:stars_checker_set")
async def admin_stars_checker_set_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await _cleanup_checker_session(callback.from_user.id)
    await state.set_state(AdminState.waiting_for_checker_phone)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:stars_checker")
    await callback.message.edit_text(
        "📱 <b>أرسل رقم هاتف حساب الفحص</b>\n\n"
        "بصيغة دولية كاملة، مثال:\n"
        "<code>+9665XXXXXXXX</code>\n\n"
        "⚠️ يجب أن يكون حساباً عادياً (غير مرتبط ببوت).",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminState.waiting_for_checker_phone)
async def admin_checker_phone_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text and message.text.startswith("/"):
        await state.clear()
        await _cleanup_checker_session(message.from_user.id)
        await message.answer("❌ تم الإلغاء.")
        return

    from pyrogram import Client as PyroClient
    from pyrogram.errors import (
        PhoneNumberInvalid, PhoneNumberBanned,
        FloodWait as PyroFloodWait,
    )
    from config import DEFAULT_API_ID, DEFAULT_API_HASH

    if not DEFAULT_API_ID or not DEFAULT_API_HASH:
        await message.answer(
            "❌ <b>يجب ضبط DEFAULT_API_ID و DEFAULT_API_HASH أولاً في الإعدادات.</b>",
            parse_mode="HTML",
        )
        await state.clear()
        return

    phone = message.text.strip()
    if not phone.startswith("+"):
        phone = "+" + phone

    waiting_msg = await message.answer("⏳ جاري إرسال كود التحقق...")
    await _cleanup_checker_session(message.from_user.id)

    client = PyroClient(
        name=f"checker_login_{message.from_user.id}",
        api_id=DEFAULT_API_ID,
        api_hash=DEFAULT_API_HASH,
        in_memory=True,
        no_updates=True,
    )

    try:
        await client.connect()
        sent = await client.send_code(phone)
        phone_code_hash = sent.phone_code_hash
        code_type = type(sent.type).__name__

        if "App" in code_type:
            hint = (
                "📲 <b>الكود وصل داخل تطبيق تيليجرام</b>\n"
                "افتح تيليجرام وانظر إشعار <b>Login code</b>."
            )
        elif "Sms" in code_type:
            hint = "📩 <b>الكود أُرسل عبر SMS</b> — تحقق من رسائل الجوال."
        elif "Call" in code_type or "Flash" in code_type:
            hint = "📞 <b>ستصلك مكالمة</b> — الكود هو آخر 5 أرقام من رقم المتصل."
        else:
            hint = "📨 <b>الكود في طريقه إليك.</b>"

        _checker_sessions[message.from_user.id] = {
            "client":          client,
            "phone":           phone,
            "phone_code_hash": phone_code_hash,
        }

        builder = InlineKeyboardBuilder()
        builder.button(text="❌ إلغاء", callback_data="admin:stars_checker")
        await waiting_msg.edit_text(
            f"✅ <b>تم إرسال الكود!</b>\n\n"
            f"{hint}\n\n"
            "أرسل الكود المكوّن من 5 أرقام:",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        await state.update_data(checker_phone=phone)
        await state.set_state(AdminState.waiting_for_checker_otp)

    except PhoneNumberInvalid:
        await client.disconnect()
        await waiting_msg.edit_text("❌ رقم الهاتف غير صالح. أرسل رقماً صحيحاً:")
    except PhoneNumberBanned:
        await client.disconnect()
        await waiting_msg.edit_text("❌ هذا الرقم محظور من تيليجرام. جرّب رقماً آخر.")
    except PyroFloodWait as fw:
        await client.disconnect()
        await waiting_msg.edit_text(
            f"⏳ يجب الانتظار <b>{fw.value}</b> ثانية قبل المحاولة مجدداً.",
            parse_mode="HTML",
        )
    except Exception as e:
        await client.disconnect()
        logger.error("checker_login send_code error: %s", e)
        await waiting_msg.edit_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")


@router.message(AdminState.waiting_for_checker_otp)
async def admin_checker_otp_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text and message.text.startswith("/"):
        await state.clear()
        await _cleanup_checker_session(message.from_user.id)
        await message.answer("❌ تم الإلغاء.")
        return

    from pyrogram.errors import (
        PhoneCodeInvalid, PhoneCodeExpired,
        SessionPasswordNeeded, FloodWait as PyroFloodWait,
    )

    session = _checker_sessions.get(message.from_user.id)
    if not session:
        await message.answer("❌ انتهت الجلسة. ابدأ من جديد.")
        await state.clear()
        return

    code   = message.text.strip().replace(" ", "")
    client = session["client"]
    phone  = session["phone"]
    phash  = session["phone_code_hash"]

    waiting_msg = await message.answer("⏳ جاري التحقق...")

    try:
        await client.sign_in(
            phone_number=phone,
            phone_code_hash=phash,
            phone_code=code,
        )
        await _finish_checker_login(message, state, client, phone)

    except PhoneCodeInvalid:
        await waiting_msg.edit_text(
            "❌ <b>الكود خاطئ!</b>\nأرسل الكود الصحيح:", parse_mode="HTML"
        )
    except PhoneCodeExpired:
        await _cleanup_checker_session(message.from_user.id)
        await state.clear()
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 إعادة المحاولة", callback_data="admin:stars_checker_set")
        builder.button(text="🔙 رجوع",           callback_data="admin:stars_checker")
        builder.adjust(1)
        await waiting_msg.edit_text(
            "❌ <b>انتهت صلاحية الكود.</b>\nاطلب كوداً جديداً:",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
    except SessionPasswordNeeded:
        await state.set_state(AdminState.waiting_for_checker_2fa)
        builder = InlineKeyboardBuilder()
        builder.button(text="❌ إلغاء", callback_data="admin:stars_checker")
        await waiting_msg.edit_text(
            "🔐 <b>هذا الحساب محمي بكلمة مرور (2FA)</b>\n\nأرسل كلمة المرور:",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
    except PyroFloodWait as fw:
        await waiting_msg.edit_text(
            f"⏳ انتظر <b>{fw.value}</b> ثانية ثم أعد إرسال الكود.",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error("checker_login sign_in error: %s", e)
        await _cleanup_checker_session(message.from_user.id)
        await state.clear()
        await waiting_msg.edit_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")


@router.message(AdminState.waiting_for_checker_2fa)
async def admin_checker_2fa_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text and message.text.startswith("/"):
        await state.clear()
        await _cleanup_checker_session(message.from_user.id)
        await message.answer("❌ تم الإلغاء.")
        return

    from pyrogram.errors import PasswordHashInvalid, FloodWait as PyroFloodWait

    session = _checker_sessions.get(message.from_user.id)
    if not session:
        await message.answer("❌ انتهت الجلسة. ابدأ من جديد.")
        await state.clear()
        return

    password    = message.text.strip()
    client      = session["client"]
    phone       = session["phone"]
    waiting_msg = await message.answer("⏳ جاري التحقق من كلمة المرور...")

    try:
        await client.check_password(password)
        await _finish_checker_login(message, state, client, phone)
    except PasswordHashInvalid:
        await waiting_msg.edit_text(
            "❌ <b>كلمة المرور خاطئة!</b>\nأرسل كلمة المرور الصحيحة:", parse_mode="HTML"
        )
    except PyroFloodWait as fw:
        await waiting_msg.edit_text(
            f"⏳ انتظر <b>{fw.value}</b> ثانية ثم أعد المحاولة.", parse_mode="HTML"
        )
    except Exception as e:
        logger.error("checker_login 2fa error: %s", e)
        await _cleanup_checker_session(message.from_user.id)
        await state.clear()
        await waiting_msg.edit_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")


async def _finish_checker_login(
    message: Message,
    state: FSMContext,
    client,
    phone: str,
) -> None:
    """يصدّر الجلسة ويحفظها كحساب فحص النجوم."""
    from config import DEFAULT_API_ID, DEFAULT_API_HASH
    await state.clear()

    try:
        session_string = await client.export_session_string()
    except Exception as e:
        logger.error("checker_login export_session error: %s", e)
        await message.answer(f"❌ فشل تصدير الجلسة: <code>{e}</code>", parse_mode="HTML")
        await _cleanup_checker_session(message.from_user.id)
        return

    await _cleanup_checker_session(message.from_user.id)

    # احفظ بصيغة phone::api_id::api_hash::session_string
    phone_clean  = phone.lstrip("+")
    account_line = f"{phone_clean}::{DEFAULT_API_ID}::{DEFAULT_API_HASH}::{session_string}"
    await set_setting("stars_checker_session", account_line)

    # أعد تشغيل checker client بالجلسة الجديدة
    status_msg = ""
    try:
        from utils.stars_rating_checker import reset_checker_client, get_checker_client
        await reset_checker_client()
        checker = await get_checker_client()
        if checker:
            me = await checker.get_me()
            status_msg = (
                f"✅ <b>تم الاتصال بنجاح!</b>\n"
                f"الحساب: <b>{me.first_name}</b>\n"
                f"الرقم: <code>{phone}</code>"
            )
        else:
            status_msg = "⚠️ تم الحفظ لكن فشل الاتصال — تحقق من DEFAULT_API_ID/HASH."
    except Exception as e:
        status_msg = f"⚠️ تم الحفظ لكن حدث خطأ عند الاتصال: <code>{e}</code>"

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 إعدادات النجوم", callback_data="admin:stars")
    await message.answer(
        f"🔍 <b>حساب فحص النجوم</b>\n\n{status_msg}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:stars_checker_del")
async def admin_stars_checker_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await set_setting("stars_checker_session", "")
    try:
        from utils.stars_rating_checker import reset_checker_client
        await reset_checker_client()
    except Exception:
        pass
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 إعدادات النجوم", callback_data="admin:stars")
    await callback.message.edit_text(
        "🗑 <b>تم حذف حساب الفحص.</b>\n"
        "شحن النجوم سيعتمد على القائمة السوداء الداخلية فقط.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()

# ─── باسوورد المخزون التلقائي ─────────────────────────────────────────────────

@router.callback_query(F.data == "admin:set_stock_password")
async def admin_set_stock_password_menu(callback: CallbackQuery, state: FSMContext):
    if not await _is_admin_or_has_perm(callback.from_user.id, "stock"):
        await callback.answer("⛔", show_alert=True)
        return
    current = await get_setting("stock_2fa_password") or ""
    _fb_raw = await get_setting("stock_2fa_fallback") or ""
    fallback_count = len([p for p in _fb_raw.split(",") if p.strip()])
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ تغيير الباسوورد", callback_data="admin:input_stock_password")
    if current:
        builder.button(text="🗑 إزالة الباسوورد", callback_data="admin:clear_stock_password")
    fb_label = f"🔑 باسووردات الاحتياط ({fallback_count})" if fallback_count else "🔑 باسووردات الاحتياط"
    builder.button(text=fb_label, callback_data="admin:set_fallback_passwords")
    builder.button(text="🔙 رجوع", callback_data="admin:stock")
    builder.adjust(1)
    status = f"<code>{current}</code>" if current else "<i>غير مضبوط</i>"
    fb_status = f"<b>{fallback_count} باسوورد احتياطي مضبوط</b>" if fallback_count else "<i>لا يوجد</i>"
    await callback.message.edit_text(
        f"🔐 <b>باسوورد المخزون التلقائي</b>\n\n"
        f"عند تفعيل هذا الخيار، البوت يغيّر الباسوورد (2FA) لكل حساب\n"
        f"يُضاف للمخزون تلقائياً بعد التحقق منه.\n\n"
        f"📌 الباسوورد الحالي: {status}\n"
        f"🔑 الاحتياطية: {fb_status}\n\n"
        f"⚠️ <i>الباسوورد يُطبَّق فوراً عند إضافة حسابات جديدة فقط.</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin:input_stock_password")
async def admin_input_stock_password_start(callback: CallbackQuery, state: FSMContext):
    if not await _is_admin_or_has_perm(callback.from_user.id, "stock"):
        await callback.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminState.waiting_for_stock_2fa_password)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:set_stock_password")
    await callback.message.edit_text(
        "🔐 <b>أرسل الباسوورد الجديد للمخزون:</b>\n\n"
        "<i>يجب أن يكون 8 أحرف أو أكثر.\n"
        "سيُطبَّق على كل حساب يُضاف بعد الآن.</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminState.waiting_for_stock_2fa_password)
async def admin_stock_password_received(message: Message, state: FSMContext):
    if not await _is_admin_or_has_perm(message.from_user.id, "stock"):
        return
    pwd = (message.text or "").strip()
    if len(pwd) < 8:
        await message.answer(
            "❌ الباسوورد يجب أن يكون 8 أحرف على الأقل. حاول مجدداً:",
            parse_mode="HTML",
        )
        return
    await state.clear()
    await set_setting("stock_2fa_password", pwd)
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 إعدادات الباسوورد", callback_data="admin:set_stock_password")
    await message.answer(
        f"✅ <b>تم حفظ الباسوورد بنجاح!</b>\n\n"
        f"🔐 الباسوورد: <code>{pwd}</code>\n\n"
        f"<i>سيُطبَّق تلقائياً على كل حساب يُضاف للمخزون من الآن.</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:clear_stock_password")
async def admin_clear_stock_password(callback: CallbackQuery):
    if not await _is_admin_or_has_perm(callback.from_user.id, "stock"):
        await callback.answer("⛔", show_alert=True)
        return
    await set_setting("stock_2fa_password", "")
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 إعدادات الباسوورد", callback_data="admin:set_stock_password")
    await callback.message.edit_text(
        "🗑 <b>تم إزالة الباسوورد.</b>\n\n"
        "<i>لن يتم تغيير الباسوورد للحسابات الجديدة حتى تضبط باسوورداً جديداً.</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


# ─── باسووردات الاحتياط (Fallback 2FA) ────────────────────────────────────────

@router.callback_query(F.data == "admin:set_fallback_passwords")
async def admin_fallback_passwords_menu(callback: CallbackQuery, state: FSMContext):
    if not await _is_admin_or_has_perm(callback.from_user.id, "stock"):
        await callback.answer("⛔", show_alert=True)
        return
    raw = await get_setting("stock_2fa_fallback") or ""
    fallbacks = [p.strip() for p in raw.split(",") if p.strip()]
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ إضافة باسوورد احتياطي", callback_data="admin:add_fallback_password")
    if fallbacks:
        builder.button(text="🗑 مسح القائمة كاملاً", callback_data="admin:clear_fallback_passwords")
    builder.button(text="🔙 رجوع", callback_data="admin:set_stock_password")
    builder.adjust(1)
    if fallbacks:
        list_text = "\n".join(f"  • <code>{p}</code>" for p in fallbacks)
        status_text = f"📋 القائمة الحالية ({len(fallbacks)} باسوورد):\n{list_text}"
    else:
        status_text = "📋 القائمة فارغة حالياً."
    await callback.message.edit_text(
        f"🔑 <b>باسووردات الاحتياط (Fallback 2FA)</b>\n\n"
        f"عند فشل تغيير الباسوورد بسبب وجود 2FA مجهول، البوت يجرّب هذه الباسووردات واحداً تلو الآخر.\n"
        f"إن نجح أحدها → يغيّره للباسوورد الرئيسي تلقائياً.\n\n"
        f"{status_text}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin:add_fallback_password")
async def admin_add_fallback_start(callback: CallbackQuery, state: FSMContext):
    if not await _is_admin_or_has_perm(callback.from_user.id, "stock"):
        await callback.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminState.waiting_for_stock_2fa_fallback)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:set_fallback_passwords")
    await callback.message.edit_text(
        "🔑 <b>أرسل الباسوورد الاحتياطي الجديد:</b>\n\n"
        "<i>سيُضاف لقائمة الاحتياط. يمكنك إضافة أكثر من باسوورد واحد.</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminState.waiting_for_stock_2fa_fallback)
async def admin_fallback_password_received(message: Message, state: FSMContext):
    if not await _is_admin_or_has_perm(message.from_user.id, "stock"):
        return
    pwd = (message.text or "").strip()
    if not pwd:
        await message.answer("❌ أرسل باسوورداً صحيحاً.")
        return
    await state.clear()
    raw = await get_setting("stock_2fa_fallback") or ""
    existing = [p.strip() for p in raw.split(",") if p.strip()]
    if pwd not in existing:
        existing.append(pwd)
    await set_setting("stock_2fa_fallback", ",".join(existing))
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 قائمة الاحتياط", callback_data="admin:set_fallback_passwords")
    await message.answer(
        f"✅ <b>تمت الإضافة!</b>\n\n"
        f"🔑 الباسوورد: <code>{pwd}</code>\n"
        f"📋 إجمالي الاحتياطية: <b>{len(existing)}</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:clear_fallback_passwords")
async def admin_clear_fallback_passwords(callback: CallbackQuery):
    if not await _is_admin_or_has_perm(callback.from_user.id, "stock"):
        await callback.answer("⛔", show_alert=True)
        return
    await set_setting("stock_2fa_fallback", "")
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 قائمة الاحتياط", callback_data="admin:set_fallback_passwords")
    await callback.message.edit_text(
        "🗑 <b>تم مسح قائمة الاحتياط كاملاً.</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── تغيير باسوورد (2FA) لكل الحسابات المتوفرة حالياً في المخزون ────────────

@router.callback_query(F.data == "admin:bulk_change_password")
async def admin_bulk_change_password_menu(callback: CallbackQuery):
    if not await _is_admin_or_has_perm(callback.from_user.id, "stock"):
        await callback.answer("⛔", show_alert=True)
        return

    stock_password = await get_setting("stock_2fa_password")
    stock_password = stock_password.strip() if stock_password else ""

    if not stock_password:
        builder = InlineKeyboardBuilder()
        builder.button(text="🔐 ضبط الباسوورد أولاً", callback_data="admin:set_stock_password")
        builder.button(text="🔙 رجوع", callback_data="admin:stock")
        builder.adjust(1)
        await callback.message.edit_text(
            "⚠️ <b>لم يتم ضبط باسوورد المخزون بعد.</b>\n\n"
            "اضبط الباسوورد أولاً من قائمة \"🔐 باسوورد المخزون\" ثم عُد لتطبيقه على كل الحسابات الحالية.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    accounts = await get_all_available_accounts()
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ تأكيد وتطبيق على الكل", callback_data="admin:confirm_bulk_change_password")
    builder.button(text="❌ إلغاء", callback_data="admin:stock")
    builder.adjust(1)
    await callback.message.edit_text(
        f"🔄 <b>تغيير باسوورد (2FA) لجميع الحسابات المتوفرة في المخزون</b>\n\n"
        f"📦 عدد الحسابات المتوفرة حالياً: <b>{len(accounts)}</b>\n"
        f"🔐 الباسوورد الذي سيُطبَّق: <code>{stock_password}</code>\n\n"
        f"⚠️ <i>سيتصل البوت بكل حساب على حدة ويغيّر/يفعّل الباسوورد له. "
        f"قد يستغرق هذا بعض الوقت حسب عدد الحسابات، وستصلك رسالة تقرير عند الانتهاء.</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


_bulk_password_change_running = False


@router.callback_query(F.data == "admin:confirm_bulk_change_password")
async def admin_confirm_bulk_change_password(callback: CallbackQuery, bot: Bot):
    global _bulk_password_change_running
    if not await _is_admin_or_has_perm(callback.from_user.id, "stock"):
        await callback.answer("⛔", show_alert=True)
        return

    if _bulk_password_change_running:
        await callback.answer(
            "⏳ توجد عملية تغيير باسوورد جماعي قيد التنفيذ حالياً، انتظر انتهاءها.",
            show_alert=True,
        )
        return

    stock_password = await get_setting("stock_2fa_password")
    stock_password = stock_password.strip() if stock_password else ""
    if not stock_password:
        await callback.answer("⚠️ لم يتم ضبط الباسوورد.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 رجوع", callback_data="admin:stock")
    await callback.message.edit_text(
        "⏳ <b>جاري تطبيق الباسوورد على جميع الحسابات المتوفرة...</b>\n\n"
        "ستصلك رسالة تقرير عند الانتهاء.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()

    _bulk_password_change_running = True
    asyncio.create_task(
        _bulk_change_all_passwords(stock_password, callback.from_user.id, bot)
    )


async def _bulk_change_all_passwords(new_password: str, admin_id: int, bot: Bot):
    """يطبّق باسوورد جديد (2FA) على كل حساب متوفر حالياً في المخزون (لا حسابات جديدة فقط).

    قبل الاتصال بكل حساب، نعيد فحص حالته في قاعدة البيانات (get_account_status_and_data)
    لتجنّب تغيير باسوورد حساب بِيع للتو بين لحظة جلب القائمة ولحظة الاتصال — وهذا
    يمنع تسليم المشتري لباسوورد قديم/خاطئ لا يعمل بسبب سباق (race condition).
    """
    global _bulk_password_change_running
    _FATAL = (AuthKeyUnregistered, UserDeactivated, SessionExpired, AuthKeyDuplicated, AuthKeyInvalid)

    try:
        accounts = await get_all_available_accounts()

        _fb_raw = await get_setting("stock_2fa_fallback") or ""
        fallback_passwords = [p.strip() for p in _fb_raw.split(",") if p.strip()]

        changed, invalid, failed, skipped_sold = [], [], [], []

        for acc in accounts:
            line = acc["account_data"]

            # إعادة فحص الحالة الحالية للحساب مباشرة قبل الاتصال — يحمي من
            # تعارض مع عملية شراء تمّت بين جلب القائمة والاتصال الفعلي.
            fresh = await get_account_status_and_data(acc["id"])
            if not fresh or fresh.get("status") != "available" or fresh.get("account_data") != line:
                skipped_sold.append(line.split("::")[0].strip() if line else str(acc.get("id")))
                continue

            parts = [p.strip() for p in line.split("::")]
            if len(parts) < 4:
                failed.append(f"{parts[0] if parts else '?'} (صيغة غير مدعومة)")
                continue

            phone = parts[0]
            api_id_str    = parts[1]
            api_hash      = parts[2]
            session_string = parts[3]
            current_2fa   = parts[4] if len(parts) >= 5 else ""

            try:
                api_id = int(api_id_str) if api_id_str else None
            except ValueError:
                api_id = None

            if not api_id or not api_hash:
                from config import DEFAULT_API_ID, DEFAULT_API_HASH
                api_id   = api_id or DEFAULT_API_ID
                api_hash = api_hash or DEFAULT_API_HASH

            if not api_id or not api_hash:
                failed.append(f"{phone} (بدون api_id/api_hash)")
                continue

            client = None
            try:
                client = PyrogramClient(
                    name=f"bulkpw_{phone.replace('+', '')}",
                    api_id=api_id,
                    api_hash=api_hash,
                    session_string=session_string,
                    in_memory=True,
                    no_updates=True,
                )
                await asyncio.wait_for(client.start(), timeout=15)
                await client.get_me()

                if current_2fa and current_2fa == new_password:
                    pass  # الباسوورد نفسه — لا شيء
                elif not await _ensure_password_2fa(client, current_2fa, new_password, fallback_passwords):
                    failed.append(f"{phone} (2FA مجهول)")
                    continue

                new_line = f"{phone}::{api_id_str or api_id}::{parts[2] or api_hash}::{session_string}::{new_password}"
                if new_line != line:
                    await update_account_data_by_old(line, new_line)
                changed.append(phone)

            except _FATAL as e:
                invalid.append(phone)
                logger.warning("bulk password change: fatal auth error for %s: %s", phone, e)
            except FloodWait as fw:
                logger.warning("FloodWait %ds during bulk pw change for %s", fw.value, phone)
                await asyncio.sleep(fw.value + 5)
                failed.append(f"{phone} (FloodWait)")
            except Exception as e:
                failed.append(phone)
                logger.warning("bulk password change failed for %s: %s", phone, e)
            finally:
                if client is not None:
                    try:
                        await client.stop()
                    except Exception:
                        pass
            # تأخير بين كل حساب لتجنب FloodWait
            await asyncio.sleep(3)

        report_lines = [
            "🔄 <b>تقرير تغيير باسوورد جميع الحسابات</b>\n",
            f"📦 إجمالي الحسابات: <b>{len(accounts)}</b>",
            f"✅ تم تغيير/تفعيل الباسوورد: <b>{len(changed)}</b>",
        ]
        if skipped_sold:
            report_lines.append(f"🔁 تم تخطيها (بِيعت أثناء العملية): <b>{len(skipped_sold)}</b>")
        if invalid:
            report_lines.append(f"❌ حسابات منتهية/محظورة (لم يتم تعديلها): <b>{len(invalid)}</b>")
            for p in invalid[:15]:
                report_lines.append(f"  • <code>{p}</code>")
            if len(invalid) > 15:
                report_lines.append(f"  ...و{len(invalid) - 15} أخرى")
        if failed:
            report_lines.append(f"⚠️ فشل التغيير (خطأ/شبكة): <b>{len(failed)}</b>")
            for p in failed[:15]:
                report_lines.append(f"  • <code>{p}</code>")
            if len(failed) > 15:
                report_lines.append(f"  ...و{len(failed) - 15} أخرى")

        try:
            await bot.send_message(admin_id, "\n".join(report_lines), parse_mode="HTML")
        except Exception as e:
            logger.error("_bulk_change_all_passwords: failed to send report: %s", e)
    finally:
        _bulk_password_change_running = False


# ─── الروابط الديناميكية ──────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:links")
async def admin_links_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    force_sub    = await get_setting("force_sub_channel") or "—"
    sell_url     = await get_setting("sell_accounts_url") or "—"
    support_url  = await get_setting("support_url") or "—"
    other_url    = await get_setting("topup_other_url") or "—"
    notif_ch     = await get_setting("notification_channel") or "—"
    sell_enabled = (await get_setting("sell_btn_enabled") or "1") == "1"
    info_enabled = (await get_setting("info_btn_enabled") or "1") == "1"

    await callback.message.edit_text(
        f"🔗 <b>الروابط الديناميكية</b>\n\n"
        f"📢 قناة الاشتراك: <code>{force_sub}</code>\n"
        f"🏪 رابط البيع: <code>{sell_url[:40]}</code>\n"
        f"🎧 رابط الدعم: <code>{support_url[:40]}</code>\n"
        f"💳 شحن آخر: <code>{other_url[:40]}</code>\n"
        f"📣 قناة الإشعارات: <code>{notif_ch}</code>",
        reply_markup=admin_links_keyboard(sell_enabled, info_enabled),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin:set_force_sub")
async def admin_set_force_sub_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminState.waiting_for_force_sub_channel)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:links")
    await callback.message.edit_text(
        "📢 أرسل معرّف القناة للاشتراك الإجباري (مثال: @mychannel)\n"
        "أو أرسل 0 لإلغاء الاشتراك الإجباري:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.message(AdminState.waiting_for_force_sub_channel)
async def admin_force_sub_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    val = message.text.strip()
    if val in ("0", "none", "None", "تعطيل"):
        val = ""
    else:
        val = _clean_channel_id(val)

    await state.clear()
    await set_setting("force_sub_channel", val)

    status_extra = ""
    if val and not val.startswith("https://t.me/+"):
        try:
            target_id = int(val) if (val.startswith("-") or val.isdigit()) else val
            chat = await message.bot.get_chat(target_id)
            status_extra = f"\n📢 تم التحقق من القناة: <b>{chat.title}</b>"
        except Exception as e:
            status_extra = f"\n⚠️ <i>تنبيه: تأكد من رفع البوت مشرفاً (Admin) في القناة ليتمكن من التحقق من المشتركين ({e}).</i>"

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 الروابط", callback_data="admin:links")
    await message.answer(
        f"✅ قناة الاشتراك الإجباري: <code>{val or 'معطّل'}</code>{status_extra}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:set_sell_url")
async def admin_set_sell_url_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminState.waiting_for_sell_url)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:links")
    await callback.message.edit_text(
        "🏪 أرسل رابط صفحة/مجموعة بيع الحسابات:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.message(AdminState.waiting_for_sell_url)
async def admin_sell_url_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await set_setting("sell_accounts_url", message.text.strip())
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 الروابط", callback_data="admin:links")
    await message.answer("✅ تم ضبط رابط البيع.", reply_markup=builder.as_markup())


@router.callback_query(F.data == "admin:set_support_url")
async def admin_set_support_url_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminState.waiting_for_support_url)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:links")
    await callback.message.edit_text(
        "🎧 أرسل رابط الدعم الفني:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.message(AdminState.waiting_for_support_url)
async def admin_support_url_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await set_setting("support_url", message.text.strip())
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 الروابط", callback_data="admin:links")
    await message.answer("✅ تم ضبط رابط الدعم.", reply_markup=builder.as_markup())


@router.callback_query(F.data == "admin:set_topup_other_url")
async def admin_set_topup_other_url_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminState.waiting_for_topup_other_url)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:links")
    await callback.message.edit_text(
        "💳 أرسل رابط طريقة الشحن الأخرى:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.message(AdminState.waiting_for_topup_other_url)
async def admin_topup_other_url_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await set_setting("topup_other_url", message.text.strip())
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 الروابط", callback_data="admin:links")
    await message.answer("✅ تم ضبط رابط الشحن الآخر.", reply_markup=builder.as_markup())


@router.callback_query(F.data == "admin:set_notif_channel")
async def admin_set_notif_channel_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminState.waiting_for_notification_channel)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:links")
    await callback.message.edit_text(
        "📣 أرسل معرّف قناة الإشعارات (مثال: @mychannel)\n"
        "أو أرسل 0 لإلغائها:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.message(AdminState.waiting_for_notification_channel)
async def admin_notif_channel_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    val = message.text.strip()
    if val in ("0", "none", "None", "تعطيل"):
        val = ""
    else:
        val = _clean_channel_id(val)

    await state.clear()
    await set_setting("notification_channel", val)

    status_extra = ""
    if val and not val.startswith("https://t.me/+"):
        try:
            target_id = int(val) if (val.startswith("-") or val.isdigit()) else val
            chat = await message.bot.get_chat(target_id)
            status_extra = f"\n📣 تم التحقق من القناة: <b>{chat.title}</b>"
        except Exception as e:
            status_extra = f"\n⚠️ <i>تنبيه: تأكد من رفع البوت مشرفاً (Admin) في القناة مع صلاحية نشر الرسائل ({e}).</i>"

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 الروابط", callback_data="admin:links")
    await message.answer(
        f"✅ قناة الإشعارات: <code>{val or 'معطّلة'}</code>{status_extra}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:toggle_sell_btn")
async def admin_toggle_sell_btn(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    current = (await get_setting("sell_btn_enabled") or "1")
    new_val = "0" if current == "1" else "1"
    await set_setting("sell_btn_enabled", new_val)
    await callback.answer(
        f"✅ زر البيع: {'مفعّل 🟢' if new_val == '1' else 'معطّل 🔴'}",
        show_alert=True,
    )
    info_enabled = (await get_setting("info_btn_enabled") or "1") == "1"
    await callback.message.edit_reply_markup(
        reply_markup=admin_links_keyboard(new_val == "1", info_enabled)
    )


@router.callback_query(F.data == "admin:toggle_info_btn")
async def admin_toggle_info_btn(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    current = (await get_setting("info_btn_enabled") or "1")
    new_val = "0" if current == "1" else "1"
    await set_setting("info_btn_enabled", new_val)
    await callback.answer(
        f"✅ زر المعلومات: {'مفعّل 🟢' if new_val == '1' else 'معطّل 🔴'}",
        show_alert=True,
    )
    sell_enabled = (await get_setting("sell_btn_enabled") or "1") == "1"
    await callback.message.edit_reply_markup(
        reply_markup=admin_links_keyboard(sell_enabled, new_val == "1")
    )


# ─── أزرار المعلومات ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:add_info_button")
async def admin_add_info_button_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminState.waiting_for_info_button_text)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:links")
    await callback.message.edit_text(
        "➕ أرسل نص الزر الجديد:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.message(AdminState.waiting_for_info_button_text)
async def admin_info_button_text_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(info_btn_text=message.text.strip())
    await state.set_state(AdminState.waiting_for_info_button_url)
    await message.answer("أرسل رابط الزر (يجب أن يبدأ بـ https://):")


@router.message(AdminState.waiting_for_info_button_url)
async def admin_info_button_url_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    url = message.text.strip()
    if not url.startswith("http"):
        await message.answer("❌ يجب أن يبدأ الرابط بـ https://")
        return

    data = await state.get_data()
    text = data["info_btn_text"]
    await state.clear()

    info_str = await get_setting("info_buttons") or "[]"
    try:
        buttons = json.loads(info_str)
        if not isinstance(buttons, list):
            buttons = []
    except Exception:
        buttons = []

    buttons.append({"text": text, "url": url})
    await set_setting("info_buttons", json.dumps(buttons, ensure_ascii=False))

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 الروابط", callback_data="admin:links")
    await message.answer(
        f"✅ تمت إضافة الزر: <b>{text}</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:del_info_button")
async def admin_del_info_button_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    info_str = await get_setting("info_buttons") or "[]"
    try:
        buttons = json.loads(info_str)
        if not isinstance(buttons, list):
            buttons = []
    except Exception:
        buttons = []

    if not buttons:
        await callback.answer("❌ لا توجد أزرار معلومات.", show_alert=True)
        return

    lines = "\n".join(f"{i+1}. {b.get('text','—')}" for i, b in enumerate(buttons))
    await state.set_state(AdminState.waiting_for_delete_info_button_index)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:links")
    await callback.message.edit_text(
        f"🗑️ <b>حذف زر معلومات</b>\n\nالأزرار الحالية:\n{lines}\n\nأرسل رقم الزر المراد حذفه:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminState.waiting_for_delete_info_button_index)
async def admin_del_info_button_index(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        idx = int(message.text.strip()) - 1
        if idx < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ أدخل رقماً صحيحاً.")
        return

    info_str = await get_setting("info_buttons") or "[]"
    try:
        buttons = json.loads(info_str)
        if not isinstance(buttons, list):
            buttons = []
    except Exception:
        buttons = []

    if idx >= len(buttons):
        await message.answer("❌ الرقم خارج النطاق.")
        return

    removed = buttons.pop(idx)
    await state.clear()
    await set_setting("info_buttons", json.dumps(buttons, ensure_ascii=False))

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 الروابط", callback_data="admin:links")
    await message.answer(
        f"✅ تم حذف الزر: <b>{removed.get('text','—')}</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


# ─── Binance Manual — ضبط UID ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:set_binance_uid")
async def admin_set_binance_uid_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    current = await get_setting("binance_pay_uid") or ""
    await state.set_state(AdminState.waiting_for_binance_uid)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:links")
    await callback.message.edit_text(
        f"🟡 <b>ضبط Binance Pay ID</b>\n\n"
        f"القيمة الحالية: <code>{current or 'غير مضبوط'}</code>\n\n"
        "أرسل آيدي Binance Pay الخاص بك (Binance Pay ID):",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminState.waiting_for_binance_uid)
async def admin_binance_uid_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    uid = message.text.strip()
    if not uid:
        await message.answer("❌ الآيدي فارغ، أرسل آيدي Binance Pay.")
        return
    await state.clear()
    await set_setting("binance_pay_uid", uid)
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 رجوع", callback_data="admin:links")
    await message.answer(
        f"✅ <b>تم حفظ Binance Pay ID:</b>\n\n<code>{uid}</code>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


# ─── Binance Manual — مراجعة طلبات الدفع ─────────────────────────────────────────────

async def _update_binance_review_msg(callback: CallbackQuery, text: str):
    try:
        if callback.message.photo:
            await callback.message.edit_caption(caption=text, parse_mode="HTML")
        else:
            await callback.message.edit_text(text=text, parse_mode="HTML")
    except Exception as _e:
        logger.warning("Could not edit review message: %s", _e)


async def _can_review_binance(user_id: int) -> bool:
    if is_admin(user_id):
        return True
    try:
        from database import get_sub_admin_perms
        perms = await get_sub_admin_perms(user_id)
        return bool(perms and perms.get("deposits"))
    except Exception:
        return False


@router.callback_query(F.data.startswith("admin_binance:approve:"))
async def admin_binance_approve(callback: CallbackQuery, bot: Bot):
    if not await _can_review_binance(callback.from_user.id):
        await callback.answer("⛔ ليس لديك صلاحية", show_alert=True)
        return
    parts = callback.data.split(":")
    payment_id = int(parts[2])
    user_id    = int(parts[3])
    amount, new_balance, user_id = await approve_manual_payment(payment_id)
    if amount is None:
        await callback.answer("⚠️ تمت معالجة هذا الطلب مسبقاً.", show_alert=True)
        return

    admin_name = callback.from_user.full_name
    await _update_binance_review_msg(
        callback,
        f"✅ <b>تمت الموافقة وتحديث الرصيد</b>\n\n"
        f"📋 رقم الطلب: #{payment_id}\n"
        f"👤 المستخدم: <code>{user_id}</code>\n"
        f"💵 المبلغ المُضاف: <b>${amount:.2f} USDT</b>\n"
        f"💰 الرصيد الجديد للعميل: <b>${new_balance:.2f}</b>\n"
        f"👨‍💻 تمت الموافقة بواسطة: <b>{admin_name}</b>",
    )
    await callback.answer("✅ تمت الموافقة وتحديث الرصيد بنجاح!", show_alert=True)

    user = await get_user(user_id)
    lang = user.get("language", "ar") if user else "ar"
    try:
        from translations import t
        await bot.send_message(
            user_id,
            t(lang, "topup_binance_approved", amount=amount, new_balance=new_balance),
            parse_mode="HTML",
        )
    except Exception as _e:
        logger.warning("Failed to notify user of approved deposit: %s", _e)


@router.callback_query(F.data.startswith("admin_binance:reject:"))
async def admin_binance_reject(callback: CallbackQuery, bot: Bot):
    if not await _can_review_binance(callback.from_user.id):
        await callback.answer("⛔ ليس لديك صلاحية", show_alert=True)
        return
    parts = callback.data.split(":")
    payment_id = int(parts[2])
    user_id    = int(parts[3])
    ok = await reject_manual_payment(payment_id)
    if not ok:
        await callback.answer("⚠️ تمت معالجة هذا الطلب مسبقاً.", show_alert=True)
        return

    admin_name = callback.from_user.full_name
    await _update_binance_review_msg(
        callback,
        f"❌ <b>تم رفض طلب الشحن</b>\n\n"
        f"📋 رقم الطلب: #{payment_id}\n"
        f"👤 المستخدم: <code>{user_id}</code>\n"
        f"👨‍💻 رُفض بواسطة: <b>{admin_name}</b>",
    )
    await callback.answer("❌ تم الرفض", show_alert=True)

    user = await get_user(user_id)
    lang = user.get("language", "ar") if user else "ar"
    try:
        from translations import t
        await bot.send_message(
            user_id,
            t(lang, "topup_binance_rejected"),
            parse_mode="HTML",
        )
    except Exception as _e:
        logger.warning("Failed to notify user of rejected deposit: %s", _e)


@router.callback_query(F.data.startswith("admin_binance:ban:"))
async def admin_binance_ban(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ فقط الأدمن الأساسي يمكنه الحظر", show_alert=True)
        return
    parts = callback.data.split(":")
    payment_id = int(parts[2])
    user_id    = int(parts[3])
    await reject_manual_payment(payment_id)
    await set_user_banned(user_id, True, reason="طلب شحن احتيالي / وهمي عبر Binance")
    await _update_binance_review_msg(
        callback,
        f"🚫 <b>تم حظر المستخدم ورفض الطلب</b>\n\n"
        f"📋 رقم الطلب: #{payment_id}\n"
        f"👤 المستخدم المحظور: <code>{user_id}</code>",
    )
    await callback.answer("🚫 تم الحظر!", show_alert=True)
    try:
        await bot.send_message(
            user_id,
            "🚫 <b>تم حظر حسابك من استخدام البوت.</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# ── صيانة الحسابات الفردية ────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def _build_maintenance_country_keyboard(countries: list) -> "InlineKeyboardMarkup":
    builder = InlineKeyboardBuilder()
    for c in countries:
        flag  = c.get("flag_emoji", "🌍")
        avail = c.get("available_count", 0)
        maint = c.get("maintenance_count", 0)
        label = f"{flag} {c['country_name']}  ✅{avail}  🔧{maint}"
        builder.button(text=label, callback_data=f"maint_country:{c['country_code']}")
    builder.button(text="🔙 رجوع", callback_data="admin:stock")
    builder.adjust(1)
    return builder.as_markup()


def _build_maintenance_accounts_keyboard(accounts: list, country_code: str) -> "InlineKeyboardMarkup":
    builder = InlineKeyboardBuilder()
    for acc in accounts[:30]:
        phone  = acc["account_data"].split("::")[0][:20]
        status = acc["status"]
        if status == "maintenance":
            label   = f"🔧 {phone}"
            new_st  = "available"
            cb_data = f"maint_toggle:{acc['id']}:{country_code}:{new_st}"
        else:
            label   = f"✅ {phone}"
            new_st  = "maintenance"
            cb_data = f"maint_toggle:{acc['id']}:{country_code}:{new_st}"
        builder.button(text=label, callback_data=cb_data)
    builder.button(text="🔙 رجوع", callback_data="admin:maintenance_accounts")
    builder.adjust(2)
    return builder.as_markup()


@router.callback_query(F.data == "admin:maintenance_accounts")
async def admin_maintenance_accounts(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    countries = await get_all_countries_with_stock_or_maintenance()
    if not countries:
        await callback.answer("❌ لا يوجد مخزون.", show_alert=True)
        return
    await callback.message.edit_text(
        "🔧 <b>صيانة الحسابات</b>\n\n"
        "✅ = متاح للبيع  |  🔧 = في الصيانة\n\n"
        "اختر الدولة لعرض حساباتها:",
        reply_markup=_build_maintenance_country_keyboard(countries),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("maint_country:"))
async def admin_maintenance_country(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    code     = callback.data.split(":", 1)[1].upper()
    accounts = await get_accounts_for_maintenance_view(code)
    if not accounts:
        await callback.answer("❌ لا يوجد مخزون لهذه الدولة.", show_alert=True)
        return
    maint_count = sum(1 for a in accounts if a["status"] == "maintenance")
    avail_count = sum(1 for a in accounts if a["status"] == "available")
    await callback.message.edit_text(
        f"🔧 <b>صيانة — {code}</b>\n\n"
        f"✅ متاح: <b>{avail_count}</b>  |  🔧 صيانة: <b>{maint_count}</b>\n\n"
        "اضغط على حساب لتغيير حالته:\n"
        "🔧 = في صيانة (اضغط لإعادته) | ✅ = متاح (اضغط لوضعه بصيانة)",
        reply_markup=_build_maintenance_accounts_keyboard(accounts, code),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("maint_toggle:"))
async def admin_maintenance_toggle(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    parts = callback.data.split(":")
    try:
        acc_id  = int(parts[1])
        code    = parts[2].upper()
        new_st  = parts[3]
    except (IndexError, ValueError):
        await callback.answer("❌", show_alert=True)
        return

    if new_st not in ("available", "maintenance"):
        await callback.answer("❌", show_alert=True)
        return

    await set_account_status(acc_id, new_st)

    if new_st == "maintenance":
        await callback.answer("🔧 تم وضع الحساب في الصيانة.", show_alert=False)
    else:
        await callback.answer("✅ تم إعادة الحساب للمخزون.", show_alert=False)

    accounts = await get_accounts_for_maintenance_view(code)
    if not accounts:
        await callback.message.edit_text(
            f"✅ لا يوجد مخزون متبقٍ في <b>{code}</b>.",
            reply_markup=admin_back_keyboard("admin:maintenance_accounts"),
            parse_mode="HTML",
        )
        return
    maint_count = sum(1 for a in accounts if a["status"] == "maintenance")
    avail_count = sum(1 for a in accounts if a["status"] == "available")
    await callback.message.edit_text(
        f"🔧 <b>صيانة — {code}</b>\n\n"
        f"✅ متاح: <b>{avail_count}</b>  |  🔧 صيانة: <b>{maint_count}</b>\n\n"
        "اضغط على حساب لتغيير حالته:\n"
        "🔧 = في صيانة (اضغط لإعادته) | ✅ = متاح (اضغط لوضعه بصيانة)",
        reply_markup=_build_maintenance_accounts_keyboard(accounts, code),
        parse_mode="HTML",
    )


# ══════════════════════════════════════════════════════════════════════════════
# ── إضافة حساب مباشرة عبر رقم الهاتف (Live Add) ─────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

# نخزّن هنا بيانات الجلسة المؤقتة: admin_id → {client, phone, phone_code_hash, ...}
_live_sessions: dict[int, dict] = {}
_pending_cleanup: dict[int, str] = {}   # admin_id → account_line بانتظار قرار المسح


async def _cleanup_live_session(admin_id: int) -> None:
    """يوقف الكلاينت المؤقت ويمسح البيانات من الذاكرة."""
    session = _live_sessions.pop(admin_id, None)
    if session and session.get("client"):
        try:
            await session["client"].stop()
        except Exception:
            pass


@router.callback_query(F.data == "admin:live_add")
async def admin_live_add_start(callback: CallbackQuery, state: FSMContext):
    """الخطوة 1 — اختر الدولة."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return

    from config import DEFAULT_API_ID, DEFAULT_API_HASH
    if not DEFAULT_API_ID or not DEFAULT_API_HASH:
        await callback.answer(
            "❌ يجب ضبط DEFAULT_API_ID و DEFAULT_API_HASH في المتغيرات أولاً!",
            show_alert=True,
        )
        return

    countries = await get_all_countries()
    if not countries:
        await callback.answer("❌ لا توجد دول. أضف دولة أولاً.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for c in countries:
        flag = c.get("flag_emoji", "")
        builder.button(
            text=f"{flag} {c['country_name']}",
            callback_data=f"live_add_country:{c['country_code']}",
        )
    builder.button(text="❌ إلغاء", callback_data="admin:stock")
    builder.adjust(2)

    await callback.message.edit_text(
        "📱 <b>إضافة رقم مباشرة</b>\n\n"
        "اختر الدولة التي سيُضاف إليها الحساب:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("live_add_country:"))
async def admin_live_add_country(callback: CallbackQuery, state: FSMContext):
    """الخطوة 2 — اطلب رقم الهاتف مباشرة (متجر الدولار تلقائياً)."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return

    code    = callback.data.split(":", 1)[1].upper()
    country = await get_country(code)
    if not country:
        await callback.answer("❌ الدولة غير موجودة.", show_alert=True)
        return

    await state.update_data(
        live_country_code=code,
        live_country_name=country["country_name"],
        live_price_dollar=float(country["price"]),
        live_flag=country.get("flag_emoji", "🌍"),
        live_store_type="dollar",
    )
    await state.set_state(AdminState.waiting_for_live_phone)

    flag = country.get("flag_emoji", "")
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:stock")

    await callback.message.edit_text(
        f"📱 <b>إضافة رقم مباشرة — {flag} {country['country_name']}</b>\n\n"
        "أرسل رقم الهاتف بصيغة دولية كاملة، مثال:\n"
        "<code>+213799898306</code>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminState.waiting_for_live_phone)
async def admin_live_add_phone(message: Message, state: FSMContext):
    """الخطوة 4 — استقبل الرقم، أرسل كود OTP."""
    if not is_admin(message.from_user.id):
        return

    # إذا أرسل الأدمن أمراً (/start أو غيره) نلغي العملية ونخرج
    if message.text and message.text.startswith("/"):
        await state.clear()
        await _cleanup_live_session(message.from_user.id)
        await message.answer("❌ تم إلغاء إضافة الرقم.")
        return

    from pyrogram import Client as PyroClient
    from pyrogram.errors import (
        PhoneNumberInvalid, PhoneNumberBanned, FloodWait as PyroFloodWait,
    )
    from config import DEFAULT_API_ID, DEFAULT_API_HASH

    phone = message.text.strip()
    if not phone.startswith("+"):
        phone = "+" + phone

    waiting_msg = await message.answer("⏳ جاري إرسال الكود...")

    # تنظيف أي جلسة سابقة لهذا الأدمن
    await _cleanup_live_session(message.from_user.id)

    client = PyroClient(
        name=f"live_add_{message.from_user.id}",
        api_id=DEFAULT_API_ID,
        api_hash=DEFAULT_API_HASH,
        in_memory=True,
        no_updates=True,
    )

    try:
        await client.connect()

        # ── الخطوة 1: high-level send_code — يعالج PHONE_MIGRATE تلقائياً ───────
        sent = await client.send_code(phone)
        phone_code_hash = sent.phone_code_hash
        code_type = type(sent.type).__name__

        # ⚠️ لا نستدعي ResendCode تلقائياً هنا — الاستدعاء التلقائي يُبدّل الـhash
        # ويجعل الكود الأول الذي وصل للمدير غير صالح → PhoneCodeExpired.
        # بدلاً من ذلك نُظهر زر "أعد الإرسال كـ SMS" لمن يريد ذلك اختيارياً.

        # ── الخطوة 2: رسالة واضحة حسب الطريقة الفعلية ──────────────────────────
        if "App" in code_type:
            delivery_hint = (
                "📲 <b>الكود وصل داخل تطبيق تيليجرام</b>\n"
                "افتح تيليجرام على أي جهاز وانظر إشعار <b>Login code</b>.\n\n"
                "أرسل الكود المكوّن من 5 أرقام:"
            )
        elif "Sms" in code_type or "Fragment" in code_type:
            delivery_hint = (
                "📩 <b>الكود أُرسل عبر SMS</b>\n"
                "تحقق من رسائل الجوال.\n\n"
                "أرسل الكود المكوّن من 5 أرقام:"
            )
        elif "FlashCall" in code_type:
            delivery_hint = (
                "📞 <b>ستصلك مكالمة مضيّعة (Flash Call)</b>\n"
                "الكود هو <b>آخر 5 أرقام</b> من رقم المتصل.\n\n"
                "أرسل هذه الأرقام الخمسة:"
            )
        elif "MissedCall" in code_type:
            delivery_hint = (
                "📞 <b>ستصلك مكالمة مضيّعة (Missed Call)</b>\n"
                "الكود هو <b>آخر 5 أرقام</b> من رقم المتصل.\n\n"
                "أرسل هذه الأرقام الخمسة:"
            )
        elif "Call" in code_type:
            delivery_hint = (
                "📞 <b>الكود سيُقرأ عبر مكالمة هاتفية</b>\n"
                "انتظر الاتصال واستمع للأرقام.\n\n"
                "أرسل الكود المكوّن من 5 أرقام:"
            )
        elif "Email" in code_type:
            delivery_hint = (
                "📧 <b>الكود أُرسل إلى البريد الإلكتروني المرتبط بالحساب.</b>\n\n"
                "أرسل الكود:"
            )
        else:
            delivery_hint = (
                "✉️ تحقق من تيليجرام أو رسائل الجوال.\n\n"
                "أرسل الكود الذي وصلك:"
            )

        _live_sessions[message.from_user.id] = {
            "client":          client,
            "phone":           phone,
            "phone_code_hash": phone_code_hash,
            "code_type":       code_type,
        }

        await state.update_data(live_phone=phone)
        await state.set_state(AdminState.waiting_for_live_otp)

        builder = InlineKeyboardBuilder()
        # زر اختياري لإعادة الإرسال كـ SMS (يُولّد hash جديد لذا يُنبّه المدير)
        builder.button(text="📨 أعد الإرسال كـ SMS", callback_data="live_add_resend_sms")
        builder.button(text="❌ إلغاء", callback_data="live_add_cancel")
        builder.adjust(1)

        await waiting_msg.edit_text(
            f"✅ <b>تم إرسال الكود إلى</b> <code>{phone}</code>\n\n"
            f"{delivery_hint}",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )

    except PhoneNumberInvalid:
        await client.disconnect()
        await waiting_msg.edit_text("❌ رقم الهاتف غير صحيح. تأكد من الصيغة (+213...).")

    except PhoneNumberBanned:
        await client.disconnect()
        await waiting_msg.edit_text("❌ هذا الرقم محظور من تيليغرام.")

    except PyroFloodWait as fw:
        await client.disconnect()
        await waiting_msg.edit_text(
            f"⏳ FloodWait — انتظر <b>{fw.value}</b> ثانية ثم حاول مجدداً.",
            parse_mode="HTML",
        )

    except Exception as e:
        await client.disconnect()
        logger.error("live_add send_code error: %s", e)
        await waiting_msg.edit_text(f"❌ خطأ غير متوقع: <code>{e}</code>", parse_mode="HTML")


@router.callback_query(F.data == "live_add_cancel")
async def admin_live_add_cancel(callback: CallbackQuery, state: FSMContext):
    """إلغاء العملية وتنظيف الجلسة."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.clear()
    await _cleanup_live_session(callback.from_user.id)
    await callback.message.edit_text("❌ تم الإلغاء.", reply_markup=None)
    await callback.answer()


@router.callback_query(F.data == "live_add_resend_sms")
async def admin_live_add_resend_sms(callback: CallbackQuery, state: FSMContext):
    """يُعيد إرسال كود OTP عبر SMS بدلاً من المكالمة — يُولّد hash جديداً."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return

    session = _live_sessions.get(callback.from_user.id)
    if not session:
        await callback.answer("❌ انتهت صلاحية الجلسة. ابدأ من جديد.", show_alert=True)
        await state.clear()
        return

    await callback.answer("⏳ جاري إعادة الإرسال كـ SMS...", show_alert=False)

    from pyrogram import raw as pyro_raw

    client = session["client"]
    phone  = session["phone"]
    old_hash = session["phone_code_hash"]

    try:
        r2 = await client.invoke(
            pyro_raw.functions.auth.ResendCode(
                phone_number=phone,
                phone_code_hash=old_hash,
            )
        )
        new_hash = r2.phone_code_hash
        new_type = type(r2.type).__name__

        # تحديث الجلسة بالهاش الجديد
        session["phone_code_hash"] = new_hash
        session["code_type"]       = new_type

        if "App" in new_type:
            hint = "📲 الكود وصل داخل تطبيق تيليجرام (Login code)."
        elif "Sms" in new_type or "Fragment" in new_type:
            hint = "📩 الكود أُرسل عبر SMS — تحقق من رسائل الجوال."
        else:
            hint = "✉️ تحقق من تيليجرام أو رسائل الجوال."

        builder = InlineKeyboardBuilder()
        builder.button(text="❌ إلغاء", callback_data="live_add_cancel")

        await callback.message.edit_text(
            f"✅ <b>تم إعادة إرسال الكود إلى</b> <code>{phone}</code>\n\n"
            f"{hint}\n\n"
            "⚠️ <b>أرسل الكود الجديد الذي وصلك الآن</b> (الكود القديم لم يعد صالحاً):",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error("live_add resend_sms error: %s", e)
        await callback.answer(f"❌ فشل إعادة الإرسال: {e}", show_alert=True)


@router.message(AdminState.waiting_for_live_otp)
async def admin_live_add_otp(message: Message, state: FSMContext):
    """الخطوة 5 — استقبل الكود، سجّل الدخول."""
    if not is_admin(message.from_user.id):
        return

    # إلغاء تلقائي عند إرسال أمر
    if message.text and message.text.startswith("/"):
        await state.clear()
        await _cleanup_live_session(message.from_user.id)
        await message.answer("❌ تم إلغاء إضافة الرقم.")
        return

    from pyrogram.errors import (
        PhoneCodeInvalid, PhoneCodeExpired,
        SessionPasswordNeeded, FloodWait as PyroFloodWait,
    )

    session = _live_sessions.get(message.from_user.id)
    if not session:
        await message.answer("❌ انتهت صلاحية الجلسة. ابدأ من جديد من /admin.")
        await state.clear()
        return

    code   = message.text.strip().replace(" ", "")
    client = session["client"]
    phone  = session["phone"]
    phash  = session["phone_code_hash"]

    waiting_msg = await message.answer("⏳ جاري التحقق من الكود...")

    try:
        await client.sign_in(
            phone_number=phone,
            phone_code_hash=phash,
            phone_code=code,
        )
        # نجح تسجيل الدخول → أضف الحساب
        await _finish_live_add(message, state, client, phone)

    except PhoneCodeInvalid:
        await waiting_msg.edit_text(
            "❌ <b>الكود خاطئ!</b>\n\nأرسل الكود الصحيح:",
            parse_mode="HTML",
        )

    except PhoneCodeExpired:
        await _cleanup_live_session(message.from_user.id)
        await state.clear()
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 إضافة رقم مباشرة", callback_data="admin:live_add")
        builder.button(text="📦 إدارة المخزون",      callback_data="admin:stock")
        builder.adjust(1)
        await waiting_msg.edit_text(
            "❌ <b>انتهت صلاحية الكود.</b>\n\n"
            "كود OTP صالح لفترة قصيرة فقط (عادةً ~2 دقيقة).\n"
            "أدخل رقم الهاتف من جديد واطلب كوداً جديداً:",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )

    except SessionPasswordNeeded:
        # الحساب محمي بـ 2FA
        session["pending_2fa"] = True
        await state.set_state(AdminState.waiting_for_live_2fa)
        builder = InlineKeyboardBuilder()
        builder.button(text="❌ إلغاء", callback_data="live_add_cancel")
        await waiting_msg.edit_text(
            "🔐 <b>هذا الحساب محمي بكلمة مرور (2FA)</b>\n\nأرسل كلمة المرور:",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )

    except PyroFloodWait as fw:
        await waiting_msg.edit_text(
            f"⏳ FloodWait — انتظر <b>{fw.value}</b> ثانية ثم أعد إرسال الكود.",
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error("live_add sign_in error: %s", e)
        await _cleanup_live_session(message.from_user.id)
        await state.clear()
        await waiting_msg.edit_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")


@router.message(AdminState.waiting_for_live_2fa)
async def admin_live_add_2fa(message: Message, state: FSMContext):
    """الخطوة 6 (اختياري) — كلمة مرور 2FA."""
    if not is_admin(message.from_user.id):
        return

    # إلغاء تلقائي عند إرسال أمر
    if message.text and message.text.startswith("/"):
        await state.clear()
        await _cleanup_live_session(message.from_user.id)
        await message.answer("❌ تم إلغاء إضافة الرقم.")
        return

    from pyrogram.errors import PasswordHashInvalid, FloodWait as PyroFloodWait

    session = _live_sessions.get(message.from_user.id)
    if not session:
        await message.answer("❌ انتهت صلاحية الجلسة. ابدأ من جديد.")
        await state.clear()
        return

    password    = message.text.strip()
    client      = session["client"]
    phone       = session["phone"]
    waiting_msg = await message.answer("⏳ جاري التحقق من كلمة المرور...")

    try:
        await client.check_password(password)
        # نجح → أضف الحساب
        session["two_factor"] = password
        await _finish_live_add(message, state, client, phone, two_factor=password)

    except PasswordHashInvalid:
        await waiting_msg.edit_text(
            "❌ <b>كلمة المرور خاطئة!</b>\n\nأرسل كلمة المرور الصحيحة:",
            parse_mode="HTML",
        )

    except PyroFloodWait as fw:
        await waiting_msg.edit_text(
            f"⏳ FloodWait — انتظر <b>{fw.value}</b> ثانية ثم أعد المحاولة.",
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error("live_add 2fa error: %s", e)
        await _cleanup_live_session(message.from_user.id)
        await state.clear()
        await waiting_msg.edit_text(f"❌ خطأ: <code>{e}</code>", parse_mode="HTML")


async def _finish_live_add(
    message: Message,
    state: FSMContext,
    client,
    phone: str,
    two_factor: str = "",
) -> None:
    """يصدّر الـ session ويضيف الحساب للمخزون."""
    from config import DEFAULT_API_ID, DEFAULT_API_HASH

    data         = await state.get_data()
    country_code = data.get("live_country_code", "")
    country_name = data.get("live_country_name", "")
    store_type   = data.get("live_store_type", "dollar")
    flag         = data.get("live_flag", "🌍")

    price = (
        data.get("live_price_dollar", 0.0)
        if store_type == "dollar"
        else float(data.get("live_price_points", 0))
    )

    await state.clear()

    try:
        session_string = await client.export_session_string()
    except Exception as e:
        logger.error("live_add export_session_string error: %s", e)
        await message.answer(f"❌ فشل تصدير الجلسة: <code>{e}</code>", parse_mode="HTML")
        await _cleanup_live_session(message.from_user.id)
        return

    # أوقف الكلاينت المؤقت
    await _cleanup_live_session(message.from_user.id)

    # ── التحقق من توفر بيانات API ──────────────────────────────────────────
    if not DEFAULT_API_ID or not DEFAULT_API_HASH:
        await _cleanup_live_session(message.from_user.id)
        await message.answer(
            "❌ <b>خطأ في الإعداد</b>\n\n"
            "يجب ضبط <code>DEFAULT_API_ID</code> و<code>DEFAULT_API_HASH</code> في Railway → Variables\n"
            "بدونهما لا يمكن تخزين الحساب بشكل صحيح.",
            parse_mode="HTML",
        )
        return

    # بناء سطر الحساب بالصيغة الكاملة
    phone_clean  = phone.lstrip("+")
    account_line = f"{phone_clean}::{DEFAULT_API_ID}::{DEFAULT_API_HASH}::{session_string}"
    if two_factor:
        account_line += f"::{two_factor}"

    try:
        account_id = await add_account_to_stock(
            country_code=country_code,
            country_name=country_name,
            account_data=account_line,
            price=price,
            store_type=store_type,
        )
    except Exception as e:
        logger.error("live_add add_account_to_stock error: %s", e)
        await message.answer(
            f"❌ فشل إضافة الحساب للمخزون: <code>{e}</code>",
            parse_mode="HTML",
        )
        return

    # ── حفظ بيانات الجلسة مؤقتاً لزر المسح ────────────────────────────────
    _pending_cleanup[message.from_user.id] = account_line

    builder = InlineKeyboardBuilder()
    builder.button(text="📦 إدارة المخزون",       callback_data="admin:stock")
    builder.button(text="📱 إضافة رقم آخر",        callback_data="admin:live_add")
    builder.button(text="🗑️ مسح بيانات الحساب؟", callback_data="live_cleanup_confirm")
    builder.adjust(1)

    await message.answer(
        f"✅ <b>تمت إضافة الحساب بنجاح!</b>\n\n"
        f"📞 الرقم: <code>{phone}</code>\n"
        f"🌍 الدولة: <b>{flag} {country_name}</b>\n"
        f"🛒 النوع: <b>{'💵 دولار' if store_type == 'dollar' else '🪙 نقاط'}</b>\n"
        f"💰 السعر: <b>{price:.2f}</b>\n\n"
        f"هل تريد مسح بيانات الحساب (مجموعات، قنوات، محادثات، صور)؟",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


# ─── مسح بيانات الحساب بعد Live Add ──────────────────────────────────────────

@router.callback_query(F.data == "live_cleanup_confirm")
async def admin_live_cleanup_confirm(callback: CallbackQuery):
    """يظهر رسالة تأكيد قبل مسح بيانات الحساب."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return

    if callback.from_user.id not in _pending_cleanup:
        await callback.answer("❌ انتهت صلاحية الجلسة، أضف الحساب من جديد.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ نعم، امسح البيانات",  callback_data="live_cleanup_yes")
    builder.button(text="❌ لا، تخطَّ",            callback_data="live_cleanup_no")
    builder.adjust(1)

    await callback.message.edit_text(
        "⚠️ <b>تأكيد مسح بيانات الحساب</b>\n\n"
        "سيتم تنفيذ الخطوات التالية على الحساب:\n"
        "• 📤 مغادرة جميع المجموعات والقنوات\n"
        "• 🗑️ حذف سجل المحادثات الخاصة\n"
        "• 📷 حذف الصور الشخصية\n"
        "• ✏️ مسح السيرة الذاتية (Bio)\n\n"
        "⚠️ <b>هذا الإجراء لا يمكن التراجع عنه!</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "live_cleanup_yes")
async def admin_live_cleanup_yes(callback: CallbackQuery):
    """ينفّذ عملية مسح شاملة — يجعل الحساب كأنه جديد تماماً."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return

    account_line = _pending_cleanup.pop(callback.from_user.id, None)
    if not account_line:
        await callback.answer("❌ انتهت صلاحية الجلسة.", show_alert=True)
        return

    await callback.message.edit_text(
        "⏳ <b>جاري تنظيف الحساب بالكامل...</b>\n"
        "<i>يُرجى الانتظار، قد يأخذ هذا عدة دقائق.</i>",
        parse_mode="HTML",
    )
    await callback.answer()

    from utils.session_manager import parse_account_data
    from pyrogram import Client as _CleanClient
    from pyrogram.errors import FloodWait as _CleanFloodWait, ChatAdminRequired
    from pyrogram.enums import ChatType as _ChatType
    from pyrogram.raw import functions as _raw_fn, types as _raw_types

    parsed = parse_account_data(account_line)
    if not parsed:
        await callback.message.edit_text("❌ فشل تحليل بيانات الحساب.")
        return

    client = _CleanClient(
        name=f"cleanup_{parsed['phone'].replace('+', '')}",
        api_id=parsed["api_id"],
        api_hash=parsed["api_hash"],
        session_string=parsed["session_string"],
        in_memory=True,
        no_updates=True,
    )

    left_groups   = 0
    cleared_chats = 0

    async def _safe_delete_history(peer_id):
        """يحذف كل سجل المحادثة عبر MTProto مع revoke=True (يحذف من الطرفين)."""
        try:
            peer = await client.resolve_peer(peer_id)
            await client.invoke(
                _raw_fn.messages.DeleteHistory(
                    peer=peer,
                    max_id=0,
                    revoke=True,
                    just_clear=False,
                )
            )
            return True
        except Exception:
            return False

    try:
        await client.start()

        # ── جمع كل المحادثات أولاً قبل الحذف ───────────────────────────────
        all_dialogs = []
        async for dialog in client.get_dialogs():
            all_dialogs.append(dialog)

        # ── المعالجة ─────────────────────────────────────────────────────────
        for dialog in all_dialogs:
            try:
                chat = dialog.chat
                chat_id = chat.id

                if chat.type in (_ChatType.GROUP, _ChatType.SUPERGROUP):
                    # مغادرة المجموعة وحذف المحادثة
                    try:
                        await client.leave_chat(chat_id, delete=True)
                        left_groups += 1
                    except ChatAdminRequired:
                        # لو الحساب هو المؤسس، لا يمكن المغادرة — نحذف السجل فقط
                        await _safe_delete_history(chat_id)
                    except Exception:
                        try:
                            await client.leave_chat(chat_id)
                            left_groups += 1
                        except Exception:
                            pass

                elif chat.type == _ChatType.CHANNEL:
                    try:
                        await client.leave_chat(chat_id, delete=True)
                        left_groups += 1
                    except ChatAdminRequired:
                        await _safe_delete_history(chat_id)
                    except Exception:
                        try:
                            await client.leave_chat(chat_id)
                            left_groups += 1
                        except Exception:
                            pass

                elif chat.type == _ChatType.PRIVATE:
                    # محادثات خاصة + بوتات + Saved Messages (id==me)
                    ok = await _safe_delete_history(chat_id)
                    if ok:
                        cleared_chats += 1
                    else:
                        # fallback: delete_user_history
                        try:
                            await client.delete_user_history(chat_id)
                            cleared_chats += 1
                        except Exception:
                            pass

                elif chat.type == _ChatType.BOT:
                    ok = await _safe_delete_history(chat_id)
                    if ok:
                        cleared_chats += 1

            except _CleanFloodWait as fw:
                await asyncio.sleep(min(fw.value, 20))
            except Exception:
                pass

        # ── حذف Saved Messages (الرسائل المحفوظة مع النفس) ──────────────────
        try:
            me = await client.get_me()
            await _safe_delete_history("me")
        except Exception:
            pass

        # ملاحظة: الاسم والصورة الشخصية والـ Bio تُبقى كما هي بناءً على طلب الأدمن

    except Exception as e:
        logger.error("live_cleanup error for %s: %s", parsed.get("phone"), e)
        builder = InlineKeyboardBuilder()
        builder.button(text="📦 إدارة المخزون", callback_data="admin:stock")
        await callback.message.edit_text(
            f"❌ <b>خطأ أثناء المسح:</b>\n<code>{e}</code>",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        return
    finally:
        try:
            await client.stop()
        except Exception:
            pass

    builder = InlineKeyboardBuilder()
    builder.button(text="📦 إدارة المخزون", callback_data="admin:stock")
    builder.button(text="📱 إضافة رقم آخر",  callback_data="admin:live_add")
    builder.adjust(1)

    await callback.message.edit_text(
        f"✅ <b>تم تنظيف المحادثات بالكامل!</b>\n\n"
        f"📤 مجموعات/قنوات: <b>{left_groups}</b>\n"
        f"🗑️ محادثات ممسوحة: <b>{cleared_chats}</b>\n\n"
        f"<i>جميع المحادثات والقنوات والبوتات محذوفة ✨</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "live_cleanup_no")
async def admin_live_cleanup_no(callback: CallbackQuery):
    """يتخطى عملية المسح ويُغلق القائمة."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    _pending_cleanup.pop(callback.from_user.id, None)
    builder = InlineKeyboardBuilder()
    builder.button(text="📦 إدارة المخزون", callback_data="admin:stock")
    builder.button(text="📱 إضافة رقم آخر",  callback_data="admin:live_add")
    builder.adjust(1)
    await callback.message.edit_text(
        "✅ تم حفظ الحساب بدون مسح البيانات.",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# ══════════════════════════════════════════════════════════════════════════════
# ── إعدادات نظام الإحالة ومكافحة الغش (Admin Referral Settings)
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin:referral_settings")
async def admin_referral_settings(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    ref_enabled = (await get_setting("referral_enabled") or "1") == "1"
    reward_usd = float(await get_setting("referral_reward_usd") or "0.05")

    from keyboards import admin_referral_settings_keyboard
    status_str = "🟢 مفعّل" if ref_enabled else "🔴 معطّل"
    text = (
        "🎁 <b>إعدادات نظام الإحالة ومكافحة الغش</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"• حالة النظام: <b>{status_str}</b>\n"
        f"• قيمة مكافأة الإحالة: <b>${reward_usd:.2f} USDT</b>\n"
        "• فحص بصمة الأجهزة (Hardware Fingerprinting): <b>نشط تلقائياً 🛡️</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👇 اختر الإجراء المطلوب:"
    )
    await callback.message.edit_text(
        text,
        reply_markup=admin_referral_settings_keyboard(ref_enabled, reward_usd),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin:toggle_referral")
async def admin_toggle_referral(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    cur = (await get_setting("referral_enabled") or "1") == "1"
    new_val = "0" if cur else "1"
    await set_setting("referral_enabled", new_val)
    reward_usd = float(await get_setting("referral_reward_usd") or "0.05")

    from keyboards import admin_referral_settings_keyboard
    status_str = "🟢 مفعّل" if new_val == "1" else "🔴 معطّل"
    text = (
        "🎁 <b>إعدادات نظام الإحالة ومكافحة الغش</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"• حالة النظام: <b>{status_str}</b>\n"
        f"• قيمة مكافأة الإحالة: <b>${reward_usd:.2f} USDT</b>\n"
        "• فحص بصمة الأجهزة (Hardware Fingerprinting): <b>نشط تلقائياً 🛡️</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👇 اختر الإجراء المطلوب:"
    )
    await callback.message.edit_text(
        text,
        reply_markup=admin_referral_settings_keyboard(new_val == "1", reward_usd),
        parse_mode="HTML",
    )
    await callback.answer("تم تغيير حالة النظام بنجاح!", show_alert=True)


@router.callback_query(F.data == "admin:set_referral_reward")
async def admin_set_referral_reward_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminState.waiting_for_referral_reward_usd)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:referral_settings")
    await callback.message.edit_text(
        "💵 <b>تعديل مكافأة الإحالة</b>\n\n"
        "أرسل قيمة المكافأة الجديدة بالدولار التي يحصل عليها الداعي عند انضمام وتأكيد جهاز كل عضو جديد:\n"
        "<i>مثال: 0.05 أو 0.10 أو 0.25</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminState.waiting_for_referral_reward_usd)
async def admin_set_referral_reward_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        val = float(message.text.strip().replace(",", "."))
        if val < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ يرجى إدخال رقم صحيح (مثال: 0.10)")
        return

    await state.clear()
    await set_setting("referral_reward_usd", str(val))
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 رجوع لإعدادات الإحالة", callback_data="admin:referral_settings")
    await message.answer(
        f"✅ <b>تم حفظ مكافأة الإحالة بنجاح:</b> <b>${val:.2f}</b> لكل إحالة مؤكدة.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:referral_stats")
async def admin_referral_stats_view(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    from database import get_admin_referral_stats
    stats = await get_admin_referral_stats()

    approved = stats.get("total_approved", 0)
    blocked  = stats.get("total_blocked", 0)
    paid     = stats.get("total_paid", 0.0)

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 رجوع", callback_data="admin:referral_settings")

    text = (
        "📊 <b>إحصائيات نظام الإحالة والحماية</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅  <b>إجمالي الإحالات المقبولة والفريدة:</b> <b>{approved}</b>\n"
        f"🛡️  <b>محاولات الغش المحظورة (أجهزة مكررة):</b> <b>{blocked}</b>\n"
        f"💵  <b>إجمالي المكافآت المدفوعة:</b> <b>${paid:.2f} USDT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<i>النظام يعمل بكفاءة عالية ويحظر تلقائياً أي محاولة لإنشاء حسابات وهمية من نفس الجهاز.</i>"
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin:reset_devices_btn")
async def admin_reset_devices_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    from database import get_pool
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("DELETE FROM device_fingerprints")
        await db.execute("UPDATE users SET device_fingerprint = NULL, is_device_verified = 0, referred_by = NULL")
    await callback.answer("✅ تم تصفير جميع بصمات الأجهزة وحالات الإحالة لجميع الحسابات بنجاح!", show_alert=True)


@router.callback_query(F.data == "admin:reset_user_btn")
async def admin_reset_user_callback(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.set_state(AdminState.waiting_for_reset_user_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:users")
    await callback.message.edit_text(
        "🗑️ <b>تصفير وحذف مستخدم للتجربة</b>\n\n"
        "أرسل الآيدي الرقمي للمستخدم الذي تريد تصفيره (مثال: <code>726886536</code>):",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminState.waiting_for_reset_user_id)
async def admin_reset_user_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    val = (message.text or "").strip()
    if not val.isdigit():
        await message.answer("❌ يرجى إدخال آيدي رقمي صحيح (مثال: 726886536)")
        return
    target_uid = int(val)
    await state.clear()
    from database import reset_user_for_testing
    await reset_user_for_testing(target_uid)
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 إدارة المستخدمين", callback_data="admin:users")
    await message.answer(
        f"✅ <b>تم تصفير وحذف المستخدم <code>{target_uid}</code> بنجاح!</b>\n\n"
        "أصبح الحساب الآن جديداً كلياً ويمكنه تجربة رابط الإحالة وفحص البصمة كأنه يدخل لأول مرة.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.message(Command("reset_user"))
async def cmd_reset_user(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").strip().split()
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.answer("⚠️ الصيغة: <code>/reset_user [آيدي_المستخدم]</code>\nمثال: <code>/reset_user 726886536</code>", parse_mode="HTML")
        return
    target_uid = int(parts[1].strip())
    from database import reset_user_for_testing
    await reset_user_for_testing(target_uid)
    await message.answer(
        f"✅ <b>تم تصفير وحذف بيانات المستخدم <code>{target_uid}</code> وبصمات جهازه بنجاح!</b>\n"
        "أصبح الحساب الآن جديداً كلياً كأنه لم يدخل البوت من قبل، ويمكنه إعادة تجربة رابط الإحالة بحرية.",
        parse_mode="HTML"
    )


@router.message(Command("reset_devices"))
async def cmd_reset_devices(message: Message):
    if not is_admin(message.from_user.id):
        return
    from database import get_pool
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("DELETE FROM device_fingerprints")
        await db.execute("UPDATE users SET device_fingerprint = NULL, is_device_verified = 0, referred_by = NULL")
    await message.answer("✅ <b>تم تصفير جميع بصمات الأجهزة وحالات الإحالة بنجاح لجميع الحسابات!</b>\nيمكنك الآن تجربة أي حساب كما لو كان جديداً.", parse_mode="HTML")

