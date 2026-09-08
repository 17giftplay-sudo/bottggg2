"""
نظام الأدمن الفرعيين — إضافة، إدارة الصلاحيات، الحذف، ولوحة العمل
"""
import logging
from typing import Optional
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS
from database import (
    get_sub_admin, add_sub_admin, remove_sub_admin,
    get_all_sub_admins,
)
from keyboards import (
    sub_admin_list_keyboard, sub_admin_perms_keyboard,
    admin_back_keyboard, sub_admin_panel_keyboard,
)
from states import SubAdminState

router = Router()
logger = logging.getLogger(__name__)

# مفاتيح الصلاحيات المتاحة — يجب أن تتطابق مع أعمدة sub_admins في قاعدة البيانات
_PERM_KEYS = ("stock", "users", "stats", "deposits", "broadcast")


# ─── مساعد: جلب صلاحيات الأدمن الفرعي ────────────────────────────────────────

async def _get_sa_perms(user_id: int) -> Optional[dict]:
    sa = await get_sub_admin(user_id)
    if not sa:
        return None
    return {
        "stock":     bool(sa.get("perm_stock")),
        "users":     bool(sa.get("perm_users")),
        "stats":     bool(sa.get("perm_stats")),
        "deposits":  bool(sa.get("perm_deposits")),
        "broadcast": bool(sa.get("perm_broadcast")),
        "label":     sa.get("label") or str(user_id),
    }


async def _sa_check(callback: CallbackQuery, perm: str) -> Optional[dict]:
    """تتحقق من صلاحية معينة وترد بـ ⛔ إذا لم تتوفر. ترجع perms إذا مسموح."""
    perms = await _get_sa_perms(callback.from_user.id)
    if not perms or not perms.get(perm):
        await callback.answer("⛔ ليس لديك صلاحية للوصول لهذا القسم.", show_alert=True)
        return None
    return perms



def is_main_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ─── قائمة الأدمن الفرعيين ────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:sub_admins")
async def sub_admins_list(callback: CallbackQuery, state: FSMContext):
    if not is_main_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.clear()
    sub_admins = await get_all_sub_admins()
    count = len(sub_admins)
    text = (
        f"👮 <b>الأدمن الفرعيون</b>\n\n"
        f"العدد الحالي: <b>{count}</b>\n\n"
        "يمكنك إضافة أدمن فرعي وتحديد الأقسام التي يستطيع الوصول إليها.\n"
        "الأدمن الفرعيون <b>لا</b> يستطيعون تعديل صلاحيات بعضهم أو إضافة أدمن آخرين."
    )
    await callback.message.edit_text(
        text,
        reply_markup=sub_admin_list_keyboard(sub_admins),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── عرض أدمن فرعي وصلاحياته ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("sadmin:view:"))
async def sub_admin_view(callback: CallbackQuery):
    if not is_main_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    uid = int(callback.data.split(":")[2])
    sa  = await get_sub_admin(uid)
    if not sa:
        await callback.answer("❌ الأدمن غير موجود.", show_alert=True)
        return
    perms = {
        "stock":     bool(sa.get("perm_stock")),
        "users":     bool(sa.get("perm_users")),
        "stats":     bool(sa.get("perm_stats")),
        "deposits":  bool(sa.get("perm_deposits")),
        "broadcast": bool(sa.get("perm_broadcast")),
    }
    label = sa.get("label") or str(uid)
    text = (
        f"👤 <b>أدمن فرعي: {label}</b>\n"
        f"🆔 الآيدي: <code>{uid}</code>\n\n"
        "اضغط على أي صلاحية لتفعيلها أو تعطيلها:"
    )
    await callback.message.edit_text(
        text,
        reply_markup=sub_admin_perms_keyboard(uid, perms),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── تبديل صلاحية ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("sadmin:toggle:"))
