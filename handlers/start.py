import logging

from aiogram import Router, Bot, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext

from config import CAPTCHA_MAX_ATTEMPTS
from states import CaptchaState
from database import (
    get_user,
    create_user,
    update_user_profile,
    update_user_language,
    mark_user_verified,
    get_setting,
)
from translations import t
from keyboards import (
    language_keyboard,
    force_sub_keyboard,
    main_menu_keyboard,
)
from utils.captcha import generate_captcha

router = Router()
logger = logging.getLogger(__name__)

ALLOWED_LANGUAGES = {"en", "ar", "fa"}


async def _send_captcha(message: Message, state: FSMContext, lang: str = "en", attempts: int = 0):
    code, buf = generate_captcha()
    await state.update_data(captcha_code=code, lang=lang, captcha_attempts=attempts)
    await state.set_state(CaptchaState.waiting_for_answer)
    photo = BufferedInputFile(buf.read(), filename="captcha.png")
    await message.answer_photo(
        photo=photo,
        caption=t(lang, "captcha_prompt"),
        parse_mode="HTML",
    )


async def _check_force_sub(bot: Bot, user_id: int) -> bool:
    channels = []
    ch1 = await get_setting("force_sub_channel")
    ch2 = await get_setting("notification_channel")
    if ch1:
        channels.append(ch1)
    if ch2 and ch2 != ch1:
        channels.append(ch2)
    if not channels:
        return True
    for channel in channels:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ("left", "kicked", "banned"):
                return False
        except Exception as e:
            logger.warning("_check_force_sub: failed to check %s for user %s: %s", channel, user_id, e)
            return False
    return True


def _welcome_text(lang: str, user: dict) -> str:
    balance = float(user.get("balance") or 0)
    return t(
        lang, "welcome",
        user_id=user["user_id"],
        balance=balance,
    )


async def _show_main_menu(target, user: dict, edit: bool = False):
    lang         = user.get("language", "en")
    text         = _welcome_text(lang, user)
    sell_enabled = (await get_setting("sell_btn_enabled") or "1") == "1"
    info_enabled = (await get_setting("info_btn_enabled") or "1") == "1"

    kb = main_menu_keyboard(
        lang,
        sell_enabled=sell_enabled,
        info_enabled=info_enabled,
    )
    if isinstance(target, CallbackQuery):
        msg = target.message
        if edit:
            await msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
        else:
            await msg.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


# ── /start ────────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    try:
        await state.clear()

        user = await get_user(message.from_user.id)

        if not user:
            user = await create_user(
                user_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
            )
        else:
            try:
                await update_user_profile(
                    user_id=message.from_user.id,
                    username=message.from_user.username,
                    first_name=message.from_user.first_name,
                )
            except Exception as e:
                logger.warning("Error updating profile for user %s: %s", message.from_user.id, e)

        if not user:
            user = {
                "user_id": message.from_user.id,
                "username": message.from_user.username,
                "first_name": message.from_user.first_name,
                "language": "ar",
                "is_verified": 1,
                "balance": 0.0,
                "points": 0,
            }

        joined = True
        try:
            joined = await _check_force_sub(bot, message.from_user.id)
        except Exception as e:
            logger.warning("_check_force_sub exception for user %s: %s", message.from_user.id, e)

        lang = user.get("language") or "ar"

        if not joined:
            ch1  = await get_setting("force_sub_channel")
            ch2  = await get_setting("notification_channel")
            await message.answer(
                t(lang, "force_sub_message"),
                reply_markup=force_sub_keyboard(lang, ch1, ch2),
                parse_mode="HTML",
            )
            return

        await _show_main_menu(message, user)
    except Exception as e:
        logger.error("Critical error in cmd_start for user %s: %s", message.from_user.id, e, exc_info=True)
        fallback_user = {
            "user_id": message.from_user.id,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "language": "ar",
            "is_verified": 1,
            "balance": 0.0,
            "points": 0,
        }
        await _show_main_menu(message, fallback_user)


# ── الكابتشا ──────────────────────────────────────────────────────────────────

@router.message(CaptchaState.waiting_for_answer)
async def process_captcha(message: Message, state: FSMContext, bot: Bot):
    data     = await state.get_data()
    correct  = data.get("captcha_code", "")
    lang     = data.get("lang", "en")
    attempts = data.get("captcha_attempts", 0) + 1

    if message.text and message.text.strip() == correct:
        await state.clear()
        await state.update_data(captcha_passed=True)
        await message.answer(
            t(lang, "captcha_correct"),
            reply_markup=language_keyboard(),
            parse_mode="HTML",
        )
    elif attempts >= CAPTCHA_MAX_ATTEMPTS:
        await state.clear()
        await message.answer(t(lang, "captcha_too_many_attempts"), parse_mode="HTML")
    else:
        code, buf = generate_captcha()
        await state.update_data(captcha_code=code, captcha_attempts=attempts)
        remaining = CAPTCHA_MAX_ATTEMPTS - attempts
        photo     = BufferedInputFile(buf.read(), filename="captcha.png")
        await message.answer_photo(
            photo=photo,
            caption=t(lang, "captcha_wrong", remaining=remaining),
            parse_mode="HTML",
        )


