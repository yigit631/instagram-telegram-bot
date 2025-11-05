from flask import Flask, request, jsonify
import telebot
import threading
import time
import requests
import os
from datetime import datetime, timedelta
import cloudinary
import cloudinary.uploader
import cloudinary.api

# Environment variables - RENDER İÇİN
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
INSTAGRAM_TOKEN = os.environ.get('INSTAGRAM_TOKEN')

# CRITICAL: Token kontrolü
if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN environment variable is required! Render Dashboard'dan ayarlayın.")
if not INSTAGRAM_TOKEN:
    raise ValueError("❌ INSTAGRAM_TOKEN environment variable is required! Render Dashboard'dan ayarlayın.")

print("=" * 60)
print("🚀 NEXABOT STARTING...")
print(f"🔑 TELEGRAM_TOKEN: {'✅' if TELEGRAM_TOKEN else '❌'}")
print(f"🔑 INSTAGRAM_TOKEN: {'✅' if INSTAGRAM_TOKEN else '❌'}")

# Cloudinary Configuration - RENDER İÇİN
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
    secure=True
)

print(f"☁️ CLOUDINARY: {'✅' if os.environ.get('CLOUDINARY_CLOUD_NAME') else '❌'}")
print("=" * 60)

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Storage
user_sessions = {}
scheduled_posts = []
post_id_counter = 1

app = Flask(__name__)

# Telegram Bot Handlers
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    user_sessions[user_id] = {'state': 'ready'}
    
    print(f"🎯 /start komutu alındı: {user_id}")
    
    welcome_text = """
🚀 *Nexabot - Instagram Otomatik Paylaşım* 🤖

☁️ *Cloudinary Entegrasyonu*
• Hem fotoğraf HEM video desteği
• Daha hızlı yükleme
• Otomatik optimizasyon

📸 *Kullanım:*
1. Fotoğraf/Video gönder
2. Açıklama yaz  
3. Zaman seç
4. Tamam! Otomatik paylaşılacak 🎉

*Not:* Video paylaşımları biraz daha uzun sürebilir.
"""
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(commands=['help'])
def send_help(message):
    print(f"🎯 /help komutu alındı: {message.from_user.id}")
    
    help_text = """
🤖 *Nexabot - Yardım*

📹 *Video Gereksinimleri:*
• Max 60 saniye
• MP4 formatı
• Max 100MB boyut

⏱️ *Video İşlem Süresi:*
• Yükleme: 1-2 dakika
• Instagram onayı: 2-3 dakika
• Toplam: ~5 dakika

*Komutlar:*
/start - Botu başlat
/help - Yardım
/posts - Gönderileri gör
/cancel - İptal et
"""
    bot.reply_to(message, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['posts'])
def show_posts(message):
    user_id = message.from_user.id
    print(f"🎯 /posts komutu alındı: {user_id}")
    
    user_posts = [p for p in scheduled_posts if p.get('user_id') == user_id]
    
    if not user_posts:
        bot.reply_to(message, "📭 Henüz zamanlanmış gönderin yok!")
        return
    
    response = "📋 *Zamanlanmış Gönderilerin:*\n\n"
    for post in user_posts[:5]:
        status_emoji = {
            'pending': '⏳',
            'processing': '🔄', 
            'completed': '✅',
            'failed': '❌'
        }.get(post['status'], '❓')
        
        media_emoji = '🎥' if post.get('media_type') == 'video' else '📸'
        time_str = datetime.fromisoformat(post['scheduled_time']).strftime('%d.%m.%Y %H:%M')
        response += f"{media_emoji} {status_emoji} *{time_str}*\n"
        response += f"📝 {post['caption'][:30]}...\n"
        
        if post.get('error_message'):
            response += f"❌ {post['error_message'][:50]}\n"
        response += "━━━━━━━━━━━━━━━━━━━━\n"
    
    bot.reply_to(message, response, parse_mode='Markdown')

@bot.message_handler(commands=['cancel'])
def cancel_operation(message):
    user_id = message.from_user.id
    print(f"🎯 /cancel komutu alındı: {user_id}")
    
    if user_id in user_sessions:
        user_sessions[user_id] = {'state': 'ready'}
        bot.reply_to(message, "❌ İşlem iptal edildi.")