async def sub_admin_toggle_perm(callback: CallbackQuery):
    if not is_main_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    parts = callback.data.split(":")
    uid   = int(parts[2])
    perm  = parts[3]
    if perm not in _PERM_KEYS:
        await callback.answer("❌ صلاحية غير معروفة.", show_alert=True)
        return
    sa = await get_sub_admin(uid)
    if not sa:
        await callback.answer("❌ الأدمن غير موجود.", show_alert=True)
        return
    perms = {
        "stock":     bool(sa.get("perm_stock")),
        "users":     bool(sa.get("perm_users")),
        "stats":     bool(sa.get("perm_stats")),
        "deposits":  bool(sa.get("perm_deposits")),
        "broadcast": bool(sa.get("perm_broadcast")),
    }
    # عكس الصلاحية المطلوبة
    perms[perm] = not perms[perm]
    await add_sub_admin(uid, sa.get("label", ""), perms)
    # تحديث الرسالة
    label = sa.get("label") or str(uid)
    text = (
        f"👤 <b>أدمن فرعي: {label}</b>\n"
        f"🆔 الآيدي: <code>{uid}</code>\n\n"
        "اضغط على أي صلاحية لتفعيلها أو تعطيلها:"
    )
    await callback.message.edit_text(
        text,
        reply_markup=sub_admin_perms_keyboard(uid, perms),
        parse_mode="HTML",
    )
    await callback.answer("✅ تم تحديث الصلاحية")


# ─── إضافة أدمن فرعي جديد ────────────────────────────────────────────────────

