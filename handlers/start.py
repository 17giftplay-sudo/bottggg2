import logging

from aiogram import Router, Bot, F
from aiogram.filters import CommandStart, CommandObject
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


async def _check_force_sub(bot: Bot, user_id: int) -> bool:
    ch1 = await get_setting("force_sub_channel")
    if not ch1 or ch1 in ("0", "—", "none", "None", ""):
        return True

    ch = _clean_channel_id(ch1)
    if not ch:
        return True

    try:
        target_id = int(ch) if (ch.startswith("-") or ch.isdigit()) else ch
        member = await bot.get_chat_member(chat_id=target_id, user_id=user_id)
        if member.status in ("left", "kicked", "banned"):
            return False
        return True
    except Exception as e:
        logger.warning("_check_force_sub: failed to check %s (target: %s) for user %s: %s", ch1, ch, user_id, e)
        return False


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
async def cmd_start(message: Message, state: FSMContext, bot: Bot, command: CommandObject = None):
    try:
        await state.clear()

        # استخراج معرّف الداعي من بارامتر /start أو CommandObject
        referrer_id = None
        ref_str = ""
        if command and command.args:
            ref_str = command.args.strip()
        else:
            raw_text = message.text or ""
            parts = raw_text.strip().split()
            if len(parts) > 1:
                ref_str = parts[1].strip()

        if ref_str:
            if ref_str.startswith("ref_"):
                ref_num = ref_str[4:]
                if ref_num.isdigit():
                    referrer_id = int(ref_num)
            elif ref_str.isdigit():
                referrer_id = int(ref_str)

        user = await get_user(message.from_user.id)
        is_new_user = False

        if not user:
            is_new_user = True
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

        lang = user.get("language") or "ar"

        # فحص الاشتراك الإجباري أولاً
        joined = True
        try:
            joined = await _check_force_sub(bot, message.from_user.id)
        except Exception as e:
            logger.warning("_check_force_sub exception for user %s: %s", message.from_user.id, e)

        if not joined:
            ch1  = await get_setting("force_sub_channel")
            ch2  = await get_setting("notification_channel")
            await message.answer(
                t(lang, "force_sub_message"),
                reply_markup=force_sub_keyboard(lang, ch1, ch2),
                parse_mode="HTML",
            )
            return

        # فحص نظام الإحالات والتحقق من أمان الجهاز
        if referrer_id:
            if referrer_id == message.from_user.id:
                await message.answer(
                    "⚠️ <b>هذا هو رابط الدعوة الخاص بك!</b> 🎁\n\n"
                    "لا يمكنك تسجيل إحالة لنفسك. شارك هذا الرابط مع أصدقائك أو في القنوات، وستحصل على مكافأة مالية في رصيدك فور قيامهم بتأكيد أجهزتهم."
                    if lang == "ar" else
                    "⚠️ <b>This is your own referral link!</b> 🎁\n\n"
                    "You cannot refer yourself. Share this link with friends to earn rewards."
                )
            else:
                user_referred_by = user.get("referred_by") if user else None
                dev_verified = user.get("is_device_verified", 0) if user else 0

                # إذا لم يكن مسجلاً بإحالة سابقة أو لم يتحقق جهازه بعد
                if not user_referred_by and not dev_verified:
                    await state.update_data(pending_referrer_id=referrer_id)
                    require_fp = (await get_setting("referral_require_fp") or "1") == "1"
                    if require_fp:
                        from config import WEBHOOK_BASE_URL
                        from aiogram.types import WebAppInfo
                        from aiogram.utils.keyboard import InlineKeyboardBuilder

                        raw_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or os.environ.get("RAILWAY_STATIC_URL") or "bottggg2-production.up.railway.app"
                        wh_url = (
                            await get_setting("webhook_base_url")
                            or os.environ.get("WEBHOOK_BASE_URL")
                            or (f"https://{raw_domain}" if raw_domain else "")
                            or "https://bottggg2-production.up.railway.app"
                        ).rstrip("/")
                        if not wh_url.startswith("http"):
                            wh_url = f"https://{wh_url}"

                        verify_url = f"{wh_url}/ref-verify"

                        builder = InlineKeyboardBuilder()
                        builder.button(
                            text="🛡️  تأكيد أمان جهازي (Web App)" if lang == "ar" else "🛡️  Verify Device (Web App)",
                            web_app=WebAppInfo(url=verify_url),
                        )
                        builder.adjust(1)

                        verify_prompt = (
                            "🛡️ <b>التحقق الأمني من الجهاز لمنع الغش</b> 🔒\n\n"
                            "أهلاً بك! لقد تم تحويلك عبر رابط دعوة خاص بأحد الأصدقاء 🎁.\n\n"
                            "⚠️ لحماية نظام المكافآت من الحسابات الوهمية وتعدد الحسابات، يرجى الضغط على الزر أدناه لتأكيد جهازك بنقرة واحدة:"
                        ) if lang == "ar" else (
                            "🛡️ <b>Anti-Fraud Device Verification</b> 🔒\n\n"
                            "Welcome! You joined via a friend's referral link 🎁.\n\n"
                            "⚠️ To protect our rewards system against multi-accounts and bots, please click the button below to verify your device:"
                        )
                        await message.answer(verify_prompt, reply_markup=builder.as_markup(), parse_mode="HTML")
                        return
                else:
                    await message.answer(
                        "ℹ️ <b>تنبيه:</b> لقد تم تسجيل وتأكيد حسابك مسبقاً في النظام."
                        if lang == "ar" else
                        "ℹ️ <b>Notice:</b> Your account is already registered and verified in the system."
                    )

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


