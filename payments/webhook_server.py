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


_REF_DEVICE_VERIFY_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>التحقق الأمني من الجهاز</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  :root {
    --bg-color: #0f172a;
    --card-bg: rgba(30, 41, 59, 0.7);
    --primary: #38bdf8;
    --primary-glow: rgba(56, 189, 248, 0.3);
    --success: #10b981;
    --error: #ef4444;
    --text: #f8fafc;
    --text-muted: #94a3b8;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
  body {
    background: radial-gradient(circle at top, #1e293b, #0f172a);
    color: var(--text);
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
  }
  .card {
    background: var(--card-bg);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 24px;
    padding: 32px 24px;
    width: 100%;
    max-width: 360px;
    text-align: center;
    box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
  }
  .shield-icon {
    width: 80px;
    height: 80px;
    margin: 0 auto 20px;
    border-radius: 50%;
    background: rgba(56, 189, 248, 0.1);
    display: flex;
    align-items: center;
    justify-content: center;
    border: 2px solid var(--primary);
    box-shadow: 0 0 25px var(--primary-glow);
    animation: pulse 2s infinite ease-in-out;
  }
  @keyframes pulse {
    0%, 100% { transform: scale(1); box-shadow: 0 0 20px var(--primary-glow); }
    50% { transform: scale(1.05); box-shadow: 0 0 35px var(--primary-glow); }
  }
  h2 { font-size: 20px; font-weight: 700; margin-bottom: 8px; }
  p { font-size: 14px; color: var(--text-muted); line-height: 1.5; margin-bottom: 24px; }
  .progress-bar {
    width: 100%;
    height: 6px;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 10px;
    overflow: hidden;
    margin-bottom: 12px;
  }
  .progress-fill {
    height: 100%;
    width: 0%;
    background: linear-gradient(90deg, #38bdf8, #818cf8);
    border-radius: 10px;
    transition: width 0.3s ease;
  }
  .status-text { font-size: 13px; color: var(--primary); font-weight: 600; }
</style>
</head>
<body>
<div class="card">
  <div class="shield-icon" id="icon">
    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      <path d="m9 12 2 2 4-4"/>
    </svg>
  </div>
  <h2 id="title">فحص أمان الجهاز</h2>
  <p id="desc">جاري التحقق من بصمة الجهاز ومطابقتها لمنع تعدد الحسابات الوهمية...</p>
  <div class="progress-bar">
    <div class="progress-fill" id="pbar"></div>
  </div>
  <div class="status-text" id="status">جاري توليد البصمة المشفرة (0%)...</div>
</div>

<script>
const tg = window.Telegram.WebApp;
try { tg.ready(); tg.expand(); } catch(e){}

async function sha256(str) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(str));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}

function getCanvasFP() {
  try {
    const canvas = document.createElement('canvas');
    canvas.width = 240; canvas.height = 60;
    const ctx = canvas.getContext('2d');
    ctx.textBaseline = "top";
    ctx.font = "14px 'Arial', sans-serif";
    ctx.textBaseline = "alphabetic";
    ctx.fillStyle = "#f60";
    ctx.fillRect(125,1,62,20);
    ctx.fillStyle = "#069";
    ctx.fillText("PandaStoreAuth, AntiFraud🔒", 2, 15);
    ctx.fillStyle = "rgba(102, 204, 0, 0.7)";
    ctx.fillText("TelegramStoreDeviceFP 2026", 4, 17);
    return canvas.toDataURL();
  } catch(e) { return "canvas_error"; }
}

function getWebGLFP() {
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if (!gl) return "no_webgl";
    const dbgRenderInfo = gl.getExtension('WEBGL_debug_renderer_info');
    const vendor = dbgRenderInfo ? gl.getParameter(dbgRenderInfo.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR);
    const renderer = dbgRenderInfo ? gl.getParameter(dbgRenderInfo.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
    return `${vendor}~${renderer}`;
  } catch(e) { return "webgl_error"; }
}

async function getAudioFP() {
  try {
    const AudioContext = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    if (!AudioContext) return "no_audio";
    const ctx = new AudioContext(1, 44100, 44100);
    const osc = ctx.createOscillator();
    osc.type = "triangle";
    osc.frequency.setValueAtTime(10000, ctx.currentTime);
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.setValueAtTime(-50, ctx.currentTime);
    comp.knee.setValueAtTime(40, ctx.currentTime);
    comp.ratio.setValueAtTime(12, ctx.currentTime);
    comp.attack.setValueAtTime(0, ctx.currentTime);
    comp.release.setValueAtTime(0.25, ctx.currentTime);
    osc.connect(comp);
    comp.connect(ctx.destination);
    osc.start(0);
    const rendered = await ctx.startRendering();
    let sum = 0;
    for (let i = 4500; i < 5000; i++) {
      sum += Math.abs(rendered.getChannelData(0)[i]);
    }
    return sum.toString();
  } catch(e) { return "audio_error"; }
}

async function runVerification() {
  const pbar = document.getElementById("pbar");
  const status = document.getElementById("status");
  
  pbar.style.width = "30%";
  status.innerText = "فحص قدرات العرض والجرافيكس...";
  
  const canvasData = getCanvasFP();
  const webglData = getWebGLFP();
  
  await new Promise(r => setTimeout(r, 200));
  pbar.style.width = "65%";
  status.innerText = "فحص معالج الصوت ومواصفات العتاد...";
  
  const audioData = await getAudioFP();
  
  const hardware = {
    screen: `${screen.width}x${screen.height}x${screen.colorDepth}@${window.devicePixelRatio||1}`,
    cores: navigator.hardwareConcurrency || 0,
    memory: navigator.deviceMemory || 0,
    touch: navigator.maxTouchPoints || 0,
    platform: navigator.platform || "",
    tz: Intl.DateTimeFormat().resolvedOptions().timeZone || "",
    lang: navigator.language || ""
  };
  
  pbar.style.width = "90%";
  status.innerText = "توليد المعرّف الأمني الفريد...";
  
  const rawFingerprint = `${canvasData}|${webglData}|${audioData}|${JSON.stringify(hardware)}`;
  const fpHash = await sha256(rawFingerprint);
  
  pbar.style.width = "100%";
  status.innerText = "✅ تم تأكيد الجهاز بنجاح!";
  
  const payload = {
    type: "device_verification",
    fp_hash: fpHash,
    hardware: hardware,
    webgl: webglData,
    timestamp: Date.now()
  };
  
  setTimeout(() => {
    try {
      tg.sendData(JSON.stringify(payload));
      tg.close();
    } catch(e) {
      status.innerText = "اضغط رجوع للعودة للبوت";
    }
  }, 600);
}

window.onload = runVerification;
</script>
</body>
</html>"""


async def handle_ref_verify(request: web.Request) -> web.Response:
    """يعرض صفحة الـ Web App الخاصة بفحص بصمة الجهاز."""
    return web.Response(text=REF_DEVICE_VERIFY_HTML if 'REF_DEVICE_VERIFY_HTML' in globals() else _REF_DEVICE_VERIFY_HTML, content_type="text/html", charset="utf-8")


# ── Health check ──────────────────────────────────────────────────────────────

async def handle_health(request: web.Request) -> web.Response:
    return web.Response(text="OK")


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/webhook/cryptomus", handle_cryptomus)
    app.router.add_post("/webhook/binance",   handle_binance)
    app.router.add_post("/oxapay_callback",   handle_oxapay)
    app.router.add_get("/ref-verify",         handle_ref_verify)
    app.router.add_get("/health",             handle_health)
    return app
