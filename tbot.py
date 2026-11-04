import time
import os
import re
import psycopg2
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

DATABASE_URL = os.environ.get("DATABASE_URL")

# تابع اتصال امن به دیتابیس ابری
def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"خطا در اتصال به دیتابیس: {e}")
        return None

# ۱. راه‌اندازی و ساخت جدول (به همراه مهاجرت خودکار ستون‌های جدید)
def init_db():
    if not DATABASE_URL:
        print("خطا: متغیر محیطی DATABASE_URL تنظیم نشده است!")
        return
        
    conn = get_db_connection()
    if not conn:
        return
        
    cursor = conn.cursor()
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
    
    # سیستم مهاجرت هوشمند برای اضافه کردن ستون‌های جدید بدون پاک شدن داده‌ها
    cursor.execute("PRAGMA table_info(users);" if "sqlite" in DATABASE_URL else """
        SELECT column_name FROM information_schema.columns WHERE table_name='users';
    """)
    # برای اطمینان از وجود ستون‌های جدید بوس، با ALTER TABLE اضافه می‌کنیم اگر نبودند
    columns_to_add = [
        ("last_kiss_time", "DOUBLE PRECISION DEFAULT 0"),
        ("last_kiss2_time", "DOUBLE PRECISION DEFAULT 0"),
        ("last_kiss3_time", "DOUBLE PRECISION DEFAULT 0")
    ]
    
    existing_cols = [row[0] for row in cursor.fetchall()] if "information_schema" in str(cursor.description or "") else []
    
    # روش امن‌تر برای اضافه کردن ستون‌ها در PostgreSQL
    for col_name, col_type in columns_to_add:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col_name} {col_type};")
        except Exception:
            pass # اگر ستون از قبل بود رد شو

    conn.commit()
    cursor.close()
    conn.close()
    print("اتصال به دیتابیس ابری و به‌روزرسانی جدول با موفقیت انجام شد!")

def ensure_user(cursor, user_id, username):
    cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO users (user_id, username, score, last_action_time, spouse_id, last_sex_time, inventory) VALUES (%s, %s, 0, 0, NULL, 0, '')",
            (user_id, username)
        )

