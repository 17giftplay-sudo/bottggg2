# 📱 Telegram Accounts Store Bot (بوت متجر حسابات تيليجرام المتقدم)

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![aiogram](https://img.shields.io/badge/aiogram-3.17+-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-asyncpg-336791?style=for-the-badge&logo=postgresql&logoColor=white)
![aiohttp](https://img.shields.io/badge/aiohttp-3.10+-blue?style=for-the-badge&logo=aiohttp&logoColor=white)
![Cryptomus](https://img.shields.io/badge/Cryptomus-Pay-6C63FF?style=for-the-badge)
![Binance Pay](https://img.shields.io/badge/Binance-Pay-F0B90B?style=for-the-badge&logo=binance&logoColor=black)
![OxaPay](https://img.shields.io/badge/OxaPay-Gateway-00D09C?style=for-the-badge)
![Telegram Stars](https://img.shields.io/badge/Telegram-Stars-FFD700?style=for-the-badge)
![Railway](https://img.shields.io/badge/Deploy-Railway-0B0D0E?style=for-the-badge&logo=railway&logoColor=white)

**A complete, production-ready, automated Telegram Account Marketplace & Session Delivery Bot with Multi-Gateway Payments, Proxy & API Rotation, and Sub-Admin Management.**

**بوت متجر متكامل وتلقائي 100% لبيع حسابات تيليجرام وجلسات العمل، مع استلام تلقائي لرمز الدخول (OTP)، بوابات دفع متعددة، تدوير البروكسيات وبيانات API، ولوحة تحكم شاملة.**

---

</div>

## 📑 جدول المحتويات / Table of Contents

- [🌟 المميزات الرئيسية / Key Features](#-المميزات-الرئيسية--key-features)
- [🏗️ بنية المشروع / Project Architecture](#️-بنية-المشروع--project-architecture)
- [⚙️ متغيرات البيئة / Environment Variables](#️-متغيرات-البيئة--environment-variables)
- [🚀 خطوات التشغيل والنشر / Deployment Guide](#-خطوات-التشغيل-والنشر--deployment-guide)
  - [1. النشر على Railway / Deploying on Railway](#1-النشر-على-railway--deploying-on-railway)
  - [2. التشغيل على سيرفر محلي أو VPS / VPS & Local Setup](#2-التشغيل-على-سيرفر-محلي-أو-vps--vps--local-setup)
- [💳 إعداد بوابات الدفع / Payment Gateways Setup](#-إعداد-بوابات-الدفع--payment-gateways-setup)
- [📦 إضافة الحسابات والمخزون / Stock Management](#-إضافة-الحسابات-والمخزون--stock-management)
- [🛡️ الأمان وتدوير البروكسي / Security & Proxy Rotation](#️-الأمان-وتدوير-البروكسي--security--proxy-rotation)
- [👑 لوحة الأدمن والمساعدين / Admin & Sub-Admin Panel](#-لوحة-الأدمن-والمساعدين--admin--sub-admin-panel)
- [❓ الأسئلة الشائعة / FAQ](#-الأسئلة-الشائعة--faq)

---

## 🌟 المميزات الرئيسية / Key Features

### 1. 📲 التسليم التلقائي لرمز الدخول (Instant Auto OTP Delivery)
- يتصل البوت تلقائياً بالحساب المباع عبر مكتبة `Pyrogram` بمجرد إتمام الشراء.
- عند طلب المستخدم لرمز تسجيل الدخول عبر تيليجرام، يلتقط البوت الرسالة من محادثة تيليجرام الرسمية ويرسل كود التحقق للمشتري فوراً.
- دعم كلمة سر التحقق بخطوتين (2FA Password) التلقائية.
- استرداد تلقائي للأموال إلى رصيد المشتري في حال عدم وصول الكود خلال المهلة المحددة (120 ثانية).

### 2. 🗂️ دعم كافة أنواع الحسابات والجلسات (Sessions & TData Support)
- دعم الجلسات النصية (String Sessions).
- دعم ملفات `.session` بصيغة Pyrogram / Telethon.
- دعم رفع ملفات الجلسات ومجلدات TData بشكل جماعي عبر أرشيف ZIP من لوحة الأدمن.
- تحويل وتصدير تلقائي للجلسات.

### 3. 💳 بوابات دفع تلقائية متعددة (4 Payment Gateways)
- **Cryptomus:** دعم الدفع بالعملات الرقمية (USDT, TRX, TON, SOL, BTC, ETH...) مع تأكيد فوري عبر Webhook.
- **Binance Pay:** دعم الدفع المباشر عبر تطبيق بينانس.
- **OxaPay:** بوابة دفع كريبتو إضافية بدون قيود.
- **Telegram Stars (نجوم تيليجرام):** شحن الرصيد المباشر عبر نجوم تيليجرام المدمجة داخل التطبيق مع تحديد سعر الصرف من لوحة التحكم.

### 4. 🌐 تدوير البروكسيات وحسابات API (Proxy & API Rotation)
- **Proxy Pool:** دعم مجموعة بروكسيات لربط الحسابات مع مطابقة كود الدولة تلقائياً (`IP:PORT:USER:PASS:COUNTRY`).
- **API Pool:** تدوير أزواج `api_id` و `api_hash` لتفادي قيود تيليجرام وحماية الحسابات من الحظر.
- إمكانية تعيين `DEFAULT_API_ID` و `DEFAULT_API_HASH` عامين لتقليص حجم كود الحساب عند الإدخال.

### 5. 🛡️ الحماية ومكافحة السبام (Security & Anti-Flood)
- كابتشا مصورة ذكية (Image CAPTCHA) تمنع الروبوتات من استهلاك موارد البوت.
- نظام Throttling Middleware متقدم يمنع تكرار الضغط والسبام مع استجابة فائقة السرعة للأزرار وتجاوز تلقائي للأدمن.
- نظام قفل الحسابات المحظورة وحماية المعاملات المالية داخل PostgreSQL Transactions لمنع تكرار شحن الرصيد (Double-Spending Protection).

### 6. 👥 نظام المشرفين الفرعيين (Sub-Admin System)
- إمكانية إضافة وتعيين مشرفين فرعيين (Sub-Admins) مع تحديد صلاحيات دقيقة لكل مشرف (إدارة المخزون، إدارة المستخدمين، الإحصائيات، إلخ).

### 7. 📊 تقارير يومية ومراقبة القنوات (Daily Reports & Channel Monitor)
- تقرير إحصائي تلقائي يومي للأدمن يوضح الأرباح، عدد المبيعات، والمستخدمين الجدد.
- فحص الاشتراك الإجباري للقنوات ومراقبة خروج المستخدمين التلقائية.

---

## 🏗️ بنية المشروع / Project Architecture

```
├── bot.py                     # نقطة الانطلاق الرئيسية وتشغيل البوت وخادم الويب
├── config.py                  # تحميل وقراءة متغيرات البيئة وإعدادات البروكسي وAPI
├── database.py                # قاعدة بيانات PostgreSQL (asyncpg) بجميع الدوال والعمليات
├── generate_session.py        # سكربت لتوليد String Session للحسابات بسهولة
├── keyboards.py               # كيبوردات وتخطيطات أزرار المستخدم والأدمن
├── states.py                  # حالات FSM للمستخدمين ولوحة الإدارة
├── translations.py            # ملف الترجمة ثنائي اللغة (العربية 🇸🇦 والإنجليزية 🇺🇸)
├── web_app_ads.html           # تطبيق Web App مصغر اختياري للإعلانات
├── requirements.txt           # مكتبات بايثون المطلوبة
├── Procfile                   # ملف تشغيل المشروع على السحابة (Railway / Heroku)
├── handlers/                  # معالجات الأوامر والأحداث
│   ├── start.py               # أمر /start، الكابتشا، الاشتراك الإجباري
│   ├── buy.py                 # تصفح الدول وشراء الحسابات والتسليم التلقائي
│   ├── sessions_buy.py        # شراء واستلام ملفات الجلسات (.session)
│   ├── top_up_final.py        # شحن الرصيد وبوابات الدفع
│   ├── profile.py             # الملف الشخصي وسجل العمليات ونظام الإحالة
│   ├── admin.py               # لوحة الأدمن الرئيسية وإدارة المخزون والأسعار
│   ├── admin_sessions.py      # إدارة جلسات العمل ورفع ملفات ZIP
│   ├── sub_admin.py           # إدارة وتعيين المساعدين والصلاحيات
│   ├── code_actions.py        # طلب الكود وتأكيد استلام OTP
│   ├── daily_report.py        # التقارير اليومية للأرباح والمبيعات
│   └── channel_monitor.py     # مراقبة قنوات الاشتراك الإجباري
├── payments/                  # خوادم وبوابات الدفع الإلكتروني
│   ├── webhook_server.py      # خادم استقبال الويب هوك (Aiohttp Webhook Server)
│   ├── cryptomus.py           # تكامل Cryptomus API
│   ├── binance_pay.py         # تكامل Binance Pay API
│   └── oxapay.py              # تكامل OxaPay API
└── utils/                     # الأدوات المساعدة
    ├── captcha.py             # توليد صور الكابتشا
    ├── security_guard.py      # فحص الحسابات والأمان
    ├── session_converter.py   # تحويل صيغ الجلسات
    ├── session_delivery.py    # تسليم ملفات الجلسات للمشتري
    ├── session_manager.py     # إدارة اتصالات Pyrogram والتنظيف
    ├── stars_rating_checker.py# فحص ومعالجة نجوم تيليجرام
    └── zip_parser.py          # فك واستخراج ملفات ZIP للجلسات
```

---

## ⚙️ متغيرات البيئة / Environment Variables

قم بإعداد المتغيرات التالية في إعدادات الاستضافة (مثل Railway Variables أو ملف `.env`):

| المتغير / Variable | الوصف / Description | إجباري؟ / Required | مثال / Example |
|---|---|:---:|---|
| `BOT_TOKEN` | توكن البوت من [@BotFather](https://t.me/BotFather) | ✅ نعم | `1234567890:ABCdef...` |
| `DATABASE_URL` | رابط قاعدة بيانات PostgreSQL | ✅ نعم | `postgresql://user:pass@host:port/dbname` |
| `ADMIN_IDS` | معرفات تيليجرام للأدمن (مفصولة بفواصل) | ✅ نعم | `123456789,987654321` |
| `WEBHOOK_BASE_URL` | رابط النطاق الخارجي لاستقبال Webhooks الدفع | 💡 مستحسن | `https://your-app.up.railway.app` |
| `PORT` | المنفذ لخادم الويب الداخلي (الافتراضي: 8080) | ⚙️ اختياري | `8080` |
| `CRYPTOMUS_MERCHANT_ID` | معرّف التاجر في بوابة Cryptomus | 💳 اختياري | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `CRYPTOMUS_API_KEY` | مفتاح الدفع (Payment API Key) من Cryptomus | 💳 اختياري | `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| `BINANCE_PAY_API_KEY` | مفتاح API من حساب تاجر Binance Pay | 💳 اختياري | `binance_api_key_here` |
| `BINANCE_PAY_SECRET_KEY`| المفتاح السري من حساب تاجر Binance Pay | 💳 اختياري | `binance_secret_key_here` |
| `OXAPAY_MERCHANT_KEY` | المفتاح التجاري من بوابة OxaPay | 💳 اختياري | `sandbox` أو مفتاحك التجاري |
| `DEFAULT_API_ID` | معرف API افتراضي لحسابات تيليجرام | ⚙️ اختياري | `2040` |
| `DEFAULT_API_HASH` | كود API Hash افتراضي | ⚙️ اختياري | `b18441a1260828d0ed5d60f4eb70e775` |
| `API_POOL` | قائمة بأزواج API متعددة للتدوير | ⚙️ اختياري | `id1:hash1,id2:hash2,id3:hash3` |
| `PROXY_POOL` | قائمة بالبروكسيات للتدوير مع دعم الدول | ⚙️ اختياري | `ip:port:user:pass:US,ip:port:user:pass:GB` |

---

## 🚀 خطوات التشغيل والنشر / Deployment Guide

### 1. النشر على Railway / Deploying on Railway

1. افتح حساباً على [Railway.app](https://railway.app).
2. أنشئ مشروعاً جديداً **New Project** واختر **Provision PostgreSQL** لإنشاء قاعدة بيانات مجانية.
3. اضغط **+ New → GitHub Repo** واربط المستودع الحالي.
4. اذهب إلى تبويب **Variables** في الخدمة وأضف المتغيرات الأساسية:
   - `BOT_TOKEN`
   - `DATABASE_URL` (اربطه بمتغير `${{Postgres.DATABASE_URL}}`)
   - `ADMIN_IDS`
   - `WEBHOOK_BASE_URL` (رابط الدومين المجاني من قسم Networking في Railway)
5. سيتم تشغيل البوت تلقائياً بفضل ملف `Procfile` المدمج.

---

### 2. التشغيل على سيرفر محلي أو VPS / VPS & Local Setup

```bash
# 1. استنساخ المستودع
git clone https://github.com/17giftplay-sudo/bottggg2.git
cd bottggg2

# 2. إنشاء بيئة بايثون افتراضية وتفعيلها
python -m venv venv
# Linux / macOS:
source venv/bin/activate
# Windows:
.\venv\Scripts\activate

# 3. تثبيت المتطلبات
pip install -r requirements.txt

# 4. ضبط المتغيرات (مثال على Linux/macOS):
export BOT_TOKEN="your_bot_token"
export DATABASE_URL="postgresql://user:password@localhost:5432/botdb"
export ADMIN_IDS="123456789"

# 5. تشغيل البوت
python bot.py
```

---

## 💳 إعداد بوابات الدفع / Payment Gateways Setup

### 🔹 1. Cryptomus
- أنشئ حساباً على [Cryptomus.com](https://cryptomus.com).
- من لوحة التحكم، استخرج `Merchant ID` و `API Key`.
- عيّن رابط الـ Webhook في لوحة Cryptomus على:
  ```
  https://your-domain.com/webhook/cryptomus
  ```

### 🔹 2. Binance Pay
- أنشئ حساب تاجر على [Binance Merchant](https://merchant.binance.com).
- استخرج `API Key` و `Secret Key`.
- عيّن رابط الـ Webhook على:
  ```
  https://your-domain.com/webhook/binance
  ```

### 🔹 3. OxaPay
- أنشئ حساباً على [OxaPay.com](https://oxapay.com).
- احصل على `Merchant Key` وضعه في المتغير `OXAPAY_MERCHANT_KEY`.
- عيّن رابط الـ Webhook على:
  ```
  https://your-domain.com/webhook/oxapay
  ```

### 🔹 4. Telegram Stars (نجوم تيليجرام)
- تعمل بشكل تلقائي وتدمج مع بوتك مباشرة دون الحاجة لأي مفاتيح خارجية.
- يمكنك تعديل سعر صرف النجمة مقابل الدولار من داخل لوحة الأدمن في تيليجرام.

---

## 📦 إضافة الحسابات والمخزون / Stock Management

### الطريقة 1: توليد جلسة حساب فردي (Single Session String)
1. شغّل سكربت التوليد:
   ```bash
   python generate_session.py
   ```
2. أدخل رقم الهاتف والرمز المستلم من تيليجرام.
3. انسخ السطر الناتج بالشكل:
   ```
   +1234567890::12345::abc123hash::BQABAgAB...longsessionstring...
   ```
   *أو بالشكل المختصر في حال تفعيل `DEFAULT_API_ID`:*
   ```
   +1234567890::BQABAgAB...longsessionstring...
   ```
4. افتح البوت في تيليجرام وارسل `/admin` ← **إدارة المخزون** ← **إضافة حساب**.

### الطريقة 2: الرفع الجماعي كملف ZIP (Bulk ZIP Upload)
1. اجمع ملفات الجلسات `.session` أو مجلدات `tdata` في ملف مضغوط `.zip`.
2. افتح `/admin` ← **إدارة الجلسات** ← **رفع ملف ZIP**.
3. يقوم البوت تلقائياً بفك الضغط، وفحص الجلسات، وفرزها حسب الدولة، وإدراجها في قاعدة البيانات فوراً.

---

## 🛡️ الأمان وتدوير البروكسي / Security & Proxy Rotation

للحفاظ على الحسابات من الحظر وضمان سرعة التسليم، يدعم البوت بروكسيات SOCKS5 / HTTP:
- قم بتهيئة متغير `PROXY_POOL` كالتالي:
  ```env
  PROXY_POOL="1.2.3.4:8080:user:pass:US,5.6.7.8:8080:user:pass:EG,9.10.11.12:8080:user:pass"
  ```
- عند طلب كود لحساب برقم أمريكي `+1`، سيبحث البوت عن بروكسي أمريكي (`US`) أولاً لتقليل مخاطر الأمان في تيليجرام.

---

## 👑 لوحة الأدمن والمساعدين / Admin & Sub-Admin Panel

بإرسال أمر `/admin` في تيليجرام، تتاح لك الخيارات التالية:

- 💵 **إدارة الرصيد:** شحن أو خصم رصيد أي مستخدم بالـ ID وعرض تفاصيل حسابه.
- 🌍 **إدارة الدول والأسعار:** إضافة دول جديدة، تعديل سعر الحسابات لكل دولة، وتحديد الحد الأدنى للإيداع.
- 📦 **المخزون المباشر:** عرض الكميات المتوفرة وتصدير بيانات الحسابات وحذف الحسابات المباعة أو التالفة.
- 👥 **المساعدين (Sub-Admins):** إضافة وإزالة مشرفين فرعيين وتحديد صلاحياتهم لمنع الوصول للمعلومات الحساسة.
- 📢 **الاشتراك الإجباري:** تعيين قنوات يلزم الاشتراك بها قبل استخدام البوت.
- 📊 **الإحصائيات والتقارير:** استعراض إجمالي المستخدمين، المبيعات، الأرباح اليومية والشهرية، وتصدير التقارير.
- ⚙️ **وضع الصيانة (Maintenance Mode):** إيقاف البوت مؤقتاً للعامة أثناء التحديثات بنقرة زر.

---

## ❓ الأسئلة الشائعة / FAQ

**س: هل يتطلب البوت وجود تطبيق تيليجرام مفتوح لاستلام الكود؟**  
ج: لا، البوت يتصل بسيرفرات تيليجرام عبر بروتوكول MTProto مباشرة ويستلم الكود بشكل آلي بالكامل 24/7.

**س: ماذا يحدث إذا لم يستلم العميل الكود؟**  
ج: بعد مرور 120 ثانية، يقوم البوت بإلغاء الطلب وإرجاع كامل المبلغ تلقائياً إلى محفظة العميل داخل البوت.

**س: هل يدعم البوت التحقق بخطوتين (2FA)؟**  
ج: نعم، يدعم إضافة كلمة سر 2FA مع الحساب ويتم تسليمها للمشتري تلقائياً مع الكود.

---

<div align="center">

**Developed with ❤️ for high performance & reliability.**

</div>


<!-- Trigger Deploy 1788976477.4092464 -->