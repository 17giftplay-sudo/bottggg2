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
from keyboards import countries_keyboard, back_to_main_keyboard
from utils.session_manager import wait_for_login_code

router = Router()
logger = logging.getLogger(__name__)


async def _sell_enabled(user_id: int = 0) -> bool:
    if user_id and user_id in ADMIN_IDS:
        return True
    val = await get_setting("sell_btn_enabled")
    return (val or "1") == "1"


def _effective_price(country: dict) -> float:
    price = float(country["price"])
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
async def show_buy_menu(callback: CallbackQuery, state: FSMContext):
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

    countries = await get_countries_with_stock()
    if not countries:
        await callback.message.edit_text(
            t(lang, "no_countries"),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        t(lang, "buy_menu", balance=float(user["balance"])),
        reply_markup=countries_keyboard(lang, countries, page=0),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy_page:"))
async def buy_page(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    raw_page = callback.data.split(":", 1)[1]
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

    countries = await get_countries_with_stock()
    if not countries:
        await callback.message.edit_text(
            t(lang, "no_countries"),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        t(lang, "buy_menu", balance=float(user["balance"])),
        reply_markup=countries_keyboard(lang, countries, page=page),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "buy_search")
async def buy_search_prompt(callback: CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    lang = user.get("language", "en")

    await state.set_state(BuyState.searching_country)
    await callback.message.edit_text(
        t(lang, "buy_search_prompt"),
        reply_markup=back_to_main_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(BuyState.searching_country)
async def buy_search_handle(message: Message, state: FSMContext):
    await state.clear()
    user = await get_user(message.from_user.id)
    if not user:
        return
    lang = user.get("language", "en")

    query         = message.text.strip().lower()
    all_countries = await get_countries_with_stock()
    results = [
        c for c in all_countries
        if query in c["country_name"].lower() or query in c["country_code"].lower()
    ]

    if not results:
        safe_query = html_module.escape(message.text.strip())
        await message.answer(
            t(lang, "buy_search_no_results", query=safe_query),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
        return

    await message.answer(
        t(lang, "buy_menu", balance=float(user["balance"])),
        reply_markup=countries_keyboard(lang, results, page=0),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("buy:"))
async def ask_confirm_purchase(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    country_code = callback.data.split(":", 1)[1]
    if not country_code or len(country_code) > _MAX_CODE_LEN or not country_code.isalpha():
        await callback.answer("Invalid country.", show_alert=True)
        return

    country_code = country_code.upper()
    user         = await get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    lang    = user.get("language", "en")

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

    ep = _effective_price(country)

    if float(user["balance"]) < ep:
        await callback.message.edit_text(
            t(lang, "insufficient_balance",
              price=ep,
              balance=float(user["balance"])),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    flag = country.get("flag_emoji", "")
    builder = InlineKeyboardBuilder()
    builder.button(text=t(lang, "btn_confirm"), callback_data=f"confirm_buy:{country_code}")
    builder.button(text=t(lang, "btn_cancel"),  callback_data="menu:buy")
    builder.adjust(1)

    await callback.message.edit_text(
        t(lang, "confirm_purchase",
          country=f"{flag} {country['country_name']}",
          price=ep,
          balance=float(user["balance"])),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_buy:"))
async def execute_purchase(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()

    country_code = callback.data.split(":", 1)[1]
    if not country_code or len(country_code) > _MAX_CODE_LEN or not country_code.isalpha():
        await callback.answer("Invalid country.", show_alert=True)
        return

    country_code = country_code.upper()
    user_id      = callback.from_user.id
    user         = await get_user(user_id)
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

    # FIX #5: نعيد حساب السعر الفعلي لحظة التنفيذ (لا نعتمد على سعر شاشة التأكيد).
    # الخطأ الأصلي: السعر المعروض قد يختلف عن السعر الفعلي إذا انتهت الـ flash sale
    #               بين لحظة الضغط على "تأكيد" ولحظة التنفيذ الفعلي.
    # الضرر: المستخدم يرى سعر عرض ويُخصم منه السعر الأصلي بدون إشعار، أو العكس.
    # الإصلاح: نحسب ep مجدداً هنا — وهو نفس ما يحسبه purchase_account داخل DB transaction.
    ep = _effective_price(country) if country else 0

    if not country or float(user["balance"]) < ep:
        await callback.message.edit_text(
            t(lang, "insufficient_balance",
              price=ep,
              balance=float(user["balance"])),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    try:
        result = await purchase_account(user_id, country_code)
    except Exception as e:
        if "no_stock" in str(e):
            await callback.message.edit_text(
                t(lang, "no_stock_for_country", country=country["country_name"]),
                reply_markup=back_to_main_keyboard(lang),
                parse_mode="HTML",
            )
            await callback.answer()
            return
        logger.error("Unexpected error in purchase_account: %s", e)
        await callback.message.edit_text(
            t(lang, "error_generic"),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    if result is None:
        await callback.message.edit_text(
            t(lang, "no_stock_for_country", country=country["country_name"]),
            reply_markup=back_to_main_keyboard(lang),
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
