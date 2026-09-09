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
    look_back_hours: int = 24,   # 24 ساعة للبحث في معاملات اليوم بالكامل
) -> tuple:
    """
    التحقق من تحويل Binance Pay عبر Transaction ID أو Order ID.
    يستخدم مزامنة الوقت المباشرة مع سيرفرات بايننس لمنع أي خطأ توقيت (Time Offset).
    """
    from config import MIN_DEPOSIT_USD
    from database import get_setting

    # جلب المفاتيح ديناميكياً من البيئة أو قاعدة البيانات
    api_key = (
        _clean_credential(os.environ.get("BINANCE_SPOT_API_KEY"))
        or _clean_credential(os.environ.get("BINANCE_PAY_API_KEY"))
        or _clean_credential(await get_setting("binance_api_key"))
        or _clean_credential(BINANCE_PAY_API_KEY)
    )
    secret_key = (
        _clean_credential(os.environ.get("BINANCE_SPOT_SECRET_KEY"))
        or _clean_credential(os.environ.get("BINANCE_PAY_SECRET_KEY"))
        or _clean_credential(await get_setting("binance_secret_key"))
        or _clean_credential(BINANCE_PAY_SECRET_KEY)
    )

    if not api_key or not secret_key:
        err = f"API keys missing in Railway Variables (api_key={bool(api_key)}, secret_key={bool(secret_key)})"
        logger.error("Binance error: %s", err)
        return VERIFY_API_ERROR, 0.0, err

    tx_id_clean = tx_id.strip()

    try:
        async with aiohttp.ClientSession() as session:
            # 1. مزامنة التوقيت الدقيق مع بايننس
            now_ms = int(time.time() * 1000)
            try:
                async with session.get("https://api.binance.com/api/v3/time", timeout=aiohttp.ClientTimeout(total=5)) as t_resp:
                    t_data = await t_resp.json(content_type=None)
                    if t_data.get("serverTime"):
                        now_ms = int(t_data["serverTime"])
            except Exception as _te:
                logger.warning("Could not sync server time with Binance, using local: %s", _te)

            start_ms = now_ms - (look_back_hours * 3600 * 1000)

            # 2. بناء التوقيع المشفر مع أقصى نافذة سماح (recvWindow = 60000ms)
            params = {
                "startTime": start_ms,
                "limit": 100,
                "timestamp": now_ms,
                "recvWindow": 60000,
            }
            query_str = urlencode(params)
            signature = hmac.new(
                secret_key.encode(),
                query_str.encode(),
                hashlib.sha256,
            ).hexdigest()

            url = f"https://api.binance.com/sapi/v1/pay/transactions?{query_str}&signature={signature}"
            headers = {"X-MBX-APIKEY": api_key}

            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json(content_type=None)

        if str(data.get("code", "")) != "000000":
            err_msg = f"Binance code {data.get('code')}: {data.get('message') or data.get('msg')}"
            logger.error(
                "Binance verify_transfer API error: %s full_response=%s",
                err_msg, data,
            )
            return VERIFY_API_ERROR, 0.0, err_msg

        transactions = data.get("data", [])
        logger.info("Binance API returned %d transactions. Searching for tx_id=%s", len(transactions), tx_id_clean)

        for tx in transactions:
            raw_trans_id = str(tx.get("transactionId") or tx.get("transId") or "").strip()
            raw_order_id = str(tx.get("orderId") or tx.get("prepayId") or "").strip()
            raw_note     = str(tx.get("note") or "").strip()

            # مطابقة بـ transactionId أو orderId أو prepayId
            matched = (
                (raw_trans_id and raw_trans_id.upper() == tx_id_clean.upper())
                or (raw_order_id and raw_order_id == tx_id_clean)
                or (tx_id_clean in str(tx))
            )
            if not matched:
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
                return VERIFY_WRONG_CURRENCY, 0.0, f"Wrong currency: {tx_currency}"

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
                return VERIFY_NOT_FOUND, 0.0, "Negative or zero amount"

            # ❌ مبلغ أقل من الحد الأدنى
            if actual < MIN_DEPOSIT_USD:
                logger.warning(
                    "Binance verify_transfer: transId=%s مبلغ أقل من الحد الأدنى — actual=%.4f < min=%.2f",
                    tx_id_clean, actual, MIN_DEPOSIT_USD,
                )
                return VERIFY_AMOUNT_TOO_LOW, actual, "Amount too low"

            # ✅ كل شيء صحيح — نُرجع المبلغ الفعلي (وليس ما كتبه المستخدم)
            logger.info(
                "Binance verify_transfer: ✅ تم التحقق — transId=%s amount=%.4f USDT",
                tx_id_clean, actual,
            )
            return VERIFY_OK, actual, "OK"

        logger.warning(
            "Binance verify_transfer: ❌ لم يُعثر على transId=%s في %d معاملة.",
            tx_id_clean, len(transactions),
        )
        return VERIFY_NOT_FOUND, 0.0, f"Not found among {len(transactions)} recent transactions"

    except Exception as e:
        err = f"Exception: {e}"
        logger.error("Binance verify_transfer exception: %s", err)
        return VERIFY_API_ERROR, 0.0, err