@bot.message_handler(content_types=['photo', 'video'])
def handle_media(message):
    try:
        user_id = message.from_user.id
        telegram_media_type = 'video' if message.video else 'photo'
        
        print(f"📸 MEDYA ALINDI: {telegram_media_type} from {user_id}")
        
        # Hemen cevap ver
        bot.reply_to(message, f"📥 {telegram_media_type} alındı! İşleniyor...")
        
        # Video süre kontrolü
        if telegram_media_type == 'video' and message.video.duration > 60:
            bot.reply_to(message, "❌ Video 60 saniyeden uzun olamaz! Lütfen daha kısa video gönderin.")
            return
        
        if telegram_media_type == 'photo':
            photo = message.photo[-1]
            file_info = bot.get_file(photo.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            
            upload_result = cloudinary.uploader.upload(
                downloaded_file,
                resource_type='image',
                folder='telegram_instagram'
            )
            instagram_media_type = 'image'
            
        else:  # video
            video = message.video
            file_info = bot.get_file(video.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            
            # Video boyut kontrolü
            if len(downloaded_file) > 100 * 1024 * 1024:  # 100MB
                bot.reply_to(message, "❌ Video 100MB'den büyük olamaz!")
                return
            
            upload_result = cloudinary.uploader.upload(
                downloaded_file,
                resource_type='video',
                folder='telegram_instagram',
                chunk_size=6000000
            )
            instagram_media_type = 'video'
        
        user_sessions[user_id] = {
            'state': 'waiting_caption',
            'media_url': upload_result['secure_url'],
            'media_type': instagram_media_type,
            'public_id': upload_result.get('public_id'),
            'duration': upload_result.get('duration', 0)
        }
        
        print(f"✅ Cloudinary yükleme başarılı: {upload_result['secure_url']}")
        
        if telegram_media_type == 'photo':
            bot.send_photo(user_id, downloaded_file, 
                          caption="📸 *Fotoğraf hazır!* Açıklama yaz:",
                          parse_mode='Markdown')
        else:
            bot.send_message(user_id, 
                           f"🎥 *Video hazır!* ({upload_result.get('duration', 0):.1f}s)\nAçıklama yaz:",
                           parse_mode='Markdown')
                      
    except Exception as e:
        print(f"❌ MEDYA HATASI: {str(e)}")
        bot.reply_to(message, f"❌ Medya işleme hatası: {str(e)}")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    try:
        user_id = message.from_user.id
        text = message.text.strip()
        
        print(f"📨 MESAJ ALINDI: '{text}' from {user_id}")
        
        if user_id not in user_sessions:
            user_sessions[user_id] = {'state': 'ready'}
        
        session = user_sessions[user_id]
        
        if session['state'] == 'waiting_caption':
            session['caption'] = text
            session['state'] = 'waiting_schedule'
            
            schedule_options = """
⏰ *Ne zaman paylaşayım?*

*Hızlı Seçenekler:*
• `şimdi` - Hemen paylaş
• `15d` - 15 dakika sonra
• `1s` - 1 saat sonra  
• `3s` - 3 saat sonra
• `yarın 09:00` - Yarın sabah 9'da

*Özel Zaman:*
• `05.12.2024 14:30`
• `14:30` (yarın 14:30)
"""
            bot.reply_to(message, schedule_options, parse_mode='Markdown')
            
        elif session['state'] == 'waiting_schedule':
            schedule_time = parse_schedule_time(text)
            
            if not schedule_time:
                bot.reply_to(message, "❌ Geçersiz zaman! Örnek: `1s` veya `yarın 09:00`")
                return
            
            success = schedule_post(user_id, session, schedule_time)
            
            if success:
                time_str = schedule_time.strftime('%d.%m.%Y %H:%M')
                media_type = 'Video' if session['media_type'] == 'video' else 'Fotoğraf'
                bot.reply_to(message, 
                           f"✅ *{media_type} zamanlandı!* 🎉\n"
                           f"📅 {time_str}\n"
                           f"Gönderiler: /posts")
            else:
                bot.reply_to(message, "❌ Zamanlanamadı!")
            
            user_sessions[user_id] = {'state': 'ready'}
            
        else:
            bot.reply_to(message, "📸 Medya göndererek başla!")
            
    except Exception as e:
        print(f"❌ MESAJ İŞLEME HATASI: {str(e)}")
        bot.reply_to(message, f"❌ Hata: {str(e)}")

def parse_schedule_time(text):
    text = text.lower().strip()
    now = datetime.now()
    
    try:
        if text == 'şimdi':
            return now + timedelta(minutes=2)
        elif text == '15d':
            return now + timedelta(minutes=15)
        elif text == '1s':
            return now + timedelta(hours=1)
        elif text == '3s':
            return now + timedelta(hours=3)
        elif text.startswith('yarın'):
            time_part = text.replace('yarın', '').strip() or '09:00'
            tomorrow = now + timedelta(days=1)
            time_obj = datetime.strptime(time_part, '%H:%M').time()
            return datetime.combine(tomorrow.date(), time_obj)
        else:
            formats = ['%d.%m.%Y %H:%M', '%H:%M']
            for fmt in formats:
                try:
                    if fmt == '%H:%M':
                        time_obj = datetime.strptime(text, fmt).time()
                        scheduled = datetime.combine(now.date(), time_obj)
                        if scheduled <= now:
                            scheduled += timedelta(days=1)
                        return scheduled
                    else:
                        return datetime.strptime(text, fmt)
                except ValueError:
                    continue
        return None
    except:
        return None

def schedule_post(user_id, session, schedule_time):
    global post_id_counter
    
    try:
        post = {
            'id': post_id_counter,
            'user_id': user_id,
            'media_url': session['media_url'],
            'media_type': session['media_type'],
            'caption': session['caption'],
            'scheduled_time': schedule_time.isoformat(),
            'status': 'pending',
            'created_at': datetime.now().isoformat(),
            'attempts': 0,
            'error_message': None
        }
        
        scheduled_posts.append(post)
        post_id_counter += 1
        
        print(f"✅ Gönderi zamanlandı: {post['id']} - {session['media_type']}")
        return True
        
    except Exception as e:
        print(f"❌ Schedule error: {e}")
        return False

def post_to_instagram(media_url, caption, media_type='image'):
    try:
        print(f"📤 Attempting to post {media_type} to Instagram...")
        
        if media_type == 'image':
            container_data = {
                'image_url': media_url,
                'caption': caption,
                'access_token': INSTAGRAM_TOKEN
            }
            endpoint = 'https://graph.instagram.com/me/media'
            container_type = "IMAGE"
            print("🔧 Creating IMAGE container...")
        else:
            container_data = {
                'media_type': 'REELS',
                'video_url': media_url,
                'caption': caption,
                'access_token': INSTAGRAM_TOKEN
            }
            endpoint = 'https://graph.instagram.com/me/media'
            container_type = "REELS"
            print("🔧 Creating VIDEO container...")
        
        container_response = requests.post(endpoint, data=container_data, timeout=60)
        container_result = container_response.json()
        print(f"📦 Container response: {container_result}")
        
        if 'id' not in container_result:
            error_msg = container_result.get('error', {}).get('message', 'Unknown container error')
            return {'error': f'Container failed: {error_msg}'}
        
        creation_id = container_result['id']
        print(f"✅ {container_type} container created: {creation_id}")
        
        if media_type == 'video':
            print("⏳ Waiting 60 seconds for video processing...")
            time.sleep(60)
        else:
            print("⏳ Waiting 15 seconds for image processing...")
            time.sleep(15)
        
        publish_url = 'https://graph.instagram.com/me/media_publish'
        publish_data = {
            'creation_id': creation_id,
            'access_token': INSTAGRAM_TOKEN
        }
        
        print("🚀 Publishing...")
        publish_response = requests.post(publish_url, data=publish_data, timeout=30)
        publish_result = publish_response.json()
        
        print(f"📮 Publish response: {publish_result}")
        
        if 'id' in publish_result:
            print(f"✅ Successfully published {media_type}: {publish_result['id']}")
            return {
                'id': publish_result['id'],
                'type': container_type,
                'media_type': media_type
            }
        else:
            error_msg = publish_result.get('error', {}).get('message', 'Unknown publish error')
            return {'error': f'Publish failed: {error_msg}'}
            
    except requests.exceptions.Timeout:
        return {'error': 'Instagram API timeout'}
    except Exception as e:
        return {'error': f'Unexpected error: {str(e)}'}

def process_scheduled_posts():
    while True:
        try:
            now = datetime.now()
            
            for post in scheduled_posts:
                if post['status'] == 'pending':
                    scheduled_time = datetime.fromisoformat(post['scheduled_time'])
                    
                    if scheduled_time <= now:
                        print(f"🔄 Processing {post['media_type']} post {post['id']}")
                        post['status'] = 'processing'
                        
                        try:
                            # Kullanıcıya işlem başladı bildirimi
                            media_type = 'Video' if post['media_type'] == 'video' else 'Fotoğraf'
                            bot.send_message(post['user_id'], f"🔄 {media_type} gönderiniz Instagram'a işleniyor...")
                            
                            # INSTAGRAM'A GÖNDER
                            result = post_to_instagram(
                                post['media_url'], 
                                post['caption'], 
                                post['media_type']
                            )
                            
                            if 'id' in result:
                                post['status'] = 'completed'
                                post['post_id'] = result['id']
                                post['post_type'] = result.get('type', 'unknown')
                                post['completed_at'] = datetime.now().isoformat()
                                
                                # BAŞARI BİLDİRİMİ
                                media_type = 'Video' if post['media_type'] == 'video' else 'Fotoğraf'
                                post_type = result.get('type', 'Gönderi')
                                bot.send_message(
                                    post['user_id'],
                                    f"✅ *{media_type} gönderiniz paylaşıldı!* 🎉\n\n"
                                    f"📝 {post['caption'][:50]}...\n"
                                    f"📊 Tip: {post_type}\n"
                                    f"🆔 ID: `{result['id']}`",
                                    parse_mode='Markdown'
                                )
                                    
                                print(f"✅ {post['media_type']} post {post['id']} completed!")
                                
                            else:
                                raise Exception(result.get('error', 'Unknown error'))
                                
                        except Exception as e:
                            post['attempts'] += 1
                            post['error_message'] = str(e)
                            post['status'] = 'failed'
                            
                            print(f"❌ Post {post['id']} failed: {e}")
                            
                            # HATA BİLDİRİMİ
                            bot.send_message(
                                post['user_id'],
                                f"❌ *Gönderi hatası!*\n\nHata: {str(e)[:100]}",
                                parse_mode='Markdown'
                            )
            
            time.sleep(30)
            
        except Exception as e:
            print(f"❌ Scheduler error: {e}")
            time.sleep(60)

# FLASK ROUTES
@app.route('/')
def home():
    photo_count = len([p for p in scheduled_posts if p.get('media_type') == 'image'])
    video_count = len([p for p in scheduled_posts if p.get('media_type') == 'video'])
    completed_count = len([p for p in scheduled_posts if p.get('status') == 'completed'])
    pending_count = len([p for p in scheduled_posts if p.get('status') == 'pending'])
    
    return f"""
    <html>
        <head>
            <title>Nexabot - Instagram Telegram Bot</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                .stats {{ background: #f5f5f5; padding: 20px; border-radius: 10px; }}
                .stat-item {{ margin: 10px 0; }}
            </style>
        </head>
        <body>
            <h1>🤖 Nexabot - Instagram Telegram Bot</h1>
            <p><strong>☁️ Cloudinary + Video Desteği</strong></p>
            
            <div class="stats">
                <h3>📊 Sistem İstatistikleri</h3>
                <div class="stat-item"><strong>Toplam Gönderi:</strong> {len(scheduled_posts)}</div>
                <div class="stat-item"><strong>Aktif Kullanıcı:</strong> {len(user_sessions)}</div>
                <div class="stat-item"><strong>📸 Fotoğraf:</strong> {photo_count}</div>
                <div class="stat-item"><strong>🎥 Video:</strong> {video_count}</div>
                <div class="stat-item"><strong>✅ Başarılı:</strong> {completed_count}</div>
                <div class="stat-item"><strong>⏳ Bekleyen:</strong> {pending_count}</div>
            </div>
            
            <p><em>Nexabot aktif ve çalışıyor... 🚀</em></p>
        </body>
    </html>
    """

@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'service': 'Nexabot',
        'timestamp': datetime.now().isoformat(),
        'scheduled_posts': len(scheduled_posts),
        'active_users': len(user_sessions)
    })

def start_bot():
    print("🤖🤖🤖 BOT THREAD BAŞLIYOR...")
    time.sleep(5)  # Flask'ın başlaması için bekle
    
    while True:
        try:
            print("🔴 WEBHOOK TEMİZLE...")
            bot.remove_webhook()
            time.sleep(2)
            print("🟢 POLLING BAŞLAT...")
            bot.polling(none_stop=True, timeout=60)
        except Exception as e:
            print(f"❌ BOT HATASI: {str(e)}")
            time.sleep(10)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    
    print("=" * 60)
    print("🚀 NEXABOT DIRECT START...")
    print(f"📍 Port: {port}")
    print("=" * 60)
    
    # Scheduler'ı başlat
    scheduler_thread = threading.Thread(target=process_scheduled_posts)
    scheduler_thread.daemon = True
    scheduler_thread.start()
    
    # Bot'u başlat
    bot_thread = threading.Thread(target=start_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Flask'ı başlat
    print("🌐 Flask server starting...")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)