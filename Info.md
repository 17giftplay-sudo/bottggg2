# XPLUS TG Store Bot

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![aiogram](https://img.shields.io/badge/aiogram-3.13-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-asyncpg-336791?style=for-the-badge&logo=postgresql&logoColor=white)
![aiohttp](https://img.shields.io/badge/aiohttp-3.11-blue?style=for-the-badge&logo=aiohttp&logoColor=white)
![Cryptomus](https://img.shields.io/badge/Cryptomus-Pay-6C63FF?style=for-the-badge)
![Binance Pay](https://img.shields.io/badge/Binance-Pay-F0B90B?style=for-the-badge&logo=binance&logoColor=black)
![Railway](https://img.shields.io/badge/Deploy-Railway-0B0D0E?style=for-the-badge&logo=railway&logoColor=white)

**A production-grade Telegram accounts store bot** — automatic login code delivery, real-time crypto payments, bilingual support, image captcha, referral system, and a full admin panel.

</div>

---

## Features

| Feature | Description |
|---|---|
| 🛡️ Image Captcha | Auto-generated captcha on first use to block bots |
| 🌍 Multi-Country Store | Buy Telegram accounts from any configured country |
| 📲 Auto Code Delivery | Bot connects to the purchased account and automatically forwards the login OTP to the buyer |
| 💳 Automatic Top Up | Real-time payments via **Cryptomus** (USDT/TRX/TON/SOL/…) and **Binance Pay** — balance credited instantly on confirmation |
| 💰 Minimum Deposit | Enforced minimum deposit of **$1.00 USD** |
| 📊 User Dashboard | Full purchase history and balance |
| 🌐 Bilingual | Full Arabic 🇸🇦 and English 🇺🇸 support |
| 🔒 Force Subscribe | Optional channel membership gate before bot access |
| 🔍 Country Search | Search countries by name or code |
| 📄 Pagination | Countries list paginated (12 per page) |
| 🛠️ Admin Panel | Full admin panel via `/admin` command |

---

## How Automatic Payments Work

```
1. User taps "Cryptomus" or "Binance Pay" in the Top Up menu
         ↓
2. Bot asks: "Enter amount (minimum $1.00)"
         ↓
3. User types the amount (e.g. 10 or 25.50)
         ↓
4. Bot calls the payment API and creates a live invoice
         ↓
5. Bot sends a "💳 Pay Now" button linking to the checkout page
         ↓
6. User completes payment on Cryptomus / Binance website
         ↓
7. Payment gateway sends a signed webhook to your server
         ↓
8. Bot verifies the signature, credits the balance atomically ✅
         ↓
9. User receives a Telegram notification: "✅ $X has been added to your balance"
```

Each payment is stored in a `payments` table. The `confirm_payment()` function runs inside a PostgreSQL transaction — preventing any double-credit even if the gateway fires duplicate webhooks.

---

## How Automatic Code Delivery Works

```
1. Buyer purchases an account
         ↓
2. Bot shows the phone number + "Request Login Code" button
         ↓
3. Buyer opens Telegram on any device, enters the phone number,
   and taps "Send Code"
         ↓
4. Telegram sends the OTP to the purchased account's inbox
         ↓
5. Your bot (via Pyrogram) is connected to that account
   and watching its inbox in real time
         ↓
6. Bot detects the OTP message from "Telegram"
   and instantly forwards the code to the buyer
         ↓
7. Buyer enters the code and logs in ✅
```

The bot waits up to **120 seconds** for the code. If no code arrives it refunds the purchase and notifies the buyer.

---

## Bot Flow

```
/start
  └── Image Captcha
        └── Language Selection (EN / AR)
              └── Force Subscribe Check (if configured)
                    └── Main Menu
                          ├── 📱 Buy Ready TG Accounts
                          │     └── Country List (paginated + searchable)
                          │           └── Purchase → 📲 Request Login Code (auto delivery)
                          ├── 💰 Sell Accounts        →  External URL
                          ├── 💳 Top Up
                          │     ├── 🔐 Cryptomus       →  Enter amount → Live invoice → Auto credit
                          │     ├── 🟡 Binance Pay     →  Enter amount → Live invoice → Auto credit
                          │     └── 💬 Other Methods   →  External URL
                          ├── 💸 Free Funds (Referral) →  Invite Link + Stats
                          ├── 📊 My Purchases          →  Account History
                          ├── 💬 Get Support           →  External URL
                          ├── 📢 Other Informations    →  Custom Info Buttons
                          └── 🌐 Change Language
```

---

## Setting Up Your Accounts (Required Before Going Live)

Each account you add to stock must have a **Pyrogram StringSession** so the bot can connect to it and fetch OTP codes.

### Step 1 — Get API credentials

1. Go to [https://my.telegram.org](https://my.telegram.org)
2. Log in with **your own personal Telegram account** (not the accounts you're selling)
3. Click **API Development Tools**
4. Create a new app — name and description can be anything
5. Copy your **API ID** and **API Hash**

> ℹ️ You can use a single API ID + API Hash for all accounts.

### Step 2 — Generate a session for each account

Run the included helper script on your local machine:

```bash
pip install pyrogram tgcrypto
python generate_session.py
```

The script will ask for:
- Your API ID and API Hash
- The phone number of the account (e.g. `+1234567890`)
- The OTP code Telegram sends to that phone

It will output a single line like:

```
+1234567890::12345678::abc123def456::BQANAQIxxxxxxxxxxxxxxxxx...
```

### Step 3 — Add the account to your bot's stock

1. Open your bot and go to `/admin`
2. Navigate to **Stock Management → Add Account to Stock**
3. Select the country
4. Paste the line from Step 2

---

## Deployment (Railway)

### Step 1 — Create the project

1. Go to [railway.app](https://railway.app) and create a new project
2. Connect your GitHub repo or use the Railway CLI

### Step 2 — Add PostgreSQL

1. Inside your project click **+ New → Database → PostgreSQL**
2. Railway automatically injects `DATABASE_URL` into your environment

### Step 3 — Set environment variables

Go to your service → **Variables** and add:

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | ✅ | Your bot token from [@BotFather](https://t.me/BotFather) |
| `ADMIN_IDS` | ✅ | Comma-separated Telegram user IDs for admins |
| `DATABASE_URL` | ✅ Auto | Set automatically by Railway PostgreSQL plugin |
| `WEBHOOK_BASE_URL` | ✅ | Your public Railway URL, e.g. `https://yourapp.up.railway.app` |
| `CRYPTOMUS_MERCHANT_ID` | ⚠️ If using Cryptomus | From [app.cryptomus.com](https://app.cryptomus.com) → Settings → Payments API |
| `CRYPTOMUS_API_KEY` | ⚠️ If using Cryptomus | Same page as above |
| `BINANCE_PAY_API_KEY` | ⚠️ If using Binance Pay | From [merchant.binance.com](https://merchant.binance.com) → API Management |
| `BINANCE_PAY_SECRET_KEY` | ⚠️ If using Binance Pay | Same page as above |

> ℹ️ To find your Telegram user ID, message [@userinfobot](https://t.me/userinfobot).

### Step 4 — Configure payment webhooks

Register these URLs in your payment provider dashboards so they can notify your bot:

| Provider | Webhook URL |
|---|---|
| Cryptomus | `https://yourapp.up.railway.app/webhook/cryptomus` |
| Binance Pay | `https://yourapp.up.railway.app/webhook/binance` |

### Step 5 — Deploy

Railway detects the `Procfile` and starts the bot automatically. The process runs **both** the Telegram polling loop and the aiohttp webhook server on the same port.

```
web: python bot.py
```

---

## Local Development

```bash
# 1. Clone the repo
git clone https://github.com/yourname/xplus-tg-bot.git
cd xplus-tg-bot

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set environment variables
export BOT_TOKEN=your_bot_token_here
export ADMIN_IDS=your_telegram_id_here
export DATABASE_URL=postgresql://user:password@localhost:5432/botdb
export WEBHOOK_BASE_URL=https://yourapp.up.railway.app
export CRYPTOMUS_MERCHANT_ID=your_merchant_id
export CRYPTOMUS_API_KEY=your_api_key
export BINANCE_PAY_API_KEY=your_api_key
export BINANCE_PAY_SECRET_KEY=your_secret_key

# 4. Run
python bot.py
```

> ℹ️ For local webhook testing, use [ngrok](https://ngrok.com) to expose your port and set `WEBHOOK_BASE_URL` to your ngrok URL.

---

## Admin Panel

Access via `/admin` command (admin Telegram IDs only).

| Section | Capabilities |
|---|---|
| 👤 User Management | View user info, add or deduct balance manually |
| 📊 Bot Statistics | Total users, total deposits, accounts sold, stock levels |
| 📦 Stock Management | Add countries, set prices, add accounts to stock, view stock |
| 💸 Referral Settings | Configure reward amount per referral |
| 🔗 Dynamic Links | Configure all external URLs and force-sub channel |

### Configurable Links (via Admin → Dynamic Links)

| Setting | Purpose |
|---|---|
| Force-Sub Channel | Channel users must join before using the bot |
| Sell Accounts URL | Link to your sell accounts page or group |
| Support URL | Link to your support contact or group |
| Top-Up Other URL | Alternative payment contact link |
| Info Buttons | Custom buttons shown under "Other Informations" |

---

## Project Structure

```
├── bot.py                    # Entry point — polling + webhook server
├── config.py                 # Environment variables and constants
├── database.py               # All database logic (asyncpg / PostgreSQL)
├── keyboards.py              # All inline keyboard builders
├── translations.py           # EN + AR text strings
├── states.py                 # FSM state groups
├── generate_session.py       # Run this locally to create sessions for your accounts
├── Procfile                  # Railway process definition
├── requirements.txt
├── handlers/
│   ├── start.py              # /start, captcha, language, force-sub
│   ├── buy.py                # Country list, pagination, search, purchase, code delivery
│   ├── topup.py              # Cryptomus + Binance Pay automatic top-up flow
│   ├── referral.py           # Referral program
│   ├── profile.py            # Profile, support, sell, info
│   └── admin.py              # Full admin panel
├── payments/
│   ├── __init__.py
│   ├── cryptomus.py          # Cryptomus invoice creation + webhook verification
│   ├── binance_pay.py        # Binance Pay order creation + webhook verification
│   └── webhook_server.py     # aiohttp server — receives and processes payment callbacks
└── utils/
    ├── captcha.py            # Image captcha generator (Pillow)
    └── session_manager.py    # Pyrogram userbot — connects to accounts and fetches OTP codes
```

---

## Tech Stack

| Library | Purpose |
|---|---|
| [aiogram 3](https://docs.aiogram.dev/) | Async Telegram Bot framework |
| [Pyrogram 2](https://docs.pyrogram.org/) | Userbot client — connects to purchased accounts to fetch OTP |
| [TgCrypto](https://github.com/pyrogram/tgcrypto) | Fast Telegram encryption (required by Pyrogram) |
| [asyncpg](https://magicstack.github.io/asyncpg/) | Async PostgreSQL driver |
| [aiohttp 3.11](https://docs.aiohttp.org/) | Webhook HTTP server for payment callbacks |
| [Pillow](https://python-pillow.org/) | Captcha image generation |

---

## Security Notes

- `BOT_TOKEN`, `ADMIN_IDS`, and all payment credentials are **never** hardcoded — the bot refuses to start without the required ones
- All payment webhooks are verified with **cryptographic signatures** before any balance is credited (MD5 for Cryptomus, HMAC-SHA512 for Binance Pay)
- `confirm_payment()` runs inside a PostgreSQL transaction with `SELECT FOR UPDATE` — preventing double-credit even if the gateway fires duplicate webhooks
- Purchases use `SELECT FOR UPDATE SKIP LOCKED` to prevent race conditions and double-spending
- Captcha has a configurable maximum attempt limit (default: 5) to block automated bots
- All admin routes verify `user_id` against `ADMIN_IDS` on every single request
- Session strings are stored in the database — ensure your PostgreSQL instance is secured and not publicly accessible

---

## License

MIT — free to use, modify, and deploy.
