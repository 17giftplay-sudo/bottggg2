"""
Binance Pay integration.
Docs: https://developers.binance.com/docs/binance-pay/api-order-create-v2
"""
import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Optional
from urllib.parse import urlencode

import aiohttp

import os
from config import BINANCE_PAY_API_KEY, BINANCE_PAY_SECRET_KEY, WEBHOOK_BASE_URL

# بيانات Binance Spot API — مختلفة عن بيانات Pay Merchant أعلاه.
# أنشئهما من: Binance → Account → API Management (نوع HMAC، صلاحية Read فقط)
# ثم أضفهما في Railway كمتغيرين: BINANCE_SPOT_API_KEY و BINANCE_SPOT_SECRET_KEY
_SPOT_API_KEY    = os.environ.get("BINANCE_SPOT_API_KEY", "")
_SPOT_SECRET_KEY = os.environ.get("BINANCE_SPOT_SECRET_KEY", "")

logger = logging.getLogger(__name__)

BINANCE_PAY_API = "https://bpay.binanceapi.com"


def _clean_credential(value: object) -> str:
    """Clean accidental whitespace/quotes/newlines copied into Railway variables."""
    cleaned = str(value or "").strip().strip('"').strip("'").strip()
    # إزالة أي \r أو \n مخفية داخل المفتاح (تحدث عند النسخ من بعض الأدوات)
    cleaned = cleaned.replace('\r', '').replace('\n', '').replace(' ', '')
    return cleaned


def _sign(timestamp: str, nonce: str, body_json: str) -> str:
    """HMAC-SHA512 of '{timestamp}\\n{nonce}\\n{body}\\n'"""
    payload = f"{timestamp}\n{nonce}\n{body_json}\n"
    return hmac.new(
        _clean_credential(BINANCE_PAY_SECRET_KEY).encode(),
        payload.encode(),
        hashlib.sha512,
    ).hexdigest().upper()