@router.callback_query(F.data == "sadmin:add")
async def sub_admin_add_start(callback: CallbackQuery, state: FSMContext):
    if not is_main_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.set_state(SubAdminState.waiting_for_user_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="admin:sub_admins")
    await callback.message.edit_text(
        "👮 <b>إضافة أدمن فرعي جديد</b>\n\n"
        "أرسل <b>آيدي تيليجرام</b> للشخص الذي تريد إضافته كأدمن فرعي:\n\n"
        "<i>يمكنه معرفة آيديه بإرسال /start لـ @userinfobot</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(SubAdminState.waiting_for_user_id)
async def sub_admin_receive_id(message: Message, state: FSMContext):
    if not is_main_admin(message.from_user.id):
        return
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("❌ آيدي غير صحيح، أرسل رقماً فقط.")
        return
    if uid in ADMIN_IDS:
        await message.answer("⚠️ هذا الآيدي هو أدمن رئيسي بالفعل.")
        return
    # احفظ uid مؤقتاً وطلب اسم/وصف
    await state.update_data(new_sub_admin_id=uid)
    await state.set_state(SubAdminState.waiting_for_perms)
    # أضفه بصلاحيات فارغة أولاً ثم عرض لوحة الصلاحيات
    await add_sub_admin(uid, str(uid), {k: False for k in _PERM_KEYS})
    sa = await get_sub_admin(uid)
    perms = {k: False for k in _PERM_KEYS}
    await state.clear()
    text = (
        f"✅ <b>تم إضافة الأدمن الفرعي</b>\n"
        f"🆔 الآيدي: <code>{uid}</code>\n\n"
        "الآن حدد الصلاحيات التي يمكنه الوصول إليها:"
    )
    await message.answer(
        text,
        reply_markup=sub_admin_perms_keyboard(uid, perms),
        parse_mode="HTML",
    )


# ─── حذف أدمن فرعي ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("sadmin:delete:"))
async def sub_admin_delete(callback: CallbackQuery):
    if not is_main_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    uid = int(callback.data.split(":")[2])
    await remove_sub_admin(uid)
    await callback.answer("🗑️ تم حذف الأدمن الفرعي", show_alert=True)
    sub_admins = await get_all_sub_admins()
    await callback.message.edit_text(
        f"👮 <b>الأدمن الفرعيون</b>\n\nالعدد الحالي: <b>{len(sub_admins)}</b>",
        reply_markup=sub_admin_list_keyboard(sub_admins),
        parse_mode="HTML",
    )


# ══════════════════════════════════════════════════════════════════════════════
# لوحة الأدمن الفرعي — القسم الخاص بهم عند ضغط /admin
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "sadmin:panel")
async def sadmin_panel(callback: CallbackQuery, state: FSMContext):
    perms = await _get_sa_perms(callback.from_user.id)
    if not perms:
        await callback.answer("⛔", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(
        f"👮 <b>لوحة الأدمن الفرعي</b>\n\n"
        f"مرحباً <b>{perms['label']}</b>!\n"
        "اختر القسم الذي تريد إدارته:",
        reply_markup=sub_admin_panel_keyboard(perms),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── الإحصائيات ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "sadmin:stats")
async def sadmin_stats(callback: CallbackQuery):
    perms = await _sa_check(callback, "stats")
    if not perms:
        return
    from database import get_bot_stats
    stats = await get_bot_stats()
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 رجوع", callback_data="sadmin:panel")
    await callback.message.edit_text(
        f"📊 <b>إحصائيات البوت</b>\n\n"
        f"👥 إجمالي المستخدمين: <b>{stats['total_users']}</b>\n"
        f"💵 إجمالي الإيداعات: <b>${stats['total_deposits']:.2f}</b>\n"
        f"📦 حسابات مباعة: <b>{stats['total_sold']}</b>\n"
        f"🗂 حسابات متوفرة: <b>{stats['total_available']}</b>\n"
        f"🌍 عدد الدول: <b>{stats['total_countries']}</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── إدارة المخزون ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "sadmin:stock")
async def sadmin_stock(callback: CallbackQuery):
    perms = await _sa_check(callback, "stock")
    if not perms:
        return
    from database import get_all_countries_with_stock_or_maintenance
    try:
        countries = await get_all_countries_with_stock_or_maintenance()
    except Exception:
        from database import get_all_countries
        countries = await get_all_countries()

    builder = InlineKeyboardBuilder()
    builder.button(text="➕ رفع حسابات (ZIP)",   callback_data="sadmin:stock_add")
    builder.button(text="📋 عرض المخزون",         callback_data="sadmin:stock_view")
    builder.button(text="🔙 رجوع",                callback_data="sadmin:panel")
    builder.adjust(1)

    lines = ["🗄️ <b>إدارة المخزون</b>\n"]
    if countries:
        for c in countries[:20]:
            flag  = c.get("flag_emoji", "🌍")
            name  = c.get("country_name", "")
            count = c.get("available_count", 0)
            lines.append(f"{flag} {name}: <b>{count}</b> حساب")
    else:
        lines.append("لا توجد دول مضافة بعد.")

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "sadmin:stock_add")
async def sadmin_stock_add(callback: CallbackQuery, state: FSMContext):
    perms = await _sa_check(callback, "stock")
    if not perms:
        return
    from database import get_all_countries
    countries = await get_all_countries()
    if not countries:
        await callback.answer("❌ لا توجد دول. اطلب من المشرف الرئيسي إضافة دول أولاً.", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for c in countries:
        flag = c.get("flag_emoji", "")
        builder.button(
            text=f"{flag} {c['country_name']}",
            callback_data=f"add_stock:{c['country_code']}",
        )
    builder.button(text="❌ إلغاء", callback_data="sadmin:stock")
    builder.adjust(2)
    await callback.message.edit_text(
        "📦 <b>إضافة مخزون</b>\n\nاختر الدولة:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "sadmin:stock_view")
async def sadmin_stock_view(callback: CallbackQuery):
    perms = await _sa_check(callback, "stock")
    if not perms:
        return
    from database import get_all_available_accounts
    try:
        accounts = await get_all_available_accounts()
    except Exception:
        accounts = []

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 رجوع", callback_data="sadmin:stock")

    if not accounts:
        await callback.message.edit_text(
            "🗄️ <b>المخزون فارغ</b>\n\nلا توجد حسابات متاحة حالياً.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    from collections import Counter
    by_country: Counter = Counter()
    for acc in accounts:
        by_country[acc.get("country_code", "?")] += 1

    lines = [f"🗄️ <b>المخزون المتاح</b> — {len(accounts)} حساب\n"]
    for cc, cnt in by_country.most_common():
        lines.append(f"🌍 <code>{cc}</code>: <b>{cnt}</b>")

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── إدارة المستخدمين ─────────────────────────────────────────────────────────

class SAdminUserState(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_amount   = State()


@router.callback_query(F.data == "sadmin:users")
async def sadmin_users(callback: CallbackQuery, state: FSMContext):
    perms = await _sa_check(callback, "users")
    if not perms:
        return
    await state.clear()
    await state.set_state(SAdminUserState.waiting_for_user_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="sadmin:panel")
    await callback.message.edit_text(
        "👥 <b>إدارة المستخدمين</b>\n\nأرسل ID المستخدم للبحث عنه:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(SAdminUserState.waiting_for_user_id)
async def sadmin_user_id_received(message: Message, state: FSMContext):
    perms = await _get_sa_perms(message.from_user.id)
    if not perms or not perms.get("users"):
        await state.clear()
        return
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("❌ ID غير صحيح، أرسل رقماً فقط.")
        return

    from database import get_user
    user = await get_user(uid)
    if not user:
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 رجوع", callback_data="sadmin:users")
        await message.answer("❌ المستخدم غير موجود.", reply_markup=builder.as_markup())
        return

    await state.clear()

    bal      = float(user.get("balance", 0))
    pts      = user.get("points", 0)
    purch    = user.get("accounts_purchased", 0)
    username = user.get("username") or "—"
    fname    = user.get("first_name") or "—"
    banned   = "🔴 محظور" if user.get("is_banned") else "🟢 نشط"

    builder = InlineKeyboardBuilder()
    if perms.get("deposits"):
        builder.button(text="➕ إضافة رصيد",  callback_data=f"sadmin:add_bal:{uid}")
        builder.button(text="➖ خصم رصيد",    callback_data=f"sadmin:ded_bal:{uid}")
        builder.adjust(2)
    builder.row()
    builder.button(text="🔙 رجوع", callback_data="sadmin:users")

    await message.answer(
        f"👤 <b>بيانات المستخدم</b>\n\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"👤 الاسم: {fname}\n"
        f"📛 المعرف: @{username}\n"
        f"💵 الرصيد: <b>${bal:.2f}</b>\n"
        f"🪙 النقاط: <b>{pts}</b>\n"
        f"📦 المشتريات: <b>{purch}</b>\n"
        f"🔰 الحالة: {banned}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("sadmin:add_bal:"))
async def sadmin_add_bal_start(callback: CallbackQuery, state: FSMContext):
    perms = await _sa_check(callback, "deposits")
    if not perms:
        return
    uid = int(callback.data.split(":")[2])
    await state.set_state(SAdminUserState.waiting_for_amount)
    await state.update_data(action="add", target_uid=uid)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="sadmin:panel")
    await callback.message.edit_text(
        f"➕ <b>إضافة رصيد للمستخدم</b> <code>{uid}</code>\n\nأرسل المبلغ بالدولار:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sadmin:ded_bal:"))
async def sadmin_ded_bal_start(callback: CallbackQuery, state: FSMContext):
    perms = await _sa_check(callback, "deposits")
    if not perms:
        return
    uid = int(callback.data.split(":")[2])
    await state.set_state(SAdminUserState.waiting_for_amount)
    await state.update_data(action="deduct", target_uid=uid)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="sadmin:panel")
    await callback.message.edit_text(
        f"➖ <b>خصم رصيد من المستخدم</b> <code>{uid}</code>\n\nأرسل المبلغ بالدولار:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(SAdminUserState.waiting_for_amount)
async def sadmin_amount_received(message: Message, state: FSMContext):
    perms = await _get_sa_perms(message.from_user.id)
    if not perms:
        await state.clear()
        return
    data   = await state.get_data()
    action = data.get("action", "add")
    uid    = data.get("target_uid")
    try:
        amount = float(message.text.strip().replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ مبلغ غير صحيح، أرسل رقماً موجباً.")
        return

    await state.clear()
    from database import add_balance, deduct_balance, get_user
    try:
        if action == "add":
            await add_balance(uid, amount)
            verb = "إضافة"
            sign = "+"
        else:
            await deduct_balance(uid, amount)
            verb = "خصم"
            sign = "-"
        user    = await get_user(uid)
        new_bal = float(user["balance"]) if user else 0
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 رجوع للوحة", callback_data="sadmin:panel")
        await message.answer(
            f"✅ <b>تمت عملية {verb} الرصيد</b>\n\n"
            f"👤 المستخدم: <code>{uid}</code>\n"
            f"💵 المبلغ: {sign}${amount:.2f}\n"
            f"💰 الرصيد الجديد: <b>${new_bal:.2f}</b>",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
    except Exception:
        await message.answer("❌ حدث خطأ أثناء تنفيذ العملية.")

