from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Premium Animated Emoji — Real IDs from Telegram
# For users WITH Premium → animated emoji plays
# For users WITHOUT Premium → fallback static emoji shows
# ─────────────────────────────────────────────────────────────────────────────
def _pe(emoji_id: str, fallback: str) -> str:
    return fallback


_E = {
    "fire":     _pe("5175145436574385802", "🔥"),
    "star":     _pe("5433670882604114909", "⭐"),
    "party":    _pe("6010608968982863617", "🎉"),
    "cool":     _pe("5904512599482965157", "✨"),
    "money":    _pe("5172879257210193582", "💳"),
    "diamond":  _pe("5433758796289685818", "💎"),
    "up":       _pe("5172748496930867424", "🔼"),
    "warning":  _pe("5172571638767551946", "⚠️"),
    "alarm":    _pe("5175046403218475179", "🚨"),
    "crown":    _pe("5433758796289685818", "👑"),
    "hundred":  _pe("5460966877238946001", "💯"),
    "cart":     _pe("5242609103527746759", "🛍️"),
    "mail":     _pe("5391287234794122328", "📩"),
    "salute":   _pe("6012468526613272811", "🫡"),
    "wave":     _pe("5798861029681142317", "👋"),
    "thumbup":  _pe("5472043065319366951", "👍"),
    "bolt":     _pe("5175145436574385802", "⚡"),
    "shield":   _pe("5172571638767551946", "🛡️"),
    "rocket":   _pe("5172748496930867424", "🚀"),
    "check":    _pe("5460966877238946001", "✅"),
}


