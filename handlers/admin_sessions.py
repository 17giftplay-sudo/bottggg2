"""
إدارة الجلسات من لوحة الأدمن.
الأدمن يرفع ZIP → البوت يستخرج الجلسات → يسأل عن السعر وكلمة المرور → يحفظ في DB.
"""
import base64
import io
import logging
import re
import zipfile

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Filter

from config import ADMIN_IDS
from database import (
    add_sessions_batch,
    get_session_countries_with_stock,
    delete_sessions_by_country,
    get_all_session_stats,
    get_all_countries_with_accounts,
    get_available_accounts_for_conversion,
)
from states import AdminSessionsState
from utils.session_converter import (
    session_string_to_sqlite_bytes,
    extract_phone_from_account_data,
    extract_session_string_from_account_data,
)

router = Router()
logger = logging.getLogger(__name__)


class IsAdmin(Filter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id in ADMIN_IDS


class IsAdminCB(Filter):
    async def __call__(self, callback: CallbackQuery) -> bool:
        return callback.from_user.id in ADMIN_IDS


# ─── لوحة إدارة الجلسات ──────────────────────────────────────────────────────

@router.callback_query(IsAdminCB(), F.data == "admin:sessions")
async def admin_sessions_panel(callback: CallbackQuery):
    countries = await get_session_countries_with_stock()
    stats     = await get_all_session_stats()

    builder = InlineKeyboardBuilder()
    builder.button(text="📤 رفع جلسات (ZIP)",         callback_data="admin_sessions:upload")
    builder.button(text="🔄 تحويل حسابات لجلسات",     callback_data="admin_sessions:convert_menu")
    for c in countries:
        flag  = c.get("flag_emoji", "")
        label = f"🗑 {flag} {c['country_name']} ({c['available_count']} متاحة)"
        builder.button(text=label, callback_data=f"admin_sessions:delete:{c['country_code']}")
    builder.button(text="🔙 رجوع", callback_data="admin:main")
    builder.adjust(1)

    total_avail = stats.get("available", 0)
    total_sold  = stats.get("sold", 0)

    await callback.message.edit_text(
        f"📦 <b>إدارة الجلسات</b>\n\n"
        f"✅ المتاحة: <b>{total_avail}</b>\n"
        f"📤 المباعة: <b>{total_sold}</b>\n\n"
        "اضغط على دولة لحذف جلساتها، أو ارفع ملف ZIP لإضافة جلسات جديدة.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── بدء رفع الجلسات ─────────────────────────────────────────────────────────

@router.callback_query(IsAdminCB(), F.data == "admin_sessions:upload")
async def admin_sessions_upload_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminSessionsState.waiting_for_zip)

    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:sessions")
    builder.adjust(1)

    await callback.message.edit_text(
        "📤 <b>رفع جلسات جديدة</b>\n\n"
        "أرسل ملف <b>ZIP</b> يحتوي على ملفات <code>.session</code>\n\n"
        "📝 يمكن أن يحتوي ZIP على <code>README.txt</code> بكلمة المرور، "
        "أو ستُدخلها يدوياً في الخطوة التالية.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── استقبال ملف ZIP ─────────────────────────────────────────────────────────

@router.message(AdminSessionsState.waiting_for_zip, IsAdmin())
async def admin_sessions_receive_zip(message: Message, state: FSMContext, bot: Bot):
    if not message.document:
        await message.answer("❌ أرسل ملف ZIP فقط.")
        return

    filename = message.document.file_name or ""
    if not filename.lower().endswith(".zip"):
        await message.answer("❌ الملف يجب أن يكون بصيغة .zip")
        return

    await message.answer("⏳ جاري قراءة الجلسات من الملف...")

    # تنزيل الملف
    file = await bot.get_file(message.document.file_id)
    buf  = io.BytesIO()
    await bot.download_file(file.file_path, destination=buf)
    buf.seek(0)

    # ── استخراج اسم الدولة من اسم الملف ─────────────────────────────────
    # مثال: Sessions_سوريا🇸🇾_1785767791_123.zip
    country_name_raw = ""
    flag_emoji       = ""
    country_code_raw = ""

    match = re.match(r"Sessions_(.+?)_\d+", filename)
    if match:
        raw = match.group(1)
        # افصل الـ flag emoji عن الاسم
        emoji_match = re.search(r"[\U0001F1E0-\U0001F1FF]{2}", raw)
        if emoji_match:
            flag_emoji = emoji_match.group(0)
            country_name_raw = raw.replace(flag_emoji, "").strip()
        else:
            country_name_raw = raw

    # ── فتح ZIP وقراءة الجلسات ──────────────────────────────────────────
    from utils.zip_parser import _parse_info_file
    try:
        with zipfile.ZipFile(buf) as zf:
            pwd_candidates = ["", "1234", "123", "password", "telethon", "session", "iblees", "admin", "RR"]

            def _safe_read(member_name: str) -> bytes:
                for pwd in pwd_candidates:
                    try:
                        if pwd:
                            zf.setpassword(pwd.encode("utf-8"))
                        return zf.read(member_name)
                    except (RuntimeError, zipfile.BadZipFile):
                        continue
                raise RuntimeError(f"Cannot decrypt or read member {member_name}")

            names    = zf.namelist()
            sessions = []
            password_from_readme = ""

            json_files = {
                os.path.basename(n).lower(): n
                for n in names if n.lower().endswith(".json")
            }
            txt_files = {
                os.path.basename(n).lower(): n
                for n in names if n.lower().endswith(".txt")
            }

            # 1. استخراج كلمة المرور والمعلومات من ملفات txt
            for name in names:
                if name.lower().endswith(".txt"):
                    try:
                        ttext = _safe_read(name).decode("utf-8", errors="ignore")
                        info  = _parse_info_file(ttext)
                        if info.get("two_factor") and not password_from_readme:
                            password_from_readme = info["two_factor"]
                    except Exception:
                        pass

            # 2. قراءة الجلسات .session
            for name in names:
                if name.endswith(".session") and not name.startswith("__"):
                    raw_filename = os.path.basename(name).replace(".session", "")
                    stem         = os.path.splitext(raw_filename)[0]

                    phone = ""
                    digits = re.sub(r"\D", "", raw_filename)
                    if len(digits) >= 7 and len(digits) <= 15:
                        phone = digits

                    if not phone:
                        for candidate_txt in (f"{stem}.txt".lower(), f"info_{stem}.txt".lower(), f"{stem}_info.txt".lower()):
                            if candidate_txt in txt_files:
                                try:
                                    ttext = _safe_read(txt_files[candidate_txt]).decode("utf-8", errors="ignore")
                                    info  = _parse_info_file(ttext)
                                    if info.get("phone"):
                                        phone = re.sub(r"\D", "", info["phone"])
                                    if info.get("two_factor") and not password_from_readme:
                                        password_from_readme = info["two_factor"]
                                except Exception:
                                    pass
                                if phone:
                                    break

                    if not phone:
                        candidate_json = f"{stem}.json".lower()
                        if candidate_json in json_files:
                            try:
                                jtext = _safe_read(json_files[candidate_json]).decode("utf-8", errors="ignore")
                                import json as _json
                                jdata = _json.loads(jtext)
                                p_val = str(jdata.get("phone") or jdata.get("phone_number") or "").strip()
                                if p_val:
                                    phone = re.sub(r"\D", "", p_val)
                                for pw_key in ("2fa", "two_step", "twoFA", "password", "pass", "2FA"):
                                    pw_val = str(jdata.get(pw_key) or "").strip()
                                    if pw_val and not password_from_readme:
                                        password_from_readme = pw_val
                                        break
                            except Exception:
                                pass

                    if not phone and digits:
                        phone = digits

                    if not phone:
                        continue

                    try:
                        data = _safe_read(name)
                        b64  = base64.b64encode(data).decode("utf-8")
                        sessions.append({"phone": phone, "session_data": b64})
                    except Exception as ex:
                        logger.warning("Failed to read session member %s: %s", name, ex)
                        continue

    except zipfile.BadZipFile:
        await message.answer("❌ الملف تالف أو ليس ZIP صالحاً.")
        await state.clear()
        return

    if not sessions:
        await message.answer("❌ لم تُوجَد أي ملفات .session في الـ ZIP.")
        await state.clear()
        return

    await state.update_data(
        sessions_to_add=sessions,
        sessions_country_name=country_name_raw or "Unknown",
        sessions_flag=flag_emoji or "🌍",
        sessions_password_found=password_from_readme,
    )
    await state.set_state(AdminSessionsState.waiting_for_country_code)

    phones_preview = "\n".join(f"  • {s['phone']}" for s in sessions[:5])
    if len(sessions) > 5:
        phones_preview += f"\n  ... و{len(sessions)-5} آخرين"

    await message.answer(
        f"✅ تم قراءة <b>{len(sessions)}</b> جلسة.\n\n"
        f"📋 أمثلة:\n{phones_preview}\n\n"
        f"📝 الدولة المُكتشفة: <b>{flag_emoji} {country_name_raw or '—'}</b>\n\n"
        "أدخل <b>كود الدولة</b> (مثل SY أو TR أو SA):",
        parse_mode="HTML",
    )


# ─── كود الدولة ──────────────────────────────────────────────────────────────

@router.message(AdminSessionsState.waiting_for_country_code, IsAdmin())
async def admin_sessions_country_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    if not re.fullmatch(r"[A-Z]{2,6}", code):
        await message.answer("❌ كود الدولة يجب أن يكون 2-6 أحرف إنجليزية (مثل SY أو TR).")
        return

    await state.update_data(sessions_country_code=code)
    await state.set_state(AdminSessionsState.waiting_for_price)

    data = await state.get_data()
    found_pw = data.get("sessions_password_found", "")

    await message.answer(
        f"✅ الكود: <b>{code}</b>\n\n"
        + (f"🔑 كلمة مرور مكتشفة من README: <code>{found_pw}</code>\n\n" if found_pw else "")
        + "أدخل <b>السعر بالدولار</b> لكل جلسة (مثل 0.15):",
        parse_mode="HTML",
    )


# ─── السعر ───────────────────────────────────────────────────────────────────

@router.message(AdminSessionsState.waiting_for_price, IsAdmin())
async def admin_sessions_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.strip().replace(",", "."))
        if price <= 0 or price > 1000:
            raise ValueError
    except ValueError:
        await message.answer("❌ أدخل سعراً صحيحاً (مثل 0.15 أو 1.5).")
        return

    await state.update_data(sessions_price=price)

    data         = await state.get_data()
    sessions     = data["sessions_to_add"]
    country_code = data["sessions_country_code"]
    country_name = data["sessions_country_name"]
    flag         = data.get("sessions_flag", "🌍")

    await state.clear()
    await message.answer("⏳ جاري حفظ الجلسات في قاعدة البيانات...")

    added = await add_sessions_batch(
        country_code=country_code,
        country_name=country_name,
        flag_emoji=flag,
        sessions=sessions,
        password="",
        price=price,
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="📦 إدارة الجلسات", callback_data="admin:sessions")
    builder.button(text="🏠 الرئيسية",       callback_data="admin:main")
    builder.adjust(1)

    await message.answer(
        f"✅ <b>تم حفظ الجلسات!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌍  الدولة: <b>{flag} {country_name}</b> ({country_code})\n"
        f"✦   المضافة: <b>{added}</b> جلسة\n"
        f"💵  السعر: <b>${price:.4f}</b> لكل جلسة\n"
        f"━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


# ─── حذف جلسات دولة ──────────────────────────────────────────────────────────

@router.callback_query(IsAdminCB(), F.data.startswith("admin_sessions:delete:"))
async def admin_sessions_delete_country(callback: CallbackQuery):
    country_code = callback.data.split(":", 2)[2].upper()

    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ نعم، احذف الجلسات المتاحة",
        callback_data=f"admin_sessions:confirm_delete:{country_code}",
    )
    builder.button(text="❌ إلغاء", callback_data="admin:sessions")
    builder.adjust(1)

    await callback.message.edit_text(
        f"⚠️ هل تريد حذف جميع الجلسات <b>المتاحة</b> للدولة <code>{country_code}</code>؟\n"
        "(الجلسات المباعة لن تُحذف)",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(IsAdminCB(), F.data.startswith("admin_sessions:confirm_delete:"))
async def admin_sessions_confirm_delete(callback: CallbackQuery):
    country_code = callback.data.split(":", 2)[2].upper()
    deleted = await delete_sessions_by_country(country_code)

    builder = InlineKeyboardBuilder()
    builder.button(text="📦 إدارة الجلسات", callback_data="admin:sessions")
    builder.adjust(1)

    await callback.message.edit_text(
        f"🗑 تم حذف <b>{deleted}</b> جلسة متاحة للدولة <code>{country_code}</code>.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer("✅")


# ══════════════════════════════════════════════════════════════════════════════
# ─── تحويل حسابات accounts_inventory إلى جلسات sessions_inventory ─────────────
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(IsAdminCB(), F.data == "admin_sessions:convert_menu")
async def admin_sessions_convert_menu(callback: CallbackQuery, state: FSMContext):
    """يعرض قائمة الدول التي لديها حسابات قابلة للتحويل."""
    countries = await get_all_countries_with_accounts()
    if not countries:
        await callback.answer("❌ لا توجد حسابات متاحة للتحويل.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for c in countries:
        flag  = c.get("flag_emoji", "")
        cnt   = c.get("account_count", 0)
        label = f"🔄 {flag} {c['country_name']}  ({cnt} حساب)"
        builder.button(
            text=label,
            callback_data=f"admin_sessions:convert_pick:{c['country_code']}",
        )
    builder.button(text="🔙 رجوع", callback_data="admin:sessions")
    builder.adjust(1)

    await callback.message.edit_text(
        "🔄 <b>تحويل حسابات إلى جلسات</b>\n\n"
        "اختر الدولة التي تريد تحويل حساباتها إلى جلسات.\n"
        "الحسابات ستُنسخ إلى مخزون الجلسات <b>دون حذفها</b> من مخزون الحسابات.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(IsAdminCB(), F.data.startswith("admin_sessions:convert_pick:"))
async def admin_sessions_convert_pick_country(callback: CallbackQuery, state: FSMContext):
    country_code = callback.data.split(":", 2)[2].upper()
    accounts = await get_available_accounts_for_conversion(country_code)
    if not accounts:
        await callback.answer("❌ لا توجد حسابات متاحة لهذه الدولة.", show_alert=True)
        return

    # معاينة
    preview = "\n".join(
        f"  • {extract_phone_from_account_data(a['account_data'])}"
        for a in accounts[:5]
    )
    if len(accounts) > 5:
        preview += f"\n  ... و{len(accounts)-5} آخرين"

    country_name = accounts[0]["country_name"]
    flag         = accounts[0]["flag_emoji"]
    price_default = float(accounts[0]["price"])

    await state.update_data(
        conv_country_code=country_code,
        conv_country_name=country_name,
        conv_flag=flag,
        conv_accounts_count=len(accounts),
        conv_price_default=price_default,
    )
    await state.set_state(AdminSessionsState.convert_waiting_for_price)

    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin_sessions:convert_menu")
    builder.adjust(1)

    await callback.message.edit_text(
        f"🔄 <b>{flag} {country_name}</b>\n\n"
        f"✦  الحسابات الجاهزة للتحويل: <b>{len(accounts)}</b>\n\n"
        f"معاينة:\n{preview}\n\n"
        f"أدخل <b>السعر بالدولار</b> لكل جلسة\n"
        f"(السعر الحالي للحساب: ${price_default:.2f}، أو اكتب <code>same</code> لاستخدامه):",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminSessionsState.convert_waiting_for_price, IsAdmin())
async def admin_sessions_convert_price(message: Message, state: FSMContext):
    data = await state.get_data()
    inp  = message.text.strip().lower()

    if inp == "same":
        price = data["conv_price_default"]
    else:
        try:
            price = float(inp.replace(",", "."))
            if price <= 0 or price > 1000:
                raise ValueError
        except ValueError:
            await message.answer("❌ أدخل سعراً صحيحاً أو اكتب <code>same</code>.",
                                  parse_mode="HTML")
            return

    await state.update_data(conv_price=price)
    await state.set_state(AdminSessionsState.convert_waiting_for_password)

    await message.answer(
        f"✅ السعر: <b>${price:.4f}</b>\n\n"
        "أدخل <b>كلمة المرور</b> للجلسات (2FA إذا كانت مضبوطة)،\n"
        "أو اكتب <code>none</code> إذا لا توجد كلمة مرور:",
        parse_mode="HTML",
    )


@router.message(AdminSessionsState.convert_waiting_for_password, IsAdmin())
async def admin_sessions_convert_execute(message: Message, state: FSMContext, bot: Bot):
    data     = await state.get_data()
    password = "" if message.text.strip().lower() == "none" else message.text.strip()

    country_code = data["conv_country_code"]
    country_name = data["conv_country_name"]
    flag         = data["conv_flag"]
    price        = data["conv_price"]

    await state.clear()
    await message.answer("⏳ جاري تحويل الحسابات إلى جلسات...")

    accounts = await get_available_accounts_for_conversion(country_code)
    if not accounts:
        await message.answer("❌ لا توجد حسابات للتحويل.")
        return

    ok_sessions  = []
    fail_count   = 0

    for acc in accounts:
        try:
            phone          = extract_phone_from_account_data(acc["account_data"])
            sess_str       = extract_session_string_from_account_data(acc["account_data"])
            sqlite_bytes   = session_string_to_sqlite_bytes(sess_str)
            b64            = base64.b64encode(sqlite_bytes).decode("utf-8")
            ok_sessions.append({"phone": phone, "session_data": b64})
        except Exception as e:
            logger.warning("convert: skip %s — %s", acc.get("id"), e)
            fail_count += 1

    if not ok_sessions:
        await message.answer(
            f"❌ تعذّر تحويل أي حساب (فشلت كل {fail_count} محاولات).\n"
            "تأكد أن الجلسات بصيغة Pyrogram v2."
        )
        return

    added = await add_sessions_batch(
        country_code=country_code,
        country_name=country_name,
        flag_emoji=flag,
        sessions=ok_sessions,
        password=password,
        price=price,
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="📦 إدارة الجلسات", callback_data="admin:sessions")
    builder.adjust(1)

    await message.answer(
        f"✅ <b>تم التحويل!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌍  الدولة: <b>{flag} {country_name}</b>\n"
        f"✅  نجح التحويل: <b>{added}</b> جلسة\n"
        + (f"⚠️  فشل التحويل: <b>{fail_count}</b> حساب\n" if fail_count else "")
        + f"💵  السعر: <b>${price:.4f}</b>\n"
        f"🔑  كلمة المرور: <code>{password if password else '—'}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