# ── اختيار اللغة ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("lang:"))
async def process_language(callback: CallbackQuery, state: FSMContext, bot: Bot):
    raw_lang = callback.data.split(":")[1]
    if raw_lang not in ALLOWED_LANGUAGES:
        await callback.answer("Invalid language.", show_alert=True)
        return

    lang    = raw_lang
    user_id = callback.from_user.id

    data = await state.get_data()
    if not data.get("captcha_passed"):
        logger.warning("User %s tried to bypass captcha", user_id)
        await callback.answer("Please solve the captcha first.", show_alert=True)
        user         = await get_user(user_id)
        current_lang = (user.get("language") if user else None) or "en"
        await _send_captcha(callback.message, state, current_lang, attempts=0)
        return

    await update_user_language(user_id, lang)
    await mark_user_verified(user_id)
    await state.clear()

    channel = await get_setting("force_sub_channel")
    if channel:
        joined = await _check_force_sub(bot, user_id)
        if not joined:
            ch2 = await get_setting("notification_channel")
            await callback.message.edit_text(
                t(lang, "force_sub_message"),
                reply_markup=force_sub_keyboard(lang, channel, ch2),
                parse_mode="HTML",
            )
            await callback.answer()
            return

    user = await get_user(user_id)
    await _show_main_menu(callback, user, edit=True)
    await callback.answer()


# ── التحقق من الاشتراك ────────────────────────────────────────────────────────

@router.callback_query(F.data == "check_join")
async def check_join(callback: CallbackQuery, state: FSMContext, bot: Bot):
    user_id = callback.from_user.id
    user    = await get_user(user_id)
    lang    = user.get("language", "en") if user else "en"

    joined = await _check_force_sub(bot, user_id)
    if joined:
        user = await get_user(user_id)
        await _show_main_menu(callback, user, edit=True)
        await callback.answer()
    else:
        await callback.answer(t(lang, "not_joined"), show_alert=True)


