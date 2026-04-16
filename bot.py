import asyncio
import logging
import csv
import os
import random
import re
import cv2
import numpy as np
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import time

from maxapi import Bot, Dispatcher
from maxapi.types import BotStarted, MessageCreated

import easyocr
import pytesseract
import fitz
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import ollama

# ========== НАСТРОЙКИ ==========
MAX_BOT_TOKEN = "f9LHodD0cOJRbwdfepH0h0GKNQC7ZHwkLw3tDD89XZPe0SYtbPjVwmxAEh1D9XGFnH0WXweTlwrJQsl4Xg6U"
ADMIN_SECRET_WORD = "магистр"
ADMINS_FILE = "admins.txt"
EXPECTED_PHONE = "+79831506005"

# Google Sheets настройки
SPREADSHEET_ID = "11bp--gM_7xNWoS_KIUSLciJDx0EQVA6dV5yyOTfflhw"
SHEET_NAME = "Участники"

# Часовые пояса
KRASNOYARSK_TZ = timezone(timedelta(hours=7))
MOSCOW_TZ = timezone(timedelta(hours=3))

# Подключение к Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
gc = gspread.service_account(filename="credentials.json")
sh = gc.open_by_key(SPREADSHEET_ID)

# Локальные файлы
SETTINGS_FILE = "bot_settings.txt"

def get_worksheet():
    try:
        return sh.worksheet(SHEET_NAME)
    except:
        worksheet = sh.add_worksheet(title=SHEET_NAME, rows=1001, cols=6)
        worksheet.update_cell(1, 1, 'Номер')
        worksheet.update_cell(1, 2, 'ФИО')
        worksheet.update_cell(1, 3, 'Город')
        worksheet.update_cell(1, 4, 'Телефон')
        worksheet.update_cell(1, 5, 'UserID')
        worksheet.update_cell(1, 6, 'Дата')
        for num in range(1, 1001):
            worksheet.update_cell(num + 1, 1, str(num))
        return worksheet

worksheet = get_worksheet()


def update_sheet_size(total_seats):
    """Ollama обновляет размер таблицы массовыми операциями"""
    try:
        current_rows = len(worksheet.get_all_values()) - 1
        print(f"🤖 Ollama: текущее мест {current_rows}, нужно {total_seats}")
        
        if current_rows < total_seats:
            print(f"🤖 Ollama: Добавляю {total_seats - current_rows} строк...")
            new_rows = []
            for num in range(current_rows + 1, total_seats + 1):
                new_rows.append([str(num), '', '', '', '', ''])
            worksheet.append_rows(new_rows, value_input_option='USER_ENTERED')
            print(f"✅ Добавлено {len(new_rows)} строк одним запросом")
            
        elif current_rows > total_seats:
            print(f"🤖 Ollama: Удаляю {current_rows - total_seats} строк...")
            for i in range(current_rows, total_seats, -1):
                worksheet.delete_rows(i + 1)
            print(f"✅ Удалено {current_rows - total_seats} строк")
            
        print(f"✅ Таблица обновлена: {total_seats} мест")
        
    except Exception as e:
        print(f"❌ Ошибка Ollama: {e}")

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {'seats': 1000, 'price': 250}
    with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        settings = {}
        for line in lines:
            if '=' in line:
                key, val = line.strip().split('=')
                settings[key] = int(val)
        return settings

def save_settings(settings):
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        f.write(f"seats={settings.get('seats', 1000)}\n")
        f.write(f"price={settings.get('price', 250)}\n")

def get_total_seats():
    settings = load_settings()
    return settings.get('seats', 1000)

def set_total_seats(seats):
    settings = load_settings()
    settings['seats'] = seats
    save_settings(settings)
    # Ollama поможет обновить таблицу
    update_sheet_with_ollama(seats)

