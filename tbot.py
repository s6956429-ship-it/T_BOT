import time
import os
import re
import psycopg2
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# گرفتن آدرس دیتابیس از متغیرهای محیطی
DATABASE_URL = os.environ.get("DATABASE_URL")

# ۱. اتصال به دیتابیس ابری PostgreSQL (Supabase) و ساخت جدول
def init_db():
    if not DATABASE_URL:
        print("خطا: متغیر محیطی DATABASE_URL تنظیم نشده است!")
        return
        
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    # ساخت جدول کاربران با سازگاری کامل با PostgreSQL
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            score INTEGER DEFAULT 0,
            last_action_time DOUBLE PRECISION DEFAULT 0,
            spouse_id BIGINT DEFAULT NULL,
            last_sex_time DOUBLE PRECISION DEFAULT 0,
            inventory TEXT DEFAULT ''
        )
    """
    )
    conn.commit()
    cursor.close()
    conn.close()
    print("اتصال به دیتابیس ابری با موفقیت برقرار شد!")

# تابع کمکی برای اطمینان از وجود کاربر در دیتابیس
def ensure_user(cursor, user_id, username):
    cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO users (user_id, username, score, last_action_time, spouse_id, last_sex_time, inventory) VALUES (%s, %s, 0, 0, NULL, 0, '')",
            (user_id, username)
        )

# تابع بررسی محدودیت زمانی (Cooldown) برای میو
def check_and_update_score(user_id, username, points=10, cooldown=60):
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    ensure_user(cursor, user_id, username)
    current_time = time.time()

    cursor.execute("SELECT score, last_action_time FROM users WHERE user_id = %s", (user_id,))
    score, last_action_time = cursor.fetchone()

    time_diff = current_time - last_action_time

    if time_diff < cooldown:
        remaining_time = int(cooldown - time_diff)
        conn.close()
        return False, score, remaining_time
    else:
        new_score = score + points
        cursor.execute(
            "UPDATE users SET score = %s, last_action_time = %s WHERE user_id = %s",
            (new_score, current_time, user_id),
        )
        conn.commit()
        cursor.close()
        conn.close()
        return True, new_score, 0

# ۲. مدیریت جامع پیام‌ها
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip().lower()
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name or "Unknown"

    # --- بخش اول: ازدواج ---
    if re.match(r"^ازدواج\b", text):
        if not update.message.reply_to_message:
            await update.message.reply_text("برای ازدواج باید روی پیام طرف مقابل ریپلای کنی و بنویسی ازدواج! 💍")
            return
        
        target_user = update.message.reply_to_message.from_user
        target_id = target_user.id
        target_name = target_user.username or target_user.first_name or "Unknown"

        if user_id == target_id:
            await update.message.reply_text("خو عاقل نمیتونی با خودت ازدواج کنی! 😅")
            return
            
        if target_user.is_bot:
            await update.message.reply_text("با بات‌ها نمیشه ازدواج کرد، دل نبند! 🤖")
            return

        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        ensure_user(cursor, user_id, username)
        ensure_user(cursor, target_id, target_name)
        
        cursor.execute("SELECT spouse_id FROM users WHERE user_id = %s", (user_id,))
        spouse_a = cursor.fetchone()[0]
        cursor.execute("SELECT spouse_id FROM users WHERE user_id = %s", (target_id,))
        spouse_b = cursor.fetchone()[0]
        
        if spouse_a is not None:
            await update.message.reply_text("تو که خودت متاهلی، اول طلاق بگیر بعد برو سراغ نفر بعدی! 😒")
            cursor.close()
            conn.close()
            return
            
        if spouse_b is not None:
            await update.message.reply_text("اون بنده خدا خودش متاهله، دست از سرش بردار! 🤭")
            cursor.close()
            conn.close()
            return
        
        cursor.execute("UPDATE users SET spouse_id = %s WHERE user_id = %s", (target_id, user_id))
        cursor.execute("UPDATE users SET spouse_id = %s WHERE user_id = %s", (user_id, target_id))
        conn.commit()
        cursor.close()
        conn.close()
        
        await update.message.reply_text(f"مبارکه! 💖\n{user.first_name} و {target_user.first_name} با هم ازدواج کردن!")
        return

    # --- بخش دوم: طلاق ---
    if re.match(r"^طلاق\b", text):
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        ensure_user(cursor, user_id, username)
        cursor.execute("SELECT score, spouse_id FROM users WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        score, spouse_id = result[0], result[1]
        
        if spouse_id is None:
            await update.message.reply_text("تو اصلاً ازدواج نکردی که حالا می‌خوای طلاق بگیری! مجردی برای خودت حال کن 😂")
            cursor.close()
            conn.close()
            return
            
        if score < 200:
            await update.message.reply_text("شما پول مهریه (۲۰۰ دلار) نداری، پس نمیتونی طلاق بدی! باید بری بیشتر میو کنی تا امتیاز جمع کنی! 💸😂")
            cursor.close()
            conn.close()
            return
            
        new_score = score - 200
        cursor.execute("UPDATE users SET score = %s, spouse_id = NULL WHERE user_id = %s", (new_score, user_id))
        cursor.execute("UPDATE users SET spouse_id = NULL WHERE user_id = %s", (spouse_id,))
        conn.commit()
        cursor.close()
        conn.close()
        
        await update.message.reply_text(f"طلاق صادر شد! 💔\n۲۰۰ دلار بابت مهریه از حسابت کم شد.\nموجودی جدید: {new_score} امتیاز")
        return

    # --- بخش سوم: دستور سکس / رابطه ---
    if re.match(r"^(سکس|رابطه)\b", text):
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        ensure_user(cursor, user_id, username)
        cursor.execute("SELECT score, spouse_id, last_sex_time FROM users WHERE user_id = %s", (user_id,))
        score, spouse_id, last_sex_time = cursor.fetchone()
        
        if spouse_id is None:
            await update.message.reply_text("تو مجردی اول باید ازدواج کنی! 🚫")
            cursor.close()
            conn.close()
            return
            
        current_time = time.time()
        cooldown_sex = 3600  # ۱ ساعت به ثانیه
        time_diff = current_time - last_sex_time
        
        if time_diff < cooldown_sex:
            remaining_min = int((cooldown_sex - time_diff) / 60)
            await update.message.reply_text(f"هنوز زوده! باید {remaining_min} دقیقه دیگه صبر کنی. ⏱️")
            cursor.close()
            conn.close()
            return
            
        cursor.execute("SELECT score, username FROM users WHERE user_id = %s", (spouse_id,))
        spouse_data = cursor.fetchone()
        spouse_score = spouse_data[0] if spouse_data else 0
        spouse_name = spouse_data[1] if spouse_data else "همسر"
        
        new_user_score = score + 1000
        new_spouse_score = spouse_score + 1000
        
        cursor.execute("UPDATE users SET score = %s, last_sex_time = %s WHERE user_id = %s", (new_user_score, current_time, user_id))
        cursor.execute("UPDATE users SET score = %s, last_sex_time = %s WHERE user_id = %s", (new_spouse_score, current_time, spouse_id))
        conn.commit()
        cursor.close()
        conn.close()
        
        user_display = f"@{user.username}" if user.username else user.first_name
        spouse_display = f"@{spouse_name}" if not spouse_name.startswith("http") and not spouse_name == "Unknown" else spouse_name
        
        await update.message.reply_text(f"{user_display} و {spouse_display} شب خوبی رو با هم گذروندن و هر کدوم ۱۰۰۰ دلار گرفتن! 😏🔥")
        return

    # --- بخش چهارم: سیستم امتیازدهی میو ---
    meow_pattern = r"^(میوو*|میاوو*|میو\s+میو)"
    
    if re.match(meow_pattern, text):
        success, total_score, remaining = check_and_update_score(user_id, username, points=10, cooldown=60)

        if success:
            reply_text = f"۱۰ امتیاز گرفتی!\nجمع امتیازات: {total_score}"
        else:
            reply_text = f"هر یک دقیقه یکبار میتونی میو میو کنی\n{remaining} ثانیه دیگه دوباره امتحان کن"

        await update.message.reply_text(reply_text)

# ۳. تابع اصلی اجرای بات
def main():
    init_db()

    TOKEN = os.environ.get("BOT_TOKEN")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    )

    print("بات با دیتابیس ابری Supabase با موفقیت روشن شد...")
    app.run_polling()

if __name__ == "__main__":
    main()
