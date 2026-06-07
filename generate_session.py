#!/usr/bin/env python3
"""
generate_session.py
────────────────────
شغّل هذا الملف مرة واحدة على جهازك المحلي لتوليد STRING_SESSION.
بعدها انسخ القيمة وضعها في Railway Variables.

الاستخدام:
  python generate_session.py
"""

import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv
import os

load_dotenv()

API_ID   = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")


async def main():
    if not API_ID or not API_HASH:
        print("❌  API_ID أو API_HASH غير موجودين في ملف .env")
        return

    print("🔐  جاري تسجيل الدخول لتوليد STRING_SESSION …\n")

    async with TelegramClient(StringSession(), API_ID, API_HASH) as client:
        await client.start()
        me = await client.get_me()
        session_str = client.session.save()

        print(f"\n✅  تم تسجيل الدخول بنجاح كـ: {me.first_name} (@{me.username})")
        print("\n" + "=" * 60)
        print("📋  STRING_SESSION — انسخ هذه القيمة إلى Railway Variables:\n")
        print(session_str)
        print("\n" + "=" * 60)
        print("\nفي Railway: Settings → Variables → Add Variable")
        print("  Name:  STRING_SESSION")
        print(f"  Value: {session_str[:30]}…  (القيمة الكاملة أعلاه)")


if __name__ == "__main__":
    asyncio.run(main())