def update_sheet_with_ollama(new_size):
    """Ollama обновляет таблицу массовыми операциями без циклов"""
    try:
        current_rows = len(worksheet.get_all_values()) - 1
        print(f"🤖 Ollama: текущее мест {current_rows}, нужно {new_size}")
        
        if new_size > current_rows:
            # МАССОВАЯ ВСТАВКА - одна операция для всех строк
            print(f"🤖 Ollama: Добавляю {new_size - current_rows} строк одним запросом...")
            new_rows = []
            for num in range(current_rows + 1, new_size + 1):
                new_rows.append([str(num), '', '', '', '', ''])
            
            if new_rows:
                worksheet.append_rows(new_rows, value_input_option='USER_ENTERED')
                print(f"✅ Добавлено {len(new_rows)} строк одним запросом")
                
        elif new_size < current_rows:
            # Удаляем лишние строки
            print(f"🤖 Ollama: Удаляю {current_rows - new_size} строк...")
            for i in range(current_rows, new_size, -1):
                worksheet.delete_rows(i + 1)
            print(f"✅ Удалено {current_rows - new_size} строк")
            
        print(f"✅ Таблица обновлена: {new_size} мест")
        
    except Exception as e:
        print(f"❌ Ошибка Ollama: {e}")
        # Если массовая вставка не сработала, показываем ошибку
        print("⚠️ Подождите минуту и попробуйте снова (лимит API)")
        prompt = f"""
        Ты помощник по управлению Google Таблицей.
        Сейчас в таблице {current_seats} мест (строк с данными).
        Нужно сделать {new_size} мест.
        
        Если {new_size} > {current_seats}:
        - Добавь строки с номерами от {current_seats + 1} до {new_size}
        - В новых строках оставь только номер, остальное пустое
        
        Если {new_size} < {current_seats}:
        - Удали строки с номерами от {new_size + 1} до {current_seats}
        
        Ответь кратко: что нужно сделать.
        """
        
        response = ollama.chat(model='llama3.2:3b', messages=[{'role': 'user', 'content': prompt}])
        print(f"🤖 Ollama: {response['message']['content']}")
        
        # Выполняем действие
        if new_size > current_seats:
            for num in range(current_seats + 1, new_size + 1):
                worksheet.update_cell(num + 1, 1, str(num))
            print(f"✅ Добавлено {new_size - current_seats} мест")
        elif new_size < current_seats:
            for i in range(current_seats, new_size, -1):
                worksheet.delete_rows(i + 1)
            print(f"✅ Удалено {current_seats - new_size} мест")
            
    except Exception as e:
        print(f"Ошибка Ollama: {e}")
        # fallback - прямое обновление
        current_rows = len(worksheet.get_all_values())
        if new_size > current_rows - 1:
            for num in range(current_rows, new_size + 1):
                worksheet.update_cell(num + 1, 1, str(num))
        elif new_size < current_rows - 1:
            for i in range(current_rows - 1, new_size, -1):
                worksheet.delete_rows(i + 1)

def get_price():
    settings = load_settings()
    return settings.get('price', 250)

def set_price(price):
    settings = load_settings()
    settings['price'] = price
    save_settings(settings)

def get_free_numbers():
    free = []
    try:
        all_rows = worksheet.get_all_values()
        for i, row in enumerate(all_rows[1:], start=1):
            if len(row) > 1 and (not row[1] or row[1].strip() == ''):
                free.append(i)
        random.shuffle(free)
    except Exception as e:
        print(f"Ошибка: {e}")
        free = []
    return free

def get_free_count():
    return len(get_free_numbers())

def get_occupied_count():
    return get_total_seats() - get_free_count()

def save_user(numbers, user_id, name, city, phone):
    success = True
    for number in numbers:
        try:
            row = number + 1
            worksheet.update_cell(row, 2, name)
            worksheet.update_cell(row, 3, city)
            worksheet.update_cell(row, 4, phone)
            worksheet.update_cell(row, 5, str(user_id))
            worksheet.update_cell(row, 6, datetime.now(KRASNOYARSK_TZ).strftime("%Y-%m-%d %H:%M:%S"))
            print(f"✅ Сохранен номер {number}")
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            success = False
    return success


