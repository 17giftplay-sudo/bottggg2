import os
import sys

# ── Credentials (MUST be set as environment variables) ─────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
if not BOT_TOKEN:
    sys.exit(
        "FATAL: BOT_TOKEN environment variable is not set.\n"
        "Set it in Railway → Variables before deploying."
    )

_raw_admin_ids = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in _raw_admin_ids.split(",") if x.strip().isdigit()]
if not ADMIN_IDS:
    print(
        "WARNING: ADMIN_IDS environment variable is not set. "
        "Admin panel (/admin) will be inaccessible.",
        file=sys.stderr,
    )

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    sys.exit(
        "FATAL: DATABASE_URL environment variable is not set.\n"
        "Add a PostgreSQL database in Railway → your project → + New → Database → PostgreSQL."
    )

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ── Bot behaviour ─────────────────────────────────────────────────────────────
CAPTCHA_LENGTH = 5
CAPTCHA_MAX_ATTEMPTS = 5
COUNTRIES_PER_PAGE = 12

# ── Payments ──────────────────────────────────────────────────────────────────
MIN_DEPOSIT_USD = 0.1

WEBHOOK_BASE_URL = os.environ.get("WEBHOOK_BASE_URL", "").rstrip("/")
WEBHOOK_PORT = int(os.environ.get("PORT", "8080"))

# ── Cryptomus ─────────────────────────────────────────────────────────────────
CRYPTOMUS_MERCHANT_ID = os.environ.get("CRYPTOMUS_MERCHANT_ID", "")
CRYPTOMUS_API_KEY     = os.environ.get("CRYPTOMUS_API_KEY", "")

# ── Binance Pay ───────────────────────────────────────────────────────────────
BINANCE_PAY_API_KEY    = os.environ.get("BINANCE_PAY_API_KEY", "")
BINANCE_PAY_SECRET_KEY = os.environ.get("BINANCE_PAY_SECRET_KEY", "")

# ── OxaPay ────────────────────────────────────────────────────────────────────
OXAPAY_MERCHANT_KEY = os.environ.get("OXAPAY_MERCHANT_KEY", "")
if not OXAPAY_MERCHANT_KEY:
    print(
        "WARNING: OXAPAY_MERCHANT_KEY environment variable is not set. "
        "OxaPay payments will be disabled.",
        file=sys.stderr,
    )

# ── Global API credentials (shared across all accounts) ───────────────────────
DEFAULT_API_ID   = int(os.environ.get("DEFAULT_API_ID", "2040") or "2040")
DEFAULT_API_HASH = (os.environ.get("DEFAULT_API_HASH", "") or "b18441a1260828d0ed5d60f4eb70e775").strip()
if DEFAULT_API_ID and DEFAULT_API_HASH:
    print("INFO: Global DEFAULT_API_ID/DEFAULT_API_HASH loaded — short account format enabled.", file=sys.stderr)


# ── API Pool (تدوير credentials تلقائياً) ─────────────────────────────────────
# الصيغة في Railway: API_POOL = id1:hash1,id2:hash2,id3:hash3
API_POOL: list[tuple[int, str]] = []
_api_pool_raw = os.environ.get("API_POOL", "").strip()
if _api_pool_raw:
    for _entry in _api_pool_raw.split(","):
        _parts = _entry.strip().split(":")
        if len(_parts) >= 2:
            try:
                _aid  = int(_parts[0].strip())
                _ahsh = _parts[1].strip()
                if _aid and _ahsh:
                    API_POOL.append((_aid, _ahsh))
            except ValueError:
                pass
    if API_POOL:
        print(f"INFO: API_POOL loaded — {len(API_POOL)} credential pair(s) for rotation.", file=sys.stderr)

# ── Proxy Pool (تدوير البروكسي مع دعم مطابقة الدولة) ─────────────────────────
# الصيغة في Railway:
#   بدون دولة  → PROXY_POOL = ip:port:user:pass,ip:port:user:pass
#   مع دولة    → PROXY_POOL = ip:port:user:pass:US,ip:port:user:pass:GB
#
# كود الدولة (اختياري) هو كود ISO مكوّن من حرفين مثل US, GB, SA, AE, EG ...
# إذا أضفت كود الدولة، البوت يختار البروكسي المناسب لبلد رقم الهاتف تلقائياً.
# إذا لم يوجد بروكسي لدولة الحساب، يختار بروكسياً عشوائياً من المجموعة.
PROXY_POOL: list[dict] = []
_proxy_pool_raw = os.environ.get("PROXY_POOL", "").strip()
if _proxy_pool_raw:
    for _entry in _proxy_pool_raw.split(","):
        _p = [x.strip() for x in _entry.strip().split(":")]
        if len(_p) >= 4:
            try:
                _proxy = {
                    "host":     _p[0],
                    "port":     int(_p[1]),
                    "username": _p[2],
                    "password": _p[3],
                    # الحقل الخامس اختياري: كود الدولة بحرفين ISO (US, GB, SA ...)
                    "country":  _p[4].upper() if len(_p) >= 5 and len(_p[4]) == 2 else None,
                }
                PROXY_POOL.append(_proxy)
            except (ValueError, IndexError):
                pass
    if PROXY_POOL:
        with_country = sum(1 for p in PROXY_POOL if p["country"])
        print(
            f"INFO: PROXY_POOL loaded — {len(PROXY_POOL)} proxies available for rotation"
            + (f" ({with_country} with country tags)." if with_country else "."),
            file=sys.stderr,
        )