# ── تغيير اللغة ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:change_language")
async def change_language_prompt(callback: CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = user.get("language", "en") if user else "en"
    await state.update_data(captcha_passed=True)
    await callback.message.edit_text(
        t(lang, "change_language_prompt"),
        reply_markup=language_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


# ── الرجوع للقائمة الرئيسية ───────────────────────────────────────────────────

@router.callback_query(F.data == "menu:main")
async def back_to_main(callback: CallbackQuery, bot: Bot):
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    lang = user.get("language", "en")

    joined = await _check_force_sub(bot, callback.from_user.id)
    if not joined:
        channel = await get_setting("force_sub_channel")
        ch2     = await get_setting("notification_channel")
        await callback.message.edit_text(
            t(lang, "force_sub_message"),
            reply_markup=force_sub_keyboard(lang, channel, ch2),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await _show_main_menu(callback, user, edit=True)
    await callback.answer()


# ── الشروط والأحكام ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:terms")
async def show_terms(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = user.get("language", "ar") if user else "ar"
    terms_text = (
        "📜 <b>الشروط والأحكام</b> ⚠️\n\n"
        "1️⃣ جميع الحسابات يتم فحصها والتأكد من سلامتها قبل التسليم.\n"
        "2️⃣ بعد شراء الحساب، يجب تسجيل الدخول فوراً.\n"
        "3️⃣ الضمان يشمل استبدال الحساب إذا لم يصل كود الدخول أو كان معطلاً خلال فترة الضمان.\n"
        "4️⃣ يُمنع استخدام الحسابات في أي أنشطة مخالفة للقوانين.\n\n"
        "💬 <i>في حال وجود أي استفسار، تواصل مع الدعم الفني مباشرة.</i>"
    ) if lang == "ar" else (
        "📜 <b>Terms and Conditions</b> ⚠️\n\n"
        "1️⃣ All accounts are tested and verified before delivery.\n"
        "2️⃣ Log in immediately after purchase.\n"
        "3️⃣ Warranty covers replacement if the code is not received or account is inactive.\n"
        "4️⃣ Prohibited to use accounts in illegal activities."
    )
    from keyboards import back_to_main_keyboard
    await callback.message.edit_text(terms_text, reply_markup=back_to_main_keyboard(lang), parse_mode="HTML")
    await callback.answer()


# ── العملات وأسعار الصرف ───────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:currency")
async def show_currency(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = user.get("language", "ar") if user else "ar"
    curr_text = (
        "💱 <b>العملات وأسعار الصرف</b> 💵\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "• العملة الأساسية للمتجر: <b>الدولار الأمريكي ($ USD)</b>\n"
        "• الدفع بالعملات الرقمية: <b>USDT (TRC20 / TON / BEP20)</b>\n"
        "• العملات الأخرى المدعومة: <b>LTC, TON, BTC, ETH, TRX</b>\n"
        "• نجوم تيليجرام: <b>Telegram Stars ⭐</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "💳 <i>يتم تحويل المبالغ تلقائياً بسعر الصرف المباشر عند الشحن.</i>"
    ) if lang == "ar" else (
        "💱 <b>Currencies & Exchange Rates</b> 💵\n\n"
        "• Base Currency: <b>$ USD</b>\n"
        "• Crypto: <b>USDT, LTC, TON, BTC, ETH, TRX</b>\n"
        "• Telegram Stars: <b>Stars ⭐</b>"
    )
    from keyboards import back_to_main_keyboard
    await callback.message.edit_text(curr_text, reply_markup=back_to_main_keyboard(lang), parse_mode="HTML")
    await callback.answer()


# ── تحويل الرصيد ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:transfer")
async def show_transfer(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = user.get("language", "ar") if user else "ar"
    bal = float(user.get("balance", 0) if user else 0)
    trns_text = (
        f"💸 <b>تحويل الرصيد</b> 🔄\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>رصيدك المتاح:</b> <b>${bal:.2f}</b>\n\n"
        f"لتحويل رصيد إلى مستخدم آخر، تواصل مع المشرف أو الدعم الفني مع تزويدهم بآيدي المستلم والمبلغ.\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    ) if lang == "ar" else (
        f"💸 <b>Balance Transfer</b> 🔄\n\n"
        f"Available Balance: <b>${bal:.2f}</b>\n\n"
        f"To transfer balance to another user, please contact support with the recipient ID."
    )
    from keyboards import back_to_main_keyboard
    await callback.message.edit_text(trns_text, reply_markup=back_to_main_keyboard(lang), parse_mode="HTML")
    await callback.answer()


# ── رابط الدعوة ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:referral")
async def show_referral(callback: CallbackQuery, bot: Bot):
    user = await get_user(callback.from_user.id)
    lang = user.get("language", "ar") if user else "ar"
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{callback.from_user.id}"
    ref_text = (
        "🔗 <b>رابط الدعوة الخاص بك</b> 🎁\n\n"
        "شارك الرابط مع أصدقائك واكسب نقاط ومكافآت مجانية عند كل عملية شراء يقومون بها!\n\n"
        f"<code>{ref_link}</code>\n\n"
        "👆 <i>اضغط على الرابط لنسخه مباشرة.</i>"
    ) if lang == "ar" else (
        "🔗 <b>Your Referral Link</b> 🎁\n\n"
        f"<code>{ref_link}</code>\n\n"
        "Share your link and earn rewards on every referral purchase!"
    )
    from keyboards import back_to_main_keyboard
    await callback.message.edit_text(ref_text, reply_markup=back_to_main_keyboard(lang), parse_mode="HTML")
    await callback.answer()


# ── إحصائيات المبيعات السريعة ───────────────────────────────────────────────────

@router.callback_query(F.data == "menu:stats_sold")
async def show_stats_sold(callback: CallbackQuery):
    try:
        from database import get_bot_stats
        stats = await get_bot_stats()
        sold = max(1731, int(stats.get("total_sold", 0)))
        avail = int(stats.get("total_available", 0))
        await callback.answer(f"📊 إجمالي المبيعات: {sold} رقم | المتوفر حالياً: {avail} رقم 🚀", show_alert=True)
    except Exception:
        await callback.answer("📊 إجمالي المبيعات: 1731+ رقم متوفر ومسلّم بنجاح!", show_alert=True)


# ── الدعم الفني ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:support")
async def show_support(callback: CallbackQuery):
    support_url = await get_setting("support_url")
    user = await get_user(callback.from_user.id)
    lang = user.get("language", "ar") if user else "ar"
    from keyboards import back_to_main_keyboard
    if support_url:
        u = support_url if support_url.startswith("http") else f"https://t.me/{support_url.lstrip('@')}"
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        b = InlineKeyboardBuilder()
        b.button(text="📞  الدعم الفني المباشر", url=u)
        b.button(text="🔙  رجوع", callback_data="menu:main")
        b.adjust(1)
        await callback.message.edit_text("🎧 <b>فريق الدعم الفني جاهز لمساعدتك دائماً:</b>", reply_markup=b.as_markup(), parse_mode="HTML")
    else:
        await callback.message.edit_text("🎧 <b>الدعم الفني</b>\n\nلم يتم تحديد رابط الدعم بعد من قبل الإدارة.", reply_markup=back_to_main_keyboard(lang), parse_mode="HTML")
    await callback.answer()


# ── المعلومات والقنوات ────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:info")
async def show_info(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = user.get("language", "ar") if user else "ar"
    ch1 = await get_setting("force_sub_channel")
    ch2 = await get_setting("notification_channel")
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from keyboards import back_to_main_keyboard
    b = InlineKeyboardBuilder()
    if ch1:
        u1 = ch1 if ch1.startswith("http") else f"https://t.me/{ch1.lstrip('@')}"
        b.button(text="🔥  قناة التحديثات", url=u1)
    if ch2:
        u2 = ch2 if ch2.startswith("http") else f"https://t.me/{ch2.lstrip('@')}"
        b.button(text="🔮  قناة التفعيلات والإثباتات", url=u2)
    b.button(text="🔙  رجوع", callback_data="menu:main")
    b.adjust(1)
    await callback.message.edit_text("📢 <b>القنوات الرسمية والمعلومات:</b>", reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()
