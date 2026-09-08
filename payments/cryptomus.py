"""
Cryptomus payment integration.
Docs: https://doc.cryptomus.com/payments
"""
import hashlib
import base64
import hmac
import json
import logging
from typing import Optional

import aiohttp

from config import CRYPTOMUS_MERCHANT_ID, CRYPTOMUS_API_KEY, WEBHOOK_BASE_URL

logger = logging.getLogger(__name__)

CRYPTOMUS_API = "https://api.cryptomus.com/v1"


def _sign(body_json: str) -> str:
    """MD5(base64(body) + api_key)"""
    encoded = base64.b64encode(body_json.encode()).decode()
    return hashlib.md5((encoded + CRYPTOMUS_API_KEY).encode()).hexdigest()


async def create_invoice(
    amount_usd: float,
    order_id: str,
) -> Optional[dict]:
    if not CRYPTOMUS_MERCHANT_ID or not CRYPTOMUS_API_KEY:
        logger.error("Cryptomus credentials not configured.")
        return None

    body = {
        "amount":               str(round(amount_usd, 2)),
        "currency":             "USD",
        "order_id":             order_id,
        "lifetime":             3600,
        "is_payment_multiple":  False,
        "url_callback":         f"{WEBHOOK_BASE_URL}/webhook/cryptomus" if WEBHOOK_BASE_URL else "",
        "url_return":           "",
        "url_success":          "",
    }
    body_json = json.dumps(body, separators=(",", ":"))

    headers = {
        "merchant":     CRYPTOMUS_MERCHANT_ID,
        "sign":         _sign(body_json),
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{CRYPTOMUS_API}/payment",
                data=body_json,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()
                if data.get("state") == 0:
                    return data.get("result")
                logger.error("Cryptomus create_invoice error: %s", data)
                return None
    except Exception as e:
        logger.error("Cryptomus create_invoice exception: %s", e)
        return None


def verify_webhook(payload: dict) -> bool:
    """
    Verifies a Cryptomus webhook signature.

    FIX: the previous implementation returned True (accept all) when the API
    key was not configured.  An attacker could exploit this to forge arbitrary
    payment confirmations by simply not sending a valid signature.  Now we
    return False (reject) when credentials are absent, so unconfigured
    deployments do not silently accept forged webhooks.
    """
    if not CRYPTOMUS_API_KEY:
        logger.error(
            "Cryptomus API key not configured — rejecting webhook to prevent "
            "forged payment confirmations."
        )
        return False   # FIX: was `return True`

    received_sign = payload.pop("sign", None)
    if not received_sign:
        return False

    body_json = json.dumps(payload, separators=(",", ":"))
    expected  = _sign(body_json)

    # Restore sign so callers still have the original dict
    payload["sign"] = received_sign

    # FIX: use hmac.compare_digest to prevent timing-oracle attacks
    return hmac.compare_digest(received_sign, expected)


def is_paid(payload: dict) -> bool:
    """Returns True when a Cryptomus webhook indicates a completed payment."""
    return payload.get("status") in ("paid", "paid_over")
