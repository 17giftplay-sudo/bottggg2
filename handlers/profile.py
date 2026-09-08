import json
import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import get_user, get_setting, get_pool
from translations import t
from keyboards import back_to_main_keyboard, info_buttons_keyboard

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data == "menu:profile")
async def show_profile(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    lang = user.get("language", "ar")

    raw_date = user.get("joined_at")
    if raw_date:
        try:
            if isinstance(raw_date, datetime):
                joined_at = raw_date.strftime("%Y-%m-%d")
            else:
                joined_at = str(raw_date)[:10]
        except Exception:
            joined_at = str(raw_date)
    else:
        joined_at = "—"

    builder = InlineKeyboardBuilder()
    builder.button(text=t(lang, "btn_history"), callback_data="menu:history")
    builder.button(text=t(lang, "btn_back"),    callback_data="menu:main")
    builder.adjust(1)

    await callback.message.edit_text(
        t(
            lang,
            "profile_menu",
            user_id=user["user_id"],
            balance=float(user.get("balance", 0.0) or 0.0),
            points=int(float(user.get("points", 0) or 0)),
            purchases=user.get("purchases", user.get("accounts_purchased", 0)),
            total_deposited=float(user.get("total_deposited", 0.0) or 0.0),
            joined_at=joined_at,
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "menu:history")
async def show_history(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    lang    = user.get("language", "ar")
    user_id = callback.from_user.id

    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            rows = await db.fetch(
                """
                SELECT ai.country_name, ai.price, ai.sold_at,
                       COALESCE(c.flag_emoji, '🌍') AS flag_emoji
                FROM accounts_inventory ai
                LEFT JOIN country_prices c ON c.country_code = ai.country_code
                WHERE ai.sold_to_user_id = $1
                  AND ai.status = 'sold'
                ORDER BY ai.sold_at DESC
                LIMIT 15
                """,
                user_id,
            )
    except Exception as e:
        logger.error("History query error for user %s: %s", user_id, e)
        rows = []

    if not rows:
        await callback.message.edit_text(
            t(lang, "history_empty"),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    items = ""
    for i, row in enumerate(rows, start=1):
        try:
            sold_at = row["sold_at"]
            if isinstance(sold_at, datetime):
                date_str = sold_at.strftime("%Y-%m-%d")
            else:
                date_str = str(sold_at)[:10] if sold_at else "—"
        except Exception:
            date_str = "—"

        items += t(
            lang,
            "history_item",
            num=i,
            flag=row["flag_emoji"] or "🌍",
            country=row["country_name"],
            price=float(row["price"]),
            date=date_str,
        )

    builder = InlineKeyboardBuilder()
    builder.button(text=t(lang, "btn_back"), callback_data="menu:profile")
    builder.adjust(1)

    await callback.message.edit_text(
        t(lang, "history_menu", items=items),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "menu:support")
async def show_support(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    lang = user.get("language", "en")

    url = await get_setting("support_url") or ""
    if not url:
        await callback.answer(t(lang, "settings_not_configured"), show_alert=True)
        return

    label = "🎧 الدعم الفني" if lang == "ar" else "🎧 Support"
    title = "🎧 <b>الدعم الفني</b>\n\nاضغط الزر أدناه للتواصل مع الدعم." if lang == "ar" \
        else "🎧 <b>Support</b>\n\nClick the button below to contact support."

    builder = InlineKeyboardBuilder()
    builder.button(text=label, url=url)
    builder.button(text=t(lang, "btn_back"), callback_data="menu:main")
    builder.adjust(1)

    await callback.message.edit_text(
        title,
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "menu:sell")
async def show_sell(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    lang = user.get("language", "en")

    url = await get_setting("sell_accounts_url") or ""
    if not url:
        await callback.answer(t(lang, "settings_not_configured"), show_alert=True)
        return

    title = "💼 <b>بيع حساباتك</b>\n\nاضغط الزر أدناه لبيع حساباتك." if lang == "ar" \
        else "💼 <b>Sell Accounts</b>\n\nClick the button below to sell your accounts."

    builder = InlineKeyboardBuilder()
    builder.button(text=t(lang, "btn_sell"), url=url)
    builder.button(text=t(lang, "btn_back"), callback_data="menu:main")
    builder.adjust(1)

    await callback.message.edit_text(
        title,
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "menu:info")
async def show_info(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    lang = user.get("language", "en")

    info_str = await get_setting("info_buttons") or "[]"
    try:
        info_buttons = json.loads(info_str)
        if not isinstance(info_buttons, list):
            info_buttons = []
    except (json.JSONDecodeError, TypeError):
        info_buttons = []

    title = "📌 <b>معلومات</b>\n\nروابط وقنوات مفيدة:" if lang == "ar" \
        else "📌 <b>Information</b>\n\nUseful links and channels:"

    await callback.message.edit_text(
        title,
        reply_markup=info_buttons_keyboard(lang, info_buttons),
        parse_mode="HTML",
    )
    await callback.answer()
