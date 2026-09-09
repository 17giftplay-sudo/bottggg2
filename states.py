from aiogram.fsm.state import State, StatesGroup


class CaptchaState(StatesGroup):
    waiting_for_answer = State()


class BuyState(StatesGroup):
    searching_country = State()


class TopUpState(StatesGroup):
    waiting_for_amount = State()
    waiting_for_stars_amount = State()


class BinanceManualState(StatesGroup):
    waiting_for_amount = State()
    waiting_for_paid_confirmation = State()
    waiting_for_hash = State()


class UserRefState(StatesGroup):
    waiting_for_referrer_code = State()


class AdminState(StatesGroup):
    waiting_for_unban_id = State()
    waiting_for_user_id_add = State()
    waiting_for_add_amount = State()
    waiting_for_user_id_deduct = State()
    waiting_for_deduct_amount = State()
    waiting_for_stock_data = State()
    waiting_for_batch_password = State()
    waiting_for_new_country_code = State()
    waiting_for_new_country_name = State()
    waiting_for_new_country_flag = State()
    waiting_for_new_country_price = State()
    waiting_for_new_price = State()
    waiting_for_new_points_price = State()
    waiting_for_flash_sale_discount = State()
    waiting_for_flash_sale_hours = State()
    waiting_for_max_ban_attempts = State()
    waiting_for_min_account_age = State()
    waiting_for_webhook_url = State()
    waiting_for_stars_rate = State()
    waiting_for_min_deposit_stars = State()
    waiting_for_min_deposit_usd = State()
    waiting_for_force_sub_channel = State()
    waiting_for_sell_url = State()
    waiting_for_support_url = State()
    waiting_for_topup_other_url = State()
    waiting_for_notification_channel = State()
    waiting_for_info_button_text = State()
    waiting_for_info_button_url = State()
    waiting_for_delete_info_button_index = State()
    waiting_for_binance_uid = State()
    waiting_for_referral_reward_usd = State()
    waiting_for_reset_user_id = State()
    # ── إضافة حساب مباشرة عبر رقم الهاتف ─────────────────────
    waiting_for_live_phone     = State()
    waiting_for_live_otp       = State()
    waiting_for_live_2fa       = State()
    waiting_for_live_country   = State()
    waiting_for_live_price     = State()
    # ── حالات إضافية ──────────────────────────────────────────
    waiting_for_view_user_id         = State()
    waiting_for_add_points_user_id   = State()
    waiting_for_add_points_amount    = State()
    waiting_for_flash_country        = State()
    # ── حساب فحص النجوم (login بالهاتف) ─────────────────────────
    waiting_for_checker_phone        = State()
    waiting_for_checker_otp          = State()
    waiting_for_checker_2fa          = State()
    waiting_for_stock_2fa_password   = State()
    waiting_for_stock_2fa_fallback   = State()
    waiting_for_user_id              = State()


class SubAdminState(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_perms   = State()


class SessionsBuyState(StatesGroup):
    waiting_for_quantity = State()
    waiting_for_confirm  = State()


class AdminSessionsState(StatesGroup):
    waiting_for_zip = State()
    waiting_for_country_code = State()
    waiting_for_price = State()
    convert_waiting_for_price = State()
    convert_waiting_for_password = State()