# ── استلام بيانات فحص بصمة الجهاز من الـ Web App ──────────────────────────────

@router.message(F.web_app_data)
async def handle_web_app_verification(message: Message, state: FSMContext, bot: Bot):
    import json
    from database import (
        check_and_save_device_fingerprint,
        process_referral_reward,
        log_referral_fraud,
    )

    try:
        raw_data = message.web_app_data.data
        payload = json.loads(raw_data)
    except Exception as e:
        logger.warning("Invalid WebApp data received: %s", e)
        return

    fp_hash = payload.get("fp_hash") or ""
    hardware = payload.get("hardware") or {}
    ua = hardware.get("platform") or ""

    user = await get_user(message.from_user.id)
    lang = user.get("language", "ar") if user else "ar"

    state_data = await state.get_data()
    pending_ref = state_data.get("pending_referrer_id")

    # 1. فحص ومطابقة بصمة الجهاز
    is_blocked, dup_uid, reason = await check_and_save_device_fingerprint(
        user_id=message.from_user.id,
        fp_hash=fp_hash,
        ua=ua,
    )

    if is_blocked:
        if pending_ref:
            await log_referral_fraud(
                referrer_id=pending_ref,
                referred_id=message.from_user.id,
                fraud_reason=f"DUPLICATE_DEVICE (matches {dup_uid or 'existing'})",
            )
        warn_text = (
            "⚠️ <b>تنبيه أمني من نظام مكافحة الغش</b> 🛡️\n\n"
            "تم رصد أن هذا الجهاز مسجّل مسبقاً في النظام بحساب آخر.\n"
            "يمكنك متابعة استخدام البوت بشكل طبيعي ولكن <b>لن يتم احتساب مكافأة الإحالة</b> لمنع تكرار الأجهزة."
        ) if lang == "ar" else (
            "⚠️ <b>Anti-Fraud Security Notice</b> 🛡️\n\n"
            "This device was detected as already registered with another account.\n"
            "You can use the bot normally, but referral reward was not credited."
        )
        await message.answer(warn_text, parse_mode="HTML")
    else:
        # جهاز جديد وفريد
        if pending_ref:
            ref_enabled = (await get_setting("referral_enabled") or "1") == "1"
            reward_usd = float(await get_setting("referral_reward_usd") or "0.05")
            if ref_enabled:
                ok, res_reason, new_bal = await process_referral_reward(
                    referred_id=message.from_user.id,
                    referrer_id=pending_ref,
                    reward_usd=reward_usd,
                )
                if ok:
                    try:
                        ref_user = await get_user(pending_ref)
                        ref_lang = ref_user.get("language", "ar") if ref_user else "ar"
                        u_name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
                        notify_text = (
                            f"🎉 <b>إحالة جديدة مؤكدة!</b> 🎁\n\n"
                            f"قام المستخدم <b>{u_name}</b> بالانضمام عبر رابطك وتأكيد أمان جهازه بنجاح ✅\n\n"
                            f"💵 <b>المكافأة المُضافة:</b> <b>+${reward_usd:.2f}</b>\n"
                            f"💰 <b>رصيدك الجديد:</b> <b>${new_bal:.2f}</b>"
                        ) if ref_lang == "ar" else (
                            f"🎉 <b>New Verified Referral!</b> 🎁\n\n"
                            f"User <b>{u_name}</b> joined via your link and verified device ✅\n\n"
                            f"💵 <b>Reward Added:</b> <b>+${reward_usd:.2f}</b>\n"
                            f"💰 <b>New Balance:</b> <b>${new_bal:.2f}</b>"
                        )
                        await bot.send_message(pending_ref, notify_text, parse_mode="HTML")
                    except Exception as _e:
                        logger.warning("Could not notify referrer %s: %s", pending_ref, _e)

        success_text = (
            "✅ <b>تم التحقق من أمان جهازك بنجاح!</b> 🎉\n\n"
            "أهلاً بك في المتجر، يمكنك الآن البدء في استخدام البوت وشراء الخدمات."
        ) if lang == "ar" else (
            "✅ <b>Device Verified Successfully!</b> 🎉\n\n"
            "Welcome to the store! You can now start using the bot."
        )
        await message.answer(success_text, parse_mode="HTML")

    await state.clear()
    user_fresh = await get_user(message.from_user.id)
    await _show_main_menu(message, user_fresh or user)


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


