import time
import sqlite3
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# ۱. راه‌اندازی دیتابیس (اضافه شدن ستون last_action_time برای ذخیره زمان آخرین امتیاز)
def init_db():
    conn = sqlite3.connect("scores.db")
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            score INTEGER DEFAULT 0,
            last_action_time REAL DEFAULT 0
        )
    """
    )
    conn.commit()
    conn.close()

# تابع بررسی محدودیت زمانی (Cooldown) و اضافه کردن امتیاز
def check_and_update_score(user_id, username, points=10, cooldown=60):
    conn = sqlite3.connect("scores.db")
    cursor = conn.cursor()
    
    current_time = time.time() # زمان حال بر حسب ثانیه

    # گرفتن امتیاز و آخرین زمان فعالیت کاربر
    cursor.execute("SELECT score, last_action_time FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()

    if result is None:
        # کاربر جدید است؛ امتیاز رو می‌دیم و زمان رو ثبت می‌کنیم
        new_score = points
        cursor.execute(
            "INSERT INTO users (user_id, username, score, last_action_time) VALUES (?, ?, ?, ?)",
            (user_id, username, new_score, current_time),
        )
        conn.commit()
        conn.close()
        return True, new_score, 0
    else:
        score, last_action_time = result
        time_diff = current_time - last_action_time

        # اگر هنوز ۱ دقیقه (۶۰ ثانیه) نگذشته باشد
        if time_diff < cooldown:
            remaining_time = int(cooldown - time_diff)
            conn.close()
            return False, score, remaining_time
        else:
            # زمان مقرر گذشته است؛ امتیاز اضافه میشه و زمان آپدیت میشه
            new_score = score + points
            cursor.execute(
                "UPDATE users SET score = ?, last_action_time = ? WHERE user_id = ?",
                (new_score, current_time, user_id),
            )
            conn.commit()
            conn.close()
            return True, new_score, 0

# ۲. مدیریت پیام‌ها
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip().lower()
    trigger_words = ["میو", "میو میو", "میاو","معو"]
    is_matched = any(word in text for word in trigger_words)

    if is_matched:
        user = update.effective_user
        user_id = user.id
        username = user.username or user.first_name or "Unknown"

        # صدا زدن تابع بررسی و ثبت امتیاز (با محدودیت ۶۰ ثانیه)
        success, total_score, remaining = check_and_update_score(user_id, username, points=10, cooldown=60)

        if success:
            # اگر محدودیت تمام شده بود و امتیاز گرفت
            reply_text = f"۱۰ امتیاز گرفتی!\nجمع امتیازات: {total_score}"
        else:
            # اگر هنوز توی محدودیت زمانی بود
            reply_text = f"هر یک دقیقه یکبار میتونی میو میو کنی\n{remaining} ثانیه دیگه دوباره امتحان کن"

        await update.message.reply_text(reply_text)

# ۳. تابع اصلی اجرای بات
def main():
    init_db()

    # توکن بات (اگر روی سرور رندر هستی از متغیر محیطی می‌خواند، یا می‌تونی موقتاً توکن خودت رو بذاری)
    import os
    TOKEN = os.environ.get("BOT_TOKEN")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    )

    print("بات با موفقیت روشن شد و سیستم کول‌دان فعال است...")
    app.run_polling()

if __name__ == "__main__":
    main()
