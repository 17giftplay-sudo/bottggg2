from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from typing import List, Dict, Any, Optional
from translations import t
from config import COUNTRIES_PER_PAGE


def language_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🇺🇸 English", callback_data="lang:en")
    builder.button(text="🇸🇦 العربية", callback_data="lang:ar")
    builder.button(text="🇮🇷 فارسی", callback_data="lang:fa")
    builder.adjust(3)
    return builder.as_markup()


def force_sub_keyboard(lang: str, channel: str, notif_channel: str = "") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    def _link(ch):
        return ch if ch.startswith("http") else f"https://t.me/{ch.lstrip('@')}"
    if channel:
        lbl = (t(lang, "btn_join_channel") + " 1") if notif_channel and notif_channel != channel else t(lang, "btn_join_channel")
        builder.button(text=lbl, url=_link(channel))
    if notif_channel and notif_channel != channel:
        lbl2 = "📣 قناة الإشعارات" if lang == "ar" else ("📣 کانال اعلان‌ها" if lang == "fa" else "📣 Notification Channel")
        builder.button(text=lbl2, url=_link(notif_channel))
    builder.button(text=t(lang, "btn_check_join"), callback_data="check_join")
    builder.adjust(1)
    return builder.as_markup()


def main_menu_keyboard(
    lang: str,
    sell_enabled: bool = False,
    info_enabled: bool = True,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    # 1. شراء الحسابات وجلسات تيليجرام بجانب بعض
    if lang == "fa":
        builder.button(text="🛒  خرید اکانت آماده", callback_data="menu:buy")
        builder.button(text="📱  سشن‌های تلگرام", callback_data="menu:sessions")
    elif lang == "ar":
        builder.button(text="🛒  شراء حسابات جاهزة", callback_data="menu:buy")
        builder.button(text="📱  جلسات تيليجرام", callback_data="menu:sessions")
    else:
        builder.button(text="🛒  Buy Ready Accounts", callback_data="menu:buy")
        builder.button(text="📱  Telegram Sessions", callback_data="menu:sessions")

    # 2. زر شحن الرصيد العريض تحت الخدمات مباشرة
    if lang == "fa":
        topup_text = "💳  افزایش موجودی و شارژ حساب"
    elif lang == "ar":
        topup_text = "💳  شحن الرصيد"
    else:
        topup_text = "💳  Top Up Balance"
    builder.button(text=topup_text, callback_data="menu:topup")

    # 3. الملف الشخصي ونظام الإحالة
    if lang == "fa":
        builder.button(text="👤  پروفایل من", callback_data="menu:profile")
        builder.button(text="🎁  کسب درآمد و زیرمجموعه", callback_data="menu:referral")
    elif lang == "ar":
        builder.button(text="👤  ملفي الشخصي", callback_data="menu:profile")
        builder.button(text="🎁  دعوة الأصدقاء والأرباح", callback_data="menu:referral")
    else:
        builder.button(text="👤  My Profile", callback_data="menu:profile")
        builder.button(text="🎁  Referral & Earn", callback_data="menu:referral")

    # 4. الدعم الفني والمعلومات
    if lang == "fa":
        builder.button(text="🎧  پشتیبانی", callback_data="menu:support")
        if info_enabled:
            builder.button(text="📢  کانال‌ها و اطلاعات", callback_data="menu:info")
    elif lang == "ar":
        builder.button(text="🎧  الدعم الفني", callback_data="menu:support")
        if info_enabled:
            builder.button(text="📢  معلومات وقنوات", callback_data="menu:info")
    else:
        builder.button(text="🎧  Support", callback_data="menu:support")
        if info_enabled:
            builder.button(text="📢  Useful Info", callback_data="menu:info")

    # 5. تغيير اللغة
    if lang == "fa":
        builder.button(text="🌐  تغییر زبان (Language)", callback_data="menu:change_language")
    elif lang == "ar":
        builder.button(text="🌐  تغيير اللغة", callback_data="menu:change_language")
    else:
        builder.button(text="🌐  Change Language", callback_data="menu:change_language")

    if info_enabled:
        builder.adjust(2, 1, 2, 2, 1)
    else:
        builder.adjust(2, 1, 2, 1, 1)
    return builder.as_markup()


def back_to_main_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t(lang, "btn_back"), callback_data="menu:main")
    return builder.as_markup()


