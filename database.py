import asyncpg
import json
import logging
import os
import random
import string
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

_settings_cache: Dict[str, tuple] = {}
_SETTINGS_TTL = 120


def _get_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        try:
            from config import DATABASE_URL as _cfg_url
            url = _cfg_url or ""
        except (ImportError, AttributeError):
            pass
    if not url:
        raise RuntimeError("DATABASE_URL غير محدد! أضفه في Railway → Variables")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


DATABASE_URL = _get_db_url()
_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=10,
            max_size=30,
            max_inactive_connection_lifetime=300.0,
            command_timeout=15.0,
        )
    return _pool


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id             BIGINT PRIMARY KEY,
                username            TEXT,
                first_name          TEXT,
                language            TEXT          DEFAULT 'en',
                balance             NUMERIC(12,4) DEFAULT 0.0,
                points              INTEGER       DEFAULT 0,
                total_deposited     NUMERIC(12,4) DEFAULT 0.0,
                total_withdrawn     NUMERIC(12,4) DEFAULT 0.0,
                deposit_count       INTEGER       DEFAULT 0,
                withdrawal_count    INTEGER       DEFAULT 0,
                accounts_purchased  INTEGER       DEFAULT 0,
                is_verified         INTEGER       DEFAULT 0,
                is_banned           INTEGER       DEFAULT 0,
                ban_reason          TEXT,
                joined_at           TIMESTAMP     DEFAULT NOW()
            )
        """)
        for col, definition in [
            ("points",     "INTEGER DEFAULT 0"),
            ("is_banned",  "INTEGER DEFAULT 0"),
            ("ban_reason", "TEXT"),
        ]:
            try:
                await db.execute(
                    f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {definition}"
                )
            except Exception:
                pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS accounts_inventory (
                id              SERIAL PRIMARY KEY,
                country_code    TEXT          NOT NULL,
                country_name    TEXT          NOT NULL,
                account_data    TEXT          NOT NULL,
                price           NUMERIC(12,4) NOT NULL,
                store_type      TEXT          DEFAULT 'dollar',
                status          TEXT          DEFAULT 'available',
                added_at        TIMESTAMP     DEFAULT NOW(),
                sold_at         TIMESTAMP,
                sold_to_user_id BIGINT,
                FOREIGN KEY (sold_to_user_id) REFERENCES users(user_id)
            )
        """)
        try:
            await db.execute(
                "ALTER TABLE accounts_inventory ADD COLUMN IF NOT EXISTS store_type TEXT DEFAULT 'dollar'"
            )
        except Exception:
            pass
        try:
            await db.execute(
                "ALTER TABLE accounts_inventory ADD COLUMN IF NOT EXISTS promo_sent BOOLEAN DEFAULT FALSE"
            )
        except Exception:
            pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS country_prices (
                country_code    TEXT PRIMARY KEY,
                country_name    TEXT          NOT NULL,
                flag_emoji      TEXT          DEFAULT '🌍',
                price           NUMERIC(12,4) NOT NULL,
                points_price    INTEGER       DEFAULT 0
            )
        """)
        try:
            await db.execute(
                "ALTER TABLE country_prices ADD COLUMN IF NOT EXISTS points_price INTEGER DEFAULT 0"
            )
        except Exception:
            pass
        for col, definition in [
            ("flash_sale_discount", "NUMERIC(5,2) DEFAULT 0"),
            ("flash_sale_until",    "TIMESTAMP"),
        ]:
            try:
                await db.execute(
                    f"ALTER TABLE country_prices ADD COLUMN IF NOT EXISTS {col} {definition}"
                )
            except Exception:
                pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key     TEXT PRIMARY KEY,
                value   TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT        NOT NULL,
                type        TEXT          NOT NULL,
                amount      NUMERIC(12,4) NOT NULL,
                description TEXT,
                created_at  TIMESTAMP     DEFAULT NOW(),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id              SERIAL PRIMARY KEY,
                order_id        TEXT          UNIQUE NOT NULL,
                user_id         BIGINT        NOT NULL,
                provider        TEXT          NOT NULL,
                amount_usd      NUMERIC(12,4) NOT NULL,
                status          TEXT          DEFAULT 'pending',
                provider_ref    TEXT,
                created_at      TIMESTAMP     DEFAULT NOW(),
                confirmed_at    TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_payments_order_id ON payments(order_id)"
        )

        await db.execute("""
            CREATE TABLE IF NOT EXISTS verified_phones (
                phone       TEXT PRIMARY KEY,
                user_id     BIGINT NOT NULL,
                verified_at TIMESTAMP DEFAULT NOW()
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS verified_ips (
                ip          TEXT PRIMARY KEY,
                user_id     BIGINT NOT NULL,
                verified_at TIMESTAMP DEFAULT NOW()
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS pending_leaves (
                user_id     BIGINT PRIMARY KEY,
                deadline    TIMESTAMP NOT NULL,
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """)
        try:
            await db.execute(
                "ALTER TABLE pending_leaves ADD COLUMN IF NOT EXISTS deadline TIMESTAMP NOT NULL DEFAULT NOW()"
            )
        except Exception:
            pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS pending_otp_sessions (
                account_id    INTEGER   PRIMARY KEY,
                buyer_id      BIGINT    NOT NULL,
                lang          TEXT      DEFAULT 'ar',
                country_name  TEXT      DEFAULT '',
                refetch_count INTEGER   DEFAULT 0,
                sent_at       TIMESTAMP NOT NULL,
                expires_at    TIMESTAMP NOT NULL,
                parsed_json   TEXT      NOT NULL
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_otp_expires ON pending_otp_sessions(expires_at)"
        )

        await db.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                id           SERIAL PRIMARY KEY,
                account_id   INTEGER   NOT NULL,
                user_id      BIGINT    NOT NULL,
                country_code TEXT      NOT NULL,
                rating       INTEGER   NOT NULL CHECK (rating BETWEEN 1 AND 5),
                created_at   TIMESTAMP DEFAULT NOW(),
                UNIQUE (account_id, user_id)
            )
        """)

        try:
            await db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_ratings_account_user ON ratings(account_id, user_id)"
            )
        except Exception:
            pass

        # ── جدول استردادات النجوم ─────────────────────────────────────────────
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stars_refunds (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT NOT NULL,
                stars       INTEGER NOT NULL DEFAULT 0,
                usd_amount  NUMERIC(12,4) NOT NULL DEFAULT 0,
                order_id    TEXT,
                refunded_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_stars_refunds_user ON stars_refunds(user_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_inventory_lookup ON accounts_inventory(country_code, status, store_type)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_inventory_status ON accounts_inventory(status)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id)"
        )

        defaults = [
            ("min_account_age_days",    "30"),
            ("webhook_base_url",        ""),
            ("force_sub_channel",       ""),
            ("sell_accounts_url",       ""),
            ("support_url",             ""),
            ("topup_other_url",         ""),
            ("info_buttons",            "[]"),
            ("notification_channel",    ""),
            ("stars_rate",              "0.011"),
            ("min_deposit_stars",       "100"),
            ("min_deposit_usd",         "1.0"),
            ("maintenance_mode",        "0"),
            ("sell_btn_enabled",        "1"),
            ("info_btn_enabled",        "1"),
            ("binance_pay_uid",         ""),
            ("referral_enabled",        "1"),
            ("referral_reward_usd",     "0.05"),
            ("referral_require_fp",     "1"),
        ]
        for key, value in defaults:
            await db.execute(
                "INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO NOTHING",
                key, value,
            )

        # ── نظام الإحالة المتقدم وبصمة الأجهزة المانعة للغش ───────────
        for col, definition in [
            ("referred_by",         "BIGINT"),
            ("device_fingerprint",  "TEXT"),
            ("is_device_verified",  "INTEGER DEFAULT 0"),
        ]:
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {definition}")
            except Exception:
                pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS device_fingerprints (
                id               SERIAL PRIMARY KEY,
                user_id          BIGINT NOT NULL,
                fingerprint_hash TEXT NOT NULL,
                ip_address       TEXT,
                user_agent       TEXT,
                created_at       TIMESTAMP DEFAULT NOW()
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_fp_hash ON device_fingerprints(fingerprint_hash)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_fp_user_id ON device_fingerprints(user_id)")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS referral_logs (
                id           SERIAL PRIMARY KEY,
                referrer_id  BIGINT NOT NULL,
                referred_id  BIGINT NOT NULL,
                reward_usd   NUMERIC(12,4) DEFAULT 0.0,
                status       TEXT DEFAULT 'pending',
                fraud_reason TEXT,
                created_at   TIMESTAMP DEFAULT NOW()
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_ref_referrer ON referral_logs(referrer_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_ref_referred ON referral_logs(referred_id)")

        # تصحيح وتصفير أرباح الإحالات السابقة المضخمة إلى 0.005$ بدقة لكل إحالة
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_inventory_status ON accounts_inventory(status)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_inventory_country_status ON accounts_inventory(country_code, status)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id)"
        )

        await db.execute("""
            CREATE TABLE IF NOT EXISTS manual_payments (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT        NOT NULL,
                amount_usd  NUMERIC(12,4) NOT NULL,
                tx_hash     TEXT          NOT NULL,
                status      TEXT          DEFAULT 'pending',
                created_at  TIMESTAMP     DEFAULT NOW(),
                reviewed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        try:
            await fix_sms_duplicate_refund_debts()
        except Exception as e:
            logger.error("Failed to run automatic SMS duplicate refund audit: %s", e)


async def fix_sms_duplicate_refund_debts() -> List[Dict[str, Any]]:
    """
    Audits all SMS activations for duplicate refund transactions.
    Finds every activation where total refund amounts exceed the activation's original cost_usd,
    deducts the exact excess amount from the user's balance (allowing negative balance for debt tracking),
    and records a correction transaction so users automatically pay off the debt upon top up.
    This query is idempotent and will never deduct duplicate amounts more than once.
    """
    results = []
    pool = await get_pool()
    async with pool.acquire() as db:
        table_exists = await db.fetchval("SELECT to_regclass('sms_activations')")
        if not table_exists:
            return results
        async with db.transaction():
            rows = await db.fetch(
                """
                SELECT 
                    sa.activation_id,
                    sa.user_id,
                    sa.phone,
                    sa.cost_usd,
                    COALESCE(SUM(t.amount), 0) AS total_refunded,
                    (COALESCE(SUM(t.amount), 0) - sa.cost_usd) AS excess_amount
                FROM sms_activations sa
                JOIN transactions t ON t.user_id = sa.user_id 
                    AND t.type = 'refund' 
                    AND (t.description LIKE '%' || sa.phone || '%' OR t.description LIKE '%' || sa.activation_id || '%')
                GROUP BY sa.activation_id, sa.user_id, sa.phone, sa.cost_usd
                HAVING COALESCE(SUM(t.amount), 0) > sa.cost_usd
                """
            )
            
            for row in rows:
                act_id = str(row["activation_id"])
                user_id = int(row["user_id"])
                phone = str(row["phone"])
                excess = float(row["excess_amount"])
                
                if excess <= 0:
                    continue
                
                already_corrected = await db.fetchval(
                    """
                    SELECT COUNT(*) 
                    FROM transactions 
                    WHERE user_id = $1 
                      AND type = 'deduction' 
                      AND (description LIKE '%' || $2 || '%' OR description LIKE '%' || $3 || '%')
                      AND description LIKE '%Correction: Deduct duplicate SMS refund%'
                    """,
                    user_id, phone, act_id
                )
                
                if already_corrected and already_corrected > 0:
                    continue
                
                new_balance = await db.fetchval(
                    """
                    UPDATE users
                    SET balance = balance - $1
                    WHERE user_id = $2
                    RETURNING balance
                    """,
                    excess, user_id
                )
                
                desc = f"Correction: Deduct duplicate SMS refund ({phone})"
                await db.execute(
                    "INSERT INTO transactions (user_id, type, amount, description) VALUES ($1, 'deduction', $2, $3)",
                    user_id, excess, desc
                )
                
                _invalidate_user_cache(user_id)
                results.append({
                    "user_id": user_id,
                    "phone": phone,
                    "excess_deducted": excess,
                    "new_balance": float(new_balance) if new_balance is not None else 0.0
                })
                
    if results:
        logger.info("Fixed duplicate SMS refund debts: %s", results)
    return results


# ─── Helpers ──────────────────────────────────────────────────────────────────




def _row_to_dict(row) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return dict(row)


def get_account_age_days(user_id: int) -> int:
    """تقدير عمر الحساب من معرف تيليجرام (snowflake).
    
    تيليجرام يستخدم Snowflake IDs — الـ 22 بت الأعلى تمثّل الثواني منذ epoch.
    الخطأ القديم: كان يستخدم >> 32 للمعرفات الكبيرة، مما أعطى نتائج خاطئة.
    """
    try:
        TELEGRAM_EPOCH = 1376438400
        # >> 22 صحيح لجميع معرفات تيليجرام بغض النظر عن حجمها
        shift = user_id >> 22
        created_ts = TELEGRAM_EPOCH + shift
        age = (datetime.now(timezone.utc).timestamp() - created_ts) / 86400
        return max(0, int(age))
    except Exception:
        return 9999


# ─── Users ────────────────────────────────────────────────────────────────────

_user_cache: Dict[int, tuple] = {}
_USER_TTL = 30  # ثانية

async def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    import time as _time
    now = _time.monotonic()
    if user_id in _user_cache:
        val, exp = _user_cache[user_id]
        if now < exp:
            return val
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        result = _row_to_dict(row)
        if result is not None:
            _user_cache[user_id] = (result, now + _USER_TTL)
        else:
            _user_cache.pop(user_id, None)
        return result

def _invalidate_user_cache(user_id: int):
    _user_cache.pop(user_id, None)





async def get_all_user_ids() -> List[int]:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch("SELECT user_id FROM users")
        return [r["user_id"] for r in rows]


async def reset_user_for_testing(user_id: int) -> bool:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute("DELETE FROM referral_logs WHERE referrer_id = $1 OR referred_id = $1", user_id)
            await db.execute("DELETE FROM device_fingerprints WHERE user_id = $1", user_id)
            await db.execute("DELETE FROM users WHERE user_id = $1", user_id)
        _invalidate_user_cache(user_id)
        return True
    except Exception as e:
        logger.error("reset_user_for_testing error for %s: %s", user_id, e)
        return False


async def create_user(
    user_id: int,
    username: Optional[str],
    first_name: Optional[str],
) -> Dict[str, Any]:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute(
                """
                INSERT INTO users (user_id, username, first_name, is_verified, language)
                VALUES ($1, $2, $3, 1, 'ar')
                ON CONFLICT (user_id) DO NOTHING
                """,
                user_id, username, first_name,
            )
        _invalidate_user_cache(user_id)
        user = await get_user(user_id)
        if user:
            return user
    except Exception as e:
        logger.error("create_user exception for user %s: %s", user_id, e)

    return {
        "user_id": user_id,
        "username": username,
        "first_name": first_name,
        "language": "ar",
        "is_verified": 1,
        "balance": 0.0,
        "points": 0,
    }


async def update_user_profile(user_id: int, username: Optional[str], first_name: Optional[str]):
    """تحديث اسم المستخدم ويوزره تلقائياً عند كل /start."""
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """UPDATE users
               SET username   = COALESCE($1, username),
                   first_name = COALESCE($2, first_name)
               WHERE user_id = $3""",
            username, first_name, user_id,
        )


async def update_user_language(user_id: int, language: str):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE users SET language = $1 WHERE user_id = $2", language, user_id
        )
    _invalidate_user_cache(user_id)


async def mark_user_verified(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE users SET is_verified = 1 WHERE user_id = $1", user_id
        )


async def set_user_banned(user_id: int, banned: bool, reason: Optional[str] = None):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE users SET is_banned = $1, ban_reason = $2 WHERE user_id = $3",
            1 if banned else 0, reason, user_id,
        )
    _invalidate_user_cache(user_id)


async def unban_user(user_id: int):
    """إلغاء حظر مستخدم وحذفه من قائمة حظر النجوم وقائمة الحظر العامة."""
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE users SET is_banned = 0, ban_reason = NULL WHERE user_id = $1", user_id
        )
        await db.execute("DELETE FROM stars_refunds WHERE user_id = $1", user_id)
    _invalidate_user_cache(user_id)


async def get_banned_users() -> List[Dict[str, Any]]:
    """يسترجع جميع المستخدمين المحظورين حالياً."""
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            "SELECT user_id, username, first_name, ban_reason FROM users WHERE is_banned = 1"
        )
        return [dict(r) for r in rows]


async def unban_all_banned_users() -> int:
    """إلغاء حظر جميع المستخدمين المحظورين وإعادة تفعيل حساباتهم."""
    pool = await get_pool()
    async with pool.acquire() as db:
        res = await db.execute("UPDATE users SET is_banned = 0, ban_reason = NULL WHERE is_banned = 1")
        await db.execute("DELETE FROM stars_refunds")
        _user_cache.clear()
        try:
            return int(res.split()[-1])
        except Exception:
            return 0


# ─── نجوم — حظر وفحص ──────────────────────────────────────────────────────────

async def is_tx_id_already_used(tx_id: str) -> bool:
    """
    يتحقق ما إذا كان Transaction ID / Order ID قد استُخدم مسبقاً.
    يفحص جدولَي payments (التلقائية) و manual_payments (اليدوية) معاً،
    لمنع إعادة استخدام نفس الـ ID سواء أُودع يدوياً أو تلقائياً.
    """
    pool = await get_pool()
    async with pool.acquire() as db:
        # فحص الإيداعات التلقائية
        row = await db.fetchrow(
            "SELECT id FROM payments WHERE provider_ref = $1 AND status IN ('confirmed', 'pending') LIMIT 1",
            tx_id,
        )
        if row:
            return True
        # فحص الإيداعات اليدوية (approved أو pending)
        row2 = await db.fetchrow(
            "SELECT id FROM manual_payments WHERE tx_hash = $1 AND status IN ('approved', 'pending') LIMIT 1",
            tx_id,
        )
        return row2 is not None


async def is_stars_banned(user_id: int) -> bool:
    """هل سبق وتسبّب هذا المستخدم في استرداد نجوم؟"""
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            "SELECT id FROM stars_refunds WHERE user_id = $1 LIMIT 1", user_id
        )
        return row is not None


async def is_trusted_stars_customer(user_id: int) -> bool:
    """
    يتأكد مما إذا كان المستخدم عميلاً قديماً موثوقاً قام بشحن النجوم مسبقاً بنجاح ولم يقم بأي استرداد للنجوم.
    """
    if await is_stars_banned(user_id):
        return False

    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            """
            SELECT id FROM payments 
            WHERE user_id = $1 
              AND provider = 'Telegram Stars' 
              AND status = 'confirmed' 
            LIMIT 1
            """,
            user_id
        )
        return row is not None


async def log_stars_refund(
    user_id: int,
    stars: int,
    usd_amount: float,
    order_id: Optional[str] = None,
):
    """يسجّل استرداد نجوم ويُضيف المستخدم للقائمة السوداء تلقائياً."""
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """
            INSERT INTO stars_refunds (user_id, stars, usd_amount, order_id)
            VALUES ($1, $2, $3, $4)
            """,
            user_id, stars, usd_amount, order_id,
        )


# ─── Settings ─────────────────────────────────────────────────────────────────

async def get_setting(key: str) -> Optional[str]:
    now = time.time()
    if key in _settings_cache:
        val, exp = _settings_cache[key]
        if now < exp:
            return val
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow("SELECT value FROM settings WHERE key = $1", key)
        val = row["value"] if row else None
        _settings_cache[key] = (val, now + _SETTINGS_TTL)
        return val


async def set_setting(key: str, value: str):
    _settings_cache[key] = (value, time.time() + _SETTINGS_TTL)
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """
            INSERT INTO settings (key, value) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            key, value,
        )


# ─── Stats ────────────────────────────────────────────────────────────────────

async def get_bot_stats() -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as db:
        total_users     = await db.fetchval("SELECT COUNT(*) FROM users") or 0
        total_deposits  = await db.fetchval(
            "SELECT COALESCE(SUM(amount_usd), 0) FROM payments WHERE status = 'confirmed'"
        ) or 0.0
        total_sold      = await db.fetchval(
            "SELECT COUNT(*) FROM accounts_inventory WHERE status = 'sold'"
        ) or 0
        total_available = await db.fetchval(
            "SELECT COUNT(*) FROM accounts_inventory WHERE status = 'available'"
        ) or 0
        total_countries = await db.fetchval("SELECT COUNT(*) FROM country_prices") or 0
        return {
            "total_users":     int(total_users),
            "total_deposits":  float(total_deposits),
            "total_sold":      int(total_sold),
            "total_available": int(total_available),
            "total_countries": int(total_countries),
        }


# ─── Balance ──────────────────────────────────────────────────────────────────

async def add_balance(user_id: int, amount: float, description: str = "Admin top-up"):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """
            UPDATE users
            SET balance         = balance + $1,
                total_deposited = total_deposited + $1,
                deposit_count   = deposit_count + 1
            WHERE user_id = $2
            """,
            amount, user_id,
        )
        await db.execute(
            "INSERT INTO transactions (user_id, type, amount, description) VALUES ($1, 'deposit', $2, $3)",
            user_id, amount, description,
        )
    _invalidate_user_cache(user_id)