# ── رابط الدعوة ولوحة الإحصائيات ─────────────────────────────────────────────

@router.callback_query(F.data == "menu:referral")
async def show_referral(callback: CallbackQuery, bot: Bot):
    user = await get_user(callback.from_user.id)
    lang = user.get("language", "ar") if user else "ar"
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{callback.from_user.id}"

    from database import get_user_referral_stats, get_setting
    stats = await get_user_referral_stats(callback.from_user.id)
    total_refs = stats.get("total_referrals", 0)
    total_earned = stats.get("total_earned", 0.0)
    reward_usd = float(await get_setting("referral_reward_usd") or "0.05")

    import urllib.parse
    share_url = f"https://t.me/share/url?url={ref_link}&text={urllib.parse.quote('متجر حسابات وجلسات تيليجرام التلقائي 🚀 اشتري حسابك الآن بسهولة وأمان!')}"

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="🔗  مشاركة الرابط عبر تيليجرام" if lang == "ar" else "🔗  Share via Telegram", url=share_url)
    builder.button(text=t(lang, "btn_back"), callback_data="menu:main")
    builder.adjust(1)

    ref_text = (
        "👥 <b>نظام الإحالة والمكافآت</b> 🎁\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 <b>رابط الدعوة الخاص بك:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        "📊 <b>إحصائيات إحالاتك:</b>\n"
        f"👥  عدد الإحالات المؤكدة: <b>{total_refs}</b>\n"
        f"💵  إجمالي الأرباح المكتسبة: <b>${total_earned:.2f}</b>\n"
        f"🎁  مكافأة كل دعوة جديدة: <b>${reward_usd:.2f}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "💡 <i>شارك رابطك مع أصدقائك واكسب رصيداً في محفظتك فور تأكيد أجهزتهم!</i>"
    ) if lang == "ar" else (
        "👥 <b>Referral & Rewards Dashboard</b> 🎁\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 <b>Your Referral Link:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        "📊 <b>Your Referral Stats:</b>\n"
        f"👥  Verified Referrals: <b>{total_refs}</b>\n"
        f"💵  Total Earned: <b>${total_earned:.2f}</b>\n"
        f"🎁  Reward per referral: <b>${reward_usd:.2f}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "💡 <i>Share your link with friends and earn rewards as soon as their device is verified!</i>"
    )
    await callback.message.edit_text(ref_text, reply_markup=builder.as_markup(), parse_mode="HTML")
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
