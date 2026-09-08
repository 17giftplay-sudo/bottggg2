import json
import logging

import aiohttp
from aiohttp import web

from database import confirm_payment
from payments.cryptomus import verify_webhook as cm_verify, is_paid as cm_is_paid
from payments.binance_pay import verify_webhook as bp_verify, is_paid as bp_is_paid
from payments.oxapay import verify_webhook as oxa_verify

logger = logging.getLogger(__name__)

_MAX_BODY_BYTES = 64 * 1024
_bot = None


def set_bot(bot):
    global _bot
    _bot = bot


async def _get_user_lang(user_id: int) -> str:
    from database import get_user
    user = await get_user(user_id)
    return user.get("language", "ar") if user else "ar"


async def _notify_user(user_id: int, amount: float, lang: str = "ar"):
    if _bot is None:
        return
    from translations import t
    from keyboards import main_menu_keyboard
    from database import get_user, get_setting
    from config import ADMIN_IDS

    try:
        user = await get_user(user_id)
        balance = float(user.get("balance", 0)) if user else 0.0
        points  = int(user.get("points", 0))     if user else 0

        await _bot.send_message(
            user_id,
            t(lang, "topup_payment_confirmed", amount=amount, new_balance=balance),
            parse_mode="HTML",
        )
        sell_enabled = (await get_setting("sell_btn_enabled") or "1") == "1"
        info_enabled = (await get_setting("info_btn_enabled") or "1") == "1"

        await _bot.send_message(
            user_id,
            t(lang, "welcome", user_id=user_id, balance=balance, points=points),
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(lang, sell_enabled=sell_enabled, info_enabled=info_enabled),
        )

        if user:
            username   = user.get("username") or ""
            first_name = user.get("first_name") or "مجهول"
            user_mention = f"@{username}" if username else f"<a href='tg://user?id={user_id}'>{first_name}</a>"
        else:
            user_mention = f"<a href='tg://user?id={user_id}'>{user_id}</a>"

        admin_text = (
            "💰 <b>إيداع جديد!</b>\n\n"
            f"👤 المستخدم: {user_mention}\n"
            f"🆔 المعرف: <code>{user_id}</code>\n"
            f"💵 المبلغ: <b>${amount:.2f} USD</b>\n"
            f"💳 الرصيد الحالي: <b>${balance:.2f} USD</b>"
        )

        for admin_id in ADMIN_IDS:
            try:
                await _bot.send_message(admin_id, admin_text, parse_mode="HTML")
            except Exception as e:
                logger.warning("Could not notify admin %s: %s", admin_id, e)

    except Exception as e:
        logger.warning("Could not notify user %s: %s", user_id, e)


# ── Cryptomus ─────────────────────────────────────────────────────────────────

async def handle_cryptomus(request: web.Request) -> web.Response:
    ip = request.remote or "unknown"
    if _is_rate_limited(ip):
        logger.warning("Cryptomus webhook: rate limited IP %s", ip)
        return web.Response(status=429, text="Too many requests")

    if request.content_length and request.content_length > _MAX_BODY_BYTES:
        return web.Response(status=413, text="Payload too large")

    try:
        body_bytes = await request.read()
        if len(body_bytes) > _MAX_BODY_BYTES:
            return web.Response(status=413, text="Payload too large")
        payload = json.loads(body_bytes)
    except json.JSONDecodeError as e:
        logger.warning("Cryptomus webhook: invalid JSON — %s | raw: %.200s", e, body_bytes)
        return web.Response(status=400, text="Bad JSON")
    except Exception as e:
        logger.warning("Cryptomus webhook: read error — %s", e)
        return web.Response(status=400, text="Bad request")

    logger.info("Cryptomus webhook received")

    if not cm_verify(payload):
        logger.warning("Cryptomus webhook: invalid signature")
        return web.Response(status=403, text="Bad signature")

    if not cm_is_paid(payload):
        return web.Response(text="ok")

    order_id = payload.get("order_id")
    if not order_id:
        return web.Response(status=400, text="Missing order_id")

    payment = await confirm_payment(order_id)
    if payment is None:
        return web.Response(text="ok")

    lang = await _get_user_lang(payment["user_id"])
    await _notify_user(payment["user_id"], float(payment["amount_usd"]), lang)
    logger.info("Cryptomus confirmed: order=%s user=%s amount=%.2f",
                order_id, payment["user_id"], float(payment["amount_usd"]))
    return web.Response(text="ok")