async def deduct_balance(user_id: int, amount: float, description: str = "Admin deduction"):
    pool = await get_pool()
    async with pool.acquire() as db:
        # نستخدم CTE لقراءة الرصيد القديم قبل التحديث، ثم نحسب المبلغ الفعلي المخصوم.
        # الخطأ السابق: "RETURNING balance" كان يُرجع الرصيد بعد التحديث لا قبله.
        row = await db.fetchrow(
            """
            WITH old AS (
                SELECT balance FROM users WHERE user_id = $2
            ),
            updated AS (
                UPDATE users
                SET balance          = GREATEST(0, balance - $1),
                    total_withdrawn  = total_withdrawn + LEAST($1::NUMERIC, balance),
                    withdrawal_count = withdrawal_count + 1
                WHERE user_id = $2
                RETURNING 1
            )
            SELECT LEAST($1::NUMERIC, old.balance) AS actual_deducted
            FROM old, updated
            """,
            amount, user_id,
        )
        # سجّل المبلغ الفعلي المخصوم (ما خُصم فعلاً) لا المبلغ المطلوب
        actual = float(row["actual_deducted"]) if row and row["actual_deducted"] is not None else amount
        await db.execute(
            "INSERT INTO transactions (user_id, type, amount, description) VALUES ($1, 'deduction', $2, $3)",
            user_id, actual, description,
        )
    _invalidate_user_cache(user_id)


