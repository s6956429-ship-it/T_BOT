import sqlite3
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# ۱. راه‌اندازی یا اتصال به پایگاه داده دیتابیس برای ذخیره امتیازها
def init_db():
    conn = sqlite3.connect("scores.db")
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            score INTEGER DEFAULT 0
        )
    """
    )
    conn.commit()
    conn.close()

# تابع برای اضافه کردن امتیاز و گرفتن مجموع امتیاز جدید کاربر
def add_score(user_id, username, points=10):
    conn = sqlite3.connect("scores.db")
    cursor = conn.cursor()

    cursor.execute("SELECT score FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()

    if result is None:
        new_score = points
        cursor.execute(
            "INSERT INTO users (user_id, username, score) VALUES (?, ?, ?)",
            (user_id, username, new_score),
        )
    else:
        new_score = result[0] + points
        cursor.execute(
            "UPDATE users SET score = ? WHERE user_id = ?",
            (new_score, user_id),
        )

    conn.commit()
    conn.close()
    return new_score

# ۲. تابع مدیریت پیام‌ها (چک کردن کلمات حساس)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip().lower()
    trigger_words = ["میو", "میو میو", "میاو"]
    is_matched = any(word in text for word in trigger_words)

    if is_matched:
        user = update.effective_user
        user_id = user.id
        # اصلاح شده تا خطایی رخ ندهد
        username = user.username or user.first_name or "Unknown"

        total_score = add_score(user_id, username, points=10)
        reply_text = f"۱۰ امتیاز گرفتی!\nجمع امتیازات: {total_score}"

        await update.message.reply_text(reply_text)

# ۳. تابع اصلی اجرای بات
def main():
    init_db()

    # توکن بات خودت رو اینجا بگذار (از BotFather گرفتی)
    TOKEN = os.environ.get("BOT_TOKEN")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    )

    print("بات با موفقیت روشن شد و داره گوش میده...")
    app.run_polling()

if __name__ == "__main__":
    main()
