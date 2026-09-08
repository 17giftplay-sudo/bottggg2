import asyncio
import logging
import uuid

from aiogram import Router, F, Bot
from aiogram.types import (
    CallbackQuery, Message, PreCheckoutQuery, LabeledPrice
)
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime, timezone

from states import TopUpState, BinanceManualState
from database import get_user, get_setting, create_payment, confirm_payment, create_manual_payment, is_stars_banned, log_stars_refund, is_tx_id_already_used
from translations import t
from keyboards import topup_keyboard, back_to_topup_keyboard, binance_manual_info_keyboard
from payments.oxapay import create_invoice as oxa_create_invoice
from payments.binance_pay import verify_transfer as binance_verify_transfer, VERIFY_OK, VERIFY_API_ERROR, VERIFY_NOT_FOUND, VERIFY_WRONG_CURRENCY, VERIFY_AMOUNT_TOO_LOW

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data == "menu:topup")
async def show_topup_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    lang = user.get("language", "en")
    min_usd = float(await get_setting("min_deposit_usd") or "1.0")
    await callback.message.edit_text(
        t(lang, "topup_menu", min_usd=min_usd),
        reply_markup=topup_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "topup:other")
async def topup_other_methods(callback: CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = user.get("language", "en") if user else "en"
    url  = await get_setting("topup_other_url") or ""
    if not url:
        await callback.answer("⚠️ This method is not available yet. Contact support.", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="🔗 Open", url=url)
    builder.button(text=t(lang, "btn_back"), callback_data="menu:topup")
    builder.adjust(1)
    await callback.message.edit_text(
        t(lang, "btn_other_methods"),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


# ── نجوم تيليجرام ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "topup:stars")
async def topup_stars_start(callback: CallbackQuery, state: FSMContext):
    user       = await get_user(callback.from_user.id)
    lang       = user.get("language", "en") if user else "en"
    min_stars  = int(await get_setting("min_deposit_stars") or "100")
    stars_rate = float(await get_setting("stars_rate") or "0.011")
    await state.set_state(TopUpState.waiting_for_stars_amount)
    await callback.message.edit_text(
        t(lang, "topup_stars_enter_amount", min_stars=min_stars, stars_rate=stars_rate),
        reply_markup=back_to_topup_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(TopUpState.waiting_for_stars_amount)
async def topup_stars_receive_amount(message: Message, state: FSMContext, bot: Bot):
    user = await get_user(message.from_user.id)
    if not user:
        return
    lang      = user.get("language", "en")
    min_stars = int(await get_setting("min_deposit_stars") or "100")
    try:
        stars = int(message.text.strip())
        if stars < min_stars:
            raise ValueError
    except ValueError:
        await message.answer(
            t(lang, "topup_stars_invalid", min_stars=min_stars),
            reply_markup=back_to_topup_keyboard(lang),
            parse_mode="HTML",
        )
        return

    stars_rate = float(await get_setting("stars_rate") or "0.011")
    usd        = round(stars * stars_rate, 4)
    await state.clear()

    # ── فحص تقييم الحساب ومستواه قبل إصدار الفاتورة ────────
    try:
        from utils.stars_rating_checker import check_user_stars_rating
        is_blocked, reason = await asyncio.wait_for(
            check_user_stars_rating(message.from_user.id), timeout=5.0
        )
        if is_blocked:
            support_url = await get_setting("support_url") or ""
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            builder = InlineKeyboardBuilder()
            if support_url:
                builder.button(text="💬 تواصل مع الدعم الفني", url=support_url)
            builder.button(text=t(lang, "btn_back"), callback_data="menu:topup")
            builder.adjust(1)

            if lang == "ar":
                blocked_text = (
                    "⚠️ <b>عذراً، الشحن عبر نجوم تيليجرام غير متاح لهذا الحساب.</b>\n\n"
                    "نظام الأمان يتطلب حداً أدنى لتقييم الحساب (<b>مستوى 1 أو أعلى 🌟</b>) للشحن المباشر بالنجوم، وذلك لحماية المتجر من الحسابات المشبوهة أو التي تسبب استرداد النجوم.\n\n"
                    "💡 <b>ماذا يمكنك أن تفعل؟</b>\n"
                    "1️⃣ يمكنك الشحن عبر <b>طرق الدفع الأخرى</b> المتاحة في البوت.\n"
                    "2️⃣ إذا كنت تعتقد أن هناك خطأ، يرجى <b>التواصل مع الدعم الفني</b> لمراجعة حسابك وتفعيله يدوياً."
                )
            else:
                blocked_text = (
                    "⚠️ <b>Sorry, Stars deposit is not available for this account.</b>\n\n"
                    "Security policy requires a Telegram account level of <b>Level 1 or higher 🌟</b> for new Stars deposits.\n\n"
                    "💡 <b>Options:</b>\n"
                    "1️⃣ Please use other payment methods available in the bot.\n"
                    "2️⃣ Contact support to review and verify your account manually."
                )
            await message.answer(blocked_text, reply_markup=builder.as_markup(), parse_mode="HTML")
            return
    except Exception as _e:
        logger.warning("topup_stars_entered rating check failed for %s: %s", message.from_user.id, _e)

    await bot.send_invoice(
        chat_id=message.chat.id,
        title=t(lang, "topup_stars_invoice_title"),
        description=t(lang, "topup_stars_invoice_desc", stars=stars, usd=usd),
        payload=f"stars:{message.from_user.id}:{stars}",
        currency="XTR",
        prices=[LabeledPrice(label=t(lang, "topup_stars_label"), amount=stars)],
    )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    payload = query.invoice_payload

    if not payload.startswith("stars:"):
        logger.warning(
            "pre_checkout: rejected unknown payload format from user=%s payload='%s'",
            query.from_user.id, payload,
        )
        await query.answer(ok=False, error_message="Invalid payment request.")
        return

    try:
        _, user_id_str, stars_str = payload.split(":", 2)
        uid   = int(user_id_str)
        stars = int(stars_str)
    except (ValueError, TypeError):
        logger.warning("pre_checkout: malformed payload '%s'", payload)
        await query.answer(ok=False, error_message="Invalid payment data.")
        return

    if uid != query.from_user.id:
        logger.warning(
            "pre_checkout: payload uid=%s != sender uid=%s — rejecting",
            uid, query.from_user.id,
        )
        await query.answer(ok=False, error_message="Payment identity mismatch.")
        return

    if stars <= 0:
        await query.answer(ok=False, error_message="Invalid stars amount.")
        return

    user = await get_user(uid)
    if not user:
        logger.warning("pre_checkout: user %s not found in DB — rejecting", uid)
        await query.answer(ok=False, error_message="User not found. Please restart the bot.")
        return

    # ── فحص تقييم النجوم عند الدفع ────────
    try:
        from utils.stars_rating_checker import check_user_stars_rating
        is_blocked, reason = await asyncio.wait_for(
            check_user_stars_rating(uid), timeout=5.0
        )
        if is_blocked:
            logger.warning(
                "pre_checkout: user %s محظور من شحن النجوم — السبب: %s", uid, reason
            )
            error_msg = "الشحن بالنجوم غير متاح لحسابك (يتطلب مستوى 1+). يرجى التواصل مع الدعم أو تجربة وسيلة دفع أخرى."
            await query.answer(ok=False, error_message=error_msg)
            return
    except asyncio.TimeoutError:
        logger.warning("pre_checkout: timeout فحص التقييم لـ %s — نقبل (fail-open)", uid)
    except Exception as _e:
        logger.warning("pre_checkout: خطأ في فحص التقييم لـ %s — %s (نقبل)", uid, _e)

    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_stars_payment(message: Message, bot: Bot):
    if not message.from_user:
        return
    payload = message.successful_payment.invoice_payload
    if not payload.startswith("stars:"):
        return
    try:
        _, user_id_str, stars_str = payload.split(":", 2)
        user_id       = int(user_id_str)
        stars_payload = int(stars_str)
    except (ValueError, TypeError):
        logger.warning("Stars payment: malformed payload '%s'", payload)
        return

    if user_id != message.from_user.id:
        logger.warning(
            "Stars payment mismatch: payload uid=%s but sender uid=%s — ignoring",
            user_id, message.from_user.id,
        )
        return

    actual_stars = message.successful_payment.total_amount
    if actual_stars != stars_payload:
        logger.warning(
            "Stars amount mismatch: payload=%d actual_paid=%d for user=%s — using actual",
            stars_payload, actual_stars, user_id,
        )
    stars = actual_stars

    stars_rate = float(await get_setting("stars_rate") or "0.011")
    usd_amount = round(stars * stars_rate, 4)

    order_id = f"STARS-{user_id}-{uuid.uuid4().hex[:8].upper()}"
    await create_payment(order_id, user_id, "Telegram Stars", usd_amount, str(stars))
    await confirm_payment(order_id)

    user = await get_user(user_id)
    lang = user.get("language", "en") if user else "en"

    await message.answer(
        t(lang, "topup_stars_confirmed", stars=stars, amount=usd_amount),
        parse_mode="HTML",
    )

    try:
        from config import ADMIN_IDS
        from database import get_sub_admins_with_perm

        now_str     = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
        uname       = f"@{message.from_user.username}" if message.from_user.username else "—"
        notif_text  = (
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "⭐  <b>إيداع بالنجوم</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤  <b>المستخدم :</b>  <a href='tg://user?id={user_id}'>{message.from_user.full_name}</a>\n"
            f"🆔  <b>الآيدي :</b>  <code>{user_id}</code>\n"
            f"🔗  <b>يوزر :</b>  {uname}\n"
            f"⭐  <b>النجوم :</b>  {stars}\n"
            f"💵  <b>المبلغ :</b>  ${usd_amount:.4f}\n"
            f"🟢  <b>الحالة :</b>  مؤكّد تلقائياً\n\n"
            f"🗓  <b>التاريخ :</b>  {now_str}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━"
        )

        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, notif_text, parse_mode="HTML")
            except Exception:
                pass

        try:
            sub_admins = await get_sub_admins_with_perm("deposits")
            for sa in sub_admins:
                try:
                    await bot.send_message(sa["user_id"], notif_text, parse_mode="HTML")
                except Exception:
                    pass
        except Exception:
            pass

    except Exception as e:
        logger.warning("Could not send Stars deposit notification: %s", e)


# ── OxaPay ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "topup:oxapay")
async def topup_oxapay_start(callback: CallbackQuery, state: FSMContext):
    user    = await get_user(callback.from_user.id)
    lang    = user.get("language", "en") if user else "en"
    min_usd = float(await get_setting("min_deposit_usd") or "1.0")

    await state.update_data(provider="OxaPay")
    await state.set_state(TopUpState.waiting_for_amount)
    await callback.message.edit_text(
        t(lang, "topup_enter_amount", provider="OxaPay", min_usd=min_usd),
        reply_markup=back_to_topup_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(TopUpState.waiting_for_amount)
async def topup_oxapay_receive_amount(message: Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if not user:
        return
    lang = user.get("language", "en")

    try:
        amount = float(message.text.strip().replace(",", "."))
        if amount <= 0:
            raise ValueError
    except Exception:
        await message.answer(
            t(lang, "topup_amount_invalid"),
            reply_markup=back_to_topup_keyboard(lang),
        )
        return

    min_usd = float(await get_setting("min_deposit_usd") or "1.0")
    if amount < min_usd:
        await message.answer(
            t(lang, "topup_amount_too_low", min_usd=min_usd),
            reply_markup=back_to_topup_keyboard(lang),
        )
        return

    await state.clear()

    order_id = f"OXA-{message.from_user.id}-{uuid.uuid4().hex[:8].upper()}"
    res = await oxa_create_invoice(amount_usd=amount, order_id=order_id)

    if not res:
        logger.error("OxaPay returned no response for order %s", order_id)
        await message.answer(
            t(lang, "topup_payment_failed"),
            reply_markup=back_to_topup_keyboard(lang),
        )
        return

    pay_url      = res.get("payLink") or res.get("payUrl") or res.get("url")
    provider_ref = res.get("trackId")

    if not pay_url:
        logger.error("OxaPay returned no payment URL. Response: %s", res)
        await message.answer(
            t(lang, "topup_payment_failed"),
            reply_markup=back_to_topup_keyboard(lang),
        )
        return

    await create_payment(order_id, message.from_user.id, "OxaPay", amount, provider_ref)

    builder = InlineKeyboardBuilder()
    builder.button(text=t(lang, "btn_pay_now"), url=pay_url)
    builder.button(text=t(lang, "btn_back"),    callback_data="menu:main")
    builder.adjust(1)

    await message.answer(
        t(lang, "topup_payment_created", amount=amount, provider="OxaPay"),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


# ── Binance Manual — التدفق الجديد: المبلغ أولاً ثم يظهر الـ ID ──────────────
#
# التدفق القديم: يظهر ID المحفظة ← يضغط "دفعت" ← يدخل المبلغ ← يدخل الهاش
# التدفق الجديد: يدخل المبلغ ← يظهر ID المحفظة ← يضغط "دفعت" ← يدخل الهاش
#
# الفائدة: المستخدم يعرف كم سيرسل قبل ما يشوف عنوان المحفظة، وهذا يقلل
# الأخطاء ويجعل التجربة أوضح.

@router.callback_query(F.data == "topup:binance_manual")
async def topup_binance_manual_start(callback: CallbackQuery, state: FSMContext):
    user    = await get_user(callback.from_user.id)
    lang    = user.get("language", "ar") if user else "ar"
    uid     = await get_setting("binance_pay_uid") or ""
    if not uid:
        await callback.answer(
            "⚠️ هذه الطريقة غير متاحة حالياً، تواصل مع الدعم." if lang == "ar"
            else "⚠️ This method is not available yet. Contact support.",
            show_alert=True,
        )
        return

    min_usd = float(await get_setting("min_deposit_usd") or "1.0")
    await state.set_state(BinanceManualState.waiting_for_amount)
    await callback.message.edit_text(
        t(lang, "topup_binance_ask_amount", min_usd=min_usd),
        reply_markup=back_to_topup_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(BinanceManualState.waiting_for_amount)
async def binance_manual_receive_amount(message: Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if not user:
        return
    lang = user.get("language", "ar")

    try:
        amount = float(message.text.strip().replace(",", "."))
        if amount <= 0:
            raise ValueError
    except Exception:
        await message.answer(
            t(lang, "topup_amount_invalid"),
            reply_markup=back_to_topup_keyboard(lang),
        )
        return

    min_usd = float(await get_setting("min_deposit_usd") or "1.0")
    if amount < min_usd:
        await message.answer(
            t(lang, "topup_amount_too_low", min_usd=min_usd),
            reply_markup=back_to_topup_keyboard(lang),
        )
        return

    uid = await get_setting("binance_pay_uid") or ""
    if not uid:
        await message.answer(
            "⚠️ هذه الطريقة غير متاحة حالياً." if lang == "ar"
            else "⚠️ This method is not available.",
            reply_markup=back_to_topup_keyboard(lang),
        )
        return

    await state.update_data(binance_amount=amount)
    await state.set_state(BinanceManualState.waiting_for_paid_confirmation)

    await message.answer(
        t(lang, "topup_binance_info", uid=uid, amount=amount),
        reply_markup=binance_manual_info_keyboard(lang),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "binance_manual:paid")
async def binance_manual_paid_click(callback: CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    lang = user.get("language", "ar") if user else "ar"

    await state.set_state(BinanceManualState.waiting_for_hash)
    await callback.message.edit_text(
        t(lang, "topup_binance_enter_hash"),
        reply_markup=back_to_topup_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(BinanceManualState.waiting_for_hash)
async def binance_manual_receive_hash(message: Message, state: FSMContext, bot: Bot):
    user = await get_user(message.from_user.id)
    if not user:
        return
    lang = user.get("language", "ar")

    tx_id = message.text.strip()

    # ── فحص 1: صيغة الـ tx_id (أرقام وحروف فقط، 8-128 حرف) ─────────────
    import re as _re
    if not _re.fullmatch(r"[A-Za-z0-9\-_]{8,128}", tx_id):
        await message.answer(
            "❌ معرّف الطلب غير صحيح.\nيجب أن يكون أرقاماً أو حروفاً (8-128 خانة).\nمثال: <code>446615649192435712</code>" if lang == "ar"
            else "❌ Invalid Order ID.\nMust be 8-128 alphanumeric characters.\nExample: <code>446615649192435712</code>",
            reply_markup=back_to_topup_keyboard(lang),
        )
        return

    # ── فحص 2: هل الـ tx_id استُخدم من قبل؟ (منع الشحن المزدوج) ────────
    if await is_tx_id_already_used(tx_id):
        await message.answer(
            "❌ هذا المعرّف استُخدم مسبقاً ولا يمكن إعادة استخدامه.\nإذا كان لديك مشكلة تواصل مع الدعم." if lang == "ar"
            else "❌ This transaction ID has already been used.\nContact support if you believe this is an error.",
            reply_markup=back_to_topup_keyboard(lang),
        )
        return

    data   = await state.get_data()
    amount = float(data.get("binance_amount", 0))

    # ── فحص 3: المبلغ من الـ state (منع انتهاء الجلسة بمبلغ صفر) ────────
    if amount <= 0:
        await state.clear()
        await message.answer(
            "⚠️ انتهت صلاحية جلستك، ابدأ من جديد." if lang == "ar"
            else "⚠️ Your session expired, please start over.",
            reply_markup=back_to_topup_keyboard(lang),
        )
        return

    await state.clear()

    # ── إشعار المستخدم بأن التحقق جارٍ ──────────────────────────────────────
    verifying_msg = await message.answer(
        "🔄 <b>جاري التحقق من المعاملة...</b>\n<i>انتظر لحظة</i>" if lang == "ar"
        else "🔄 <b>Verifying transaction...</b>\n<i>Please wait</i>",
        parse_mode="HTML",
    )

    # ── التحقق التلقائي عبر Binance API ─────────────────────────────────────
    verify_result, actual_amount = await binance_verify_transfer(tx_id)

    try:
        await verifying_msg.delete()
    except Exception:
        pass

    if verify_result == VERIFY_OK:
        # ── ✅ تأكيد الدفع وشحن الرصيد — نستخدم المبلغ الفعلي من Binance ──
        # إذا كتب المستخدم مبلغاً أكبر مما أرسل، نشحن الفعلي فقط
        credited    = round(actual_amount, 4)
        order_id    = f"BNB-{message.from_user.id}-{uuid.uuid4().hex[:8].upper()}"
        await create_payment(order_id, message.from_user.id, "Binance Pay", credited, tx_id)
        payment     = await confirm_payment(order_id)
        user_fresh  = await get_user(message.from_user.id)
        new_balance = float(user_fresh.get("balance", 0)) if user_fresh else credited

        # إذا كان المبلغ الفعلي أقل مما طلبه المستخدم — أخبره
        if credited < amount - 0.01:
            note_ar = f"\n\n⚠️ <i>لاحظنا أن المبلغ المُحوَّل فعلياً هو <b>${credited:.2f}</b> وليس <b>${amount:.2f}</b> — تم شحن المبلغ الفعلي فقط.</i>"
            note_en = f"\n\n⚠️ <i>We noticed the actual transferred amount was <b>${credited:.2f}</b>, not <b>${amount:.2f}</b> — only the actual amount was credited.</i>"
        else:
            note_ar = note_en = ""

        await message.answer(
            t(lang, "topup_binance_approved", amount=credited, new_balance=new_balance)
            + (note_ar if lang == "ar" else note_en),
            parse_mode="HTML",
        )

        # إشعار الأدمن بالشحن الناجح
        try:
            from config import ADMIN_IDS
            from database import get_sub_admins_with_perm
            from datetime import datetime, timezone

            now_str = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
            uname   = f"@{message.from_user.username}" if message.from_user.username else "—"
            claimed_note = f"\n⚠️  المبلغ المُدخَل: <b>${amount:.2f}</b> (تم شحن الفعلي فقط)" if credited < amount - 0.01 else ""
            notif   = (
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "✅  <b>إيداع Binance — تأكيد تلقائي</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👤  المستخدم: <a href='tg://user?id={message.from_user.id}'>{message.from_user.full_name}</a>\n"
                f"🆔  الآيدي: <code>{message.from_user.id}</code>\n"
                f"🔗  يوزر: {uname}\n"
                f"💵  المبلغ الفعلي: <b>${credited:.2f}</b>{claimed_note}\n"
                f"🔑  Transaction ID: <code>{tx_id}</code>\n"
                f"💰  الرصيد الجديد: <b>${new_balance:.2f}</b>\n"
                f"🟢  الحالة: <b>مؤكّد تلقائياً ✅</b>\n\n"
                f"🗓  التاريخ: {now_str}\n\n"
                "━━━━━━━━━━━━━━━━━━━━━"
            )
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(admin_id, notif, parse_mode="HTML")
                except Exception:
                    pass
            sub_admins = await get_sub_admins_with_perm("deposits")
            for sa in sub_admins:
                try:
                    await bot.send_message(sa["user_id"], notif, parse_mode="HTML")
                except Exception:
                    pass
        except Exception as e:
            logger.warning("Binance auto-confirm admin notify error: %s", e)

    elif verify_result == VERIFY_API_ERROR:
        # ── ⚠️ API فشل — أرسل للأدمن للمراجعة اليدوية ────────────────────
        try:
            payment_id = await create_manual_payment(message.from_user.id, amount, tx_id)

            await message.answer(
                (
                    "⏳ <b>طلبك قيد المراجعة</b>\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💵  المبلغ: <b>${amount:.2f}</b>\n"
                    f"🔑  Transaction ID: <code>{tx_id}</code>\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n\n"
                    "سيتم مراجعة طلبك من قِبل الأدمن وإضافة الرصيد خلال دقائق."
                ) if lang == "ar" else (
                    "⏳ <b>Your request is under review</b>\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💵  Amount: <b>${amount:.2f}</b>\n"
                    f"🔑  Transaction ID: <code>{tx_id}</code>\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n\n"
                    "An admin will review your request and add the balance within minutes."
                ),
                parse_mode="HTML",
            )

            # إشعار الأدمن لمراجعة الطلب يدوياً
            from config import ADMIN_IDS
            from database import get_sub_admins_with_perm
            from datetime import datetime, timezone
            from keyboards import admin_binance_review_keyboard

            now_str = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
            uname   = f"@{message.from_user.username}" if message.from_user.username else "—"
            review_text = (
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "🟡  <b>طلب إيداع Binance — مراجعة يدوية</b>\n"
                "⚠️  <i>التحقق التلقائي لم يتمكن من الوصول للـ API</i>\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👤  المستخدم: <a href='tg://user?id={message.from_user.id}'>{message.from_user.full_name}</a>\n"
                f"🆔  الآيدي: <code>{message.from_user.id}</code>\n"
                f"🔗  يوزر: {uname}\n"
                f"💵  المبلغ المُرسَل: <b>${amount:.2f} USDT</b>\n"
                f"🔑  Transaction ID: <code>{tx_id}</code>\n\n"
                f"🗓  التاريخ: {now_str}\n\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "تحقق من المعاملة في تطبيق Binance ثم اضغط موافقة أو رفض."
            )
            kb = admin_binance_review_keyboard(payment_id, message.from_user.id)
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(admin_id, review_text, parse_mode="HTML", reply_markup=kb)
                except Exception:
                    pass
            try:
                sub_admins = await get_sub_admins_with_perm("deposits")
                for sa in sub_admins:
                    try:
                        await bot.send_message(sa["user_id"], review_text, parse_mode="HTML", reply_markup=kb)
                    except Exception:
                        pass
            except Exception:
                pass

        except Exception as e:
            logger.error("Binance VERIFY_API_ERROR fallback failed: %s", e)
            await message.answer(
                "⚠️ حدث خطأ، تواصل مع الدعم وأرسل Transaction ID الخاص بك." if lang == "ar"
                else "⚠️ An error occurred. Please contact support with your Transaction ID.",
                reply_markup=back_to_topup_keyboard(lang),
            )

    elif verify_result == VERIFY_WRONG_CURRENCY:
        # ── ❌ عملة غير USDT ───────────────────────────────────────────────
        await message.answer(
            (
                "❌ <b>عملة غير مقبولة</b>\n\n"
                "نحن نقبل فقط <b>USDT</b>.\n"
                "تأكد أنك أرسلت USDT وليس BNB أو أي عملة أخرى."
            ) if lang == "ar" else (
                "❌ <b>Currency not accepted</b>\n\n"
                "We only accept <b>USDT</b>.\n"
                "Please make sure you sent USDT, not BNB or any other currency."
            ),
            reply_markup=back_to_topup_keyboard(lang),
            parse_mode="HTML",
        )

    elif verify_result == VERIFY_AMOUNT_TOO_LOW:
        # ── ❌ مبلغ أقل من الحد الأدنى ────────────────────────────────────
        from config import MIN_DEPOSIT_USD
        await message.answer(
            (
                f"❌ <b>المبلغ أقل من الحد الأدنى</b>\n\n"
                f"المبلغ المُحوَّل: <b>${actual_amount:.2f} USDT</b>\n"
                f"الحد الأدنى للإيداع: <b>${MIN_DEPOSIT_USD:.2f} USDT</b>\n\n"
                "يرجى إيداع مبلغ أعلى من الحد الأدنى."
            ) if lang == "ar" else (
                f"❌ <b>Amount below minimum</b>\n\n"
                f"Transferred amount: <b>${actual_amount:.2f} USDT</b>\n"
                f"Minimum deposit: <b>${MIN_DEPOSIT_USD:.2f} USDT</b>\n\n"
                "Please deposit an amount above the minimum."
            ),
            reply_markup=back_to_topup_keyboard(lang),
            parse_mode="HTML",
        )

    else:
        # ── ❌ VERIFY_NOT_FOUND — الـ tx_id غير موجود ─────────────────────
        await message.answer(
            (
                "❌ <b>لم يتم التحقق من المعاملة</b>\n\n"
                "الأسباب المحتملة:\n"
                "• معرّف المعاملة (Transaction ID) غير صحيح\n"
                "• لم تكتمل المعاملة بعد — انتظر دقيقة وأعد المحاولة\n\n"
                "💡 تأكد أنك تُدخل <b>Transaction ID</b> وليس رقم الطلب (Order ID).\n\n"
                "تواصل مع الدعم إذا تأكدت من صحة المعاملة."
            ) if lang == "ar" else (
                "❌ <b>Transaction could not be verified</b>\n\n"
                "Possible reasons:\n"
                "• Incorrect Transaction ID\n"
                "• Transaction not yet complete — wait a moment and retry\n\n"
                "💡 Make sure you enter the <b>Transaction ID</b>, not the Order ID.\n\n"
                "Contact support if you are sure the transaction is correct."
            ),
            reply_markup=back_to_topup_keyboard(lang),
            parse_mode="HTML",
        )


# ── استرداد نجوم (Refund) ─────────────────────────────────────────────────────
@router.message(F.refunded_payment)
async def handle_refunded_stars_payment(message: Message, bot: Bot):
    """
    تيليجرام يرسل هذا الحدث عندما يستردّ نجوماً دفعها مستخدم للبوت.
    نقوم تلقائياً بـ:
      1. تسجيل الاسترداد في قاعدة البيانات (blacklist).
      2. خصم المبلغ المسترد من رصيد المستخدم.
      3. إشعار الأدمن.
    """
    if not message.from_user:
        return

    rp        = message.refunded_payment
    user_id   = message.from_user.id
    stars     = rp.total_amount
    payload   = rp.invoice_payload or ""

    stars_rate = float(await get_setting("stars_rate") or "0.011")
    usd_amount = round(stars * stars_rate, 4)

    order_id = payload if payload.startswith("stars:") else None

    # 1) أضف للقائمة السوداء
    await log_stars_refund(user_id, stars, usd_amount, order_id)

    # 2) خصم الرصيد
    try:
        from database import get_pool
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute(
                """
                UPDATE users
                SET balance = GREATEST(0, balance - $1)
                WHERE user_id = $2
                """,
                usd_amount, user_id,
            )
    except Exception as e:
        logger.error("handle_refunded_payment: خطأ في خصم الرصيد لـ %s: %s", user_id, e)

    logger.warning(
        "REFUND: user=%s stars=%d usd=%.4f payload='%s'",
        user_id, stars, usd_amount, payload,
    )

    # 3) إشعار الأدمن
    try:
        from config import ADMIN_IDS
        from database import get_sub_admins_with_perm

        uname   = f"@{message.from_user.username}" if message.from_user.username else "—"
        now_str = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
        notif_text = (
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🔴  <b>استرداد نجوم (REFUND)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤  المستخدم: <a href='tg://user?id={user_id}'>{message.from_user.full_name}</a>\n"
            f"🆔  الآيدي: <code>{user_id}</code>\n"
            f"🔗  يوزر: {uname}\n"
            f"⭐  النجوم المستردة: <b>{stars}</b>\n"
            f"💵  المبلغ المخصوم: <b>${usd_amount:.4f}</b>\n"
            "🚫  الحالة: <b>مُضاف للقائمة السوداء تلقائياً</b>\n\n"
            f"🗓  التاريخ: {now_str}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━"
        )

        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, notif_text, parse_mode="HTML")
            except Exception:
                pass

        try:
            sub_admins = await get_sub_admins_with_perm("deposits")
            for sa in sub_admins:
                try:
                    await bot.send_message(sa["user_id"], notif_text, parse_mode="HTML")
                except Exception:
                    pass
        except Exception:
            pass
    except Exception as e:
        logger.error("handle_refunded_payment: خطأ في إشعار الأدمن: %s", e)