# ─── Points ───────────────────────────────────────────────────────────────────

async def add_points(user_id: int, points: int, description: str = ""):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("UPDATE users SET points = points + $1 WHERE user_id = $2", points, user_id)
        if description:
            await db.execute(
                "INSERT INTO transactions (user_id, type, amount, description) VALUES ($1, 'add_points', $2, $3)",
                user_id, points, description,
            )
    _invalidate_user_cache(user_id)


async def is_promo_sent(phone: str) -> bool:
    return True


async def mark_promo_sent(phone: str) -> None:
    pass


async def deduct_points(user_id: int, points: int, description: str = ""):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("UPDATE users SET points = GREATEST(0, points - $1) WHERE user_id = $2", points, user_id)
        if description:
            await db.execute(
                "INSERT INTO transactions (user_id, type, amount, description) VALUES ($1, 'deduct_points', $2, $3)",
                user_id, points, description,
            )
    _invalidate_user_cache(user_id)


# ─── Phone / IP Verification ──────────────────────────────────────────────────

async def is_phone_already_used(phone: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            "SELECT phone FROM verified_phones WHERE phone = $1", phone
        )
        return row is not None


async def register_verified_phone(user_id: int, phone: str):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "INSERT INTO verified_phones (phone, user_id) VALUES ($1, $2) ON CONFLICT (phone) DO NOTHING",
            phone, user_id,
        )


async def is_ip_already_used(ip: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow("SELECT ip FROM verified_ips WHERE ip = $1", ip)
        return row is not None


async def register_verified_ip(user_id: int, ip: str):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "INSERT INTO verified_ips (ip, user_id) VALUES ($1, $2) ON CONFLICT (ip) DO NOTHING",
            ip, user_id,
        )


# ─── Pending Leaves (Channel Monitor) ────────────────────────────────────────

async def add_pending_leave(user_id: int, deadline: datetime):
    if isinstance(deadline, datetime) and deadline.tzinfo is not None:
        deadline = deadline.astimezone(timezone.utc).replace(tzinfo=None)
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """
            INSERT INTO pending_leaves (user_id, deadline)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET deadline = EXCLUDED.deadline
            """,
            user_id, deadline,
        )


async def remove_pending_leave(user_id: int):
    await delete_pending_leave(user_id)


async def get_pending_leave(user_id: int) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            "SELECT * FROM pending_leaves WHERE user_id = $1", user_id
        )
        return _row_to_dict(row)


