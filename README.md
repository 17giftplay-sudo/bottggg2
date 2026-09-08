# 📱 Telegram Accounts Store Bot

A fully-featured Telegram bot that lets you **sell Telegram accounts** to customers automatically — with built-in payments, an admin panel, and multi-language support.

---

> 💬 **Need help?** If you run into any issue at any step, contact support on Telegram: **[@Mohammed_Promoter](https://t.me/Mohammed_Promoter)**

---

## 📋 Table of Contents

1. [What Does This Bot Do?](#-what-does-this-bot-do)
2. [What You Need Before Starting](#-what-you-need-before-starting)
3. [Step 1 — Create Your Telegram Bot](#step-1--create-your-telegram-bot)
4. [Step 2 — Set Up a Free Database](#step-2--set-up-a-free-database)
5. [Step 3 — Deploy on Railway (Free Hosting)](#step-3--deploy-on-railway-free-hosting)
6. [Step 4 — Set Up Payments](#step-4--set-up-payments)
7. [Step 5 — Add Your First Accounts to the Store (Stock)](#step-5--add-your-first-accounts-to-the-store-stock)
8. [Admin Panel Guide](#-admin-panel-guide)
9. [Bot Features Overview](#-bot-features-overview)
10. [Frequently Asked Questions](#-frequently-asked-questions)

---

## 🤖 What Does This Bot Do?

This bot turns your Telegram into a **fully automated store** for selling Telegram accounts. Once set up, it runs 24/7 without you doing anything — customers browse, pay, and receive accounts automatically.

**Key highlights:**
- Customers top up their balance using **Cryptomus**, **Binance Pay**, or **Telegram Stars**
- They browse accounts by **country**, buy instantly, and the account is delivered to them automatically
- You manage everything through a private **Admin Panel** inside Telegram
- Supports **English and Arabic** languages
- Has a **referral system** so users can invite friends for rewards
- Protects against bots with a **CAPTCHA** on first use

---

## 🛠 What You Need Before Starting

You don't need to be a developer. Just have the following ready:

| What | Where to Get It | Cost |
|------|----------------|------|
| Telegram account | You already have one | Free |
| Railway account (hosting) | [railway.app](https://railway.app) | Free tier available |
| Bot Token | [@BotFather](https://t.me/BotFather) on Telegram | Free |
| Your Telegram User ID | [@userinfobot](https://t.me/userinfobot) on Telegram | Free |
| Payment credentials (optional) | Cryptomus or Binance Pay | Free to sign up |

---

## Step 1 — Create Your Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send the command `/newbot`
3. Follow the prompts — choose a name and a username for your bot (username must end in `bot`, e.g. `myaccstore_bot`)
4. BotFather will give you a **Bot Token** that looks like this:
   ```
   1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
   ```
5. **Copy and save this token** — you will need it in Step 3

---

## Step 2 — Set Up a Free Database

The bot needs a **PostgreSQL database** to store users, orders, and account stock. Railway provides one for free.

1. Go to [railway.app](https://railway.app) and sign in (or sign up)
2. Click **New Project**
3. Select **Deploy from GitHub repo** (you'll upload the files) — OR just click **+New → Database → PostgreSQL**
4. Railway will create a database and show you a **DATABASE_URL** (looks like `postgresql://user:password@host/dbname`)
5. **Copy and save this URL** — you will need it in Step 3

---

## Step 3 — Deploy on Railway (Free Hosting)

This is where you actually run the bot.

### Upload the Code

1. Go to [railway.app](https://railway.app) → your project
2. Click **+ New → GitHub Repo** and connect your GitHub account
3. Upload the bot files to a GitHub repository (all the files from this zip, including `bot.py`, `handlers/`, etc.)
4. Railway will detect the `Procfile` and automatically know how to start the bot

### Set the Environment Variables

This is the most important step. In Railway, go to your service → **Variables** tab and add the following:

| Variable Name | Value | Required? |
|---------------|-------|-----------|
| `BOT_TOKEN` | Your Bot Token from BotFather | ✅ Yes |
| `DATABASE_URL` | Your PostgreSQL URL from Step 2 | ✅ Yes |
| `ADMIN_IDS` | Your Telegram User ID (e.g. `123456789`) | ✅ Yes |
| `WEBHOOK_BASE_URL` | Your Railway app URL (e.g. `https://yourapp.up.railway.app`) | Recommended |
| `CRYPTOMUS_MERCHANT_ID` | From your Cryptomus account | Optional |
| `CRYPTOMUS_API_KEY` | From your Cryptomus account | Optional |
| `BINANCE_PAY_API_KEY` | From your Binance merchant account | Optional |
| `BINANCE_PAY_SECRET_KEY` | From your Binance merchant account | Optional |

> ℹ️ **How to find your Telegram User ID:** Message [@userinfobot](https://t.me/userinfobot) and it will tell you your numeric ID.

> ℹ️ **Multiple admins:** If you want more than one admin, separate their IDs with commas: `123456789,987654321`

### Deploy

Once variables are set, Railway will automatically deploy the bot. You should see logs confirming it started. Go to Telegram and send `/start` to your bot to test it.

---

## Step 4 — Set Up Payments

The bot supports three payment methods. You only need to set up the ones you want to use.

### 💳 Cryptomus (Cryptocurrency Payments)

1. Go to [app.cryptomus.com](https://app.cryptomus.com) and create an account
2. Navigate to **Settings → Payments API**
3. Copy your **Merchant ID** and **API Key**
4. Add them to Railway variables: `CRYPTOMUS_MERCHANT_ID` and `CRYPTOMUS_API_KEY`
5. In Cryptomus, set your webhook URL to: `https://yourapp.up.railway.app/webhook/cryptomus`

### 💛 Binance Pay

1. Go to [merchant.binance.com](https://merchant.binance.com) and register as a merchant
2. Navigate to **API Management** and create an API key
3. Copy your **API Key** and **Secret Key**
4. Add them to Railway variables: `BINANCE_PAY_API_KEY` and `BINANCE_PAY_SECRET_KEY`
5. In Binance, set your webhook URL to: `https://yourapp.up.railway.app/webhook/binance`

### ⭐ Telegram Stars

This works automatically — no setup needed. Customers can pay directly using Telegram's built-in Stars currency.

---

## Step 5 — Add Your First Accounts to the Store (Stock)

Before customers can buy anything, you need to add Telegram accounts to your inventory. This requires generating a **session string** for each account.

### Generate a Session String

For each Telegram account you want to sell, do the following:

1. Open a terminal/command prompt on your computer
2. Make sure Python is installed: [python.org/downloads](https://python.org/downloads)
3. Install the required library by running:
   ```
   pip install pyrogram tgcrypto
   ```
4. Run the session generator:
   ```
   python generate_session.py
   ```
5. Follow the prompts:
   - Go to [my.telegram.org](https://my.telegram.org) → **API Development Tools** → create an app → copy the **API ID** and **API Hash**
   - Enter the phone number of the account you want to sell (with country code, e.g. `+1234567890`)
   - Enter the OTP code that Telegram sends to that phone
6. The script will output a line like:
   ```
   +1234567890::12345::abc123hash::BQABAgAB...longstring...
   ```
7. **Copy this line** — it is your account data to paste into the admin panel

### Add the Account via Admin Panel

1. In Telegram, send `/admin` to your bot
2. Go to **Stock Management → Add Account to Stock**
3. First, make sure the country exists (see Admin Panel guide below)
4. Paste the session string line you generated above
5. The account is now in stock and available for purchase ✅

---

## 🛠 Admin Panel Guide

Send `/admin` to your bot to open the admin panel. Here's what each section does:

### 👤 User Management
- **Add/Deduct Balance** — manually change a user's balance by their Telegram ID
- **View user info** — look up any user by their ID

### 📦 Stock Management
- **Add Country** — add a new country category (e.g. "United States", code "US", price in USD, flag emoji like 🇺🇸)
- **Update Country Price** — change the selling price for a country
- **Add Account to Stock** — paste session strings here to add inventory
- **View Stock** — see how many accounts are available per country

### 🔗 Links & Channels
- **Force Subscribe Channel** — set a channel that users must join before using the bot
- **Support Link** — set the link shown when users click "Get Support"
- **Sell Account Link** — set the link shown when users click "Sell Accounts"

### 📢 Info Buttons
- Configure up to several custom information buttons that appear in the bot's menu

### ⭐ Telegram Stars Settings
- Set the conversion rate between Stars and USD

### 📊 Bot Statistics
- View total users, total orders, revenue, and other stats

---

## ✨ Bot Features Overview

| Feature | Details |
|---------|---------|
| 🌐 Languages | English and Arabic |
| 🔒 CAPTCHA | Image-based captcha protects against bots on first use |
| 📢 Force Subscribe | Require users to join your channel before accessing the bot |
| 💳 Payments | Cryptomus (crypto), Binance Pay, Telegram Stars |
| 🛒 Account Delivery | Automatic — account delivered instantly after purchase |
| 💸 Referral System | Users get rewards for inviting friends |
| 📊 Profile / History | Users can view their purchase history |
| 🔑 Session Login | Bot handles Telegram login code automatically after purchase |
| 🛠 Admin Panel | Full management panel accessible via `/admin` |

---

## ❓ Frequently Asked Questions

**Q: The bot doesn't start — what do I check?**
Make sure all three required variables are set in Railway: `BOT_TOKEN`, `DATABASE_URL`, and `ADMIN_IDS`. The bot will not start without them.

**Q: I can't access the admin panel.**
Make sure your Telegram User ID is correctly set in the `ADMIN_IDS` variable. You can get your ID by messaging [@userinfobot](https://t.me/userinfobot).

**Q: Payments aren't working.**
Check that your webhook URL is correctly set in both Railway (`WEBHOOK_BASE_URL`) and your payment provider's dashboard. The URL must match exactly.

**Q: A customer paid but their balance didn't update.**
This is usually a webhook issue. Make sure your `WEBHOOK_BASE_URL` is correct and your Railway app is publicly accessible.

**Q: How do I add more accounts?**
Run `generate_session.py` for each account and paste the output into the admin panel under **Stock Management → Add Account to Stock**.

**Q: Can I add more than one admin?**
Yes — add multiple Telegram IDs separated by commas in the `ADMIN_IDS` variable. Example: `111222333,444555666`

---

## 📞 Support

If you encounter any problem that is not covered in this guide, please reach out directly:

**Telegram: [@Mohammed_Promoter](https://t.me/Mohammed_Promoter)**

Response is typically fast. Please describe your issue clearly and mention which step you are stuck on.

---

*Thank you for purchasing this bot. We wish you great success with your store! 🚀*
