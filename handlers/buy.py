import asyncio
import html as html_module
import logging
from datetime import datetime, timezone

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from states import BuyState
from database import get_user, get_countries_with_stock, purchase_account, get_country, get_setting
from config import ADMIN_IDS
from translations import t
from keyboards import countries_keyboard, back_to_main_keyboard, buy_category_keyboard
from utils.session_manager import wait_for_login_code

router = Router()
logger = logging.getLogger(__name__)


async def _sell_enabled(user_id: int = 0) -> bool:
    if user_id and user_id in ADMIN_IDS:
        return True
    val = await get_setting("sell_btn_enabled")
    return (val or "1") == "1"


def _effective_price(country: dict, category: str = "regular") -> float:
    if category == "old":
        raw_price = float(country.get("old_price") or country["price"])
        if raw_price <= 0:
            raw_price = float(country["price"])
    else:
        raw_price = float(country["price"])

    price = raw_price
    discount = float(country.get("flash_sale_discount") or 0)
    flash_until = country.get("flash_sale_until")
    if discount > 0 and flash_until:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if flash_until > now:
            price = round(price * (1 - discount / 100), 4)
    return price

_MAX_PAGE     = 500
_MAX_CODE_LEN = 10


@router.callback_query(F.data == "menu:buy")
async def show_buy_categories(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    lang = user.get("language", "en")

    if not await _sell_enabled(callback.from_user.id):
        await callback.answer(
            "🔴 المتجر متوقف مؤقتاً." if lang == "ar" else "🔴 Store is temporarily closed.",
            show_alert=True,
        )
        return

    text = (
        f"🛒 <b>متجر الحسابات الجاهزة</b>\n\n"
        f"💰 رصيدك الحالي: <b>${float(user['balance']):.2f}</b>\n\n"
        f"اختر نوع الحسابات المطلوب تصفحه:"
    ) if lang == "ar" else (
        f"🛒 <b>Ready Accounts Store</b>\n\n"
        f"💰 Current Balance: <b>${float(user['balance']):.2f}</b>\n\n"
        f"Select the accounts category to browse:"
    )
    await callback.message.edit_text(
        text,
        reply_markup=buy_category_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy_cat:"))
async def show_category_countries(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    category = callback.data.split(":", 1)[1]
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    lang = user.get("language", "en")

    if not await _sell_enabled(callback.from_user.id):
        await callback.answer(
            "🔴 المتجر متوقف مؤقتاً." if lang == "ar" else "🔴 Store is temporarily closed.",
            show_alert=True,
        )
        return

    countries = await get_countries_with_stock(category=category)
    cat_name = "🏛️ أرقام قديمة" if category == "old" else "📱 حسابات عادية"
    if not countries:
        builder = InlineKeyboardBuilder()
        other_cat = "regular" if category == "old" else "old"
        other_label = "📱 تصفح الحسابات العادية" if category == "old" else "🏛️ تصفح الأرقام القديمة"
        builder.button(text=other_label, callback_data=f"buy_cat:{other_cat}")
        builder.button(text=t(lang, "btn_back"), callback_data="menu:buy")
        builder.adjust(1)
        await callback.message.edit_text(
            f"📭 <b>لا توجد {cat_name} متوفرة حالياً في المخزون.</b>\n\nيمكنك مراجعة القسم الآخر أو العودة لاحقاً.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    text = (
        f"🛒 <b>متجر الحسابات الجاهزة — {cat_name}</b>\n\n"
        f"💰 رصيدك الحالي: <b>${float(user['balance']):.2f}</b>\n\n"
        f"اختر الدولة للشراء واستلام كود الدخول فوراً:"
    ) if lang == "ar" else (
        f"🛒 <b>Ready Accounts Store — {cat_name}</b>\n\n"
        f"💰 Balance: <b>${float(user['balance']):.2f}</b>\n\n"
        f"Select a country to purchase:"
    )
    await callback.message.edit_text(
        text,
        reply_markup=countries_keyboard(lang, countries, page=0, store_type="dollar", category=category),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy_page:"))
async def buy_page(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    parts = callback.data.split(":")
    if len(parts) >= 3:
        category = parts[1]
        raw_page = parts[2]
    else:
        category = "regular"
        raw_page = parts[1]

    try:
        page = int(raw_page)
        if page < 0 or page > _MAX_PAGE:
            raise ValueError
    except ValueError:
        await callback.answer("Invalid page.", show_alert=True)
        return

    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    lang = user.get("language", "en")

    countries = await get_countries_with_stock(category=category)
    cat_name = "🏛️ أرقام قديمة" if category == "old" else "📱 حسابات عادية"
    if not countries:
        await callback.message.edit_text(
            t(lang, "no_countries"),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    text = (
        f"🛒 <b>متجر الحسابات الجاهزة — {cat_name}</b>\n\n"
        f"💰 رصيدك الحالي: <b>${float(user['balance']):.2f}</b>\n\n"
        f"اختر الدولة للشراء واستلام كود الدخول فوراً:"
    ) if lang == "ar" else (
        f"🛒 <b>Ready Accounts Store — {cat_name}</b>\n\n"
        f"💰 Balance: <b>${float(user['balance']):.2f}</b>\n\n"
        f"Select a country to purchase:"
    )
    await callback.message.edit_text(
        text,
        reply_markup=countries_keyboard(lang, countries, page=page, store_type="dollar", category=category),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy_search"))
async def buy_search_prompt(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    category = parts[1] if len(parts) > 1 else "regular"
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    lang = user.get("language", "en")

    await state.set_state(BuyState.searching_country)
    await state.update_data(search_category=category)
    builder = InlineKeyboardBuilder()
    builder.button(text=t(lang, "btn_back"), callback_data=f"buy_cat:{category}")
    await callback.message.edit_text(
        t(lang, "buy_search_prompt"),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(BuyState.searching_country)
async def buy_search_handle(message: Message, state: FSMContext):
    data = await state.get_data()
    category = data.get("search_category", "regular")
    await state.clear()
    user = await get_user(message.from_user.id)
    if not user:
        return
    lang = user.get("language", "en")

    query = message.text.strip().lower()
    all_countries = await get_countries_with_stock(category=category)
    results = [
        c for c in all_countries
        if query in c["country_name"].lower() or query in c["country_code"].lower()
    ]

    builder = InlineKeyboardBuilder()
    builder.button(text=t(lang, "btn_back"), callback_data=f"buy_cat:{category}")
    if not results:
        safe_query = html_module.escape(message.text.strip())
        await message.answer(
            t(lang, "buy_search_no_results", query=safe_query),
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        return

    cat_name = "🏛️ أرقام قديمة" if category == "old" else "📱 حسابات عادية"
    await message.answer(
        f"🔎 <b>نتائج البحث في {cat_name}:</b>\n💰 رصيدك: <b>${float(user['balance']):.2f}</b>",
        reply_markup=countries_keyboard(lang, results, page=0, store_type="dollar", category=category),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("buy:"))
async def ask_confirm_purchase(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    parts = callback.data.split(":")
    if len(parts) >= 3:
        category = parts[1]
        country_code = parts[2]
    else:
        category = "regular"
        country_code = parts[1]

    if not country_code or len(country_code) > _MAX_CODE_LEN or not country_code.isalpha():
        await callback.answer("Invalid country.", show_alert=True)
        return

    country_code = country_code.upper()
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    lang = user.get("language", "en")

    if not await _sell_enabled(callback.from_user.id):
        await callback.answer(
            "🔴 المتجر متوقف مؤقتاً." if lang == "ar" else "🔴 Store is temporarily closed.",
            show_alert=True,
        )
        return
    country = await get_country(country_code)
    if not country:
        await callback.answer(t(lang, "error_generic"), show_alert=True)
        return

    ep = _effective_price(country, category=category)

    if float(user["balance"]) < ep:
        builder = InlineKeyboardBuilder()
        builder.button(text="💳 شحن الرصيد", callback_data="menu:topup")
        builder.button(text=t(lang, "btn_back"), callback_data=f"buy_cat:{category}")
        builder.adjust(1)
        await callback.message.edit_text(
            t(lang, "insufficient_balance", price=ep, balance=float(user["balance"])),
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    cat_label = "🏛️ أرقام قديمة" if category == "old" else "📱 حسابات عادية"
    flag = country.get("flag_emoji", "")
    builder = InlineKeyboardBuilder()
    builder.button(text=t(lang, "btn_confirm"), callback_data=f"confirm_buy:{category}:{country_code}")
    builder.button(text=t(lang, "btn_cancel"),  callback_data=f"buy_cat:{category}")
    builder.adjust(1)

    confirm_msg = (
        f"🛍️ <b>تأكيد عملية الشراء</b>\n\n"
        f"🏷️ القسم: <b>{cat_label}</b>\n"
        f"🌍 الدولة: <b>{flag} {country['country_name']}</b>\n"
        f"💵 السعر: <b>${ep:.2f}</b>\n"
        f"💰 رصيدك الحالي: <b>${float(user['balance']):.2f}</b>\n"
        f"💳 المتبقي بعد الشراء: <b>${(float(user['balance']) - ep):.2f}</b>\n\n"
        f"هل أنت متأكد من الشراء واستلام كود الدخول؟"
    ) if lang == "ar" else (
        f"🛍️ <b>Confirm Purchase</b>\n\n"
        f"🏷️ Category: <b>{cat_label}</b>\n"
        f"🌍 Country: <b>{flag} {country['country_name']}</b>\n"
        f"💵 Price: <b>${ep:.2f}</b>\n"
        f"💰 Balance: <b>${float(user['balance']):.2f}</b>\n\n"
        f"Are you sure you want to proceed?"
    )

    await callback.message.edit_text(
        confirm_msg,
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_buy:"))
async def execute_purchase(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    parts = callback.data.split(":")
    if len(parts) >= 3:
        category = parts[1]
        country_code = parts[2]
    else:
        category = "regular"
        country_code = parts[1]

    if not country_code or len(country_code) > _MAX_CODE_LEN or not country_code.isalpha():
        await callback.answer("Invalid country.", show_alert=True)
        return

    country_code = country_code.upper()
    user_id = callback.from_user.id
    user = await get_user(user_id)
    if not user:
        await callback.answer()
        return

    lang = user.get("language", "en")

    if not await _sell_enabled(callback.from_user.id):
        await callback.answer(
            "🔴 المتجر متوقف مؤقتاً، لا يمكن إتمام الشراء." if lang == "ar"
            else "🔴 Store is closed. Purchase blocked.",
            show_alert=True,
        )
        return
    country = await get_country(country_code)
    ep = _effective_price(country, category=category) if country else 0

    if not country or float(user["balance"]) < ep:
        builder = InlineKeyboardBuilder()
        builder.button(text="💳 شحن الرصيد", callback_data="menu:topup")
        builder.button(text=t(lang, "btn_back"), callback_data=f"buy_cat:{category}")
        builder.adjust(1)
        await callback.message.edit_text(
            t(lang, "insufficient_balance", price=ep, balance=float(user["balance"])),
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    try:
        result = await purchase_account(user_id, country_code, category=category)
    except Exception as e:
        logger.error("Unexpected error in purchase_account: %s", e)
        builder = InlineKeyboardBuilder()
        builder.button(text=t(lang, "btn_back"), callback_data=f"buy_cat:{category}")
        await callback.message.edit_text(
            t(lang, "error_generic"),
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    if result is None:
        builder = InlineKeyboardBuilder()
        builder.button(text=t(lang, "btn_back"), callback_data=f"buy_cat:{category}")
        await callback.message.edit_text(
            t(lang, "no_stock_for_country", country=country["country_name"]),
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        await callback.answer()
        return


    flag       = country.get("flag_emoji", "")
    phone      = result["account_data"].split("::")[0].strip()

    builder = InlineKeyboardBuilder()
    builder.button(text=t(lang, "btn_back"), callback_data="menu:main")

    acc_parts = [p.strip() for p in result["account_data"].split("::")]
    two_factor = acc_parts[2] if len(acc_parts) == 3 else (acc_parts[4] if len(acc_parts) >= 5 else "")

    _success_text = t(lang, "purchase_success",
                      country=f"{flag} {country['country_name']}",
                      price=float(result["price"]),
                      balance=float(result["new_balance"]),
                      phone=phone)

    if two_factor:
        if lang == "ar":
            _success_text += f"\n\n🔐 <b>باسوورد التحقق (2FA):</b> <code>{two_factor}</code>"
        elif lang == "fa":
            _success_text += f"\n\n🔐 <b>رمز عبور دومرحله‌ای (2FA):</b> <code>{two_factor}</code>"
        else:
            _success_text += f"\n\n🔐 <b>2FA Password:</b> <code>{two_factor}</code>"

    await callback.message.edit_text(
        _success_text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer("✅")

    task = asyncio.create_task(
        wait_for_login_code(
            account_id=result["id"],
            account_data_raw=result["account_data"],
            buyer_id=user_id,
            bot=bot,
            lang=lang,
            country_name=country["country_name"],
            price=float(result["price"]),
            flag=country.get("flag_emoji", "🌍"),
        )
    )

    def _log_task_error(task_result):
        if not task_result.cancelled() and task_result.exception():
            logger.error("wait_for_login_code raised: %s", task_result.exception())

    task.add_done_callback(_log_task_error)