async def get_all_pending_leaves() -> List[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch("SELECT * FROM pending_leaves")
        return [dict(r) for r in rows]


async def delete_pending_leave(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "DELETE FROM pending_leaves WHERE user_id = $1", user_id
        )


# ─── Countries / Inventory ────────────────────────────────────────────────────

async def get_countries_with_stock() -> List[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """
            SELECT cp.country_code, cp.country_name, cp.flag_emoji, cp.price,
                   cp.flash_sale_discount, cp.flash_sale_until,
                   COUNT(ai.id) AS stock_count
            FROM country_prices cp
            LEFT JOIN accounts_inventory ai
                ON ai.country_code = cp.country_code
                AND ai.status = 'available'
                AND ai.store_type = 'dollar'
            GROUP BY cp.country_code, cp.country_name, cp.flag_emoji, cp.price,
                     cp.flash_sale_discount, cp.flash_sale_until
            HAVING COUNT(ai.id) > 0
            ORDER BY cp.country_name
            """
        )
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        results = []
        for r in rows:
            d = dict(r)
            discount  = float(d.get("flash_sale_discount") or 0)
            until     = d.get("flash_sale_until")
            if discount > 0 and until and until > now:
                d["has_flash_sale"]  = True
                d["effective_price"] = round(float(d["price"]) * (1 - discount / 100), 4)
            else:
                d["has_flash_sale"]  = False
                d["effective_price"] = float(d["price"])
            results.append(d)
        return results


async def get_countries_with_points_stock() -> List[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """
            SELECT cp.country_code, cp.country_name, cp.flag_emoji, cp.points_price,
                   COUNT(ai.id) AS stock_count
            FROM country_prices cp
            LEFT JOIN accounts_inventory ai
                ON ai.country_code = cp.country_code
                AND ai.status = 'available'
                AND ai.store_type = 'points'
            WHERE cp.points_price > 0
            GROUP BY cp.country_code, cp.country_name, cp.flag_emoji, cp.points_price
            HAVING COUNT(ai.id) > 0
            ORDER BY cp.country_name
            """
        )
        return [dict(r) for r in rows]


async def get_all_countries() -> List[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """
            SELECT cp.country_code, cp.country_name, cp.flag_emoji, cp.price, cp.points_price,
                   COUNT(ai.id) AS stock_count
            FROM country_prices cp
            LEFT JOIN accounts_inventory ai
                ON ai.country_code = cp.country_code AND ai.status = 'available'
            GROUP BY cp.country_code, cp.country_name, cp.flag_emoji, cp.price, cp.points_price
            ORDER BY cp.country_name
            """
        )
        return [dict(r) for r in rows]


async def get_country(country_code: str) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            "SELECT * FROM country_prices WHERE country_code = $1", country_code
        )
        return _row_to_dict(row)


async def add_country(
    country_code: str,
    country_name: str,
    flag_emoji: str,
    price: float,
    points_price: int = 0,
):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """
            INSERT INTO country_prices (country_code, country_name, flag_emoji, price, points_price)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (country_code) DO UPDATE
                SET country_name  = EXCLUDED.country_name,
                    flag_emoji    = EXCLUDED.flag_emoji,
                    price         = EXCLUDED.price,
                    points_price  = EXCLUDED.points_price
            """,
            country_code, country_name, flag_emoji, price, points_price,
        )


async def update_country_price(country_code: str, price: float):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE country_prices SET price = $1 WHERE country_code = $2",
            price, country_code,
        )


async def update_country_points_price(country_code: str, points_price: int):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE country_prices SET points_price = $1 WHERE country_code = $2",
            points_price, country_code,
        )