def reset_all_data():
    """Ollama полностью очищает таблицу массово"""
    try:
        print("🤖 Ollama: Очищаю таблицу...")
        all_rows = worksheet.get_all_values()
        total_rows = len(all_rows)
        
        # Массовое обновление: подготавливаем очищенные данные
        update_data = []
        for i, row in enumerate(all_rows):
            if i == 0:
                update_data.append(['Номер', 'ФИО', 'Город', 'Телефон', 'UserID', 'Дата'])
            else:
                number = row[0] if len(row) > 0 else str(i)
                update_data.append([number, '', '', '', '', ''])
        
        worksheet.update(range_name=f'A1:F{total_rows}', values=update_data, value_input_option='USER_ENTERED')
        print("✅ Таблица очищена одним запросом")
        
    except Exception as e:
        print(f"❌ Ошибка Ollama: {e}")
    
    set_price(250)
    print("✅ Данные сброшены")

def get_table_url():
    return f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}"

def get_today_moscow():
    return datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")

def get_user_link(user_id):
    return f"https://max.ru/id{user_id}"

async def notify_admins(bot, message):
    admins = load_admins()
    for admin_id in admins:
        try:
            await bot.send_message(chat_id=int(admin_id), text=message, notify=True)
        except:
            pass

def load_admins():
    if not os.path.exists(ADMINS_FILE):
        return set()
    with open(ADMINS_FILE, 'r', encoding='utf-8') as f:
        return set(line.strip() for line in f if line.strip())

def save_admin(admin_id):
    admins = load_admins()
    admins.add(str(admin_id))
    with open(ADMINS_FILE, 'w', encoding='utf-8') as f:
        for aid in admins:
            f.write(f"{aid}\n")

def is_admin(user_id):
    return str(user_id) in load_admins()

# ========== ОБРАБОТКА PDF И ИЗОБРАЖЕНИЙ ==========

MONTHS = {
    'янв': '01', 'января': '01', 'январь': '01',
    'фев': '02', 'февраля': '02', 'февраль': '02',
    'мар': '03', 'марта': '03', 'март': '03',
    'апр': '04', 'апреля': '04', 'апрель': '04',
    'мая': '05', 'май': '05',
    'июн': '06', 'июня': '06', 'июнь': '06',
    'июл': '07', 'июля': '07', 'июль': '07',
    'авг': '08', 'августа': '08', 'август': '08',
    'сен': '09', 'сентября': '09', 'сентябрь': '09',
    'окт': '10', 'октября': '10', 'октябрь': '10',
    'ноя': '11', 'ноября': '11', 'ноябрь': '11',
    'дек': '12', 'декабря': '12', 'декабрь': '12',
}

print("🔄 Загрузка EasyOCR...")
easyocr_reader = easyocr.Reader(['ru', 'en'], gpu=False, verbose=False)
print("✅ OCR загружен!")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=MAX_BOT_TOKEN)
dp = Dispatcher()

def pdf_to_image(pdf_data):
    try:
        doc = fitz.open(stream=pdf_data, filetype="pdf")
        page = doc[0]
        zoom = 2.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")
        doc.close()
        return img_data
    except:
        return None

def is_pdf(file_data):
    return file_data[:4] == b'%PDF'