# ── OxaPay ────────────────────────────────────────────────────────────────────

async def handle_oxapay(request: web.Request) -> web.Response:
    ip = request.remote or "unknown"
    if _is_rate_limited(ip):
        logger.warning("OxaPay webhook: rate limited IP %s", ip)
        return web.Response(status=429, text="Too many requests")

    try:
        body_bytes = await request.read()
        if len(body_bytes) > _MAX_BODY_BYTES:
            return web.Response(status=413, text="Payload too large")
        data = json.loads(body_bytes)
    except json.JSONDecodeError as e:
        logger.warning("OxaPay webhook: invalid JSON — %s | raw: %.200s", e, body_bytes)
        return web.Response(text="error", status=400)
    except Exception as e:
        logger.warning("OxaPay webhook: read error — %s", e)
        return web.Response(text="error", status=400)

    received_hmac = request.headers.get("HMAC", "")
    if not oxa_verify(body_bytes, received_hmac):
        logger.warning("OxaPay webhook: invalid HMAC — rejected")
        return web.Response(status=403, text="Bad signature")

    logger.info("OxaPay webhook verified")

    status = data.get("status", "")
    if status != "Paid":
        logger.info("OxaPay webhook: status=%s — ignoring", status)
        return web.Response(text="OK")

    order_id = data.get("orderId") or data.get("order_id")
    if not order_id:
        logger.warning("OxaPay webhook: missing orderId")
        return web.Response(status=400, text="Missing orderId")

    payment = await confirm_payment(order_id)
    if payment is None:
        logger.info("OxaPay: already confirmed or not found: %s", order_id)
        return web.Response(text="OK")

    user_id = payment["user_id"]
    amount  = float(payment["amount_usd"])
    lang    = await _get_user_lang(user_id)
    await _notify_user(user_id, amount, lang)
    logger.info("OxaPay confirmed: order=%s user=%s amount=%.2f", order_id, user_id, amount)
    return web.Response(text="OK")


# ── Binance Pay ───────────────────────────────────────────────────────────────

async def handle_binance(request: web.Request) -> web.Response:
    ip = request.remote or "unknown"
    if _is_rate_limited(ip):
        logger.warning("Binance webhook: rate limited IP %s", ip)
        return web.json_response({"returnCode": "FAIL", "returnMessage": "Too many requests"}, status=429)

    if request.content_length and request.content_length > _MAX_BODY_BYTES:
        return web.json_response({"returnCode": "FAIL", "returnMessage": "Payload too large"}, status=413)

    timestamp = request.headers.get("BinancePay-Timestamp", "")
    nonce     = request.headers.get("BinancePay-Nonce", "")
    signature = request.headers.get("BinancePay-Signature", "")

    body_bytes = await request.read()
    if len(body_bytes) > _MAX_BODY_BYTES:
        return web.json_response({"returnCode": "FAIL", "returnMessage": "Payload too large"}, status=413)
    body_str = body_bytes.decode()

    if not bp_verify(timestamp, nonce, body_str, signature):
        logger.warning("Binance Pay webhook: invalid signature")
        return web.json_response({"returnCode": "FAIL", "returnMessage": "Bad signature"}, status=403)

    try:
        payload = json.loads(body_str)
    except json.JSONDecodeError as e:
        logger.warning("Binance webhook: invalid JSON — %s | raw: %.200s", e, body_str)
        return web.json_response({"returnCode": "FAIL", "returnMessage": "Bad JSON"}, status=400)

    logger.info("Binance Pay webhook received")

    if not bp_is_paid(payload):
        return web.json_response({"returnCode": "SUCCESS", "returnMessage": None})

    biz_data = {}
    if payload.get("data"):
        try:
            biz_data = json.loads(payload["data"])
        except json.JSONDecodeError as e:
            logger.warning("Binance webhook: could not parse biz_data — %s", e)

    order_id = biz_data.get("merchantTradeNo") or payload.get("bizIdStr", "")
    if not order_id:
        return web.json_response({"returnCode": "FAIL", "returnMessage": "Missing order_id"}, status=400)

    payment = await confirm_payment(order_id)
    if payment is None:
        return web.json_response({"returnCode": "SUCCESS", "returnMessage": None})

    lang = await _get_user_lang(payment["user_id"])
    await _notify_user(payment["user_id"], float(payment["amount_usd"]), lang)
    logger.info("Binance Pay confirmed: order=%s user=%s amount=%.2f",
                order_id, payment["user_id"], float(payment["amount_usd"]))
    return web.json_response({"returnCode": "SUCCESS", "returnMessage": None})