async def add_account_to_stock(
    country_code: str,
    country_name: str,
    account_data: str,
    price: float,
    store_type: str = "dollar",
    status: str = "available",
) -> int:
    """
    يُضيف حساباً إلى المخزون.

    status: 'available' (جاهز للبيع) | 'maintenance' (في انتظار التحقق).
    عند الإضافة عبر لوحة الأدمن، يجب تمرير status='maintenance' ثم تفعيله
    بعد التحقق من الجلسة — راجع _validate_and_activate_stock في admin.py.
    """
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            """
            INSERT INTO accounts_inventory
                (country_code, country_name, account_data, price, store_type, status)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            country_code, country_name, account_data, price, store_type, status,
        )
        return row["id"]


async def purchase_account(user_id: int, country_code: str) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.transaction():
            user = await db.fetchrow(
                "SELECT balance FROM users WHERE user_id = $1 FOR UPDATE", user_id
            )
            country = await db.fetchrow(
                "SELECT * FROM country_prices WHERE country_code = $1", country_code
            )
            if not user or not country:
                return None

            price = float(country["price"])
            discount  = float(country.get("flash_sale_discount") or 0)
            flash_until = country.get("flash_sale_until")
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if discount > 0 and flash_until and flash_until > now:
                price = round(price * (1 - discount / 100), 4)
            if float(user["balance"]) < price:
                return None

            account = await db.fetchrow(
                """
                SELECT * FROM accounts_inventory
                WHERE country_code = $1 AND status = 'available' AND store_type = 'dollar'
                ORDER BY added_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED
                """,
                country_code,
            )
            if not account:
                return None

            await db.execute(
                "UPDATE accounts_inventory SET status='sold', sold_at=NOW(), sold_to_user_id=$1, price=$3 WHERE id=$2",
                user_id, account["id"], price,
            )
            await db.execute(
                """
                UPDATE users
                SET balance            = balance - $1,
                    total_withdrawn    = total_withdrawn + $1,
                    withdrawal_count   = withdrawal_count + 1,
                    accounts_purchased = accounts_purchased + 1
                WHERE user_id = $2
                """,
                price, user_id,
            )
            await db.execute(
                "INSERT INTO transactions (user_id, type, amount, description) VALUES ($1,'purchase',$2,$3)",
                user_id, price, f"Purchased account — {country['country_name']}",
            )
            return {
                "id":           account["id"],
                "account_data": account["account_data"],
                "price":        price,
                "new_balance":  float(user["balance"]) - price,
                "country_name": country["country_name"],
            }


async def purchase_account_points(user_id: int, country_code: str) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.transaction():
            user = await db.fetchrow(
                "SELECT points FROM users WHERE user_id = $1 FOR UPDATE", user_id
            )
            country = await db.fetchrow(
                "SELECT * FROM country_prices WHERE country_code = $1", country_code
            )
            if not user or not country:
                return None

            pts_price   = int(country.get("points_price") or 0)
            user_points = int(user["points"] or 0)

            if pts_price <= 0 or user_points < pts_price:
                return None

            account = await db.fetchrow(
                """
                SELECT * FROM accounts_inventory
                WHERE country_code = $1 AND status = 'available' AND store_type = 'points'
                ORDER BY added_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED
                """,
                country_code,
            )
            if not account:
                return None

            await db.execute(
                "UPDATE accounts_inventory SET status='sold', sold_at=NOW(), sold_to_user_id=$1, price=$3 WHERE id=$2",
                user_id, account["id"], float(pts_price),
            )
            await db.execute(
                """
                UPDATE users
                SET points             = GREATEST(0, points - $1),
                    accounts_purchased = accounts_purchased + 1
                WHERE user_id = $2
                """,
                pts_price, user_id,
            )
            await db.execute(
                "INSERT INTO transactions (user_id, type, amount, description) VALUES ($1,'points_purchase',$2,$3)",
                user_id, float(pts_price),
                f"Purchased account with points — {country['country_name']}",
            )
            return {
                "id":           account["id"],
                "account_data": account["account_data"],
                "points_price": pts_price,
                "new_points":   user_points - pts_price,
                "country_name": country["country_name"],
                "flag_emoji":   country.get("flag_emoji", "🌍"),
            }


async def refund_account_purchase(
    account_id: int,
    user_id: int,
    mark_invalid: bool = False,
) -> bool:
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.transaction():
            account = await db.fetchrow(
                "SELECT * FROM accounts_inventory WHERE id = $1 AND sold_to_user_id = $2",
                account_id, user_id,
            )
            if not account:
                return False

            price      = float(account["price"])
            store_type = account.get("store_type", "dollar")

            if mark_invalid:
                await db.execute("DELETE FROM accounts_inventory WHERE id = $1", account_id)
            else:
                await db.execute(
                    "UPDATE accounts_inventory SET status='available', sold_at=NULL, sold_to_user_id=NULL WHERE id=$1",
                    account_id,
                )

            if store_type == "points":
                pts_price = int(price)
                await db.execute(
                    "UPDATE users SET points = points + $1, accounts_purchased = GREATEST(0, accounts_purchased-1) WHERE user_id=$2",
                    pts_price, user_id,
                )
                await db.execute(
                    "INSERT INTO transactions (user_id, type, amount, description) VALUES ($1,'points_refund',$2,$3)",
                    user_id, float(pts_price), "Refund — session invalid or timeout",
                )
            else:
                await db.execute(
                    """
                    UPDATE users
                    SET balance            = balance + $1,
                        total_withdrawn    = GREATEST(0, total_withdrawn - $1),
                        withdrawal_count   = GREATEST(0, withdrawal_count - 1),
                        accounts_purchased = GREATEST(0, accounts_purchased - 1)
                    WHERE user_id = $2
                    """,
                    price, user_id,
                )
                await db.execute(
                    "INSERT INTO transactions (user_id, type, amount, description) VALUES ($1,'refund',$2,$3)",
                    user_id, price, "Refund — session invalid or timeout",
                )
            return True


async def refund_to_maintenance(
    account_id: int,
    user_id: int,
) -> bool:
    """
    يُعيد الحساب لحالة 'maintenance' (لا 'available') بعد انتهاء مهلة الكود.
    هذا يمنع بيع نفس الحساب مباشرةً مرة ثانية قبل مراجعة الأدمن.
    يُسترد رصيد المستخدم كالعادة.
    """
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.transaction():
            account = await db.fetchrow(
                "SELECT * FROM accounts_inventory WHERE id = $1 AND sold_to_user_id = $2",
                account_id, user_id,
            )
            if not account:
                return False

            price      = float(account["price"])
            store_type = account.get("store_type", "dollar")

            # ← الفرق الوحيد عن refund_account_purchase: 'maintenance' بدلاً من 'available'
            await db.execute(
                "UPDATE accounts_inventory SET status='maintenance', sold_at=NULL, sold_to_user_id=NULL WHERE id=$1",
                account_id,
            )

            if store_type == "points":
                pts_price = int(price)
                await db.execute(
                    "UPDATE users SET points = points + $1, accounts_purchased = GREATEST(0, accounts_purchased-1) WHERE user_id=$2",
                    pts_price, user_id,
                )
                await db.execute(
                    "INSERT INTO transactions (user_id, type, amount, description) VALUES ($1,'points_refund',$2,$3)",
                    user_id, float(pts_price), "Refund — code timeout (sent to maintenance)",
                )
            else:
                await db.execute(
                    """
                    UPDATE users
                    SET balance            = balance + $1,
                        total_withdrawn    = GREATEST(0, total_withdrawn - $1),
                        withdrawal_count   = GREATEST(0, withdrawal_count - 1),
                        accounts_purchased = GREATEST(0, accounts_purchased - 1)
                    WHERE user_id = $2
                    """,
                    price, user_id,
                )
                await db.execute(
                    "INSERT INTO transactions (user_id, type, amount, description) VALUES ($1,'refund',$2,$3)",
                    user_id, price, "Refund — code timeout (sent to maintenance)",
                )
            return True


# ─── Payments ─────────────────────────────────────────────────────────────────

async def create_payment(
    order_id: str,
    user_id: int,
    provider: str,
    amount_usd: float,
    provider_ref: Optional[str] = None,
) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """
            INSERT INTO payments (order_id, user_id, provider, amount_usd, provider_ref)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (order_id) DO NOTHING
            """,
            order_id, user_id, provider, amount_usd, provider_ref,
        )
        row = await db.fetchrow("SELECT * FROM payments WHERE order_id = $1", order_id)
        return dict(row) if row else {}


async def confirm_payment(order_id: str) -> Optional[Dict[str, Any]]:
    """
    تأكيد الدفع: يُضيف الرصيد للمستخدم ويُحدّث حالة الدفع إلى confirmed.
    يُرجع سجل الدفع أو None إذا كان مؤكداً مسبقاً / غير موجود.
    """
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.transaction():
            payment = await db.fetchrow(
                "SELECT * FROM payments WHERE order_id = $1 AND status = 'pending' FOR UPDATE",
                order_id,
            )
            if not payment:
                return None

            amount  = float(payment["amount_usd"])
            user_id = payment["user_id"]

            await db.execute(
                "UPDATE payments SET status='confirmed', confirmed_at=NOW() WHERE order_id=$1",
                order_id,
            )
            new_balance = await db.fetchval(
                """
                UPDATE users
                SET balance         = balance + $1,
                    total_deposited = total_deposited + $1,
                    deposit_count   = deposit_count + 1
                WHERE user_id = $2
                RETURNING balance
                """,
                amount, user_id,
            )
            await db.execute(
                "INSERT INTO transactions (user_id, type, amount, description) VALUES ($1,'deposit',$2,$3)",
                user_id, amount,
                f"Payment confirmed — {payment['provider']} — {order_id}",
            )
            _invalidate_user_cache(user_id)
            res = dict(payment)
            res["new_balance"] = float(new_balance) if new_balance is not None else amount
            return res


async def get_available_accounts_by_country(country_code: str) -> List[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            "SELECT * FROM accounts_inventory WHERE country_code = $1 AND status = 'available' ORDER BY added_at DESC",
            country_code,
        )
        return [dict(r) for r in rows]


async def delete_account_from_stock(account_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as db:
        res = await db.execute("DELETE FROM accounts_inventory WHERE id = $1", account_id)
        return res != "DELETE 0"


async def update_account_data_by_old(old_data: str, new_data: str) -> bool:
    """يحدّث account_data في المخزون (يُستخدم بعد تغيير الباسوورد للحسابات المتاحة)."""
    pool = await get_pool()
    async with pool.acquire() as db:
        res = await db.execute(
            "UPDATE accounts_inventory SET account_data = $1 WHERE account_data = $2",
            new_data, old_data,
        )
        return res != "UPDATE 0"


async def update_account_data_by_id(account_id: int, new_data: str) -> bool:
    """يحدّث account_data بواسطة ID مباشرة (بدون شرط status).
    يُستخدم أثناء الاستيراد قبل أن يصبح الحساب 'available'."""
    pool = await get_pool()
    async with pool.acquire() as db:
        res = await db.execute(
            "UPDATE accounts_inventory SET account_data = $1 WHERE id = $2",
            new_data, account_id,
        )
        return res != "UPDATE 0"


async def get_account_status_and_data(account_id: int) -> Optional[Dict[str, Any]]:
    """يُرجع status و account_data الحاليين لحساب معيّن.

    يُستخدم قبل الاتصال بأي حساب في عمليات تغيير الباسوورد الجماعي، للتأكد
    أن الحساب لم يُبَع (status تغيّر إلى sold) بين لحظة جلب القائمة ولحظة
    الاتصال الفعلي — لتجنّب تغيير باسوورد حساب بِيع للتو وتسليم المشتري
    باسوورد قديم لا يعمل، أو تحديث سجل حساب لم يعد متوفراً.
    """
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            "SELECT status, account_data FROM accounts_inventory WHERE id = $1",
            account_id,
        )
        return dict(row) if row else None


async def get_all_available_accounts() -> List[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            "SELECT id, country_code, country_name, account_data FROM accounts_inventory WHERE status = 'available' ORDER BY country_code"
        )
        return [dict(r) for r in rows]





async def set_account_status(account_id: int, status: str):
    """تغيير حالة حساب (available / maintenance / sold)."""
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE accounts_inventory SET status = $1 WHERE id = $2",
            status, account_id,
        )


async def get_accounts_for_maintenance_view(country_code: str) -> List[Dict[str, Any]]:
    """يُرجع الحسابات المتاحة + الصيانة لدولة معينة."""
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            "SELECT id, account_data, status, store_type FROM accounts_inventory "
            "WHERE country_code = $1 AND status IN ('available', 'maintenance') "
            "ORDER BY status DESC, added_at DESC",
            country_code,
        )
        return [dict(r) for r in rows]


async def get_all_countries_with_stock_or_maintenance() -> List[Dict[str, Any]]:
    """يُرجع الدول التي تحتوي على حسابات متاحة أو في صيانة."""
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """
            SELECT cp.country_code, cp.country_name, cp.flag_emoji,
                   COUNT(CASE WHEN ai.status = 'available'    THEN 1 END) AS available_count,
                   COUNT(CASE WHEN ai.status = 'maintenance'  THEN 1 END) AS maintenance_count
            FROM country_prices cp
            LEFT JOIN accounts_inventory ai
                ON ai.country_code = cp.country_code
                AND ai.status IN ('available', 'maintenance')
            GROUP BY cp.country_code, cp.country_name, cp.flag_emoji
            HAVING COUNT(ai.id) > 0
            ORDER BY cp.country_name
            """
        )
        return [dict(r) for r in rows]


# ─── Flash Sale ───────────────────────────────────────────────────────────────

async def set_flash_sale(country_code: str, discount_pct: float, hours: float):
    until = datetime.now(timezone.utc).replace(tzinfo=None)
    from datetime import timedelta
    until = until + timedelta(hours=hours)
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """
            UPDATE country_prices
            SET flash_sale_discount = $1, flash_sale_until = $2
            WHERE country_code = $3
            """,
            discount_pct, until, country_code,
        )


async def clear_flash_sale(country_code: str):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE country_prices SET flash_sale_discount = 0, flash_sale_until = NULL WHERE country_code = $1",
            country_code,
        )


async def get_active_flash_sales() -> List[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as db:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        rows = await db.fetch(
            """
            SELECT country_code, country_name, flag_emoji, price,
                   flash_sale_discount, flash_sale_until
            FROM country_prices
            WHERE flash_sale_discount > 0 AND flash_sale_until > $1
            ORDER BY flash_sale_until
            """,
            now,
        )
        return [dict(r) for r in rows]


# ─── Ratings ──────────────────────────────────────────────────────────────────

async def add_rating(account_id: int, user_id: int, country_code: str, rating: int):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """
            INSERT INTO ratings (account_id, user_id, country_code, rating)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (account_id, user_id) DO UPDATE SET rating = EXCLUDED.rating
            """,
            account_id, user_id, country_code, rating,
        )


async def get_country_avg_rating(country_code: str) -> Optional[float]:
    pool = await get_pool()
    async with pool.acquire() as db:
        val = await db.fetchval(
            "SELECT AVG(rating)::NUMERIC(3,1) FROM ratings WHERE country_code = $1",
            country_code,
        )
        return float(val) if val is not None else None


async def get_ratings_stats() -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as db:
        total  = await db.fetchval("SELECT COUNT(*) FROM ratings") or 0
        avg    = await db.fetchval("SELECT AVG(rating)::NUMERIC(3,1) FROM ratings")
        rows   = await db.fetch(
            """
            SELECT country_code, COUNT(*) AS cnt, AVG(rating)::NUMERIC(3,1) AS avg_rating
            FROM ratings
            GROUP BY country_code
            ORDER BY avg_rating DESC
            LIMIT 10
            """
        )
        return {
            "total_ratings": int(total),
            "overall_avg":   float(avg) if avg else 0.0,
            "by_country":    [dict(r) for r in rows],
        }


# ─── Pending OTP Sessions ─────────────────────────────────────────────────────

async def save_pending_session(account_id: int, data: dict):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """
            INSERT INTO pending_otp_sessions
                (account_id, buyer_id, lang, country_name, refetch_count,
                 sent_at, expires_at, parsed_json)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (account_id) DO UPDATE
                SET buyer_id      = EXCLUDED.buyer_id,
                    lang          = EXCLUDED.lang,
                    country_name  = EXCLUDED.country_name,
                    refetch_count = EXCLUDED.refetch_count,
                    sent_at       = EXCLUDED.sent_at,
                    expires_at    = EXCLUDED.expires_at,
                    parsed_json   = EXCLUDED.parsed_json
            """,
            account_id,
            data["buyer_id"],
            data.get("lang", "ar"),
            data.get("country_name", ""),
            data.get("refetch_count", 0),
            data["sent_at"].replace(tzinfo=None),
            data["expires_at"].replace(tzinfo=None),
            json.dumps(data["parsed"]),
        )


async def update_pending_session_refetch(account_id: int, refetch_count: int):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE pending_otp_sessions SET refetch_count = $1 WHERE account_id = $2",
            refetch_count, account_id,
        )


async def delete_pending_session(account_id: int):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "DELETE FROM pending_otp_sessions WHERE account_id = $1", account_id
        )


async def load_all_pending_sessions() -> list:
    pool = await get_pool()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with pool.acquire() as db:
        rows = await db.fetch(
            "SELECT * FROM pending_otp_sessions WHERE expires_at > $1", now
        )
        return [dict(r) for r in rows]


# ─── Manual Binance Payments ──────────────────────────────────────────────────

async def create_manual_payment(user_id: int, amount_usd: float, tx_hash: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            """
            INSERT INTO manual_payments (user_id, amount_usd, tx_hash, status)
            VALUES ($1, $2, $3, 'pending')
            RETURNING id
            """,
            user_id, amount_usd, tx_hash,
        )
        return row["id"]


async def get_manual_payment(payment_id: int) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            "SELECT * FROM manual_payments WHERE id = $1", payment_id
        )
        return _row_to_dict(row)


async def approve_manual_payment(payment_id: int) -> Tuple[Optional[float], Optional[float], Optional[int]]:
    """يوافق على الدفع ويضيف الرصيد للمستخدم. يُرجع (amount_usd, new_balance, user_id) أو (None, None, None) إذا تم مسبقاً."""
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.transaction():
            row = await db.fetchrow(
                "SELECT * FROM manual_payments WHERE id = $1 FOR UPDATE", payment_id
            )
            if not row or row["status"] != "pending":
                return None, None, None
            amount = float(row["amount_usd"])
            user_id = row["user_id"]
            await db.execute(
                """
                UPDATE manual_payments
                SET status = 'approved', reviewed_at = NOW()
                WHERE id = $1
                """,
                payment_id,
            )
            new_balance = await db.fetchval(
                """
                UPDATE users
                SET balance         = balance + $1,
                    total_deposited = total_deposited + $1,
                    deposit_count   = deposit_count + 1
                WHERE user_id = $2
                RETURNING balance
                """,
                amount, user_id,
            )
            await db.execute(
                "INSERT INTO transactions (user_id, type, amount, description) VALUES ($1, 'deposit', $2, $3)",
                user_id, amount, f"Manual Binance Pay — payment #{payment_id}",
            )
            _invalidate_user_cache(user_id)
            return amount, float(new_balance) if new_balance is not None else amount, user_id


async def reject_manual_payment(payment_id: int) -> bool:
    """يرفض الدفع. يُرجع True إذا تم تحديثه."""
    pool = await get_pool()
    async with pool.acquire() as db:
        result = await db.execute(
            """
            UPDATE manual_payments
            SET status = 'rejected', reviewed_at = NOW()
            WHERE id = $1 AND status = 'pending'
            """,
            payment_id,
        )
        return result == "UPDATE 1"



# ─── Sub-Admins ───────────────────────────────────────────────────────────────

async def init_sub_admins_table():
    """يُنشئ جدول الأدمن الفرعيين إذا لم يكن موجوداً."""
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sub_admins (
                user_id     BIGINT PRIMARY KEY,
                label       TEXT          DEFAULT '',
                perm_stock      INTEGER DEFAULT 0,
                perm_users      INTEGER DEFAULT 0,
                perm_stats      INTEGER DEFAULT 0,
                perm_deposits   INTEGER DEFAULT 0,
                perm_broadcast  INTEGER DEFAULT 0,
                added_at    TIMESTAMP DEFAULT NOW()
            )
        """)