_STRINGS: dict[str, dict[str, str]] = {
    "ar": {
        # ── الكابتشا ──────────────────────────────────────────────
        "captcha_prompt": (
            "🛡️ <b>التحقق من الهوية</b>\n\n"
            "🔢 أدخل الأرقام الظاهرة في الصورة:"
        ),
        "captcha_correct": f"{_E['party']} <b>ممتاز!</b> {_E['thumbup']}\n\nاختر لغتك:",
        "captcha_wrong": (
            f"{_E['warning']} <b>إجابة خاطئة!</b>\n\n"
            "🔄 المحاولات المتبقية: <b>{remaining}</b>\n"
            "🔢 أدخل الأرقام الظاهرة في الصورة:"
        ),
        "captcha_too_many_attempts": (
            f"{_E['alarm']} <b>تجاوزت عدد المحاولات المسموح بها.</b>\n\n"
            "🔁 أرسل /start للمحاولة مجدداً."
        ),

        # ── اللغة والترحيب ────────────────────────────────────────
        "choose_language": "🌍 اختر لغتك:",
        "change_language_prompt": "🌍 <b>اختر اللغة الجديدة:</b>",
        "welcome": (
            f"{_E['crown']} <b>أهلاً بك في المتجر الرسمي للخدمات الرقمية</b> {_E['cool']}\n"
            f"{_E['bolt']} <b>الوجهة الأولى والأسرع لشراء حسابات وجلسات تيليجرام</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🪪 <b>الآيدي:</b> <code>{user_id}</code>\n"
            f"{_E['diamond']} <b>الرصيد المتاح:</b> <b>${{balance:.2f}}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "👇 <b>اختر الخدمة المطلوبة من الأزرار أدناه:</b>"
        ),

        # ── الاشتراك الإجباري ─────────────────────────────────────
        "force_sub_message": (
            f"{_E['alarm']} <b>يجب الاشتراك في قناتنا أولاً</b> 🔒\n\n"
            "اشترك في القناة ثم اضغط ✅ تحقق من الاشتراك"
        ),
        "not_joined": f"{_E['warning']} لم تشترك في القناة بعد! اشترك ثم اضغط تحقق.",

        # ── الرصيد ────────────────────────────────────────────────
        "balance_menu": (
            f"{_E['diamond']} <b>تفاصيل محفظتك الرقمية</b> 💳\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{_E['money']}  <b>الرصيد المتاح:</b> <b>${{balance:.2f}}</b>\n"
            "📦  <b>عدد المشتريات:</b> <b>{purchases}</b>\n"
            "📊  <b>إجمالي الإيداعات:</b> <b>${total_deposited:.2f}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━"
        ),

        # ── الملف الشخصي ──────────────────────────────────────────
        "profile_menu": (
            f"{_E['crown']} <b>ملفك الشخصي (VIP)</b> {_E['cool']}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🪪  <b>المعرّف:</b> <code>{user_id}</code>\n"
            f"{_E['diamond']}  <b>الرصيد:</b> <b>${{balance:.2f}}</b>\n"
            "📦  <b>إجمالي المشتريات:</b> <b>{purchases}</b>\n"
            "📊  <b>إجمالي الإيداعات:</b> <b>${total_deposited:.2f}</b>\n"
            "📅  <b>تاريخ الانضمام:</b> <b>{joined_at}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━"
        ),
        "settings_not_configured": f"{_E['warning']} هذه الخاصية غير مضبوطة من قِبل المشرف.",

        # ── الصيانة ───────────────────────────────────────────────
        "maintenance": f"{_E['alarm']} <b>البوت في وضع الصيانة</b> ⚙️\n\nنعمل على تحسين الخدمة، عد لاحقاً.",

        # ── الشراء ────────────────────────────────────────────────
        "no_countries": (
            f"{_E['cart']} <b>متجر الحسابات</b>\n\n"
            f"{_E['warning']} لا توجد دول متاحة حالياً، حاول لاحقاً."
        ),
        "buy_menu": (
            f"{_E['cart']} <b>شراء حسابات تيليجرام</b>\n\n"
            f"{_E['money']} رصيدك: <b>${{balance:.2f}}</b>\n\n"
            "🌍 اختر الدولة:"
        ),
        "buy_search_prompt": "🔍 أرسل اسم الدولة للبحث:",
        "buy_search_no_results": f"{_E['warning']} لم يتم العثور على نتائج لـ «{{query}}».",
        "error_generic": f"{_E['warning']} حدث خطأ غير متوقع، حاول مجدداً.",
        "insufficient_balance": (
            f"{_E['alarm']} <b>رصيد غير كافٍ</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🏷️  السعر: <b>${price:.2f}</b>\n"
            f"{_E['money']}  رصيدك: <b>${{balance:.2f}}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{_E['up']} اشحن رصيدك ثم حاول مجدداً."
        ),
        "confirm_purchase": (
            f"{_E['cart']} <b>تأكيد الشراء</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🌍  الدولة: <b>{country}</b>\n"
            "🏷️  السعر: <b>${price:.2f}</b>\n"
            f"{_E['money']}  رصيدك: <b>${{balance:.2f}}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "هل تريد تأكيد الشراء؟"
        ),
        "no_stock_for_country": f"📦 نفد المخزون لهذه الدولة، حاول لاحقاً.",
        "purchase_success": (
            f"{_E['party']} <b>تم الشراء بنجاح!</b> {_E['hundred']}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🌍  الدولة: <b>{country}</b>\n"
            f"{_E['money']}  المدفوع: <b>${{price:.2f}}</b>\n"
            "💰  رصيدك المتبقي: <b>${balance:.2f}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📱 الرقم: <code>{phone}</code>\n\n"
            "⏳ <b>جاري انتظار كود تسجيل الدخول...</b>\n"
            "<i>سجّل الدخول بهذا الرقم الآن وسنرسل لك الكود تلقائياً.</i>\n\n"
            "💬 <b>ملاحظة:</b> إذا حدثت معك أي مشكلة، تواصل مع الدعم الفني وسيقوم بتعويضك بحساب جديد مباشرة! 🎧"
        ),

        # ── الشحن ─────────────────────────────────────────────────
        "topup_menu": (
            f"{_E['money']} <b>شحن الرصيد</b> 💳\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{_E['money']}  الحد الأدنى للإيداع: <b>${{min_usd:.2f}}</b>\n"
            "🔐  جميع المدفوعات مؤمّنة ومشفّرة\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⬇️ اختر طريقة الشحن:"
        ),
        "topup_enter_amount": (
            f"{_E['money']} <b>أدخل المبلغ المراد شحنه بالدولار:</b>\n\n"
            "📌 الحد الأدنى: <b>${min_usd:.2f}</b>\n\n"
            "<i>مثال: 5 أو 10.50</i>"
        ),
        "topup_amount_invalid": f"{_E['warning']} مبلغ غير صالح، أدخل رقماً صحيحاً.",
        "topup_amount_too_low": f"{_E['warning']} الحد الأدنى للشحن هو <b>${{min_usd:.2f}}</b>.",
        "topup_payment_created": (
            "⏳ <b>تم إنشاء طلب الدفع</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{_E['money']}  المبلغ: <b>${{amount:.2f}}</b>\n"
            "🏦  مزود الدفع: <b>{provider}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{_E['thumbup']} أكمل الدفع ثم انتظر التأكيد التلقائي"
        ),
        "topup_payment_failed": f"{_E['alarm']} فشل إنشاء طلب الدفع، حاول مجدداً.",
        "topup_payment_confirmed": (
            f"{_E['party']} <b>تم تأكيد الدفع!</b> {_E['hundred']}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{_E['money']}  المبلغ المُضاف: <b>${{amount:.2f}}</b>\n"
            "💰  رصيدك الجديد: <b>${new_balance:.2f}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━"
        ),
        "topup_stars_enter_amount": (
            f"{_E['star']} <b>أرسل عدد النجوم المراد شحنها:</b>\n\n"
            "📌 الحد الأدنى: <b>{min_stars} نجمة</b>\n"
            "💱 سعر النجمة: <b>${stars_rate:.4f}</b>\n\n"
            "<i>مثال: 100 أو 500</i>"
        ),
        "topup_stars_invalid": f"{_E['warning']} عدد نجوم غير صالح، أدخل رقماً صحيحاً.",
        "topup_stars_blocked_rating": (
            f"{_E['alarm']} <b>النجوم التي لديك غير صالحة للشحن</b>\n\n"
            "⚠️ تقييمك في تيليجرام سلبي حالياً، مما يعني أن النجوم المستخدمة قد تكون غير نظامية.\n\n"
            "⏳ <b>ملاحظة:</b> يتجدد التقييم تلقائياً كل <b>21 يوماً</b>. بعد انتهاء هذه المدة يمكنك المحاولة مجدداً.\n\n"
            "💳 <b>جرّب الشحن بإحدى الطرق الأخرى:</b>\n"
            "• Crypto (OxaPay)\n"
            "• Binance Pay\n"
            "• طرق الشحن الأخرى"
        ),
        "topup_stars_invoice_title": "شحن رصيد — نجوم تيليجرام",
        "topup_stars_invoice_desc": "شحن ${usd:.2f} بـ {stars} نجمة تيليجرام.",
        "topup_stars_label": "شحن رصيد",
        "topup_stars_confirmed": (
            f"{_E['party']} <b>تم قبول النجوم!</b> {_E['star']}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{_E['star']}  النجوم: <b>{{stars}}</b>\n"
            f"{_E['money']}  المُضاف: <b>${{amount:.2f}}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━"
        ),

        # ── الجلسة ────────────────────────────────────────────────
        "session_format_error": (
            f"{_E['warning']} <b>Session String غير صالح</b>\n\n"
            "الحساب الذي تم شراؤه يحتوي على session string بصيغة خاطئة "
            "(ليس Pyrogram v2).\n\n"
            f"{_E['money']} تم استرداد رصيدك تلقائياً.\n\n"
            "<i>إذا كنت البائع، أعد توليد الجلسة باستخدام generate_session.py</i>"
        ),
        "session_waiting": (
            "⏳ <b>جاري انتظار كود تسجيل الدخول...</b>\n\n"
            "📱 الرقم: <code>{phone}</code>\n"
            "⏱️ المهلة: <b>{timeout} ثانية (~5 دقائق)</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "📲 <b>ماذا تفعل الآن؟</b>\n\n"
            "1️⃣ افتح تطبيق <b>تيليجرام</b> على هاتفك\n"
            "2️⃣ اضغط <b>تسجيل الدخول</b>\n"
            "3️⃣ أدخل الرقم: <code>{phone}</code>\n"
            "4️⃣ عند سؤالك عن طريقة الاستلام اختر:\n"
            "   «<b>إرسال الكود إلى تطبيقي الآخر</b>»\n\n"
            "✅ <b>سيُرسل لك الكود هنا تلقائياً فور وصوله.</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━"
        ),
        "session_timeout": (
            f"{_E['alarm']} <b>انتهت المهلة ({300} ثانية)</b>\n\n"
            "لم يصل أي كود خلال الوقت المحدد.\n\n"
            "🔍 <b>الأسباب المحتملة:</b>\n"
            "• لم تُدخل الرقم في تطبيق تيليجرام\n"
            "• الجلسة انتهت صلاحيتها (حساب محذوف أو موقوف)\n\n"
            f"{_E['money']} تم استرداد رصيدك تلقائياً، حاول مجدداً."
        ),
        "session_success": (
            f"{_E['party']} <b>وصل الكود!</b> {_E['hundred']}\n\n"
            "🔑 <b>كود تسجيل الدخول:</b>\n\n"
            "<code>{code}</code>\n\n"
            "💬 <b>ملاحظة:</b> إذا حدثت معك أي مشكلة، تواصل مع الدعم الفني وسيقوم بتعويضك بحساب جديد مباشرة! 🎧"
        ),
        "session_error": (
            f"{_E['alarm']} <b>حساب غير صالح</b>\n\n"
            "تعذّر الاتصال بهذا الحساب.\n"
            f"{_E['money']} تم استرداد رصيدك تلقائياً."
        ),
        "session_network_error": (
            f"{_E['alarm']} <b>خطأ في الشبكة</b>\n\n"
            "تعذّر الاتصال بخوادم تيليجرام بعد عدة محاولات.\n"
            f"{_E['money']} تم استرداد رصيدك تلقائياً، حاول مجدداً لاحقاً."
        ),

        # ── سجل المشتريات ─────────────────────────────────────────
        "history_menu": (
            f"🗂️ <b>سجل مشترياتك</b> {_E['cart']}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "{items}"
            "━━━━━━━━━━━━━━━━━━━━━"
        ),
        "history_empty": (
            f"🗂️ <b>سجل المشتريات</b>\n\n"
            "لا توجد مشتريات بعد. 📭\n\n"
            f"{_E['cart']} ابدأ بشراء أول حساب من المتجر!"
        ),
        "history_item": "  {num}. {flag} {country}  —  💸 <b>${price:.2f}</b>  —  📅 {date}\n",

        # ── أزرار القائمة الرئيسية ────────────────────────────────
        "btn_buy":             "🛍️  شراء حساب تيليجرام",
        "btn_sessions":        "📦  شراء جلسات",
        "btn_topup":           "💰  شحن الرصيد",
        "btn_profile":         "🪪  ملفي الشخصي",
        "btn_sell":            "🏪  بيع حساب",
        "btn_support":         "🎧  الدعم الفني",
        "btn_info":            "ℹ️  معلومات",
        "btn_change_language": "🌍  اللغة",
        "btn_back":            "🔙  رجوع",
        "btn_history":         "📜  سجل مشترياتي",

        # ── أزرار عامة ────────────────────────────────────────────
        "btn_confirm":         "✅  تأكيد",
        "btn_cancel":          "❌  إلغاء",
        "btn_pay_now":         "💳  ادفع الآن",

        # ── أزرار الشحن ───────────────────────────────────────────
        "btn_stars":           "⭐  شحن بالنجوم",
        "btn_other_methods":   "🔄  طرق دفع أخرى",

        # ── أزرار القناة ──────────────────────────────────────────
        "btn_join_channel":    "📢  اشترك في القناة",
        "btn_check_join":      "🔍  تحقق من الاشتراك",

        # ── أزرار البحث ───────────────────────────────────────────
        "btn_search":          "🔎  بحث",

        # ── Binance Pay (مراجعة يدوية) ────────────────────────────
        "btn_binance_manual": "🟡  Binance Pay — USDT (يدوي 👨‍💻)",
        "btn_binance_pay":    "🟡  Binance Pay — USDT (يدوي 👨‍💻)",

        "topup_binance_ask_amount": (
            f"{_E['money']} <b>إيداع عبر Binance Pay — USDT</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{_E['money']}  الحد الأدنى: <b>${{min_usd:.2f}}</b>\n"
            "💱  العملة المقبولة: <b>USDT فقط</b>\n"
            "🛡️  التحقق: <b>مراجعة يدوية من الإدارة 👨‍💻</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "أدخل المبلغ الذي تريد إيداعه بالدولار $:"
        ),
        "topup_binance_info": (
            f"{_E['money']} <b>معلومات الدفع — Binance Pay</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{_E['money']}  المبلغ المطلوب: <b>${{amount:.2f}} USDT</b>\n"
            "💱  العملة: <b>USDT فقط</b>\n"
            "🏦  الشبكة: <b>Binance Pay ID</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔑 <b>معرّف المحفظة (Pay ID):</b>\n"
            "<code>{uid}</code>\n\n"
            f"{_E['warning']} <b>أرسل بالضبط ${{amount:.2f}} USDT عبر Binance Pay ID.</b>\n\n"
            f"بعد الإرسال اضغط {_E['thumbup']} <b>دفعت المبلغ</b> لإرسال الإثبات أو معرّف العملية."
        ),
        "topup_binance_enter_amount": (
            f"{_E['money']} <b>أدخل المبلغ الذي أرسلته بالدولار $</b>\n\n"
            "<i>مثال: 5 أو 10.50</i>"
        ),
        "topup_binance_enter_hash": (
            f"🔑 <b>إثبات عملية التحويل</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "📸 <b>يمكنك إرسال:</b>\n"
            "1️⃣ <b>صورة إيصال التحويل (Screenshot)</b> 🖼️\n"
            "2️⃣ أو كتابة <b>معرّف الطلب (Order ID / TxID)</b> نصياً 🔢\n\n"
            "مثال للمعّرف: <code>446615649192435712</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "👇 أرسل الصورة أو رقم المعاملة الآن:"
        ),
        "topup_binance_pending": (
            "⏳ <b>تم استلام طلب الشحن بنجاح!</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{_E['money']}  المبلغ: <b>${{amount:.2f}} USDT</b>\n"
            "🔑  الإثبات / المعرّف: <code>{tx_hash}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⏱️ طلبك قيد المراجعة حالياً من قِبل الإدارة، وسيتم إضافة الرصيد إلى حسابك فور التأكد."
        ),
        "topup_binance_approved": (
            f"{_E['party']} <b>تم قبول عملية الشحن وإضافة الرصيد!</b> {_E['hundred']}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{_E['money']}  المبلغ المُضاف: <b>${{amount:.2f}}</b>\n"
            "💰  رصيدك الجديد: <b>${new_balance:.2f}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"شكراً لاستخدامك البوت! {_E['fire']}"
        ),
        "topup_binance_rejected": (
            f"{_E['alarm']} <b>تم رفض طلب الشحن</b>\n\n"
            "لم يتم التحقق من عملية الدفع من قِبل الإدارة.\n"
            "تواصل مع الدعم الفني إذا كنت متأكداً من صحة التحويل."
        ),
    },

    "en": {
        # ── Captcha ───────────────────────────────────────────────
        "captcha_prompt": (
            "🛡️ <b>Identity Verification</b>\n\n"
            "🔢 Enter the numbers shown in the image:"
        ),
        "captcha_correct": f"{_E['party']} <b>Excellent!</b> {_E['thumbup']}\n\nChoose your language:",
        "captcha_wrong": (
            f"{_E['warning']} <b>Wrong answer!</b>\n\n"
            "🔄 Remaining attempts: <b>{remaining}</b>\n"
            "🔢 Enter the numbers shown in the image:"
        ),
        "captcha_too_many_attempts": (
            f"{_E['alarm']} <b>Too many failed attempts.</b>\n\n"
            "🔁 Send /start to try again."
        ),

        # ── Language & Welcome ────────────────────────────────────
        "choose_language": "🌍 Choose your language:",
        "change_language_prompt": "🌍 <b>Choose a new language:</b>",
        "welcome": (
            f"{_E['wave']} <b>Welcome to the Official Digital Store!</b> {_E['fire']}\n"
            "⚡ <b>Best & fastest bot for Telegram accounts & sessions.</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🪪 <b>User ID:</b> <code>{user_id}</code>\n"
            f"{_E['money']} <b>Balance:</b> <b>${{balance:.2f}}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "👇 <b>Choose from the menu below:</b>"
        ),

        # ── Force Subscribe ───────────────────────────────────────
        "force_sub_message": (
            f"{_E['alarm']} <b>You must join our channel first</b> 🔒\n\n"
            "Join the channel then press ✅ Verify"
        ),
        "not_joined": f"{_E['warning']} You haven't joined the channel yet!",



        # ── Balance ───────────────────────────────────────────────
        "balance_menu": (
            f"{_E['money']} <b>Your Balance</b> 💳\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{_E['money']}  Available: <b>${{balance:.2f}}</b>\n"
            "🔸  Points: <b>{points:.0f}</b>\n"
            "📦  Purchases: <b>{purchases}</b>\n"
            "📊  Total deposited: <b>${total_deposited:.2f}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━"
        ),

        # ── Profile ───────────────────────────────────────────────
        "profile_menu": (
            f"{_E['crown']} <b>Your Profile</b> {_E['cool']}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🪪  ID: <code>{user_id}</code>\n"
            f"{_E['money']}  Balance: <b>${{balance:.2f}}</b>\n"
            "🔸  Points: <b>{points}</b>\n"
            "📦  Purchases: <b>{purchases}</b>\n"
            "📊  Total deposited: <b>${total_deposited:.2f}</b>\n"
            "📅  Joined: <b>{joined_at}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━"
        ),
        "settings_not_configured": f"{_E['warning']} This feature has not been configured by the admin.",
        "maintenance": f"{_E['alarm']} <b>Bot is under maintenance</b> ⚙️\n\nWe are improving the service, check back later.",

        # ── Buy ───────────────────────────────────────────────────
        "no_countries": (
            f"{_E['cart']} <b>Account Store</b>\n\n"
            f"{_E['warning']} No countries available right now, try again later."
        ),
        "buy_menu": (
            f"{_E['cart']} <b>Buy Telegram Accounts</b>\n\n"
            f"{_E['money']} Your balance: <b>${{balance:.2f}}</b>\n\n"
            "🌍 Select a country:"
        ),
        "buy_search_prompt": "🔍 Send a country name to search:",
        "buy_search_no_results": f"{_E['warning']} No results found for «{{query}}».",
        "error_generic": f"{_E['warning']} An unexpected error occurred, please try again.",
        "insufficient_balance": (
            f"{_E['alarm']} <b>Insufficient Balance</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🏷️  Price: <b>${price:.2f}</b>\n"
            f"{_E['money']}  Your balance: <b>${{balance:.2f}}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{_E['up']} Top up your balance and try again."
        ),
        "confirm_purchase": (
            f"{_E['cart']} <b>Confirm Purchase</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🌍  Country: <b>{country}</b>\n"
            "🏷️  Price: <b>${price:.2f}</b>\n"
            f"{_E['money']}  Your balance: <b>${{balance:.2f}}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Confirm purchase?"
        ),
        "no_stock_for_country": "📦 Out of stock for this country, try again later.",
        "purchase_success": (
            f"{_E['party']} <b>Purchase Successful!</b> {_E['hundred']}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🌍  Country: <b>{country}</b>\n"
            f"{_E['money']}  Paid: <b>${{price:.2f}}</b>\n"
            "💰  Remaining: <b>${balance:.2f}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📱 Number: <code>{phone}</code>\n\n"
            "⏳ <b>Waiting for login code...</b>\n"
            "<i>Log in with this number now and we'll send you the code automatically.</i>"
        ),

        # ── Top Up ────────────────────────────────────────────────
        "topup_menu": (
            f"{_E['money']} <b>Top Up Balance</b> 💳\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{_E['money']}  Minimum deposit: <b>${{min_usd:.2f}}</b>\n"
            "🔐  All payments are secured & encrypted\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⬇️ Choose a payment method:"
        ),
        "topup_enter_amount": (
            f"{_E['money']} <b>Enter the amount to deposit in USD:</b>\n\n"
            "📌 Minimum: <b>${min_usd:.2f}</b>\n\n"
            "<i>Example: 5 or 10.50</i>"
        ),
        "topup_amount_invalid": f"{_E['warning']} Invalid amount, please enter a valid number.",
        "topup_amount_too_low": f"{_E['warning']} Minimum deposit is <b>${{min_usd:.2f}}</b>.",
        "topup_payment_created": (
            "⏳ <b>Payment request created</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{_E['money']}  Amount: <b>${{amount:.2f}}</b>\n"
            "🏦  Provider: <b>{provider}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{_E['thumbup']} Complete the payment and wait for automatic confirmation"
        ),
        "topup_payment_failed": f"{_E['alarm']} Failed to create payment request, try again.",
        "topup_payment_confirmed": (
            f"{_E['party']} <b>Payment Confirmed!</b> {_E['hundred']}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{_E['money']}  Amount added: <b>${{amount:.2f}}</b>\n"
            "💰  New balance: <b>${new_balance:.2f}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━"
        ),
        "topup_stars_enter_amount": (
            f"{_E['star']} <b>Enter the number of Stars to deposit:</b>\n\n"
            "📌 Minimum: <b>{min_stars} stars</b>\n"
            "💱 Rate: <b>${stars_rate:.4f} per star</b>\n\n"
            "<i>Example: 100 or 500</i>"
        ),
        "topup_stars_invalid": f"{_E['warning']} Invalid star count, please enter a valid number.",
        "topup_stars_blocked_rating": (
            f"{_E['alarm']} <b>Your stars are not eligible for deposit</b>\n\n"
            "⚠️ Your Telegram rating is currently negative, which means your stars may be irregular.\n\n"
            "⏳ <b>Note:</b> Ratings refresh automatically every <b>21 days</b>. You can try again after that period.\n\n"
            "💳 <b>Try depositing with another method:</b>\n"
            "• Crypto (OxaPay)\n"
            "• Binance Pay\n"
            "• Other top-up methods"
        ),
        "topup_stars_invoice_title": "Top Up — Telegram Stars",
        "topup_stars_invoice_desc": "Deposit ${usd:.2f} using {stars} Telegram Stars.",
        "topup_stars_label": "Deposit Balance",
        "topup_stars_confirmed": (
            f"{_E['party']} <b>Stars accepted!</b> {_E['star']}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{_E['star']}  Stars: <b>{{stars}}</b>\n"
            f"{_E['money']}  Added: <b>${{amount:.2f}}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━"
        ),

        # ── Session ───────────────────────────────────────────────
        "session_format_error": (
            f"{_E['warning']} <b>Invalid Session String</b>\n\n"
            "The purchased account contains a session string in the wrong format "
            "(not Pyrogram v2).\n\n"
            f"{_E['money']} Your balance has been refunded automatically.\n\n"
            "<i>If you are the seller, regenerate the session using generate_session.py</i>"
        ),
        "session_waiting": (
            "⏳ <b>Waiting for login code...</b>\n\n"
            "📱 Number: <code>{phone}</code>\n"
            "⏱️ Timeout: <b>{timeout} seconds (~5 min)</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "📲 <b>What to do now:</b>\n\n"
            "1️⃣ Open <b>Telegram</b> on your phone\n"
            "2️⃣ Tap <b>Log In</b>\n"
            "3️⃣ Enter the number: <code>{phone}</code>\n"
            "4️⃣ When asked how to receive the code, choose:\n"
            "   \"<b>Send code to my other device</b>\"\n\n"
            "✅ <b>The code will be sent to you here automatically.</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━"
        ),
        "session_timeout": (
            f"{_E['alarm']} <b>Timed out (300 seconds)</b>\n\n"
            "No login code arrived within the allowed time.\n\n"
            "🔍 <b>Possible reasons:</b>\n"
            "• You didn't enter the number in Telegram\n"
            "• Session expired (account deleted or banned)\n\n"
            f"{_E['money']} Your balance has been refunded automatically. Please try again."
        ),
        "session_success": (
            f"{_E['party']} <b>Code received!</b> {_E['hundred']}\n\n"
            "🔑 <b>Login Code:</b>\n\n"
            "<code>{code}</code>"
        ),
        "session_error": (
            f"{_E['alarm']} <b>Invalid account</b>\n\n"
            "Could not connect to this account.\n"
            f"{_E['money']} Your balance has been refunded automatically."
        ),
        "session_network_error": (
            f"{_E['alarm']} <b>Network error</b>\n\n"
            "Could not reach Telegram servers after several attempts.\n"
            f"{_E['money']} Your balance has been refunded automatically. Please try again later."
        ),

        # ── Purchase History ──────────────────────────────────────
        "history_menu": (
            f"🗂️ <b>Your Purchase History</b> {_E['cart']}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "{items}"
            "━━━━━━━━━━━━━━━━━━━━━"
        ),
        "history_empty": (
            f"🗂️ <b>Purchase History</b>\n\n"
            "No purchases yet. 📭\n\n"
            f"{_E['cart']} Start by buying your first account from the store!"
        ),
        "history_item": "  {num}. {flag} {country}  —  💸 <b>${price:.2f}</b>  —  📅 {date}\n",

        # ── Main Menu Buttons ─────────────────────────────────────
        "btn_buy":             "🛍️  Buy Telegram Account",
        "btn_sessions":        "📦  Buy Sessions",
        "btn_topup":           "💰  Top Up Balance",
        "btn_profile":         "🪪  My Profile",
        "btn_sell":            "🏪  Sell Account",
        "btn_support":         "🎧  Support",
        "btn_info":            "ℹ️  Information",
        "btn_change_language": "🌍  Language",
        "btn_back":            "🔙  Back",
        "btn_history":         "📜  Purchase History",

        # ── Common Buttons ────────────────────────────────────────
        "btn_confirm":         "✅  Confirm",
        "btn_cancel":          "❌  Cancel",
        "btn_pay_now":         "💳  Pay Now",

        # ── Top Up Buttons ────────────────────────────────────────
        "btn_stars":           "⭐  Pay with Stars",
        "btn_other_methods":   "🔄  Other Methods",

        # ── Channel Buttons ───────────────────────────────────────
        "btn_join_channel":    "📢  Join Channel",
        "btn_check_join":      "🔍  Verify Subscription",

        # ── Search Button ─────────────────────────────────────────
        "btn_search":          "🔎  Search",

        # ── Binance Pay (Auto-verify) ─────────────────────────────
        "btn_binance_manual": "🟡  Binance Pay — USDT (Manual)",
        "btn_binance_pay":    "🟡  Binance Pay — USDT (Manual)",

        "topup_binance_ask_amount": (
            f"{_E['money']} <b>Deposit via Binance Pay — USDT</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{_E['money']}  Minimum: <b>${{min_usd:.2f}}</b>\n"
            "💱  Accepted currency: <b>USDT only</b>\n"
            "🛡️  Verification: <b>Manual Admin Review 👨‍💻</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Enter the amount you want to deposit in USD $:"
        ),
        "topup_binance_info": (
            f"{_E['money']} <b>Payment Details — Binance Pay</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{_E['money']}  Required amount: <b>${{amount:.2f}} USDT</b>\n"
            "💱  Currency: <b>USDT only</b>\n"
            "🏦  Network: <b>Binance Pay ID</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔑 <b>Wallet ID (Pay ID):</b>\n"
            "<code>{uid}</code>\n\n"
            f"{_E['warning']} <b>Send exactly ${{amount:.2f}} USDT via Binance Pay ID.</b>\n\n"
            f"After sending, press {_E['thumbup']} <b>I Paid</b> to submit proof or Order ID."
        ),
        "topup_binance_enter_amount": (
            f"{_E['money']} <b>Enter the amount you sent in $</b>\n\n"
            "<i>Example: 5 or 10.50</i>"
        ),
        "topup_binance_enter_hash": (
            f"🔑 <b>Payment Proof Submission</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "📸 <b>You can send:</b>\n"
            "1️⃣ <b>Payment screenshot / receipt</b> 🖼️\n"
            "2️⃣ Or write your <b>Order ID / TxID</b> 🔢\n\n"
            "Example: <code>446615649192435712</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "👇 Send screenshot or transaction ID now:"
        ),
        "topup_binance_pending": (
            "⏳ <b>Top-up request submitted!</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{_E['money']}  Amount: <b>${{amount:.2f}} USDT</b>\n"
            "🔑  Proof / ID: <code>{tx_hash}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⏱️ Your request is under review by admin and balance will be added once confirmed."
        ),
        "topup_binance_approved": (
            f"{_E['party']} <b>Top-up Request Approved!</b> {_E['hundred']}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{_E['money']}  Amount added: <b>${{amount:.2f}}</b>\n"
            "💰  New balance: <b>${new_balance:.2f}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Thank you for using our bot! {_E['fire']}"
        ),
        "topup_binance_rejected": (
            f"{_E['alarm']} <b>Top-up Request Rejected</b>\n\n"
            "The payment could not be verified by administration.\n"
            "Contact support if you're sure the transfer was completed."
        ),
    },
    "fa": {
        # ── Captcha ───────────────────────────────────────────────
        "captcha_prompt": (
            "🛡️ <b>تأیید هویت</b>\n\n"
            "🔢 اعداد نمایش داده شده در تصویر را وارد کنید:"
        ),
        "captcha_correct": f"{_E['party']} <b>عالی!</b> {_E['thumbup']}\n\nزبان خود را انتخاب کنید:",
        "captcha_wrong": (
            f"{_E['warning']} <b>پاسخ اشتباه است!</b>\n\n"
            "🔄 فرصت‌های باقی‌مانده: <b>{remaining}</b>\n"
            "🔢 اعداد نمایش داده شده در تصویر را وارد کنید:"
        ),
        "captcha_too_many_attempts": (
            f"{_E['alarm']} <b>تعداد تلاش‌های ناموفق بیش از حد مجاز است.</b>\n\n"
            "🔁 برای تلاش مجدد دستور /start را ارسال کنید."
        ),

        # ── Language & Welcome ────────────────────────────────────
        "choose_language": "🌍 زبان خود را انتخاب کنید:",
        "change_language_prompt": "🌍 <b>زبان جدید را انتخاب کنید:</b>",
        "welcome": (
            f"{_E['wave']} <b>به فروشگاه رسمی خدمات دیجیتال خوش آمدید!</b> {_E['fire']}\n"
            "⚡ <b>سریع‌ترین ربات خرید اکانت و سشن تلگرام.</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🪪 <b>شناسه:</b> <code>{user_id}</code>\n"
            f"{_E['money']} <b>موجودی:</b> <b>${{balance:.2f}}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "👇 <b>از منوی زیر انتخاب کنید:</b>"
        ),

        # ── Force Subscribe ───────────────────────────────────────
        "force_sub_message": (
            f"{_E['alarm']} <b>لطفاً ابتدا در کانال ما عضو شوید</b> 🔒\n\n"
            "پس از عضویت در کانال، دکمه ✅ بررسی عضویت را بزنید"
        ),
        "not_joined": f"{_E['warning']} شما هنوز در کانال عضو نشده‌اید!",

        # ── Balance ───────────────────────────────────────────────
        "balance_menu": (
            f"{_E['money']} <b>موجودی حساب شما</b> 💳\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{_E['money']}  موجودی قابل استفاده: <b>${{balance:.2f}}</b>\n"
            "🔸  امتیاز: <b>{points:.0f}</b>\n"
            "📦  تعداد خریدها: <b>{purchases}</b>\n"
            "📊  مجموع شارژ: <b>${total_deposited:.2f}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━"
        ),

        # ── Profile ───────────────────────────────────────────────
        "profile_menu": (
            f"{_E['crown']} <b>پروفایل کاربری</b> {_E['cool']}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🪪  شناسه: <code>{user_id}</code>\n"
            f"{_E['money']}  موجودی: <b>${{balance:.2f}}</b>\n"
            "🔸  امتیاز: <b>{points}</b>\n"
            "📦  خریدها: <b>{purchases}</b>\n"
            "📊  مجموع واریزها: <b>${total_deposited:.2f}</b>\n"
            "📅  تاریخ عضویت: <b>{joined_at}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━"
        ),
        "settings_not_configured": f"{_E['warning']} این بخش توسط مدیریت تنظیم نشده است.",
        "maintenance": f"{_E['alarm']} <b>ربات در حال به‌روزرسانی است</b> ⚙️\n\nلطفاً دقایقی دیگر مراجعه فرمایید.",

        # ── Buy ───────────────────────────────────────────────────
        "no_countries": (
            f"{_E['cart']} <b>فروشگاه اکانت</b>\n\n"
            f"{_E['warning']} در حال حاضر کشوری در دسترس نیست، لطفاً بعداً تلاش کنید."
        ),
        "buy_menu": (
            f"{_E['cart']} <b>خرید اکانت‌های تلگرام</b>\n\n"
            f"{_E['money']} موجودی شما: <b>${{balance:.2f}}</b>\n\n"
            "🌍 کشور مورد نظر را انتخاب کنید:"
        ),
        "buy_search_prompt": "🔍 نام کشور را برای جستجو ارسال کنید:",
        "buy_search_no_results": f"{_E['warning']} نتیجه‌ای برای «{{query}}» یافت نشد.",
        "error_generic": f"{_E['warning']} خطای غیرمنتظره‌ای رخ داد، لطفاً دوباره تلاش کنید.",
        "insufficient_balance": (
            f"{_E['alarm']} <b>موجودی ناکافی است</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🏷️  قیمت: <b>${price:.2f}</b>\n"
            f"{_E['money']}  موجودی شما: <b>${{balance:.2f}}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{_E['up']} لطفاً حساب خود را شارژ کرده و دوباره تلاش کنید."
        ),
        "confirm_purchase": (
            f"{_E['cart']} <b>تأیید خرید</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🌍  کشور: <b>{country}</b>\n"
            "🏷️  قیمت: <b>${price:.2f}</b>\n"
            f"{_E['money']}  موجودی: <b>${{balance:.2f}}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "آیا مایل به تأیید خرید هستید؟"
        ),
        "no_stock_for_country": f"📦 موجودی این کشور به پایان رسیده است.",
        "purchase_success": (
            f"{_E['party']} <b>خرید با موفقیت انجام شد!</b> {_E['hundred']}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🌍  کشور: <b>{country}</b>\n"
            f"{_E['money']}  پرداخت شده: <b>${{price:.2f}}</b>\n"
            "💰  موجودی باقی‌مانده: <b>${balance:.2f}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📱 شماره: <code>{phone}</code>\n\n"
            "⏳ <b>در انتظار کد ورود...</b>\n"
            "<i>اکنون با این شماره وارد شوید؛ کد ورود به صورت خودکار برای شما ارسال خواهد شد.</i>\n\n"
            "💬 <b>نکته:</b> در صورت بروز هرگونه مشکل، با پشتیبانی تماس بگیرید تا فوراً اکانت جایگزین دریافت کنید! 🎧"
        ),

        # ── Top Up ────────────────────────────────────────────────
        "topup_menu": (
            f"{_E['money']} <b>افزایش موجودی و شارژ حساب</b> 💳\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{_E['money']}  حداقل مبلغ شارژ: <b>${{min_usd:.2f}}</b>\n"
            "🔐  تمامی پرداخت‌ها امن و خودکار هستند\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⬇️ روش پرداخت را انتخاب کنید:"
        ),
        "topup_enter_amount": (
            f"{_E['money']} <b>مبلغ مورد نظر را به دلار وارد کنید:</b>\n\n"
            "📌 حداقل مبلغ: <b>${min_usd:.2f}</b>\n\n"
            "<i>مثال: 5 یا 10.50</i>"
        ),
        "topup_amount_invalid": f"{_E['warning']} مبلغ نامعتبر است، لطفاً یک عدد صحیح وارد کنید.",
        "topup_amount_too_low": f"{_E['warning']} حداقل مبلغ شارژ <b>${{min_usd:.2f}}</b> است.",

        # ── Session & Waiting ─────────────────────────────────────
        "session_waiting": (
            "⏳ <b>در انتظار کد ورود...</b>\n\n"
            "📱 شماره: <code>{phone}</code>\n"
            "⏱️ مهلت زمان: <b>{timeout} ثانیه</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "✅ <b>کد ورود به محض دریافت در اینجا ارسال خواهد شد.</b>"
        ),
        "session_success": (
            f"{_E['party']} <b>کد دریافت شد!</b> {_E['hundred']}\n\n"
            "🔑 <b>کد ورود:</b>\n\n"
            "<code>{code}</code>\n\n"
            "💬 <b>نکته:</b> در صورت بروز هرگونه مشکل، با پشتیبانی تماس بگیرید تا فوراً اکانت جایگزین دریافت کنید! 🎧"
        ),
        "session_timeout": (
            f"{_E['alarm']} <b>مهلت زمانی به پایان رسید</b>\n\n"
            f"{_E['money']} مبلغ پرداختی به موجودی شما بازگردانده شد."
        ),
        "session_error": (
            f"{_E['alarm']} <b>خطا در اکانت</b>\n\n"
            f"{_E['money']} مبلغ به موجودی شما بازگردانده شد."
        ),

        # ── Buttons ───────────────────────────────────────────────
        "btn_buy":             "🛍️  خرید اکانت تلگرام",
        "btn_sessions":        "📦  خرید سشن تلگرام",
        "btn_topup":           "💰  افزایش موجودی",
        "btn_profile":         "🪪  پروفایل کاربری",
        "btn_support":         "🎧  پشتیبانی",
        "btn_info":            "ℹ️  اطلاعات",
        "btn_change_language": "🌍  تغییر زبان",
        "btn_back":            "🔙  بازگشت",
        "btn_history":         "📜  تاریخچه خریدها",
        "btn_confirm":         "✅  تأیید",
        "btn_cancel":          "❌  لغو",
        "btn_pay_now":         "💳  پرداخت اکنون",
        "btn_stars":           "⭐  شارژ با استارز (Telegram Stars)",
        "btn_other_methods":   "🔄  سایر روش‌های پرداخت",
        "btn_join_channel":    "📢  عضویت در کانال",
        "btn_check_join":      "🔍  بررسی عضویت",
        "btn_search":          "🔎  جستجو",
        "btn_binance_pay":    "🟡  Binance Pay — USDT (خودکار ⚡)",
        "btn_binance_manual": "🟡  Binance Pay — دستی",
    },
}


def t(lang: str, key: str, **kwargs: Any) -> str:
    lang = lang if lang in _STRINGS else "en"
    text = _STRINGS[lang].get(key) or _STRINGS["en"].get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return text