def back_to_topup_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t(lang, "btn_back"), callback_data="menu:topup")
    return builder.as_markup()


def topup_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💠  OxaPay — USDT / LTC / TON / BTC / ETH / TRX", callback_data="topup:oxapay")
    builder.button(text=t(lang, "btn_binance_pay"), callback_data="topup:binance_manual")
    builder.button(text=t(lang, "btn_stars"),          callback_data="topup:stars")
    builder.button(text=t(lang, "btn_other_methods"),  callback_data="topup:other")
    builder.button(text=t(lang, "btn_back"),           callback_data="menu:main")
    builder.adjust(1, 1, 1, 1, 1)
    return builder.as_markup()


def countries_keyboard(
    lang: str,
    countries: List[Dict[str, Any]],
    page: int = 0,
    store_type: str = "dollar",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    start = page * COUNTRIES_PER_PAGE
    end   = start + COUNTRIES_PER_PAGE

    for c in countries[start:end]:
        qty = int(c.get("stock_count", 0))
        if store_type == "points":
            pts = int(c.get("points_price", 0))
            builder.button(
                text=f"{c.get('flag_emoji','🌍')}  {c['country_name']}  ·  {pts} 🪙  [{qty}]",
                callback_data=f"pbuy:{c['country_code']}",
            )
        elif store_type == "sessions":
            flag = c.get("flag_emoji", "🌍")
            ep   = float(c.get("effective_price", c["price"]))
            disc = float(c.get("flash_sale_discount") or 0)
            if c.get("has_flash_sale"):
                builder.button(
                    text=f"{flag}  {c['country_name']}  [{qty}]  ·  ⚡ ${ep:.2f}  (-{disc:.0f}%)",
                    callback_data=f"sess_buy:{c['country_code']}",
                )
            else:
                builder.button(
                    text=f"{flag}  {c['country_name']}  [{qty}]  ·  ${float(c['price']):.2f}",
                    callback_data=f"sess_buy:{c['country_code']}",
                )
        else:
            flag = c.get("flag_emoji", "🌍")
            if c.get("has_flash_sale"):
                orig = float(c["price"])
                eff  = float(c.get("effective_price", orig))
                disc = float(c.get("flash_sale_discount", 0))
                builder.button(
                    text=f"{flag}  {c['country_name']}  [{qty}]  ·  ⚡ ${eff:.2f}  (-{disc:.0f}%)",
                    callback_data=f"buy:{c['country_code']}",
                )
            else:
                builder.button(
                    text=f"{flag}  {c['country_name']}  [{qty}]  ·  ${float(c['price']):.2f}",
                    callback_data=f"buy:{c['country_code']}",
                )
    builder.adjust(1)

    nav = []
    if store_type == "points":
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️ السابق", callback_data=f"pbuy_page:{page-1}"))
        if end < len(countries):
            nav.append(InlineKeyboardButton(text="التالي ▶️", callback_data=f"pbuy_page:{page+1}"))
    elif store_type == "sessions":
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️ السابق", callback_data=f"sessions_page:{page-1}"))
        if end < len(countries):
            nav.append(InlineKeyboardButton(text="التالي ▶️", callback_data=f"sessions_page:{page+1}"))
    else:
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️ السابق", callback_data=f"buy_page:{page-1}"))
        if end < len(countries):
            nav.append(InlineKeyboardButton(text="التالي ▶️", callback_data=f"buy_page:{page+1}"))
    if nav:
        builder.row(*nav)

    if store_type == "points":
        builder.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="menu:main"))
    elif store_type == "sessions":
        builder.row(InlineKeyboardButton(text="🛒  شراء حساب عادي (مع كود دخول)" if lang == "ar" else "🛒  Buy Regular Account (with code)", callback_data="menu:buy"))
        builder.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="menu:main"))
    else:
        builder.row(InlineKeyboardButton(text=t(lang, "btn_search"), callback_data="buy_search"))
        builder.row(InlineKeyboardButton(text=t(lang, "btn_back"),   callback_data="menu:main"))
    return builder.as_markup()