async def add_sub_admin(user_id: int, label: str, perms: dict) -> bool:
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("""
            INSERT INTO sub_admins
                (user_id, label, perm_stock, perm_users, perm_stats, perm_deposits, perm_broadcast)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (user_id) DO UPDATE SET
                label        = EXCLUDED.label,
                perm_stock   = EXCLUDED.perm_stock,
                perm_users   = EXCLUDED.perm_users,
                perm_stats   = EXCLUDED.perm_stats,
                perm_deposits= EXCLUDED.perm_deposits,
                perm_broadcast=EXCLUDED.perm_broadcast
        """,
            user_id,
            label,
            1 if perms.get("stock")     else 0,
            1 if perms.get("users")     else 0,
            1 if perms.get("stats")     else 0,
            1 if perms.get("deposits")  else 0,
            1 if perms.get("broadcast") else 0,
        )
    return True


async def remove_sub_admin(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as db:
        result = await db.execute("DELETE FROM sub_admins WHERE user_id = $1", user_id)
        return result != "DELETE 0"


async def get_all_sub_admins() -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch("SELECT * FROM sub_admins ORDER BY added_at")
        return [dict(r) for r in rows]


async def get_sub_admin(user_id: int) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow("SELECT * FROM sub_admins WHERE user_id = $1", user_id)
        return _row_to_dict(row)


async def get_sub_admins_with_perm(perm: str) -> list:
    """يُرجع قائمة الأدمن الفرعيين الذين لديهم صلاحية معينة."""
    col_map = {
        "stock":     "perm_stock",
        "users":     "perm_users",
        "stats":     "perm_stats",
        "deposits":  "perm_deposits",
        "broadcast": "perm_broadcast",
    }
    col = col_map.get(perm)
    if not col:
        return []
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(f"SELECT * FROM sub_admins WHERE {col} = 1")
        return [dict(r) for r in rows]


# ─── Daily Stats ──────────────────────────────────────────────────────────────

async def get_daily_stats() -> Dict[str, Any]:
    """إحصائيات اليوم الحالي فقط."""
    pool = await get_pool()
    async with pool.acquire() as db:
        new_users = await db.fetchval(
            "SELECT COUNT(*) FROM users WHERE joined_at >= NOW() - INTERVAL '24 hours'"
        ) or 0
        daily_deposits = await db.fetchval(
            """SELECT COALESCE(SUM(amount_usd), 0) FROM payments
               WHERE status = 'confirmed' AND confirmed_at >= NOW() - INTERVAL '24 hours'"""
        ) or 0.0
        daily_sold = await db.fetchval(
            "SELECT COUNT(*) FROM accounts_inventory WHERE status = 'sold' AND sold_at >= NOW() - INTERVAL '24 hours'"
        ) or 0
        total_available = await db.fetchval(
            "SELECT COUNT(*) FROM accounts_inventory WHERE status = 'available'"
        ) or 0
        total_users = await db.fetchval("SELECT COUNT(*) FROM users") or 0
        total_deposits = await db.fetchval(
            "SELECT COALESCE(SUM(amount_usd), 0) FROM payments WHERE status = 'confirmed'"
        ) or 0.0
        # مبيعات حسب الدولة اليوم
        country_sales = await db.fetch(
            """SELECT country_name, COUNT(*) as cnt
               FROM accounts_inventory
               WHERE status = 'sold' AND sold_at >= NOW() - INTERVAL '24 hours'
               GROUP BY country_name ORDER BY cnt DESC LIMIT 5"""
        )
        return {
            "new_users":       int(new_users),
            "daily_deposits":  float(daily_deposits),
            "daily_sold":      int(daily_sold),
            "total_available": int(total_available),
            "total_users":     int(total_users),
            "total_deposits":  float(total_deposits),
            "country_sales":   [dict(r) for r in country_sales],
        }






# ══════════════════════════════════════════════════════════════════════════════
# ─── Sessions Inventory ───────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

async def _ensure_sessions_table():
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions_inventory (
                id              SERIAL PRIMARY KEY,
                country_code    TEXT          NOT NULL,
                country_name    TEXT          NOT NULL,
                flag_emoji      TEXT          DEFAULT '🌍',
                phone           TEXT          NOT NULL,
                session_data    TEXT          NOT NULL,
                password        TEXT          DEFAULT '',
                price           NUMERIC(12,4) NOT NULL,
                status          TEXT          DEFAULT 'available',
                added_at        TIMESTAMP     DEFAULT NOW(),
                sold_at         TIMESTAMP,
                sold_to_user_id BIGINT,
                bundle_order_id TEXT
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_country_status ON sessions_inventory(country_code, status)"
        )


async def add_sessions_batch(
    country_code: str,
    country_name: str,
    flag_emoji: str,
    sessions: list,
    password: str,
    price: float,
) -> int:
    """يُضيف دفعة جلسات إلى قاعدة البيانات. يُرجع عدد الجلسات المضافة."""
    await _ensure_sessions_table()
    pool = await get_pool()
    added = 0
    async with pool.acquire() as db:
        for sess in sessions:
            try:
                await db.execute(
                    """
                    INSERT INTO sessions_inventory
                        (country_code, country_name, flag_emoji, phone, session_data, password, price)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT DO NOTHING
                    """,
                    country_code, country_name, flag_emoji,
                    sess["phone"], sess["session_data"], password, price,
                )
                added += 1
            except Exception:
                pass
    return added


async def get_session_countries_with_stock() -> list:
    """يُرجع الدول التي لديها جلسات متاحة مع عدد المتاحة والسعر."""
    await _ensure_sessions_table()
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """
            SELECT country_code, country_name, flag_emoji,
                   MIN(price) AS price,
                   COUNT(*) AS available_count
            FROM sessions_inventory
            WHERE status = 'available'
            GROUP BY country_code, country_name, flag_emoji
            ORDER BY country_name
            """
        )
    return [dict(r) for r in rows]


