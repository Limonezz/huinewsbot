import asyncio
import sqlite3
import os
from datetime import datetime, time
import pytz
from telethon import TelegramClient, events
import logging
import time as time_module

API_ID = ('24826804')
API_HASH = ('048e59c243cce6ff788a7da214bf8119')
BOT_TOKEN = ('7597923417:AAEyZvTyyrPFQDz1o1qURDeCEoBFc0fMWaY')
# Проверяем что все переменные установлены
if not all([API_ID, API_HASH, BOT_TOKEN]):
    raise ValueError("❌ Не установлены переменные окружения!")

CHANNELS = [
    'gubernator_46', 'kursk_info46', 'Alekhin_Telega', 'rian_ru',
    'kursk_ak46', 'zhest_kursk_146', 'novosti_efir', 'kursk_tipich',
    'seymkursk', 'kursk_smi', 'kursk_russia', 'belgorod01', 'kurskadm',
    'Avtokadr46', 'kurskbomond', 'prigranichie_radar1', 'grohot_pgr',
    'kursk_nasv', 'mchs_46', 'patriot046', 'kursk_now', 'Hinshtein',
    'incidentkursk', 'zhest_belgorod', 'Pogoda_Kursk', 'pb_032',
    'tipicl32', 'bryansk_smi'
]

SUBSCRIBERS_FILE = 'subscribers.txt'

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ===== ФУНКЦИИ ДЛЯ ПОДПИСЧИКОВ =====
def load_subscribers():
    try:
        with open(SUBSCRIBERS_FILE, 'r') as f:
            return [int(line.strip()) for line in f if line.strip()]
    except FileNotFoundError:
        return []

def save_subscribers(subscribers):
    with open(SUBSCRIBERS_FILE, 'w') as f:
        for user_id in subscribers:
            f.write(f"{user_id}\n")

def add_subscriber(user_id):
    subscribers = load_subscribers()
    if user_id not in subscribers:
        subscribers.append(user_id)
        save_subscribers(subscribers)
        logger.info(f"✅ Новый подписчик: {user_id}")
    return subscribers

def remove_subscriber(user_id):
    subscribers = load_subscribers()
    if user_id in subscribers:
        subscribers.remove(user_id)
        save_subscribers(subscribers)
        logger.info(f"❌ Отписался: {user_id}")
    return subscribers

# ===== ФУНКЦИИ ДЛЯ РАССЫЛКИ =====
def init_db():
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS parsed_posts (
            post_id TEXT PRIMARY KEY,
            channel TEXT,
            text TEXT
        )
    ''')
    return conn

def is_post_sent(conn, post_id):
    cursor = conn.cursor()
    cursor.execute("SELECT post_id FROM parsed_posts WHERE post_id = ?", (post_id,))
    return cursor.fetchone() is not None

def mark_post_as_sent(conn, post_id, channel, text):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO parsed_posts (post_id, channel, text) VALUES (?, ?, ?)",
        (post_id, channel, text)
    )
    conn.commit()

def generate_post_id(channel_name, message_id):
    return f"{channel_name}_{message_id}"

async def parse_channel(client, channel_name, conn):
    try:
        logger.info(f"🔍 Парсим канал: {channel_name}")
        messages = await client.get_messages(channel_name, limit=5)
        new_posts = []
        posts_count = 0
        
        for message in messages:
            if not message.text or not message.text.strip():
                continue
            
            post_id = generate_post_id(channel_name, message.id)
            
            if not is_post_sent(conn, post_id):
                post_text = message.text.strip()
                if len(post_text) > 1000:
                    post_text = post_text[:1000] + "..."
                
                formatted_post = f"📢 **{channel_name}**\n\n{post_text}\n\n🕒 *Время публикации:* {message.date.astimezone(pytz.timezone('Europe/Moscow')).strftime('%H:%M %d.%m.%Y')}"
                
                new_posts.append({
                    'text': formatted_post,
                    'post_id': post_id,
                    'channel': channel_name
                })
                
                mark_post_as_sent(conn, post_id, channel_name, message.text)
                posts_count += 1
                
                if posts_count >= 2:
                    break
        
        return new_posts
        
    except Exception as e:
        logger.error(f"❌ Ошибка парсинга {channel_name}: {e}")
        return []

async def send_news_to_user(client, user_id, posts):
    if not posts:
        await client.send_message(user_id, "📭 Свежих новостей за последнее время нет!")
        return
    
    moscow_time = datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M %d.%m.%Y')
    
    await client.send_message(
        user_id,
        f"📊 **СВЕЖИЕ НОВОСТИ**\n"
        f"🕒 *Актуально на:* {moscow_time} (МСК)\n"
        f"📈 *Всего новостей:* {len(posts)}\n"
        f"────────────────"
    )
    
    for post in posts:
        try:
            await client.send_message(user_id, post['text'], parse_mode='md')
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"❌ Ошибка отправки пользователю {user_id}: {e}")

async def send_news_to_all_subscribers(client):
    subscribers = load_subscribers()
    if not subscribers:
        logger.info("📭 Нет подписчиков для отправки")
        return
    
    logger.info(f"📨 Начинаем отправку для {len(subscribers)} подписчиков")
    
    db_conn = init_db()
    all_news = []
    
    for channel in CHANNELS:
        try:
            channel_news = await parse_channel(client, channel, db_conn)
            all_news.extend(channel_news)
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"❌ Ошибка канала {channel}: {e}")
    
    for user_id in subscribers:
        try:
            await send_news_to_user(client, user_id, all_news)
            logger.info(f"✅ Отправили пользователю {user_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки пользователю {user_id}: {e}")
    
    logger.info(f"✅ Отправка завершена для {len(subscribers)} подписчиков")

def should_send_news():
    """Проверяем, нужно ли сейчас рассылать новости (09, 13 или 19 часов по МСК)"""
    moscow_time = datetime.now(pytz.timezone('Europe/Moscow'))
    current_hour = moscow_time.hour
    current_minute = moscow_time.minute
    return current_hour in [9, 13, 19] and current_minute == 0

# ===== ОСНОВНАЯ ФУНКЦИЯ =====
async def main():
    client = TelegramClient('news_bot_session', API_ID, API_HASH)
    
    # Обработчики команд
    @client.on(events.NewMessage(pattern='/start'))
    async def start_handler(event):
        user_id = event.chat_id
        add_subscriber(user_id)
        await event.reply("🎉 Вы подписались на новости!")
    
    @client.on(events.NewMessage(pattern='/stop'))
    async def stop_handler(event):
        user_id = event.chat_id
        remove_subscriber(user_id)
        await event.reply("❌ Вы отписались от новостей")
    
    @client.on(events.NewMessage(pattern='/stats'))
    async def stats_handler(event):
        subscribers = load_subscribers()
        await event.reply(f"📊 Подписчиков: {len(subscribers)}")
    
    try:
        await client.start(bot_token=BOT_TOKEN)
        logger.info("✅ Бот запущен и авторизован")
        
        # Бесконечный цикл для проверки времени
        while True:
            if should_send_news():
                logger.info("🕒 Время рассылать новости!")
                await send_news_to_all_subscribers(client)
            
            # Проверяем каждую минуту
            await asyncio.sleep(60)
            
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")
    finally:
        await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())