# ── فحص IP من الخادم (server-side) ───────────────────────────────────────────
#
# الفحص يتم على الخادم لتجنب مشاكل CORS والحجب في المتصفح.
# الخادم يقرأ IP المستخدم من headers الطلب ويفحصه عبر ipwho.is أو ipapi.co.
# الـ WebApp يستدعي /ref-ip-info (نفس الخادم) ثم يرسل النتيجة للبوت.

import secrets
import time as _time

# ── نظام الـ Nonce لحماية /ref-ip-info ────────────────────────────────────────
# بدلاً من تضمين التوكن السري في HTML (يظهر في سورس الصفحة)،
# نُولّد nonce عشوائياً لكل طلب على /ref-ip-check ونحفظه مؤقتاً (30 ثانية).
# الـ JS يُرسل هذا الـ nonce عند استدعاء /ref-ip-info، وبعد الاستخدام يُحذف.
_active_nonces: dict = {}  # {nonce: expiry_timestamp}
_NONCE_TTL = 30  # ثانية


def _cleanup_expired_nonces():
    now = _time.time()
    expired = [k for k, v in _active_nonces.items() if v < now]
    for k in expired:
        del _active_nonces[k]


_REF_IP_CHECK_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>فحص الموقع الجغرافي</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: var(--tg-theme-bg-color, #fff);
    color: var(--tg-theme-text-color, #000);
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    min-height: 100vh; padding: 24px; text-align: center;
  }
  .spinner {
    width: 48px; height: 48px;
    border: 4px solid rgba(0,0,0,0.1);
    border-top-color: var(--tg-theme-button-color, #2481cc);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin-bottom: 20px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .msg { font-size: 16px; line-height: 1.6; }
  .ok  { color: #27ae60; font-size: 40px; margin-bottom: 12px; }
  .err { color: #e74c3c; font-size: 40px; margin-bottom: 12px; }
</style>
</head>
<body>
<div id="app">
  <div class="spinner"></div>
  <div class="msg">جاري فحص موقعك الجغرافي...<br><small>لا تغلق هذه الصفحة</small></div>
</div>
<script>
const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

async function checkIP() {
  try {
    // الـ nonce مؤقت (30 ثانية) — لا يُكشف أي سر دائم في المصدر
    const nonce = "%%NONCE%%";
    const res = await fetch(`/ref-ip-info?nonce=${nonce}`, {
      cache: "no-store",
      headers: { "X-Requested-With": "TelegramWebApp" }
    });
    const d = await res.json();
    sendResult(d);
  } catch (e) {
    sendResult({ ip: "", country: "__FAIL__", vpn: false });
  }
}

function sendResult(payload) {
  const app = document.getElementById("app");
  if (payload.vpn) {
    app.innerHTML = '<div class="err">⚠️</div><div class="msg">تم رصد VPN أو Proxy</div>';
  } else if (!payload.country || payload.country === "__FAIL__") {
    app.innerHTML = '<div class="err">❌</div><div class="msg">تعذّر فحص الموقع</div>';
  } else {
    app.innerHTML = '<div class="ok">✅</div><div class="msg">تم التحقق بنجاح</div>';
  }
  setTimeout(() => {
    tg.sendData(JSON.stringify(payload));
    tg.close();
  }, 900);
}

checkIP();
</script>
</body>
</html>"""


async def handle_ref_ip_check(request: web.Request) -> web.Response:
    """يُولّد nonce عشوائياً لكل طلب ويُضمّنه في HTML بدلاً من التوكن السري."""
    _cleanup_expired_nonces()
    nonce = secrets.token_urlsafe(32)
    _active_nonces[nonce] = _time.time() + _NONCE_TTL
    html = _REF_IP_CHECK_HTML.replace("%%NONCE%%", nonce)
    return web.Response(text=html, content_type="text/html", charset="utf-8")


# ── Rate Limiter بسيط للـ Webhooks ────────────────────────────────────────────
_webhook_rate: dict = {}   # {ip: [timestamp, ...]}
_RATE_WINDOW  = 60         # ثانية
_RATE_LIMIT   = 30         # أقصى طلب في الدقيقة لكل IP


def _is_rate_limited(ip: str) -> bool:
    now   = _time.time()
    hits  = _webhook_rate.get(ip, [])
    hits  = [t for t in hits if now - t < _RATE_WINDOW]
    if len(hits) >= _RATE_LIMIT:
        _webhook_rate[ip] = hits
        return True
    hits.append(now)
    _webhook_rate[ip] = hits
    return False


async def handle_ref_ip_info(request: web.Request) -> web.Response:
    """
    يقرأ IP المستخدم ويفحصه server-side.
    يُرجع JSON: { ip, country, vpn }

    الحماية: نتحقق من nonce مؤقت يُولَّد عند تقديم صفحة /ref-ip-check.
    الـ nonce صالح لمرة واحدة فقط (single-use) ومدته 30 ثانية،
    لذلك حتى لو رأى أحد المصدر، لن يستطيع إعادة الاستخدام.
    """
    nonce = (
        request.query.get("nonce", "")
        or request.headers.get("X-Nonce", "")
    )
    if not nonce or nonce not in _active_nonces:
        logger.warning("ref-ip-info: invalid or expired nonce from %s", request.remote)
        return web.json_response({"error": "Unauthorized"}, status=403)

    # استخدام الـ nonce مرة واحدة فقط ثم احذفه
    if _active_nonces.get(nonce, 0) < _time.time():
        del _active_nonces[nonce]
        return web.json_response({"error": "Nonce expired"}, status=403)
    del _active_nonces[nonce]

    # آخر IP في X-Forwarded-For هو الذي أضافه الـ proxy الموثوق (Railway / Nginx)
    # أما أول IP فيمكن للمستخدم تزويره بسهولة
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",")]
        ip = parts[-1]  # الأخير = proxy موثوق، الأول = قابل للتزوير
    else:
        ip = request.headers.get("X-Real-IP", "") or str(request.remote or "")

    country = ""
    is_vpn  = False

    if ip:
        # المحاولة الأولى: ipwho.is
        try:
            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"https://ipwho.is/{ip}") as resp:
                    data = await resp.json(content_type=None)
                    if data.get("success") and data.get("country_code"):
                        country = data["country_code"]
                        is_vpn  = data.get("type") in ("Tor", "Proxy")
        except Exception as e:
            logger.debug("IP lookup (ipwho.is) failed for %s: %s", ip, e)

        # المحاولة الثانية: ipapi.co
        if not country:
            try:
                timeout = aiohttp.ClientTimeout(total=8)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(f"https://ipapi.co/{ip}/json/") as resp:
                        data = await resp.json(content_type=None)
                        if data.get("country_code") and not data.get("error"):
                            country = data["country_code"]
            except Exception as e:
                logger.debug("IP lookup (ipapi.co) failed for %s: %s", ip, e)

    result = {"ip": ip, "country": country or "__FAIL__", "vpn": is_vpn}
    logger.info("IP check: ip=%s country=%s vpn=%s", ip, result["country"], is_vpn)
    # لا نرسل Access-Control-Allow-Origin: * لأن ذلك يتيح لأي موقع قراءة بيانات IP المستخدم
    return web.json_response(result)


# ── Health check ──────────────────────────────────────────────────────────────

async def handle_health(request: web.Request) -> web.Response:
    return web.Response(text="OK")


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> web.Application:
    # ملاحظة: لا حاجة لاستبدال أي placeholder ثابت — الـ nonce يُضاف ديناميكياً
    # في كل طلب داخل handle_ref_ip_check عبر .replace("%%NONCE%%", nonce)
    app = web.Application()
    app.router.add_post("/webhook/cryptomus", handle_cryptomus)
    app.router.add_post("/webhook/binance",   handle_binance)
    app.router.add_post("/oxapay_callback",   handle_oxapay)
    app.router.add_get("/ref-ip-check",       handle_ref_ip_check)
    app.router.add_get("/ref-ip-info",        handle_ref_ip_info)
    app.router.add_get("/health",             handle_health)
    return app