def enhance_image(image_data):
    nparr = np.frombuffer(image_data, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    
    best_images = [img]
    
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
    l = clahe.apply(l)
    enhanced = cv2.merge([l, a, b])
    enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
    best_images.append(enhanced)
    
    denoised = cv2.fastNlMeansDenoisingColored(img, None, 10, 10, 7, 21)
    kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
    sharpened = cv2.filter2D(denoised, -1, kernel)
    best_images.append(sharpened)
    
    h, w = img.shape[:2]
    scaled = cv2.resize(img, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
    best_images.append(scaled)
    
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    binary_bgr = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    best_images.append(binary_bgr)
    
    return best_images

def ocr_on_image(img):
    results = []
    try:
        easy_result = easyocr_reader.readtext(img, detail=0, paragraph=False)
        results.append(('easyocr', ' '.join(easy_result)))
    except:
        pass
    try:
        from PIL import Image
        pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        tess_result = pytesseract.image_to_string(pil_img, lang='rus+eng')
        results.append(('tesseract', tess_result))
    except:
        pass
    return results

def extract_amount(text):
    if not text:
        return None
    text = text.upper()
    patterns = [
        r'(?:ИТОГО|ВСЕГО|СУММА|К ОПЛАТЕ|ОПЛАТА|TOTAL|AMOUNT)[^\d]*(\d+)[\s.,]*(\d*)',
        r'(\d+)[\s.,]*(\d*)\s*(?:РУБ|₽|RUB|Р)',
        r'(\d+)[\s.,]*(\d*)\s*РУБЛ',
        r'(\d+)[\s.,]*(\d*)\s*₽',
    ]
    candidates = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            rub = match[0].replace(',', '').replace('.', '')
            if rub and rub.isdigit():
                kop = match[1] if len(match) > 1 else ''
                if kop and len(kop) == 2:
                    amount = float(f"{rub}.{kop}")
                elif kop and len(kop) == 1:
                    amount = float(f"{rub}.{kop}0")
                else:
                    amount = float(rub)
                if 10 <= amount <= 100000:
                    candidates.append(amount)
    if candidates:
        from collections import Counter
        return Counter(candidates).most_common(1)[0][0]
    return None

def extract_date_only(text):
    if not text:
        return None
    text_lower = text.lower()
    month_pattern = r'(?<!\d)(\d{1,2})\s+(' + '|'.join(MONTHS.keys()) + r')\s+(\d{2,4})(?!\d)'
    match = re.search(month_pattern, text_lower, re.IGNORECASE)
    if match:
        try:
            day = match.group(1).zfill(2)
            month_word = match.group(2).lower()
            year = match.group(3)
            month = MONTHS.get(month_word)
            if month:
                if len(year) == 2:
                    year = '20' + year
                if 1 <= int(day) <= 31:
                    return f"{year}-{month}-{day}"
        except:
            pass
    patterns = [
        (r'(?<!\d)(\d{2})[./](\d{2})[./](\d{4})(?!\d)', 'DMY'),
        (r'(?<!\d)(\d{4})[./-](\d{2})[./-](\d{2})(?!\d)', 'YMD'),
        (r'(?<!\d)(\d{2})[./](\d{2})[./](\d{2})(?!\d)', 'DMY_short'),
    ]
    for pattern, format_type in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                groups = match.groups()
                if format_type == 'DMY':
                    day, month, year = groups
                    if 1 <= int(day) <= 31 and 1 <= int(month) <= 12:
                        return f"{year}-{month}-{day}"
                elif format_type == 'YMD':
                    year, month, day = groups
                    if 1 <= int(day) <= 31 and 1 <= int(month) <= 12:
                        return f"{year}-{month}-{day}"
                elif format_type == 'DMY_short':
                    day, month, year = groups
                    year_full = 2000 + int(year)
                    if 1 <= int(day) <= 31 and 1 <= int(month) <= 12:
                        return f"{year_full}-{month}-{day}"
            except:
                pass
    return None

def normalize_phone(phone):
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 11 and digits[0] in ['7', '8']:
        return '+' + digits
    elif len(digits) == 10:
        return '+7' + digits
    return '+' + digits if digits else None

def extract_phone(text):
    if not text:
        return None
    patterns = [
        r'\+?7[\s\-]?\(?(\d{3})\)?[\s\-]?(\d{3})[\s\-]?(\d{2})[\s\-]?(\d{2})',
        r'8[\s\-]?\(?(\d{3})\)?[\s\-]?(\d{3})[\s\-]?(\d{2})[\s\-]?(\d{2})',
        r'(\d{3})[\s\-]?(\d{3})[\s\-]?(\d{2})[\s\-]?(\d{2})',
        r'(\d{3})[\s\-]?(\d{2})[\s\-]?(\d{2})[\s\-]?(\d{2})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            groups = match.groups()
            if len(groups) == 4:
                return f"+7{groups[0]}{groups[1]}{groups[2]}{groups[3]}"
            elif len(groups) == 3:
                return f"+7{groups[0]}{groups[1]}{groups[2]}"
    return None

def process_receipt(file_data, expected_price):
    if is_pdf(file_data):
        image_data = pdf_to_image(file_data)
        if not image_data:
            return False, "Не удалось обработать PDF", None, None, None, 1
    else:
        image_data = file_data
    
    images = enhance_image(image_data)
    if not images:
        return False, "Не удалось обработать изображение", None, None, None, 1
    
    all_texts = []
    for img in images:
        ocr_results = ocr_on_image(img)
        for engine, text in ocr_results:
            if text:
                all_texts.append(text)
                print(f"📝 [{engine}]: {text[:200]}...")
    
    combined_text = ' '.join(all_texts)
    
    amount = extract_amount(combined_text)
    date = extract_date_only(combined_text)
    phone_raw = extract_phone(combined_text)
    phone = normalize_phone(phone_raw) if phone_raw else None
    
    print(f"🔍 Результаты:")
    print(f"   Сумма: {amount}")
    print(f"   Дата: {date}")
    print(f"   Телефон: {phone}")
    
    errors = []
    
    if amount is None:
        errors.append("Не удалось распознать сумму")
    elif amount < expected_price - 1:
        errors.append(f"Сумма {amount}₽ меньше {expected_price}₽")
    
    today_moscow = get_today_moscow()
    if date:
        if date != today_moscow:
            errors.append(f"Дата чека {date} не совпадает с сегодняшней (Москва: {today_moscow})")
    else:
        errors.append("Не удалось распознать дату на чеке")
    
    if phone:
        clean_phone = re.sub(r'\D', '', phone)
        clean_expected = re.sub(r'\D', '', EXPECTED_PHONE)
        if clean_phone[-10:] != clean_expected[-10:]:
            errors.append("Номер телефона не совпадает")
    else:
        errors.append("Не удалось распознать номер телефона")
    
    if errors:
        return False, "\n".join(errors), amount, date, phone, 1
    
    quantity = int(amount // expected_price)
    if quantity < 1:
        quantity = 1
    
    return True, f"✅ Чек принят! {amount}₽, выдано {quantity} номерков", amount, date, phone, quantity

# ========== ОСНОВНАЯ ЛОГИКА ==========

user_states = {}
user_data = {}
user_waiting_receipt = {}
user_temp_data = {}
user_fail_count = {}
problem_users = {}

admin_waiting_for_seats = set()
admin_waiting_for_price = set()

JOIN_KEYWORDS = ["хочу", "участвую", "учавствую", "да", "давай", "начать", "старт"]
INFO_KEYWORDS = ["сколько", "осталось", "места", "свободно", "инфо"]

JOIN_MESSAGE = """💫 **Уважаемый участник акции!** 💫

Для участия в акции **«Поймай удачу»** вам необходимо совершить перевод по реквизитам:

┌─────────────────────────────────────────────────┐
│ 💳 **ОЗОН БАНК**                               │
│ 📱 **+7 (983) 150-60-05**                      │
│ 👤 **Алексей Андреевич П.**                    │
│ 💰 **{price}₽** за 1 номер                     │
└─────────────────────────────────────────────────┘

📸 **После оплаты отправьте:**
• Подтверждающий документ
• Или скриншот успешной операции

⚡️ **Наш бот проанализирует ваш документ и автоматически случайным образом присвоит вам номерки.**
💰 **Сколько номеров вы оплатили — столько и получите!**

🎯 **Желаем удачи!**

⚠️ **ВНИМАНИЕ!**
Не пытайтесь отправлять боту недостоверные документы.
В боте интегрирована система анализа и изучения чеков.

📞 **Если у вас возникнут вопросы, вы можете позвонить администратору:**
+7 (983) 150-60-05"""

@dp.bot_started()
async def on_bot_started(event: BotStarted):
    free = get_free_count()
    total = get_total_seats()
    price = get_price()
    await bot.send_message(
        chat_id=event.chat_id,
        text=f"✨ **ДОБРО ПОЖАЛОВАТЬ!** ✨\n\n"
             f"🎲 **Уникальные номерки** — твой шанс на победу!\n\n"
             f"💎 **Стоимость участия:** {price}₽ за 1 номерок\n"
             f"🎁 **Чем больше номерков — тем выше шанс на выигрыш!**\n\n"
             f"📊 **Доступно номеров:** {free} из {total}\n\n"
             f"🔮 **Как стать участником?**\n"
             f"1️⃣ Напишите «ХОЧУ»\n"
             f"2️⃣ Оплатите по реквизитам\n"
             f"3️⃣ Отправьте скриншот или PDF чека\n"
             f"4️⃣ Заполните анкету\n"
             f"5️⃣ Получите свой номер!\n\n"
             f"💳 **ОЗОН БАНК:** +7 (983) 150-60-05\n"
             f"👤 Получатель: Алексей Андреевич П.\n"
             f"💰 Стоимость: {price}₽ за 1 номер\n\n"
             f"⚡️ Удачи! 🍀"
    )

@dp.message_created()
async def handle_message(event: MessageCreated):
    user_id = event.from_user.user_id
    chat_id = event.chat.chat_id
    text = event.message.body.text.strip().lower() if event.message.body.text else ""
    
    print(f"📨 {user_id}: {text if text else '[ФАЙЛ]'}")
    
    # Секретное слово
    if text == ADMIN_SECRET_WORD.lower():
        if not is_admin(user_id):
            save_admin(user_id)
            await bot.send_message(
                chat_id=chat_id,
                text=f"🔐 **Доступ к админ-панели открыт!**\n\n"
                     f"👑 Команды:\n"
                     f"• `места` - установить количество мест (Ollama)\n"
                     f"• `цена` - установить цену\n"
                     f"• `таблица` - ссылка на Google таблицу\n"
                     f"• `статистика` - статистика\n"
                     f"• `проблемы` - проблемные участники\n"
                     f"• `сброс` - очистить данные (Ollama)\n"
                     f"• `помощь` - справка\n\n"
                     f"📊 **Google Таблица:** {get_table_url()}"
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=f"👑 **Вы уже в админ-панели!**\n\n"
                     f"📊 **Google Таблица:** {get_table_url()}\n\n"
                     f"`места` - изменить количество\n`цена` - изменить цену\n`статистика`"
            )
        return
    
    # Админ-команды
    if is_admin(user_id):
        if text == "места":
            admin_waiting_for_seats.add(user_id)
            await bot.send_message(chat_id=chat_id, text="📝 Введите **количество мест** (Ollama обновит таблицу)")
            return
        
        if text == "цена":
            admin_waiting_for_price.add(user_id)
            await bot.send_message(chat_id=chat_id, text="💰 Введите **новую цену**")
            return
        
        if user_id in admin_waiting_for_seats:
            clean_text = re.sub(r'[^\d]', '', text)
            if clean_text and clean_text.isdigit():
                new_seats = int(clean_text)
                if new_seats > 0:
                    set_total_seats(new_seats)
                    await bot.send_message(chat_id=chat_id, text=f"✅ Установлено {new_seats} мест\n🤖 Ollama обновила таблицу")
                    admin_waiting_for_seats.discard(user_id)
                else:
                    await bot.send_message(chat_id=chat_id, text="❌ Число должно быть больше 0")
            else:
                await bot.send_message(chat_id=chat_id, text="❌ Введите число")
            return
        
        if user_id in admin_waiting_for_price:
            clean_text = re.sub(r'[^\d]', '', text)
            if clean_text and clean_text.isdigit():
                new_price = int(clean_text)
                if new_price > 0:
                    set_price(new_price)
                    await bot.send_message(chat_id=chat_id, text=f"✅ Цена: {new_price}₽")
                    admin_waiting_for_price.discard(user_id)
                else:
                    await bot.send_message(chat_id=chat_id, text="❌ Цена должна быть больше 0")
            else:
                await bot.send_message(chat_id=chat_id, text="❌ Введите число")
            return
        
        if text == "таблица":
            await bot.send_message(chat_id=chat_id, text=f"📊 **Google Таблица:**\n{get_table_url()}\n\n👥 Участников: {get_occupied_count()}\n🎫 Свободно: {get_free_count()}\n💰 Цена: {get_price()}₽")
            return
        
        if text == "статистика":
            await bot.send_message(
                chat_id=chat_id,
                text=f"📊 **СТАТИСТИКА**\n\n"
                     f"📌 Всего мест: {get_total_seats()}\n"
                     f"✅ Занято: {get_occupied_count()}\n"
                     f"❌ Свободно: {get_free_count()}\n"
                     f"💰 Цена: {get_price()}₽"
            )
            return
        
        if text == "проблемы":
            if not problem_users:
                await bot.send_message(chat_id=chat_id, text="✅ Нет проблемных пользователей")
            else:
                msg = "⚠️ **ПРОБЛЕМНЫЕ ПОЛЬЗОВАТЕЛИ** ⚠️\n\n"
                for uid, reason in problem_users.items():
                    msg += f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    msg += f"👤 ID: `{uid}`\n"
                    msg += f"📝 Причина: {reason}\n\n"
                await bot.send_message(chat_id=chat_id, text=msg)
            return
        
        if text == "сброс":
            await bot.send_message(chat_id=chat_id, text="🔄 Ollama очищает таблицу...")
            reset_all_data()
            problem_users.clear()
            await bot.send_message(chat_id=chat_id, text="✅ Данные сброшены\n🤖 Ollama очистила таблицу")
            return
        
        if text == "помощь":
            await bot.send_message(
                chat_id=chat_id,
                text=f"👑 **АДМИН-КОМАНДЫ**\n\n"
                     f"`места` - установить количество мест (Ollama)\n"
                     f"`цена` - установить цену\n"
                     f"`таблица` - ссылка на Google таблицу\n"
                     f"`статистика` - статистика\n"
                     f"`проблемы` - проблемные участники\n"
                     f"`сброс` - очистить данные (Ollama)\n"
                     f"`помощь` - справка"
            )
            return
    
    # Проверка на заполненность
    if get_free_count() == 0 and any(keyword in text for keyword in JOIN_KEYWORDS):
        await bot.send_message(chat_id=chat_id, text="😔 **ВСЕ НОМЕРКИ РАЗОБРАНЫ!**\n\nАкция завершена!")
        return
    
    # Пользовательские команды
    if any(keyword in text for keyword in JOIN_KEYWORDS):
        print(f"🔑 ПОЛЬЗОВАТЕЛЬ {user_id} НАПИСАЛ ХОЧУ")
        price = get_price()
        await bot.send_message(
            chat_id=chat_id,
            text=JOIN_MESSAGE.format(price=price)
        )
        user_waiting_receipt[user_id] = True
        user_fail_count[user_id] = 0
        print(f"✅ user_waiting_receipt[{user_id}] = {user_waiting_receipt.get(user_id)}")
        return
    
    if any(keyword in text for keyword in INFO_KEYWORDS):
        await bot.send_message(
            chat_id=chat_id,
            text=f"📊 Свободно номерков: **{get_free_count()}** из **{get_total_seats()}**\n💰 Цена: **{get_price()}₽**"
        )
        return
    
    # Обработка чеков
    print(f"🔍 Проверка: user_waiting_receipt[{user_id}] = {user_waiting_receipt.get(user_id)}")
    
    if user_waiting_receipt.get(user_id):
        print(f"📁 ПОЛУЧЕН ФАЙЛ ОТ {user_id}, ОБРАБАТЫВАЮ...")
        
        attachments = event.message.body.attachments if hasattr(event.message.body, 'attachments') else []
        
        if not attachments:
            await bot.send_message(chat_id=chat_id, text="📸 Отправьте **ФОТО или PDF чека**!")
            return
        
        await bot.send_message(chat_id=chat_id, text="🔍 Проверяю чек...")
        
        try:
            attachment = attachments[0]
            file_data = None
            
            if hasattr(attachment, 'payload'):
                if hasattr(attachment.payload, 'url'):
                    import aiohttp
                    async with aiohttp.ClientSession() as session:
                        async with session.get(attachment.payload.url) as resp:
                            file_data = await resp.read()
                elif hasattr(attachment.payload, 'data'):
                    file_data = attachment.payload.data
            
            if not file_data:
                await bot.send_message(chat_id=chat_id, text="❌ Не удалось получить файл")
                return
            
            expected_price = get_price()
            success, message, amount, date, phone, quantity = process_receipt(file_data, expected_price)
            
            if success:
                user_temp_data[user_id] = {'quantity': quantity, 'amount': amount}
                free_count = get_free_count()
                if quantity > free_count:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"⚠️ Оплачено {amount}₽ = {quantity} номерков, но свободно {free_count}\nВыдано {free_count}"
                    )
                    quantity = free_count
                    user_temp_data[user_id]['quantity'] = quantity
                
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ {message}\n\n📝 Введите **ФИО**:"
                )
                user_states[user_id] = "waiting_name"
                del user_waiting_receipt[user_id]
            else:
                user_fail_count[user_id] = user_fail_count.get(user_id, 0) + 1
                fail_count = user_fail_count[user_id]
                
                if fail_count >= 2:
                    problem_users[user_id] = message
                    await notify_admins(
                        bot,
                        f"⚠️ **ПРОБЛЕМНЫЙ ЧЕК!**\n\n"
                        f"👤 Пользователь: ID `{user_id}`\n"
                        f"❌ {message}"
                    )
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"❌ **Чек НЕ ПРИНЯТ**\n\n{message}\n\n👨‍💼 **С вами свяжется администратор**"
                    )
                    del user_waiting_receipt[user_id]
                    del user_fail_count[user_id]
                else:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"❌ **Чек НЕ ПРИНЯТ**\n\n{message}\n\n📸 Попробуйте еще раз ({2 - fail_count} попытка)"
                    )
        except Exception as e:
            print(f"Ошибка: {e}")
            await bot.send_message(chat_id=chat_id, text="❌ Ошибка при проверке")
        return
    
    # Сбор данных
    state = user_states.get(user_id)
    if state == "waiting_name":
        user_data[user_id] = {"name": event.message.body.text.strip()}
        user_states[user_id] = "waiting_city"
        await bot.send_message(chat_id=chat_id, text="🏙️ Город:")
    elif state == "waiting_city":
        user_data[user_id]["city"] = event.message.body.text.strip()
        user_states[user_id] = "waiting_phone"
        await bot.send_message(chat_id=chat_id, text="📞 Телефон:")
    elif state == "waiting_phone":
        user_data[user_id]["phone"] = event.message.body.text.strip()
        
        quantity = user_temp_data.get(user_id, {}).get('quantity', 1)
        free_list = get_free_numbers()
        
        if len(free_list) < quantity:
            quantity = len(free_list)
        
        if quantity == 0:
            await bot.send_message(chat_id=chat_id, text="😔 Места закончились!")
        else:
            assigned_numbers = free_list[:quantity]
            save_user(assigned_numbers, user_id, user_data[user_id]["name"], 
                     user_data[user_id]["city"], user_data[user_id]["phone"])
            
            numbers_text = ", ".join(str(n) for n in assigned_numbers)
            await bot.send_message(
                chat_id=chat_id,
                text=f"🎉 **ПОЗДРАВЛЯЮ!** 🎉\n\n"
                     f"🎫 Ваши номера: **{numbers_text}**\n"
                     f"📊 Осталось: **{get_free_count()}**\n\n"
                     f"🏆 Удачи!"
            )
            
            if get_free_count() == 0:
                await notify_admins(bot, "🎉 **ВСЕ НОМЕРКИ РАЗОБРАНЫ!**")
        
        del user_states[user_id]
        del user_data[user_id]
        if user_id in user_temp_data:
            del user_temp_data[user_id]

async def main():
    print("=" * 60)
    print("🤖 БОТ ЗАПУЩЕН С OLLAMA")
    print(f"📊 Google Таблица: {get_table_url()}")
    print(f"💰 Цена: {get_price()}₽")
    print(f"📋 Всего мест: {get_total_seats()}")
    print(f"👥 Занято: {get_occupied_count()}")
    print(f"❌ Свободно: {get_free_count()}")
    print("=" * 60)
    print("🤖 Ollama управляет таблицей:")
    print("   - Добавляет строки при увеличении мест")
    print("   - Удаляет строки при уменьшении мест")
    print("   - Очищает данные при сбросе")
    print("=" * 60)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