def check_and_update_score(user_id, username, points=10, cooldown=60):
    conn = get_db_connection()
    if not conn:
        return False, 0, 60
        
    cursor = conn.cursor()
    ensure_user(cursor, user_id, username)
    current_time = time.time()

    cursor.execute("SELECT score, last_action_time FROM users WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()
    score, last_action_time = result if result else (0, 0)

    time_diff = current_time - last_action_time

    if time_diff < cooldown:
        remaining_time = int(cooldown - time_diff)
        cursor.close()
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

        # --- تابع کمکی برای مدیریت مستقل دستورات تعاملی (مثل کیس، بغل و غیره) ---
    async def handle_custom_interaction(action_title, time_column_name, reward_amount, message_template):
        if not update.message.reply_to_message:
            await update.message.reply_text(f"برای انجام «{action_title}» باید روی پیام طرف مقابل ریپلای کنی! 🫂")
            return
            
        target_user = update.message.reply_to_message.from_user
        target_id = target_user.id
        target_name = target_user.username or target_user.first_name or "Unknown"

        if user_id == target_id:
            await update.message.reply_text("نمیتونی این کار رو با خودت انجام بدی عاقل! 😅")
            return
            
        if target_user.is_bot:
            await update.message.reply_text("با بات‌ها نمیشه این کارها رو کرد! 🤖")
            return

        conn = get_db_connection()
        if not conn:
            await update.message.reply_text("خطا در اتصال به دیتابیس!")
            return
        cursor = conn.cursor()
        
        ensure_user(cursor, user_id, username)
        ensure_user(cursor, target_id, target_name)
        
        # چک کردن زمان آخرین استفاده از این دستور خاص
        cursor.execute(f"SELECT score, {time_column_name} FROM users WHERE user_id = %s", (user_id,))
        user_res = cursor.fetchone()
        user_score, last_time = user_res if user_res else (0, 0)
        
        current_time = time.time()
        cooldown = 3600  # ۱ ساعت به ثانیه
        time_diff = current_time - last_time
        
        if time_diff < cooldown:
            remaining_min = int((cooldown - time_diff) / 60)
            await update.message.reply_text(f"هنوز زوده! برای این کار باید {remaining_min} دقیقه دیگه صبر کنی. ⏱️")
            cursor.close()
            conn.close()
            return
            
        # گرفتن امتیاز هدف
        cursor.execute("SELECT score FROM users WHERE user_id = %s", (target_id,))
        target_res = cursor.fetchone()
        target_score = target_res[0] if target_res else 0
        
        # اضافه کردن پاداش به هر دو نفر و آپدیت زمان
        new_user_score = user_score + reward_amount
        new_target_score = target_score + reward_amount
        
        cursor.execute(f"UPDATE users SET score = %s, {time_column_name} = %s WHERE user_id = %s", (new_user_score, current_time, user_id))
        cursor.execute(f"UPDATE users SET score = %s WHERE user_id = %s", (new_target_score, target_id))
        conn.commit()
        cursor.close()
        conn.close()
        
        user_display = f"@{user.username}" if user.username else user.first_name
        target_display = f"@{target_user.username}" if target_user.username else target_user.first_name
        
        # ساخت متن نهایی با قالب دلخواه شما
        final_message = message_template.replace("{user}", user_display).replace("{target}", target_display).replace("{reward}", str(reward_amount))
        await update.message.reply_text(final_message)

    # --- ۱. دستور کیس (بوس) ---
    if re.match(r"^(کیس|بوس)\b", text):
        await handle_custom_interaction(
            action_title="کیس",
            time_column_name="last_kiss_time",
            reward_amount=300,
            message_template="{user} لبای {target} رو بوسید و نفری {reward} دلار گرفتن. 😘🔥"
        )
        return

    # --- ۲. دستور بغل (بوس۲ سابق) ---
    if re.match(r"^گی\b", text):
        await handle_custom_interaction(
            action_title="گی",
            time_column_name="last_kiss2_time",
            reward_amount=500,
            message_template="{user} کون {target} گذاشت و آبشو ریخت توش و نفری {reward} دلار گرفتن. 🍑💦"
        )
        return

    # --- ۳. دستور بوس۳ (می‌تونی اسم و متن دلخواهت رو اینجا بذاری) ---
    if re.match(r"^لز\b", text):
        await handle_custom_interaction(
            action_title="لز",
            time_column_name="last_kiss3_time",
            reward_amount=500,
            message_template="{user} و {target} قیچی کردن و نفری {reward} دلار گرفتن. 🐳"
        )
        return


    # --- موجودی ---
    if re.match(r"^موجودی\b", text):
        conn = get_db_connection()
        if not conn:
            await update.message.reply_text("خطا در اتصال به دیتابیس!")
            return
        cursor = conn.cursor()
        ensure_user(cursor, user_id, username)
        
        cursor.execute("SELECT score, spouse_id FROM users WHERE user_id = %s", (user_id,))
        score, spouse_id = cursor.fetchone()
        
        spouse_text = "مجرد 🥲"
        if spouse_id:
            cursor.execute("SELECT username FROM users WHERE user_id = %s", (spouse_id,))
            spouse_res = cursor.fetchone()
            if spouse_res:
                spouse_text = f"متاهل با @{spouse_res[0]}" if not spouse_res[0].startswith("http") else f"متاهل"

        cursor.close()
        conn.close()
        
        await update.message.reply_text(f"💳 کارت بانکی شما:\n\n💰 موجودی: {score} دلار\n💍 وضعیت تأهل: {spouse_text}")
        return

    # --- رده‌بندی (/top) ---
    if re.match(r"^(رده‌بندی|رده بندی|top)\b", text):
        conn = get_db_connection()
        if not conn:
            await update.message.reply_text("خطا در اتصال به دیتابیس!")
            return
        cursor = conn.cursor()
        
        cursor.execute("SELECT username, score FROM users ORDER BY score DESC LIMIT 10")
        top_users = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        if not top_users:
            await update.message.reply_text("هنوز هیچ‌کسی امتیازی ثبت نکرده!")
            return
            
        leaderboard_text = "🏆 **۱۰ نفر برتر گروه (ثروتمندان):**\n\n"
        for index, (uname, uscore) in enumerate(top_users, start=1):
            display_name = f"@{uname}" if uname and not uname.startswith("http") else "کارگر بی‌نام"
            medal = "🥇" if index == 1 else "🥈" if index == 2 else "🥉" if index == 3 else f"{index}."
            leaderboard_text += f"{medal} {display_name} ➔ **{uscore} دلار**\n"
            
        await update.message.reply_text(leaderboard_text, parse_mode="Markdown")
        return

    # --- انتقال وجه ---
    transfer_match = re.match(r"^انتقال\s+(\d+)", text)
    if transfer_match:
        amount = int(transfer_match.group(1))
        
        if amount <= 0:
            await update.message.reply_text("مبلغ انتقال باید بیشتر از صفر باشه! 🤨")
            return
            
        if not update.message.reply_to_message:
            await update.message.reply_text("برای انتقال وجه باید روی پیام شخصی که می‌خوای بهش پول بفرستی ریپلای کنی! 💸")
            return
            
        target_user = update.message.reply_to_message.from_user
        target_id = target_user.id
        target_name = target_user.username or target_user.first_name or "Unknown"
        
        if user_id == target_id:
            await update.message.reply_text("نمی‌تونی به خودت پول انتقال بدی عاقل! 😅")
            return
            
        if target_user.is_bot:
            await update.message.reply_text("با بات‌ها معامله مالی نکن، پولت رو می‌خورن! 🤖")
            return
            
        conn = get_db_connection()
        if not conn:
            await update.message.reply_text("خطا در اتصال به دیتابیس!")
            return
        cursor = conn.cursor()
        
        ensure_user(cursor, user_id, username)
        ensure_user(cursor, target_id, target_name)
        
        cursor.execute("SELECT score FROM users WHERE user_id = %s", (user_id,))
        sender_score = cursor.fetchone()[0]
        
        if sender_score < amount:
            await update.message.reply_text(f"موجودی حسابت کافی نیست! موجودی فعلی شما: {sender_score} دلار ❌")
            cursor.close()
            conn.close()
            return
            
        cursor.execute("UPDATE users SET score = score - %s WHERE user_id = %s", (amount, user_id))
        cursor.execute("UPDATE users SET score = score + %s WHERE user_id = %s", (amount, target_id))
        
        conn.commit()
        
        cursor.execute("SELECT score FROM users WHERE user_id = %s", (user_id,))
        new_sender_score = cursor.fetchone()[0]
        
        cursor.close()
        conn.close()
        
        target_display = f"@{target_user.username}" if target_user.username else target_user.first_name
        sender_display = f"@{user.username}" if user.username else user.first_name
        
        await update.message.reply_text(f"💳 انتقال موفق!\n\nمبلغ **{amount} دلار** از {sender_display} به {target_display} منتقل شد.\nموجودی جدید شما: {new_sender_score} دلار", parse_mode="Markdown")
        return

    # --- ازدواج ---
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

        conn = get_db_connection()
        if not conn:
            return
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

    # --- طلاق ---
    if re.match(r"^طلاق\b", text):
        conn = get_db_connection()
        if not conn:
            return
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

    # --- رابطه (مخصوص متاهل‌ها) ---
    if re.match(r"^(سکس|رابطه)\b", text):
        conn = get_db_connection()
        if not conn:
            return
        cursor = conn.cursor()
        
        ensure_user(cursor, user_id, username)
        cursor.execute("SELECT score, spouse_id, last_sex_time FROM users WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        score, spouse_id, last_sex_time = result if result else (0, None, 0)
        
        if spouse_id is None:
            await update.message.reply_text("تو مجردی اول باید ازدواج کنی! 🚫")
            cursor.close()
            conn.close()
            return
            
        current_time = time.time()
        cooldown_sex = 3600
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

    # --- سیستم امتیازدهی میو ---
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

    print("بات پیشرفته با قابلیت بوس و دستورات سفارشی روشن شد...")
    app.run_polling()

if __name__ == "__main__":
    main()