async def create_order(
    amount_usd: float,
    order_id: str,
) -> Optional[dict]:
    api_key = _clean_credential(BINANCE_PAY_API_KEY)
    secret_key = _clean_credential(BINANCE_PAY_SECRET_KEY)
    if not api_key or not secret_key:
        logger.error("Binance Pay credentials not configured.")
        return None

    timestamp = str(int(time.time() * 1000))
    nonce     = uuid.uuid4().hex

    body = {
        "env":             {"terminalType": "WEB"},
        "merchantTradeNo": order_id,
        "orderAmount":     round(amount_usd, 2),
        "currency":        "USDT",
        "description":     "Balance Top-Up",
        "goods": {
            "goodsType":        "02",
            "goodsCategory":    "Z000",
            "referenceGoodsId": "topup",
            "goodsName":        "Balance Top-Up",
        },
    }
    body_json = json.dumps(body, separators=(",", ":"))

    headers = {
        "BinancePay-Timestamp":      timestamp,
        "BinancePay-Nonce":          nonce,
        "BinancePay-Certificate-SN": api_key,
        "BinancePay-Signature":      _sign(timestamp, nonce, body_json),
        "Content-Type":              "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BINANCE_PAY_API}/binancepay/openapi/v2/order",
                data=body_json,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()
                if data.get("status") == "SUCCESS":
                    return data.get("data")
                logger.error("Binance Pay create_order error: %s", data)
                return None
    except Exception as e:
        logger.error("Binance Pay create_order exception: %s", e)
        return None


def verify_webhook(
    timestamp: str,
    nonce: str,
    body_json: str,
    received_signature: str,
) -> bool:
    """
    Verifies a Binance Pay webhook signature.

    FIX: same class of bug as Cryptomus — missing credentials previously made
    this return True, allowing forged webhooks.  Now returns False so the
    endpoint rejects all requests until credentials are properly set.
    """
    if not _clean_credential(BINANCE_PAY_SECRET_KEY):
        logger.error(
            "Binance Pay secret key not configured — rejecting webhook to "
            "prevent forged payment confirmations."
        )
        return False   # FIX: was `return True`

    expected = _sign(timestamp, nonce, body_json)
    # FIX: use hmac.compare_digest to prevent timing-oracle attacks
    return hmac.compare_digest(expected, received_signature.upper())


def is_paid(payload: dict) -> bool:
    biz_type   = payload.get("bizType", "")
    biz_status = payload.get("bizStatus", "")
    return biz_type == "PAY" and biz_status == "PAY_SUCCESS"


VERIFY_OK             = "verified"       # ✅ تم التحقق — أضف المبلغ الفعلي
VERIFY_API_ERROR      = "api_error"      # ⚠️ الـ API أعاد خطأ — أرسل للأدمن
VERIFY_NOT_FOUND      = "not_found"      # ❌ الـ tx_id غير موجود في السجل
VERIFY_WRONG_CURRENCY = "wrong_currency" # ❌ العملة ليست USDT
VERIFY_AMOUNT_TOO_LOW = "amount_too_low" # ❌ المبلغ أقل من الحد الأدنى


async def verify_transfer(
    tx_id: str,
    look_back_hours: int = 5,   # 5 ساعات فقط — يمنع إعادة استخدام الرموز القديمة
) -> tuple:
    """
    التحقق من تحويل Binance Pay عبر Transaction ID.

    يُرجع tuple (status, actual_amount):
      VERIFY_OK, amount        — تم التحقق، actual_amount = المبلغ الفعلي المُحوَّل.
      VERIFY_API_ERROR, 0.0    — فشل الاتصال — أرسل للأدمن للمراجعة اليدوية.
      VERIFY_NOT_FOUND, 0.0    — الـ tx_id غير موجود.
      VERIFY_WRONG_CURRENCY, 0.0 — العملة ليست USDT.
      VERIFY_AMOUNT_TOO_LOW, amount — المبلغ أقل من الحد الأدنى.

    يتطلب: API Key بصلاحية "Enable Reading" من حساب Binance الذي يستقبل المدفوعات.
    """
    # استخدام BINANCE_SPOT_API_KEY / BINANCE_SPOT_SECRET_KEY إذا وُجدا،
    # وإلا الرجوع إلى BINANCE_PAY_API_KEY / BINANCE_PAY_SECRET_KEY كاحتياط.
    from config import MIN_DEPOSIT_USD

    api_key    = _clean_credential(_SPOT_API_KEY) or _clean_credential(BINANCE_PAY_API_KEY)
    secret_key = _clean_credential(_SPOT_SECRET_KEY) or _clean_credential(BINANCE_PAY_SECRET_KEY)
    if not api_key or not secret_key:
        logger.error("Binance Spot API key غير مضبوط — إرسال للمراجعة اليدوية.")
        return VERIFY_API_ERROR, 0.0

    # ── تشخيص: هل يُستخدم مفتاح Spot المنفصل أم مفتاح Pay القديم؟ ──────────
    using_spot = bool(_clean_credential(_SPOT_API_KEY))
    logger.info(
        "Binance DIAG: using=%s api_key len=%d first=%s last=%s | secret_key len=%d first=%s last=%s",
        "SPOT_KEY" if using_spot else "PAY_KEY(fallback)",
        len(api_key), api_key[:2], api_key[-2:],
        len(secret_key), secret_key[:2], secret_key[-2:],
    )

    import time as _t
    now_ms   = int(_t.time() * 1000)
    start_ms = now_ms - look_back_hours * 3600 * 1000

    # Sign the exact percent-encoded query string sent to Binance.
    params = {
        "startTime": start_ms,
        "limit": 100,
        "timestamp": now_ms,
        "recvWindow": 5000,
    }
    query_str = urlencode(params)
    signature = hmac.new(
        secret_key.encode(),
        query_str.encode(),
        hashlib.sha256,
    ).hexdigest()

    url     = f"https://api.binance.com/sapi/v1/pay/transactions?{query_str}&signature={signature}"
    headers = {"X-MBX-APIKEY": api_key}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json(content_type=None)

        # الـ API يُرجع {"code":"000000",...} عند النجاح
        if str(data.get("code", "")) != "000000":
            logger.error(
                "Binance verify_transfer: API error code=%s msg=%s full_response=%s",
                data.get("code"),
                data.get("message") or data.get("msg", ""),
                data,
            )
            return VERIFY_API_ERROR, 0.0

        transactions = data.get("data", [])
        tx_id_clean  = tx_id.strip()

        logger.info(
            "Binance verify_transfer: API returned %d transactions. Looking for transactionId=%s",
            len(transactions), tx_id_clean,
        )
        for _i, _tx in enumerate(transactions[:5]):
            _tid = _tx.get("transactionId") or _tx.get("transId") or "N/A"
            _amt = _tx.get("amount", "?")
            _cur = _tx.get("currency", "?")
            _typ = _tx.get("transactionType") or _tx.get("bizType") or "?"
            logger.info("  [%d] transactionId=%s amount=%s %s type=%s", _i, _tid, _amt, _cur, _typ)

        for tx in transactions:
            raw_trans_id = str(
                tx.get("transactionId") or tx.get("transId") or ""
            ).strip()
            raw_order_id = str(tx.get("orderId") or "").strip()

            # مطابقة بـ transactionId أو orderId (معرّف الطلب الذي يراه المستخدم)
            if (raw_trans_id.upper() != tx_id_clean.upper()
                    and raw_order_id != tx_id_clean):
                continue

            # ── تم العثور على الـ tx_id — نفحص العملة والمبلغ ──────────────

            funds      = tx.get("fundsDetail") or []
            usdt_fund  = next((f for f in funds if f.get("currency", "").upper() == "USDT"), None)

            # نحدد العملة
            tx_currency = (usdt_fund or {}).get("currency", "") or tx.get("currency", "")
            tx_currency = tx_currency.upper()

            # ❌ عملة غير USDT
            if tx_currency and tx_currency != "USDT":
                logger.warning(
                    "Binance verify_transfer: transId=%s عملة غير مقبولة — currency=%s",
                    tx_id_clean, tx_currency,
                )
                return VERIFY_WRONG_CURRENCY, 0.0

            # نحدد المبلغ الفعلي
            if usdt_fund:
                amount_str = usdt_fund.get("amount", "0")
            else:
                amount_str = str(tx.get("amount", "0"))

            try:
                actual = float(amount_str)
            except (ValueError, TypeError):
                actual = 0.0

            # مبلغ سالب أو صفر = مصروف وليس إيراد
            if not funds and actual <= 0:
                logger.warning(
                    "Binance verify_transfer: transId=%s مبلغ سالب أو صفر — actual=%.4f",
                    tx_id_clean, actual,
                )
                return VERIFY_NOT_FOUND, 0.0

            # ❌ مبلغ أقل من الحد الأدنى
            if actual < MIN_DEPOSIT_USD:
                logger.warning(
                    "Binance verify_transfer: transId=%s مبلغ أقل من الحد الأدنى — actual=%.4f < min=%.2f",
                    tx_id_clean, actual, MIN_DEPOSIT_USD,
                )
                return VERIFY_AMOUNT_TOO_LOW, actual

            # ✅ كل شيء صحيح — نُرجع المبلغ الفعلي (وليس ما كتبه المستخدم)
            logger.info(
                "Binance verify_transfer: ✅ تم التحقق — transId=%s amount=%.4f USDT",
                tx_id_clean, actual,
            )
            return VERIFY_OK, actual

        logger.warning(
            "Binance verify_transfer: ❌ لم يُعثر على transId=%s في %d معاملة. "
            "تأكد أن المستخدم يُرسل transId الصحيح وليس رقم الطلب.",
            tx_id_clean, len(transactions),
        )
        return VERIFY_NOT_FOUND, 0.0

    except Exception as e:
        logger.error("Binance verify_transfer exception: %s — إرسال للمراجعة اليدوية", e)
        return VERIFY_API_ERROR, 0.0