async def get_session_country(country_code: str) -> Optional[Dict[str, Any]]:
    """يُرجع معلومات دولة الجلسات مع عدد المتاح."""
    await _ensure_sessions_table()
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            """
            SELECT country_code, country_name, flag_emoji,
                   MIN(price) AS price,
                   COUNT(*) AS available_count
            FROM sessions_inventory
            WHERE country_code = $1 AND status = 'available'
            GROUP BY country_code, country_name, flag_emoji
            """,
            country_code,
        )
    return dict(row) if row else None


async def purchase_sessions(
    user_id: int,
    country_code: str,
    quantity: int,
) -> Optional[Dict[str, Any]]:
    """
    يشتري qty جلسة من دولة محددة ويخصم الرصيد.
    يُرجع: {sessions, total_paid, new_balance, country_name, flag_emoji, password}
    أو None إذا فشل (رصيد غير كافٍ أو مخزون غير كافٍ).
    """
    await _ensure_sessions_table()
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.transaction():
            # احجز الجلسات أولاً (FOR UPDATE لمنع Race Condition)
            rows = await db.fetch(
                """
                SELECT id, phone, session_data, password, price, country_name, flag_emoji
                FROM sessions_inventory
                WHERE country_code = $1 AND status = 'available'
                ORDER BY added_at ASC
                LIMIT $2
                FOR UPDATE SKIP LOCKED
                """,
                country_code, quantity,
            )
            if len(rows) < quantity:
                return None

            total_price = sum(float(r["price"]) for r in rows)

            # تحقق من الرصيد
            user_row = await db.fetchrow(
                "SELECT balance FROM users WHERE user_id = $1 FOR UPDATE",
                user_id,
            )
            if not user_row or float(user_row["balance"]) < total_price:
                return None

            bundle_id = f"SESS-{user_id}-{int(__import__('time').time())}"

            # خصم الرصيد
            new_balance = await db.fetchval(
                """
                UPDATE users
                SET balance = balance - $1,
                    total_withdrawn = total_withdrawn + $1,
                    withdrawal_count = withdrawal_count + 1
                WHERE user_id = $2
                RETURNING balance
                """,
                total_price, user_id,
            )

            # تحديث حالة الجلسات
            ids = [r["id"] for r in rows]
            await db.execute(
                f"""
                UPDATE sessions_inventory
                SET status = 'sold', sold_at = NOW(),
                    sold_to_user_id = $1, bundle_order_id = $2
                WHERE id = ANY($3::int[])
                """,
                user_id, bundle_id, ids,
            )

            # تسجيل المعاملة
            await db.execute(
                "INSERT INTO transactions (user_id, type, amount, description) VALUES ($1, 'deduction', $2, $3)",
                user_id, total_price, f"شراء {quantity} جلسات - {country_code} [{bundle_id}]",
            )

            return {
                "sessions":     [dict(r) for r in rows],
                "total_paid":   round(total_price, 4),
                "new_balance":  round(float(new_balance), 4),
                "country_name": rows[0]["country_name"],
                "flag_emoji":   rows[0]["flag_emoji"],
                "password":     rows[0]["password"],
                "bundle_id":    bundle_id,
            }


async def delete_sessions_by_country(country_code: str) -> int:
    """يحذف الجلسات المتاحة لدولة معينة. يُرجع عدد المحذوفات."""
    await _ensure_sessions_table()
    pool = await get_pool()
    async with pool.acquire() as db:
        result = await db.execute(
            "DELETE FROM sessions_inventory WHERE country_code = $1 AND status = 'available'",
            country_code,
        )
    return int(result.split()[-1]) if result else 0


async def get_all_session_stats() -> Dict[str, Any]:
    """إحصائيات الجلسات الكاملة."""
    await _ensure_sessions_table()
    pool = await get_pool()
    async with pool.acquire() as db:
        available = await db.fetchval(
            "SELECT COUNT(*) FROM sessions_inventory WHERE status = 'available'"
        ) or 0
        sold = await db.fetchval(
            "SELECT COUNT(*) FROM sessions_inventory WHERE status = 'sold'"
        ) or 0
    return {"available": int(available), "sold": int(sold)}


async def get_available_accounts_for_conversion(country_code: str) -> list:
    """يُرجع الحسابات المتاحة في دولة معينة لتحويلها لجلسات."""
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """
            SELECT ai.id, ai.account_data, ai.price,
                   cp.country_name, cp.flag_emoji
            FROM accounts_inventory ai
            JOIN country_prices cp ON cp.country_code = ai.country_code
            WHERE ai.country_code = $1 AND ai.status = 'available'
            ORDER BY ai.added_at ASC
            """,
            country_code,
        )
    return [dict(r) for r in rows]


async def get_all_countries_with_accounts() -> list:
    """يُرجع الدول التي لديها حسابات متاحة مع العدد."""
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """
            SELECT cp.country_code, cp.country_name, cp.flag_emoji, cp.price,
                   COUNT(ai.id) AS account_count
            FROM country_prices cp
            JOIN accounts_inventory ai
                ON ai.country_code = cp.country_code AND ai.status = 'available'
            GROUP BY cp.country_code, cp.country_name, cp.flag_emoji, cp.price
            ORDER BY cp.country_name
            """
        )
    return [dict(r) for r in rows]


