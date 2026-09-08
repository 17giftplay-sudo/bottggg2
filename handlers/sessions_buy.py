"""
شراء جلسات (sessions) — نفس مخزون accounts_inventory.
البوت يتصل بـ Telegram، يُزيل الباسوورد، ويُسلّم .session + معلومات الحساب.
"""
import asyncio
import io
import logging
import zipfile
from datetime import datetime, timezone

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import (
    get_user,
    get_setting,
    get_countries_with_stock,
    get_country,
    get_pool,
    purchase_accounts_as_sessions,
)
from keyboards import back_to_main_keyboard, countries_keyboard
from translations import t
from states import SessionsBuyState

router  = Router()
logger  = logging.getLogger(__name__)
_MAX_QTY = 20


def _effective_price(country: dict) -> float:
    from datetime import datetime, timezone
    price       = float(country["price"])
    discount    = float(country.get("flash_sale_discount") or 0)
    flash_until = country.get("flash_sale_until")
    if discount > 0 and flash_until:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if flash_until > now:
            price = round(price * (1 - discount / 100), 4)
    return price


# ─── فتح قائمة الجلسات ────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:sessions")
async def show_sessions_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    lang = user.get("language", "ar")

    sell_enabled = (await get_setting("sell_btn_enabled") or "1") == "1"
    if not sell_enabled:
        await callback.answer(
            "🔴 المتجر متوقف مؤقتاً." if lang == "ar"
            else "🔴 Store is temporarily closed.",
            show_alert=True,
        )
        return

    countries = await get_countries_with_stock()
    if not countries:
        await callback.message.edit_text(
            (
                "📦 <b>شراء جلسات Telegram</b>\n\n"
                "❌ لا توجد حسابات متاحة حالياً.\nعد لاحقاً."
            ) if lang == "ar" else (
                "📦 <b>Buy Telegram Sessions</b>\n\n"
                "❌ No accounts available right now."
            ),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    kb = countries_keyboard(lang, countries, page=0, store_type="sessions")
    await callback.message.edit_text(
        (
            "📦 <b>شراء جلسات Telegram (Sessions)</b>\n\n"
            "⚠️ <b>تنبيه هام:</b>\n"
            "هذا القسم مخصص <b>لأصحاب السكربتات وبرامج البوتات والأدوات التلقائية</b> لتسليم ملفات <code>.session + .json</code> جاهزة.\n\n"
            "📱 <b>إذا كنت تريد حساباً عادياً لتسجيل الدخول به على هاتفك:</b>\n"
            "اضغط على زر <b>«🛒 شراء حساب عادي»</b> بالأسفل لاستلام كود الدخول مباشرة.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🌍 <b>اختر الدولة لشراء ملف الجلسة:</b>"
        ) if lang == "ar" else (
            "📦 <b>Buy Telegram Sessions</b>\n\n"
            "⚠️ <b>Important Notice:</b>\n"
            "This section is intended for <b>script developers, bot owners, and automation tools</b> to receive ready <code>.session + .json</code> files.\n\n"
            "📱 <b>If you want a regular account to log in on your phone:</b>\n"
            "Click <b>«🛒 Buy Regular Account»</b> below to receive login code directly.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🌍 <b>Choose a country to buy session file:</b>"
        ),
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


# ─── تنقّل الصفحات ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("sessions_page:"))
async def sessions_page(callback: CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    lang      = user.get("language", "ar")
    page      = int(callback.data.split(":")[1])
    countries = await get_countries_with_stock()
    kb        = countries_keyboard(lang, countries, page=page, store_type="sessions")
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()


# ─── اختيار الدولة ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("sess_buy:"))
async def sessions_pick_country(callback: CallbackQuery, state: FSMContext):
    country_code = callback.data.split(":", 1)[1].upper()
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    lang    = user.get("language", "ar")
    country = await get_country(country_code)

    if not country:
        await callback.answer("❌", show_alert=True)
        return

    ep   = _effective_price(country)
    flag = country.get("flag_emoji", "")

    # عدد الحسابات الفعلي
    _pool = await get_pool()
    async with _pool.acquire() as _db:
        stock = int(await _db.fetchval(
            "SELECT COUNT(*) FROM accounts_inventory "
            "WHERE country_code=$1 AND status='available' AND store_type='dollar'",
            country_code,
        ) or 0)

    if stock == 0:
        await callback.answer(
            "❌ لا توجد حسابات متاحة لهذه الدولة." if lang == "ar"
            else "❌ No accounts available for this country.",
            show_alert=True,
        )
        return

    await state.update_data(
        sess_country_code=country_code,
        sess_country_name=country["country_name"],
        sess_flag=flag,
        sess_price=ep,
        sess_max=min(stock, _MAX_QTY),
    )
    await state.set_state(SessionsBuyState.waiting_for_quantity)

    builder = InlineKeyboardBuilder()
    for q in [1, 2, 3, 5]:
        if q <= stock:
            builder.button(text=str(q), callback_data=f"sess_qty:{country_code}:{q}")
    builder.button(
        text="🔙 رجوع" if lang == "ar" else "🔙 Back",
        callback_data="menu:sessions",
    )
    builder.adjust(4, 1)

    await callback.message.edit_text(
        (
            f"📦 <b>{flag} {country['country_name']}</b>\n\n"
            f"✦  المتاح: <b>{stock}</b> حساب\n"
            f"💵  السعر: <b>${ep:.2f}</b> لكل جلسة\n\n"
            "أدخل عدد الجلسات أو اختر:"
        ) if lang == "ar" else (
            f"📦 <b>{flag} {country['country_name']}</b>\n\n"
            f"✦  Available: <b>{stock}</b>\n"
            f"💵  Price: <b>${ep:.2f}</b>/session\n\n"
            "Enter number of sessions or choose:"
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── كمية سريعة ───────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("sess_qty:"))
async def sessions_quick_qty(callback: CallbackQuery, state: FSMContext):
    parts        = callback.data.split(":")
    country_code = parts[1].upper()
    qty          = int(parts[2])
    user         = await get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    lang = user.get("language", "ar")

    data = await state.get_data()
    if data.get("sess_country_code") != country_code:
        country = await get_country(country_code)
        if not country:
            await callback.answer("❌", show_alert=True)
            return
        ep = _effective_price(country)
        await state.update_data(
            sess_country_code=country_code,
            sess_country_name=country["country_name"],
            sess_flag=country.get("flag_emoji", ""),
            sess_price=ep,
            sess_max=min(20, _MAX_QTY),
        )

    await _show_confirm(callback.message, state, user, lang, qty, edit=True)
    await state.set_state(SessionsBuyState.waiting_for_confirm)
    await callback.answer()


# ─── كمية نصية ────────────────────────────────────────────────────────────────

@router.message(SessionsBuyState.waiting_for_quantity)
async def sessions_text_qty(message: Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if not user:
        return
    lang = user.get("language", "ar")
    try:
        qty = int(message.text.strip())
        if qty <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer(
            "❌ أدخل رقماً صحيحاً أكبر من صفر." if lang == "ar"
            else "❌ Enter a valid number greater than 0."
        )
        return

    data    = await state.get_data()
    max_qty = data.get("sess_max", 1)
    if qty > max_qty:
        await message.answer(
            f"❌ الحد الأقصى المتاح <b>{max_qty}</b>." if lang == "ar"
            else f"❌ Maximum available: <b>{max_qty}</b>.",
            parse_mode="HTML",
        )
        return

    await _show_confirm(message, state, user, lang, qty, edit=False)
    await state.set_state(SessionsBuyState.waiting_for_confirm)


# ─── helper: شاشة التأكيد ─────────────────────────────────────────────────────

async def _show_confirm(target, state, user, lang, qty, *, edit: bool):
    data         = await state.get_data()
    country_name = data["sess_country_name"]
    flag         = data["sess_flag"]
    price_each   = data["sess_price"]
    total        = round(qty * price_each, 4)
    balance      = float(user["balance"])
    country_code = data["sess_country_code"]

    await state.update_data(sess_qty=qty, sess_total=total)

    balance_ok = balance >= total
    builder    = InlineKeyboardBuilder()
    if balance_ok:
        builder.button(
            text="✅ تأكيد الشراء" if lang == "ar" else "✅ Confirm Purchase",
            callback_data=f"sess_confirm:{country_code}:{qty}",
        )
    builder.button(
        text="❌ إلغاء" if lang == "ar" else "❌ Cancel",
        callback_data="menu:sessions",
    )
    builder.adjust(1)

    text = (
        f"📦 <b>تأكيد الطلب</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌍  الدولة: <b>{flag} {country_name}</b>\n"
        f"✦   الكمية: <b>{qty} جلسة</b>\n"
        f"💵  سعر الجلسة: <b>${price_each:.2f}</b>\n"
        f"💰  الإجمالي: <b>${total:.2f}</b>\n"
        f"👛  رصيدك: <b>${balance:.2f}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        + ("✅ رصيدك كافٍ — اضغط تأكيد." if balance_ok
           else f"❌ رصيدك غير كافٍ — تحتاج <b>${total-balance:.2f}</b> إضافية.")
    ) if lang == "ar" else (
        f"📦 <b>Order Confirmation</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌍  Country: <b>{flag} {country_name}</b>\n"
        f"✦   Quantity: <b>{qty} sessions</b>\n"
        f"💵  Price/session: <b>${price_each:.2f}</b>\n"
        f"💰  Total: <b>${total:.2f}</b>\n"
        f"👛  Balance: <b>${balance:.2f}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        + ("✅ Balance sufficient — press Confirm." if balance_ok
           else f"❌ Insufficient balance — need <b>${total-balance:.2f}</b> more.")
    )

    if edit and hasattr(target, "edit_text"):
        await target.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ─── تأكيد الشراء + توليد الجلسات ────────────────────────────────────────────

@router.callback_query(F.data.startswith("sess_confirm:"))
async def sessions_execute(callback: CallbackQuery, state: FSMContext, bot: Bot):
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Invalid.", show_alert=True)
        return
    country_code = parts[1].upper()
    try:
        qty = int(parts[2])
    except ValueError:
        await callback.answer("Invalid.", show_alert=True)
        return

    # تحقق من الكمية قبل أي شيء
    if qty <= 0 or qty > _MAX_QTY:
        await callback.answer("❌ كمية غير صالحة.", show_alert=True)
        return

    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    lang = user.get("language", "ar")
    await state.clear()

    proc = await callback.message.edit_text(
        "⏳ <b>جاري شراء الحسابات...</b>" if lang == "ar"
        else "⏳ <b>Purchasing accounts...</b>",
        parse_mode="HTML",
    )

    # ── شراء من المخزون ──────────────────────────────────────────────────────
    try:
        result = await purchase_accounts_as_sessions(callback.from_user.id, country_code, qty)
    except Exception as e:
        logger.error("purchase_accounts_as_sessions: %s", e)
        result = None

    if result is None:
        await proc.edit_text(
            "❌ رصيدك غير كافٍ أو الحسابات نفدت." if lang == "ar"
            else "❌ Insufficient balance or out of stock.",
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    flag  = result["flag_emoji"]
    cname = result["country_name"]

    # ── الاتصال بـ Telegram لكل حساب وإزالة الباسوورد ────────────────────────
    await proc.edit_text(
        f"⏳ <b>جاري تجهيز {qty} جلسة... قد يستغرق دقيقة.</b>" if lang == "ar"
        else f"⏳ <b>Preparing {qty} session(s)... this may take a minute.</b>",
        parse_mode="HTML",
    )

    from utils.session_delivery import prepare_session_for_delivery

    # جلب الباسوورد المحدد للمخزون (إن وُجد)
    new_password = (await get_setting("stock_2fa_password") or "").strip()

    tasks = [
        prepare_session_for_delivery(acc["account_data"], new_password=new_password)
        for acc in result["accounts"]
    ]
    deliveries = await asyncio.gather(*tasks, return_exceptions=True)

    # ── توليد ZIP ────────────────────────────────────────────────────────────
    zip_buf  = io.BytesIO()
    ok_infos = []
    fail_count = 0

    from utils.session_converter import session_string_to_telethon_sqlite
    from utils.session_manager import parse_account_data

    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for d in deliveries:
            if isinstance(d, Exception):
                fail_count += 1
                continue

            phone = d.get("phone", "unknown")
            sb    = d.get("session_bytes", b"")

            # إذا كان الاتصال فشل أو الملف فارغ → fallback: توليد محلي
            if not d.get("ok") or not sb:
                if not d.get("ok"):
                    fail_count += 1
                try:
                    _acc = next(
                        (a for a in result["accounts"]
                         if a["account_data"].split("::")[0].strip() == phone),
                        None,
                    )
                    if _acc:
                        parsed = parse_account_data(_acc["account_data"])
                        if parsed:
                            sb = await asyncio.to_thread(
                                session_string_to_telethon_sqlite,
                                parsed["session_string"], phone
                            )
                            d = {
                                "phone":           phone,
                                "api_id":          parsed.get("api_id", ""),
                                "api_hash":        parsed.get("api_hash", ""),
                                "session_string":  parsed.get("session_string", ""),
                                "username":        "",
                                "full_name":       "",
                                "password_changed": False,
                            }
                        else:
                            continue
                    else:
                        continue
                except Exception:
                    continue

            if sb:
                zf.writestr(f"{phone}.session", sb)
            d["session_bytes"] = b""  # لا نحتاجه في ok_infos
            ok_infos.append(d)

        # README.txt — هيدر + معلومات كل حساب
        pw_label = f"كلمة المرور الجديدة: {new_password}" if new_password else "تمت إزالة الباسوورد ✅"
        readme_lines = [
            f"📦 الحزمة: {flag} {cname} | الصيغة: file | العدد: {len(ok_infos)}",
            "━━━━━━━━━━━━━━━━━━━━",
            "",
        ]
        for i, d in enumerate(ok_infos, 1):
            uname = d.get("username", "") or ""
            name  = d.get("full_name", "") or ""
            readme_lines += [
                f"[{i}]",
                f"📱 الرقم: {d['phone']}",
            ]
            if name:
                readme_lines.append(f"👤 الاسم: {name}")
            if uname:
                readme_lines.append(f"🔗 اليوزر: {uname}")
            readme_lines += [
                f"🔑 API ID: {d.get('api_id', '')}",
                f"🗝  API Hash: {d.get('api_hash', '')}",
                f"🔐 {pw_label}",
                f"📝 Session String:",
                d.get("session_string", ""),
                "",
            ]
        zf.writestr("README.txt", "\n".join(readme_lines).encode("utf-8"))

    zip_buf.seek(0)
    zip_name = f"Sessions_{flag}{cname}_{int(datetime.now().timestamp())}.zip"
    zip_file = BufferedInputFile(zip_buf.read(), filename=zip_name)

    # ── رسالة النجاح ─────────────────────────────────────────────────────────
    ok_count    = len(ok_infos)
    pw_line_ar  = (
        f"🔑  كلمة المرور الجديدة: <code>{new_password}</code>"
        if new_password else
        "🔑  تمت إزالة الباسوورد ✅"
    )
    pw_line_en  = (
        f"🔑  New password: <code>{new_password}</code>"
        if new_password else
        "🔑  Password removed ✅"
    )
    warn_ar = f"\n\n⚠️ <b>{fail_count}</b> جلسة تعذّر تجهيزها." if fail_count else ""
    warn_en = f"\n\n⚠️ <b>{fail_count}</b> session(s) failed." if fail_count else ""

    success_text = (
        f"✅ <b>تم تجهيز طلبك بنجاح!</b>\n"
        f"📦  الدولة: <b>{flag} {cname}</b>\n"
        f"🔢  الجلسات السليمة: <b>{ok_count}</b>\n"
        f"💰  الصافي المدفوع: <b>${result['total_paid']:.2f}</b>\n"
        f"{pw_line_ar}"
        f"{warn_ar}\n\n"
        f"💬 <b>ملاحظة:</b> إذا حدثت معك أي مشكلة في الحسابات، تواصل مع الدعم الفني وسيقوم بتعويضك بحساب جديد مباشرة! 🎧"
    ) if lang == "ar" else (
        f"✅ <b>Your sessions are ready!</b>\n"
        f"📦  Country: <b>{flag} {cname}</b>\n"
        f"🔢  Sessions: <b>{ok_count}</b>\n"
        f"💰  Total paid: <b>${result['total_paid']:.2f}</b>\n"
        f"{pw_line_en}"
        f"{warn_en}\n\n"
        f"💬 <b>Note:</b> If you encounter any issue, contact support and they will replace it with a new account directly! 🎧"
    )

    await proc.delete()
    await bot.send_document(
        callback.from_user.id,
        zip_file,
        caption=success_text,
        parse_mode="HTML",
        reply_markup=back_to_main_keyboard(lang),
    )

    # ── إشعار الأدمن ─────────────────────────────────────────────────────────
    try:
        from config import ADMIN_IDS
        now_s = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
        uname = f"@{callback.from_user.username}" if callback.from_user.username else "—"
        notif = (
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "📦  <b>بيع جلسات</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤  <a href='tg://user?id={callback.from_user.id}'>{callback.from_user.full_name}</a>\n"
            f"🆔  <code>{callback.from_user.id}</code>  |  {uname}\n"
            f"🌍  {flag} {cname}\n"
            f"✦   {ok_count} جلسة\n"
            f"💵  <b>${result['total_paid']:.2f}</b>\n"
            f"🗓  {now_s}\n"
            "━━━━━━━━━━━━━━━━━━━━━"
        )
        for aid in ADMIN_IDS:
            try:
                await bot.send_message(aid, notif, parse_mode="HTML")
            except Exception:
                pass
    except Exception as ex:
        logger.warning("sessions admin notify: %s", ex)

    # ── إشعار قناة الإشعارات ─────────────────────────────────────────────────
    try:
        notif_channel = await get_setting("notification_channel")
        if notif_channel:
            uid_str      = str(callback.from_user.id)
            masked_buyer = "*****" + uid_str[-4:]
            now_s        = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
            ch_msg = (
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "📦  <b>شراء جلسات</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🌍  <b>الدولة:</b>  {flag} {cname}\n"
                f"🔢  <b>العدد:</b>  {ok_count} جلسة\n"
                f"💰  <b>المدفوع:</b>  ${result['total_paid']:.2f}\n"
                f"👤  <b>العميل:</b>  <code>{masked_buyer}</code>\n"
                f"🟢  <b>الحالة:</b>  تم التسليم\n\n"
                f"🗓  <b>التاريخ:</b>  {now_s}\n\n"
                "━━━━━━━━━━━━━━━━━━━━━"
            )
            from aiogram.utils.keyboard import InlineKeyboardBuilder as _KB
            bot_info = await bot.get_me()
            ch_kb = _KB()
            ch_kb.button(text="🔗  ـ  رابط البوت  ـ  🔗", url=f"https://t.me/{bot_info.username}")
            await bot.send_message(
                chat_id=notif_channel,
                text=ch_msg,
                parse_mode="HTML",
                reply_markup=ch_kb.as_markup(),
            )
    except Exception as ex:
        logger.warning("sessions channel notify: %s", ex)

    await callback.answer("✅")
