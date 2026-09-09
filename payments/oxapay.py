import hashlib
import hmac
import logging
import aiohttp
from typing import Optional

from config import OXAPAY_MERCHANT_KEY

logger = logging.getLogger(__name__)


async def create_invoice(amount_usd: float, order_id: str) -> Optional[dict]:
    if not OXAPAY_MERCHANT_KEY:
        logger.error("OxaPay merchant key not configured.")
        return None

    url = "https://api.oxapay.com/merchants/request"
    payload = {
        "merchant":    OXAPAY_MERCHANT_KEY.strip(),
        "amount":      float(amount_usd),
        "currency":    "USD",
        "orderId":     str(order_id),
        "description": f"Deposit Order {order_id}",
    }

    try:
        import os
        from database import get_setting
        raw_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or os.environ.get("RAILWAY_STATIC_URL") or "bottggg2-production.up.railway.app"
        wh_url = (await get_setting("webhook_base_url") or os.environ.get("WEBHOOK_BASE_URL") or (f"https://{raw_domain}" if raw_domain else "")).rstrip("/")
        if wh_url:
            if not wh_url.startswith("http"):
                wh_url = f"https://{wh_url}"
            payload["callbackUrl"] = f"{wh_url}/oxapay_callback"
    except Exception:
        pass

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                data = await resp.json()
                logger.info("OxaPay API response: %s", data)

                if data.get("result") == 100:
                    actual_url = data.get("payLink") or data.get("payUrl") or data.get("url")
                    return {
                        "payUrl":  actual_url,
                        "payLink": actual_url,
                        "trackId": data.get("trackId"),
                    }
                else:
                    logger.error("OxaPay error: %s", data.get("message"))
                    return None
    except Exception as e:
        logger.error("OxaPay create_invoice exception: %s", e)
        return None


def verify_webhook(body_bytes: bytes, received_hmac: str) -> bool:
    if not OXAPAY_MERCHANT_KEY:
        logger.error("OxaPay key not configured — rejecting webhook.")
        return False

    if not received_hmac:
        return False

    expected = hmac.new(
        OXAPAY_MERCHANT_KEY.encode(),
        body_bytes,
        hashlib.sha512,
    ).hexdigest()

    return hmac.compare_digest(expected, received_hmac.lower())
