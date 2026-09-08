"""
generate_session.py
────────────────────
Run this script ONCE for each Telegram account you own to generate
a Pyrogram StringSession. Then store the output in your bot's stock.

Usage:
    python generate_session.py

You will be prompted for:
    - API ID and API Hash (from https://my.telegram.org)
    - Phone number
    - The OTP code Telegram sends to that account

The script prints the final account_data line ready to paste into
the bot's admin panel.

Requirements:
    pip install pyrogram tgcrypto
"""

import asyncio
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded


async def main():
    print("=" * 50)
    print("  XPLUS — Pyrogram Session Generator")
    print("=" * 50)
    print()
    print("Get your API ID and API Hash from: https://my.telegram.org")
    print()

    api_id   = int(input("Enter API ID   : ").strip())
    api_hash = input("Enter API Hash : ").strip()
    phone    = input("Enter Phone Number (with country code, e.g. +1234567890): ").strip()

    async with Client(
        name="session_gen",
        api_id=api_id,
        api_hash=api_hash,
        phone_number=phone,
        in_memory=True,
    ) as client:
        try:
            session_string = await client.export_session_string()
        except SessionPasswordNeeded:
            password = input("Two-step verification is enabled. Enter your password: ").strip()
            await client.check_password(password)
            session_string = await client.export_session_string()

    print()
    print("=" * 50)
    print("  ✅ Session generated successfully!")
    print("=" * 50)
    print()
    print("Copy the line below and paste it into the bot admin panel")
    print("when adding stock (Admin → Stock Management → Add Account to Stock):")
    print()
    print(f"{phone}::{api_id}::{api_hash}::{session_string}")
    print()
    print("⚠️  Keep this line private. Anyone with it can access the account.")


if __name__ == "__main__":
    asyncio.run(main())