def request_contact_keyboard(lang: str) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(
        text="📱  مـشـاركـة رقـمـي" if lang == "ar" else "📱  Share My Number",
        request_contact=True,
    )
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def info_buttons_keyboard(lang: str, info_buttons: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for btn in info_buttons:
        if isinstance(btn, dict) and btn.get("text") and btn.get("url"):
            builder.button(text=btn["text"], url=btn["url"])
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="menu:main"))
    return builder.as_markup()


# ── Admin ─────────────────────────────────────────────────────────────────────

def admin_main_keyboard(maintenance_on: bool = False, sell_on: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👥  إدارة المستخدمين",    callback_data="admin:users")
    builder.button(text="📊  إحصائيات البوت",      callback_data="admin:stats")
    builder.button(text="🗄️  إدارة المخزون",       callback_data="admin:stock")

    builder.button(text="⭐  إعدادات النجوم",      callback_data="admin:stars")
    builder.button(text="🎁  إعدادات الإحالة",     callback_data="admin:referral_settings")
    builder.button(text="🔗  الروابط الديناميكية", callback_data="admin:links")
    builder.button(text="👮  الأدمن الفرعيون",    callback_data="admin:sub_admins")
    if sell_on:
        builder.button(text="🟢  المتجر: مفتوح",      callback_data="admin:toggle_sell_btn_main")
    else:
        builder.button(text="🔴  المتجر: موقوف",      callback_data="admin:toggle_sell_btn_main")
    if maintenance_on:
        builder.button(text="🟢  تشغيل البوت",         callback_data="admin:maintenance")
    else:
        builder.button(text="🔴  إيقاف البوت للصيانة", callback_data="admin:maintenance")
    builder.adjust(2, 1, 2, 2, 1, 1)
    return builder.as_markup()


def admin_referral_settings_keyboard(ref_enabled: bool = True, reward_usd: float = 0.05) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if ref_enabled:
        builder.button(text="🟢 نظام الإحالة: مفعّل", callback_data="admin:toggle_referral")
    else:
        builder.button(text="🔴 نظام الإحالة: معطّل", callback_data="admin:toggle_referral")
    builder.button(text=f"💵 مكافأة الدعوة: ${reward_usd:.2f}", callback_data="admin:set_referral_reward")
    builder.button(text="📊 إحصائيات الإحالة ومحاولات الغش", callback_data="admin:referral_stats")
    builder.button(text="🧹 تصفير جميع الأجهزة للتجربة", callback_data="admin:reset_devices_btn")
    builder.button(text="🔙 رجوع", callback_data="admin:main")
    builder.adjust(1, 1, 1, 1, 1)
    return builder.as_markup()


def admin_users_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔍  عرض مستخدم",   callback_data="admin:view_user")
    builder.button(text="➕  إضافة رصيد",    callback_data="admin:add_balance")
    builder.button(text="➖  خصم رصيد",      callback_data="admin:deduct_balance")
    builder.button(text="🪙  إضافة نقاط",   callback_data="admin:add_points")
    builder.button(text="🗑️  تصفير مستخدم للتجربة", callback_data="admin:reset_user_btn")
    builder.button(text="🔙  رجوع",          callback_data="admin:main")
    builder.adjust(1, 2, 1, 1, 1)
    return builder.as_markup()


def admin_stock_keyboard(promo_on: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕  إضافة حساب للمخزون",   callback_data="admin:add_stock")
    builder.button(text="📱  إضافة رقم مباشرة",     callback_data="admin:live_add")
    builder.button(text="📋  عرض وإلغاء الأرقام",   callback_data="admin:view_stock")
    builder.button(text="🔧  صيانة الحسابات",       callback_data="admin:maintenance_accounts")
    builder.button(text="🌍  إضافة دولة جديدة",     callback_data="admin:add_country")
    builder.button(text="💲  تغيير سعر دولة",       callback_data="admin:change_price")
    builder.button(text="⚡  فلاش سيل",             callback_data="admin:flash_sale")
    builder.button(text="🔍  فحص صحة الحسابات",     callback_data="admin:check_accounts")
    builder.button(text="🔙  رجوع",                 callback_data="admin:main")
    builder.adjust(1, 1, 2, 2, 2, 1)
    return builder.as_markup()


def admin_stock_type_keyboard(code: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💵  متجر الدولار (الرئيسي)", callback_data=f"stock_type:dollar:{code}")
    builder.button(text="🪙  متجر النقاط", callback_data=f"stock_type:points:{code}")
    builder.button(text="🔙  رجوع", callback_data="admin:stock")
    builder.adjust(1)
    return builder.as_markup()


def admin_links_keyboard(sell_enabled: bool = True, info_enabled: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📢  قناة الاشتراك الإجباري", callback_data="admin:set_force_sub")
    builder.button(text="🏪  رابط بيع الحسابات",      callback_data="admin:set_sell_url")
    builder.button(text="🎧  رابط الدعم الفني",       callback_data="admin:set_support_url")
    builder.button(text="💳  رابط شحن آخر",           callback_data="admin:set_topup_other_url")
    builder.button(text="📣  قناة الإشعارات",         callback_data="admin:set_notif_channel")
    builder.button(text="🟡  Binance Pay ID",          callback_data="admin:set_binance_uid")
    sell_toggle = "🟢  زر البيع: مفعّل" if sell_enabled else "🔴  زر البيع: معطّل"
    info_toggle = "🟢  زر المعلومات: مفعّل" if info_enabled else "🔴  زر المعلومات: معطّل"
    builder.button(text=sell_toggle, callback_data="admin:toggle_sell_btn")
    builder.button(text=info_toggle, callback_data="admin:toggle_info_btn")
    builder.button(text="➕  إضافة زر معلومات",       callback_data="admin:add_info_button")
    builder.button(text="🗑️  حذف زر معلومات",        callback_data="admin:del_info_button")
    builder.button(text="🔙  رجوع",                   callback_data="admin:main")
    builder.adjust(1, 2, 2, 1, 1, 2, 1, 1)
    return builder.as_markup()


def admin_stars_keyboard(check_enabled: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    toggle_text = "🟢 التحقق من مستوى النجوم (مفعّـل)" if check_enabled else "🔴 التحقق من مستوى النجوم (معطّـل)"
    builder.button(text=toggle_text,                   callback_data="admin:toggle_stars_check")
    builder.button(text="💱  سعر النجمة",              callback_data="admin:set_stars_rate")
    builder.button(text="⭐  الحد الأدنى للنجوم",      callback_data="admin:set_min_stars")
    builder.button(text="💲  الحد الأدنى بالدولار",    callback_data="admin:set_min_usd")
    builder.button(text="🔍  حساب فحص النجوم",         callback_data="admin:stars_checker")
    builder.button(text="🔓  إدارة إلغاء الحظر",        callback_data="admin:unban_menu")
    builder.button(text="🔙  رجوع",                    callback_data="admin:main")
    builder.adjust(1, 1, 2, 1, 1, 1)
    return builder.as_markup()


def admin_countries_keyboard(countries: List[Dict[str, Any]], action: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for c in countries:
        builder.button(
            text=f"{c.get('flag_emoji','🌍')}  {c['country_name']}",
            callback_data=f"{action}:{c['country_code']}",
        )
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙  رجوع", callback_data="admin:stock"))
    return builder.as_markup()


def code_actions_keyboard(
    account_id: int,
    lang: str,
    refetch_remaining: int = 2,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if refetch_remaining > 0:
        label = (
            f"🔄 إعادة جلب الكود ({refetch_remaining} متبقية)"
            if lang == "ar" else
            f"🔄 Re-fetch code ({refetch_remaining} left)"
        )
        builder.button(text=label, callback_data=f"code_refetch:{account_id}")
    builder.button(
        text="🚪 تسجيل الخروج من الحساب" if lang == "ar" else "🚪 Log out from account",
        callback_data=f"code_logout:{account_id}",
    )
    builder.adjust(1)
    return builder.as_markup()


def rating_keyboard(account_id: int, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    stars_map = ["⭐", "⭐⭐", "⭐⭐⭐", "⭐⭐⭐⭐", "⭐⭐⭐⭐⭐"]
    for i, label in enumerate(stars_map, start=1):
        builder.button(text=label, callback_data=f"rate:{account_id}:{i}")
    builder.button(
        text="⏭ تخطي" if lang == "ar" else "⏭ Skip",
        callback_data=f"rate:{account_id}:0",
    )
    builder.adjust(5, 1)
    return builder.as_markup()


def admin_flash_sale_keyboard(countries: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for c in countries:
        flag = c.get("flag_emoji", "🌍")
        builder.button(
            text=f"{flag} {c['country_name']}",
            callback_data=f"flash_set:{c['country_code']}",
        )
    builder.button(text="🧹 إلغاء كل الفلاش سيل", callback_data="flash_clear_all")
    builder.button(text="🔙 رجوع",                 callback_data="admin:stock")
    builder.adjust(2)
    return builder.as_markup()


def admin_back_keyboard(back_to: str = "admin:main") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙  رجوع", callback_data=back_to)
    return builder.as_markup()


def admin_info_buttons_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕  إضافة زر معلومات", callback_data="admin:add_info_button")
    builder.button(text="🗑️  حذف زر معلومات",  callback_data="admin:del_info_button")
    builder.button(text="🔙  رجوع",             callback_data="admin:links")
    builder.adjust(2, 1)
    return builder.as_markup()


def binance_manual_info_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅  دفعت المبلغ" if lang == "ar" else "✅  I Paid",
        callback_data="binance_manual:paid",
    )
    builder.button(text=t(lang, "btn_back"), callback_data="menu:topup")
    builder.adjust(1)
    return builder.as_markup()


def admin_binance_review_keyboard(payment_id: int, user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ موافقة — إضافة الرصيد",
        callback_data=f"admin_binance:approve:{payment_id}:{user_id}",
    )
    builder.button(
        text="❌ رفض",
        callback_data=f"admin_binance:reject:{payment_id}:{user_id}",
    )
    builder.button(
        text="🚫 حظر المستخدم",
        callback_data=f"admin_binance:ban:{payment_id}:{user_id}",
    )
    builder.adjust(1)
    return builder.as_markup()


# ── Sub-Admin ─────────────────────────────────────────────────────────────────

def sub_admin_panel_keyboard(perms: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if perms.get("stats"):
        builder.button(text="📊  الإحصائيات",        callback_data="sadmin:stats")
    if perms.get("stock"):
        builder.button(text="🗄️  إدارة المخزون",    callback_data="sadmin:stock")
    if perms.get("users"):
        builder.button(text="👥  إدارة المستخدمين",  callback_data="sadmin:users")
    if perms.get("broadcast"):
        builder.button(text="📢  إرسال برودكاست",   callback_data="sadmin:broadcast")
    builder.adjust(1)
    return builder.as_markup()


def sub_admin_list_keyboard(sub_admins: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for sa in sub_admins:
        label = sa.get("label") or str(sa["user_id"])
        builder.button(
            text=f"👤 {label}",
            callback_data=f"sadmin:view:{sa['user_id']}",
        )
    builder.button(text="➕ إضافة أدمن فرعي", callback_data="sadmin:add")
    builder.button(text="🔙 رجوع",             callback_data="admin:main")
    builder.adjust(1)
    return builder.as_markup()


def sub_admin_perms_keyboard(user_id: int, perms: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    perm_labels = {
        "stock":     "🗄️ إدارة المخزون",
        "users":     "👥 إدارة المستخدمين",
        "stats":     "📊 الإحصائيات",
        "deposits":  "💰 إشعارات الإيداعات",
        "broadcast": "📢 إرسال برودكاست",
    }
    for key, label in perm_labels.items():
        val = perms.get(key, False)
        icon = "✅" if val else "❌"
        builder.button(
            text=f"{icon} {label}",
            callback_data=f"sadmin:toggle:{user_id}:{key}",
        )
    builder.button(text="🗑️ حذف هذا الأدمن",   callback_data=f"sadmin:delete:{user_id}")
    builder.button(text="🔙 رجوع لقائمة الأدمن", callback_data="admin:sub_admins")
    builder.adjust(1)
    return builder.as_markup()