async def purchase_accounts_as_sessions(
    user_id: int,
    country_code: str,
    quantity: int,
) -> Optional[Dict[str, Any]]:
    """
    يشتري qty حساباً من accounts_inventory ويسلّمها كجلسات (.session).
    يُرجع: {accounts: [...], total_paid, new_balance, country_name, flag_emoji}
    أو None إذا فشل (رصيد غير كافٍ أو مخزون غير كافٍ).
    """
    if quantity <= 0 or quantity > 50:
        return None

    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.transaction():
            # احسب السعر الفعلي (مع Flash Sale)
            country = await db.fetchrow(
                "SELECT * FROM country_prices WHERE country_code = $1", country_code
            )
            if not country:
                return None

            unit_price = float(country["price"])
            discount   = float(country.get("flash_sale_discount") or 0)
            flash_until = country.get("flash_sale_until")
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if discount > 0 and flash_until and flash_until > now:
                unit_price = round(unit_price * (1 - discount / 100), 4)

            total_price = round(unit_price * quantity, 4)

            # تحقق من الرصيد
            user_row = await db.fetchrow(
                "SELECT balance FROM users WHERE user_id = $1 FOR UPDATE", user_id
            )
            if not user_row or float(user_row["balance"]) < total_price:
                return None

            # احجز الحسابات
            accounts = await db.fetch(
                """
                SELECT id, account_data FROM accounts_inventory
                WHERE country_code = $1 AND status = 'available' AND store_type = 'dollar'
                ORDER BY added_at ASC
                LIMIT $2
                FOR UPDATE SKIP LOCKED
                """,
                country_code, quantity,
            )
            if len(accounts) < quantity:
                return None

            ids = [a["id"] for a in accounts]

            # حدّث حالة الحسابات
            await db.execute(
                f"""
                UPDATE accounts_inventory
                SET status = 'sold', sold_at = NOW(), sold_to_user_id = $1, price = $2
                WHERE id = ANY($3::int[])
                """,
                user_id, unit_price, ids,
            )

            # خصم الرصيد
            new_balance = await db.fetchval(
                """
                UPDATE users
                SET balance            = balance - $1,
                    total_withdrawn    = total_withdrawn + $1,
                    withdrawal_count   = withdrawal_count + 1,
                    accounts_purchased = accounts_purchased + $2
                WHERE user_id = $3
                RETURNING balance
                """,
                total_price, quantity, user_id,
            )

            await db.execute(
                "INSERT INTO transactions (user_id, type, amount, description) VALUES ($1,'purchase',$2,$3)",
                user_id, total_price,
                f"شراء {quantity} جلسات — {country['country_name']}",
            )

            return {
                "accounts":     [dict(a) for a in accounts],
                "total_paid":   total_price,
                "new_balance":  round(float(new_balance), 4),
                "unit_price":   unit_price,
                "country_name": country["country_name"],
                "flag_emoji":   country.get("flag_emoji", "🌍"),
            }


# ══════════════════════════════════════════════════════════════════════════════
# ── نظام الإحالة المتقدم وبصمة الأجهزة المانعة للغش (Anti-Fraud Referral System)
# ══════════════════════════════════════════════════════════════════════════════

async def check_and_save_device_fingerprint(
    user_id: int,
    fp_hash: str,
    ip: str = "",
    ua: str = "",
) -> Tuple[bool, Optional[int], str]:
    """
    يفحص بصمة الجهاز لمنع تكرار الحسابات على نفس الهاتف أو الكمبيوتر.
    يُرجع: (is_blocked: bool, duplicate_user_id: Optional[int], reason: str)
    """
    if not fp_hash or len(fp_hash) < 16:
        return False, None, "INVALID_FP"

    pool = await get_pool()
    async with pool.acquire() as db:
        # 1. هل نفس بصمة الجهاز مسجلة لمستخدم آخر؟
        existing_fp = await db.fetchrow(
            """
            SELECT user_id FROM device_fingerprints
            WHERE fingerprint_hash = $1 AND user_id != $2
            ORDER BY id ASC LIMIT 1
            """,
            fp_hash, user_id,
        )
        if existing_fp:
            dup_id = existing_fp["user_id"]
            return True, dup_id, "DUPLICATE_DEVICE"

        # 2. فحص الـ IP (إذا كان الـ IP مسجلاً لأكثر من 4 حسابات مختلفة)
        if ip and ip not in ("127.0.0.1", "localhost", "::1", ""):
            ip_count = await db.fetchval(
                """
                SELECT COUNT(DISTINCT user_id) FROM device_fingerprints
                WHERE ip_address = $1 AND user_id != $2
                """,
                ip, user_id,
            )
            if ip_count and ip_count >= 4:
                return True, None, "IP_RATE_EXCEEDED"

        # 3. حفظ البصمة لهذا المستخدم
        await db.execute(
            """
            INSERT INTO device_fingerprints (user_id, fingerprint_hash, ip_address, user_agent)
            VALUES ($1, $2, $3, $4)
            """,
            user_id, fp_hash, ip, ua,
        )
        await db.execute(
            """
            UPDATE users
            SET device_fingerprint = $1, is_device_verified = 1
            WHERE user_id = $2
            """,
            fp_hash, user_id,
        )
        _invalidate_user_cache(user_id)
        return False, None, "OK"


async def process_referral_reward(
    referred_id: int,
    referrer_id: int,
    reward_usd: float = 0.05,
) -> Tuple[bool, str, float]:
    """
    يربط الإحالة ويمنح المكافأة للداعي داخل معاملة ذرية آمنة.
    يُرجع: (success: bool, reason: str, new_referrer_balance: float)
    """
    if referred_id == referrer_id:
        return False, "SELF_REFERRAL", 0.0

    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.transaction():
            # التحقق من أن الداعي موجود
            referrer = await db.fetchrow(
                "SELECT balance FROM users WHERE user_id = $1 FOR UPDATE",
                referrer_id,
            )
            if not referrer:
                return False, "REFERRER_NOT_FOUND", 0.0

            # التحقق من أن المدعو لم يُحل مسبقاً
            user_row = await db.fetchrow(
                "SELECT referred_by FROM users WHERE user_id = $1 FOR UPDATE",
                referred_id,
            )
            if user_row and user_row.get("referred_by"):
                return False, "ALREADY_REFERRED", float(referrer["balance"])

            # التحقق من عدم تسجيل نفس الإحالة في logs
            prev_log = await db.fetchrow(
                "SELECT id FROM referral_logs WHERE referred_id = $1 AND status = 'approved'",
                referred_id,
            )
            if prev_log:
                return False, "ALREADY_REWARDED", float(referrer["balance"])

            # ربط الإحالة
            await db.execute(
                "UPDATE users SET referred_by = $1 WHERE user_id = $2",
                referrer_id, referred_id,
            )

            new_bal = float(referrer["balance"])
            if reward_usd > 0:
                new_bal = await db.fetchval(
                    """
                    UPDATE users
                    SET balance = balance + $1
                    WHERE user_id = $2
                    RETURNING balance
                    """,
                    reward_usd, referrer_id,
                )
                await db.execute(
                    """
                    INSERT INTO transactions (user_id, type, amount, description)
                    VALUES ($1, 'referral_reward', $2, $3)
                    """,
                    referrer_id, reward_usd, f"مكافأة دعوة مستخدم جديد ({referred_id})",
                )

            await db.execute(
                """
                INSERT INTO referral_logs (referrer_id, referred_id, reward_usd, status)
                VALUES ($1, $2, $3, 'approved')
                """,
                referrer_id, referred_id, reward_usd,
            )

            _invalidate_user_cache(referrer_id)
            _invalidate_user_cache(referred_id)
            return True, "OK", float(new_bal) if new_bal is not None else 0.0


async def log_referral_fraud(referrer_id: int, referred_id: int, fraud_reason: str):
    """يسجل محاولة غش محظورة في الإحالات."""
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """
            INSERT INTO referral_logs (referrer_id, referred_id, reward_usd, status, fraud_reason)
            VALUES ($1, $2, 0.0, 'blocked_fraud', $3)
            """,
            referrer_id, referred_id, fraud_reason,
        )


async def get_user_referral_stats(user_id: int) -> Dict[str, Any]:
    """يجلب إحصائيات الإحالة للمستخدم."""
    pool = await get_pool()
    async with pool.acquire() as db:
        total_referrals = await db.fetchval(
            "SELECT COUNT(*) FROM referral_logs WHERE referrer_id = $1 AND status = 'approved'",
            user_id,
        ) or 0
        total_earned = await db.fetchval(
            "SELECT COALESCE(SUM(reward_usd), 0) FROM referral_logs WHERE referrer_id = $1 AND status = 'approved'",
            user_id,
        ) or 0.0
        return {
            "total_referrals": int(total_referrals),
            "total_earned": float(total_earned),
        }


async def get_admin_referral_stats() -> Dict[str, Any]:
    """يجلب إحصائيات الإحالات العامة للأدمن."""
    pool = await get_pool()
    async with pool.acquire() as db:
        total_approved = await db.fetchval(
            "SELECT COUNT(*) FROM referral_logs WHERE status = 'approved'"
        ) or 0
        total_blocked = await db.fetchval(
            "SELECT COUNT(*) FROM referral_logs WHERE status = 'blocked_fraud'"
        ) or 0
        total_paid = await db.fetchval(
            "SELECT COALESCE(SUM(reward_usd), 0) FROM referral_logs WHERE status = 'approved'"
        ) or 0.0
        return {
            "total_approved": int(total_approved),
            "total_blocked": int(total_blocked),
            "total_paid": float(total_paid),
        }


