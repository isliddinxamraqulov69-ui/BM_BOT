import asyncio
import json
import os
import re
import threading
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from flask import Flask, jsonify
from waitress import serve
from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.enums import ChatMemberStatus, ChatType, MessageEntityType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton as AiogramInlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
    MessageEntity,
    ReplyKeyboardRemove,
)
try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None
    genai_types = None


# ==================================================
# BOT SOZLAMALARI
# ==================================================

# BotFather bergan YANGI tokenni qo‘ying
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN topilmadi. BotFather bergan yangi tokenni "
        "BOT_TOKEN muhit o'zgaruvchisiga kiriting."
    )


# Qabul va tashrif arizalari boradigan Telegram ID
ADMIN_ID = 7338097352
SUPERADMIN_ID = 6907502858
CHANNEL_USERNAME = "@BM_Bekobod"
CHANNEL_URL = "https://t.me/BM_Bekobod"
APPLICATIONS_PATH = Path(__file__).with_name("applications.json")
USERS_PATH = Path(__file__).with_name("users.json")

# Administrator ma’lumotlari
ADMIN_PHONE = "+998 94 835 66 66"
ADMIN_USERNAME = "@bm_qabul"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
gemini_client = (
    genai.Client(api_key=GEMINI_API_KEY)
    if GEMINI_API_KEY and genai
    else None
)


bot = Bot(token=TOKEN)
dp = Dispatcher()
web_app = Flask(__name__)
SERVICE_STATE = {
    "web": "starting",
    "bot": "starting",
    "bot_error": None,
}


@web_app.get("/")
def web_home():
    return """
    <!doctype html>
    <html lang="uz">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Buxoro Maktabi Bot</title>
        <style>
          body { font-family: Arial, sans-serif; background: #f4f7fb; color: #172033;
                 margin: 0; display: grid; min-height: 100vh; place-items: center; }
          main { width: min(620px, calc(100% - 40px)); background: white; padding: 36px;
                 border-radius: 18px; box-shadow: 0 12px 35px #1d35571a; }
          h1 { color: #176b3a; margin-top: 0; } p { line-height: 1.65; }
          .status { display: inline-block; color: #126b36; background: #e8f7ee;
                    padding: 8px 13px; border-radius: 999px; font-weight: 700; }
        </style>
      </head>
      <body><main>
        <div class="status">● Tizim ishlamoqda</div>
        <h1>Buxoro Maktabi Telegram boti</h1>
        <p>Bot orqali maktab haqida ma’lumot olish, qabulga yozilish va
        maktabga tashrif uchun so‘rov qoldirish mumkin.</p>
        <p>Manzil: Bekobod shahri, sobiq Qishloq Qurilish banki binosi.</p>
      </main></body>
    </html>
    """, 200


@web_app.get("/health")
def web_health():
    return jsonify(
        status="ok",
        service="bm-qabul-bot",
        web=SERVICE_STATE["web"],
        bot=SERVICE_STATE["bot"],
        bot_error=SERVICE_STATE["bot_error"],
    ), 200


@web_app.get("/ready")
def web_ready():
    ready = SERVICE_STATE["web"] == "running" and SERVICE_STATE["bot"] == "running"
    return jsonify(
        ready=ready,
        web=SERVICE_STATE["web"],
        bot=SERVICE_STATE["bot"],
    ), 200 if ready else 503


# ==================================================
# TUGMA VA EMOJI DIZAYNI
# Optima Team botidagi dizayn mexanizmi bilan bir xil.
# ==================================================

DESIGN = {
    "button_style": "primary",
    "premium_emoji_id": "",
    "button_designs": {
        "send_phone": {"style": "success", "emoji_id": ""},
        "cancel": {"style": "danger", "emoji_id": ""},
    },
    "message_emojis": {},
    "message_templates": {},
    "target_group_id": 0,
}

DESIGN_PATH = Path(__file__).with_name("design_settings.json")

BUTTON_CATALOG = [
    ("about_school", "🏫 Maktab haqida"),
    ("teachers", "👨‍🏫 Ustozlar"),
    ("directions", "📚 Yo‘nalishlar"),
    ("prices", "💰 Narxlar"),
    ("registration", "📝 Qabulga yozilish"),
    ("visit", "📅 Tashrif buyurish"),
    ("education", "🎓 Ta’lim tizimi"),
    ("schedule", "🍽 Kun tartibi"),
    ("faq", "❓ Savol-javob"),
    ("location", "📍 Manzil"),
    ("contact", "☎️ Bog‘lanish"),
    ("send_phone", "📱 Telefon raqamni kiritish"),
    ("admin", "✈️ Administratorga yozish"),
    ("map", "🗺 Xaritada ko‘rish"),
    ("back", "⬅️ Orqaga qaytish"),
    ("home", "🏠 Bosh menyu"),
    ("cancel", "❌ Bekor qilish"),
    ("group_bot", "🤖 Botga o‘tish"),
    ("group_admin", "👤 Adminga o‘tish"),
    ("ai", "🤖 AI yordamchi"),
    ("kitchen", "🍽 Oshxona"),
    ("classrooms", "🏫 Sinfxonalar"),
]
BUTTON_LABELS = dict(BUTTON_CATALOG)
DESIGN_PAGE_SIZE = 10

MESSAGE_EMOJI_CATALOG = [
    ("education", "Ta’lim", "🎓"),
    ("school", "Maktab", "🏫"),
    ("modern_education", "Zamonaviy ta’lim", "🏆"),
    ("qualified_teachers", "Malakali ustozlar", "👨‍🏫"),
    ("individual_approach", "Individual yondashuv", "📚"),
    ("english", "Ingliz tili", "🇬🇧"),
    ("mathematics", "Matematika", "🧮"),
    ("robotics", "Robototexnika", "🤖"),
    ("meals", "2 mahal issiq ovqat", "🍽"),
    ("work_hours", "08:00–17:00", "🕘"),
    ("application", "Ariza", "📝"),
    ("visit", "Tashrif", "📅"),
    ("success", "Muvaffaqiyat", "✅"),
    ("warning", "Ogohlantirish", "⚠️"),
    ("user", "Foydalanuvchi", "👤"),
    ("phone", "Telefon", "📱"),
    ("child", "Farzand", "🧒"),
    ("age", "Yosh", "🎂"),
    ("time", "Vaqt", "🕒"),
    ("location", "Manzil", "📍"),
    ("contact", "Bog‘lanish", "☎️"),
]
MESSAGE_EMOJI_DEFAULTS = {
    key: fallback for key, _label, fallback in MESSAGE_EMOJI_CATALOG
}

MESSAGE_TEMPLATE_CATALOG = [
    ("welcome", "Bosh sahifa xabari", "🎓 Assalomu alaykum!"),
    ("school_info", "Maktab haqida", "🏫 BUXORO MAKTABI"),
    ("teachers", "Ustozlar", "👨‍🏫 BUXORO MAKTABI USTOZLARI"),
    ("directions", "Yo‘nalishlar", "📚 BUXORO MAKTABI YO‘NALISHLARI"),
    ("prices", "Narxlar", "💰 YANGI O‘QUV YILI UCHUN OYLIK TO‘LOVLAR"),
    ("education", "Ta’lim tizimi", "🎓 BUXORO MAKTABI TA’LIM TIZIMI"),
    ("schedule", "Kun tartibi", "🍽 BUXORO MAKTABI KUN TARTIBI"),
    ("faq", "Savol-javob", "❓ KO‘P SO‘RALADIGAN SAVOLLAR"),
    ("location", "Manzil", "📍 BUXORO MAKTABI MANZILI"),
    ("contact", "Bog‘lanish", "☎️ ADMINISTRATOR BILAN BOG‘LANISH"),
]

TEAM_PAGE_BASE = "https://buxoromaktabibekobod.uz"
TEAM_MEMBERS = [
    {
        "name": "Direktor",
        "role": "Maktab direktori",
        "short": "Rahbar va matematika mutaxassisi",
        "full": "Oliy ma'lumotli rahbar. 7 yillik ish tajribasiga ega, matematika fanidan 5 yil dars bergan. Matematikadan A darajali sertifikat sohibi. 100 dan ortiq o'quvchining TDM va milliy sertifikatlarda yuqori natija qo'lga kiritishiga ko'maklashgan. 2 yil boshqaruv tizimida faoliyat yuritgan.",
        "image": "/Direktor.webp",
    },
    {
        "name": "Akmal To'lkinovich",
        "role": "Direktor o'rinbosari",
        "short": "11 yillik tajriba",
        "full": "Oliy ma'lumotli mutaxassis. 11 yillik ish tajribasiga ega, direktor o'rinbosari lavozimida 4 yil faoliyat yuritgan. O'nlab ustozlarning oliy toifa va milliy sertifikatlarga ega bo'lishiga hissa qo'shgan.",
        "image": "/Akmal-Tolkinovich.webp",
    },
    {
        "name": "Mr. Sherzod",
        "role": "Ingliz tili o'qituvchisi",
        "short": "5 yillik tajriba",
        "full": "5 yillik tajribaga ega ingliz tili o'qituvchisi. O'quvchilarni qisqa vaqt ichida yuqori natijalarga olib chiqishi bilan tanilgan.",
        "image": "/Mr.Sherzod.webp",
    },
    {
        "name": "Faxriyor G'iyosov",
        "role": "Biologiya o'qituvchisi",
        "short": "4 yillik tajribaga ega kuchli o'qituvchi",
        "full": "Biologiya o'qituvchisi. 4 yillik tajribaga ega kuchli mutaxassis. SamDU (Samarqand Davlat universiteti) biologiya fakultetini tamomlagan.",
        "image": "/Faxriyor-Giyosov.webp",
    },
    {
        "name": "Anorkulov Komronbek",
        "role": "Ingliz tili o'qituvchisi",
        "short": "IELTS overall 8.0",
        "full": "IELTS overall 8.0, Reading va Listening bo'limlaridan 8.5 ball olgan. 4 yillik tajribaga ega. O'quvchilari IELTS 7.0 va 7.5 natijalarga erishgan.",
        "image": "/English.webp",
    },
    {
        "name": "Teshayev Feruzbek",
        "role": "Matematika o'qituvchisi",
        "short": "Prezident maktablariga tayyorlov",
        "full": "Oliy ma'lumotli matematika o'qituvchisi. 3 yillik tajribaga ega. Prezident, Al-Xorazmiy va ixtisoslashtirilgan maktablar imtihonlariga tayyorlashda kuchli mutaxassis.",
        "image": "/Teshayev-Feruzbek.webp",
    },
    {
        "name": "Hakimbek G'ulomjonov",
        "role": "Huquq va ingliz tili o'qituvchisi",
        "short": "IELTS 7.0",
        "full": "IELTS 7.0 darajasiga ega huquq va ingliz tili o'qituvchisi. O'quvchilarga huquqiy savodxonlik va ingliz tilini tizimli o'rgatadi.",
        "image": "/LawXuquq.webp",
    },
    {
        "name": "Mamadaliyev Abdulaziz",
        "role": "Jismoniy tarbiya o'qituvchisi",
        "short": "6 yillik tajriba",
        "full": "Sport murabbiyligi bo'yicha sertifikatga ega. 2025-yilda futbol bo'yicha DXX kubogi chempioni, stol tennisi bo'yicha viloyat chempioni. Futbol, stol tennisi, shaxmat va badminton bo'yicha mahoratli murabbiy. 6 yillik tajribaga ega.",
        "image": "/GYM.webp",
    },
    {
        "name": "Xojimuratov Bekzod",
        "role": "Tarix o'qituvchisi",
        "short": "Tarix fanidan A+ darajadagi mutaxassis",
        "full": "Oliy ma'lumotli tarix fani o'qituvchisi. Tarix fanidan milliy sertifikati A+ darajada. Shogirdlarini 100 foiz A va A+ natijalarga olib chiqqan. 6 yillik tajribaga ega.",
        "image": "/History.webp",
    },
    {
        "name": "Qarshiboyev Ma'ruf",
        "role": "Matematika o'qituvchisi",
        "short": "B darajali milliy sertifikat",
        "full": "GulDUni 2023-yilda tamomlagan. 4 yillik tajribaga ega mutaxassis, matematikadan B darajali milliy sertifikat sohibi. 10 ga yaqin o'quvchining OTMga kirishiga yordam bergan.",
        "image": "/Ma'ruf Qarshiboyev.JPG",
    },
    {
        "name": "Haqberdiyev Asadbek",
        "role": "Ona tili o'qituvchisi",
        "short": "A sertifikat va turk tili B2",
        "full": "Oliy ma'lumotli, 2-toifali ona tili o'qituvchisi. 4 yillik tajribaga ega. Ona tilidan A daraja va turk tilidan B2 sertifikat sohibi. 20 dan ortiq o'quvchini turk tili va milliy sertifikat yo'nalishlarida yuqori natijaga olib chiqqan.",
        "image": "/Asadbek-Haqberdiyev.webp",
    },
    {
        "name": "Islom Qahhoraliyev",
        "role": "Fizika va matematika o'qituvchisi",
        "short": "2 fandan sertifikat",
        "full": "Oliy ma'lumotli matematika va fizika o'qituvchisi. Har ikki fandan sertifikatga ega: matematikadan A daraja, fizikadan yuqori natijalarni qo'lga kiritgan. 5 yillik tajribaga ega, 30 dan ortiq o'quvchini yuqori natijaga olib chiqqan.",
        "image": "/Islom Qahhoraliyev.webp",
    },
    {
        "name": "Umarov Zamira",
        "role": "Boshlang'ich sinf ingliz tili o'qituvchisi",
        "short": "IELTS 6.5, rus tili C1",
        "full": "Rossiyada pedagogika yo'nalishida tahsil olgan. IELTS 6.5, rus tili darajasi C1. 3 yillik tajribaga ega, yuzlab o'quvchilarga ustozlik qilgan.",
        "image": "/English 2.webp",
    },
    {
        "name": "Shodmatova Nozima",
        "role": "Boshlang'ich sinf o'qituvchisi",
        "short": "36 yillik tajriba",
        "full": "36 yillik tajribaga ega boshlang'ich sinf ustozi. Minglab o'quvchilarga ta'lim bergan, shogirdlari nufuzli ta'lim muassasalari va ish joylarida faoliyat yuritmoqda.",
        "image": "/Boshlangich1.webp",
    },
    {
        "name": "Mirzayeva Mohidil Abdunaviyevna",
        "role": "Boshlang'ich sinf o'qituvchisi",
        "short": "1-toifali ustoz",
        "full": "Oliy ma'lumotli, 1-toifali boshlang'ich sinf o'qituvchisi. 8 yillik ish tajribasiga ega. O'quvchilari fan olimpiadalarida a'lo natijalarni qayd etgan.",
        "image": "/Boshlangich.webp",
    },
    {
        "name": "Otaboyeva Shaxnoza",
        "role": "Rus tili o'qituvchisi",
        "short": "Rus tilidan C1",
        "full": "Oliy ma'lumotli rus tili o'qituvchisi. Rus tilidan C1 sertifikatiga ega. 7 yillik ish tajribasiga ega, yuzlab o'quvchilarga rus tilini mukammal o'zlashtirishda yordam bergan.",
        "image": "/Rus Tili.webp",
    },
    {
        "name": "Raxmatkulova Saboat Berdikulovna",
        "role": "Oliy toifali boshlang'ich sinf o'qituvchisi",
        "short": "30 yillik tajriba",
        "full": "Oliy ma'lumotli, oliy toifali ustoz. 30 yillik tajribaga ega. O'quvchilari fan olimpiadalarida yuqori natijalar qayd etgan. 4 ta sinfni 1-sinfdan 4-sinfgacha yetaklab ta'lim bergan.",
        "image": "/Boshlangich3.webp",
    },
    {
        "name": "Samijon ustoz",
        "role": "Tarbiya fani o'qituvchisi",
        "short": "Arab va ingliz tillari",
        "full": "Oliy ma'lumotli tarbiya fani o'qituvchisi. Arab va ingliz tillarida erkin muloqot qila oladi. 2017–2021-yillarda O'zbekiston Xalqaro Islom Akademiyasida din sotsiopsixologiyasi yo'nalishida tahsil olgan. 2021–2023-yillarda Mirzo Ulug'bek maktabida, 2023–2025-yillarda Saudiya Arabistonining Makka shahrida faoliyat olib borgan.",
        "image": "/Tarbiya-ustoz.webp",
    },
]

KITCHEN_STAFF = [
    {
        "name": "Mamadaliyeva Ma'mura",
        "role": "Oshxona boshlig'i",
        "full": "Oshxona jarayoni, sifat nazorati va bolalar ovqatlanish tartibiga mas'ul.",
        "image": "/Mamadaliyeva-Mamura.webp",
    },
    {
        "name": "Shoira Rahmatullayevna",
        "role": "Bosh oshpaz",
        "full": "Buxoro Maktabi bosh oshpazi. 33 yillik ish tajribasiga ega malakali oshpaz.",
        "image": "/Shoira-Rahmatullayevna.webp",
    },
    {
        "name": "Saydullayeva Sevara",
        "role": "Bosh qandolatchi",
        "full": "5 yillik tajribaga ega mohir qandolatchi. Hozirda Buxoro Maktabining bosh qandolatchisi.",
        "image": "/Saydullayeva-Sevara.webp",
    },
]

KITCHEN_GALLERIES = [
    {
        "title": "Maktabgacha tayyorlov nonushtasi",
        "subtitle": "Nolavoylar uchun nonushta lavhalari",
        "images": [f"/ovqatlar/nonushta{index}.webp" for index in range(1, 7)],
    },
    {
        "title": "Tushlik",
        "subtitle": "Issiq taom va kunlik tushliklar",
        "images": [
            f"/ovqatlar/obed{index}.webp"
            for index in [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22]
        ],
    },
    {
        "title": "Poldnik",
        "subtitle": "Tushdan keyingi yengil ovqatlar",
        "images": [
            f"/ovqatlar/{name}.webp"
            for name in [
                "Poldnik1", "poldnik2", "poldnik3", "poldnik4", "poldnik5",
                "poldnik6", "poldnik7", "poldnik10", "poldnik11", "poldnik12",
                "poldnik13", "poldnik14", "poldnik15", "poldnik16", "poldnik17",
                "poldnik18", "poldnik19", "poldnik20", "poldnik21", "poldnik22",
                "poldnik23", "poldnik24",
            ]
        ],
    },
]

CLASSROOMS = [
    ("Biologiya xonasi", "Fan xonasi", "Biologiya darslari uchun yorug' va tartibli o'quv muhiti.", "/Sinfxonalar/biologiya-xonasi.webp", "Fan xonasi • Ko'rgazmali dars • Qulay muhit"),
    ("Sinf xonasi", "O'quv xona", "Kunlik dars jarayonlari uchun shinam va yorug' sinf xonasi.", "/Sinfxonalar/img-1997.webp", "Yorug' xona • Partalar • Dars muhiti"),
    ("Kimyo xonasi", "Laboratoriya", "Kimyo fanidan amaliy va nazariy mashg'ulotlar o'tiladigan xona.", "/Sinfxonalar/kimyo-xona.webp", "Kimyo • Amaliy dars • Fan muhiti"),
    ("Kimyo laboratoriyasi", "Laboratoriya", "Kimyo darslari uchun jihozlangan qo'shimcha o'quv muhiti.", "/Sinfxonalar/kimyo-xona-2.webp", "Laboratoriya • Tajriba • Nazorat"),
    ("Maktabgacha tayyorlov yotoqxonasi", "Dam olish xonasi", "Maktabgacha tayyorlov bolalari uchun qulay dam olish xonasi.", "/Sinfxonalar/maktabgacha-tayyorlov-yotoqxonasi.webp", "Yotoqxona • Qulaylik • Tartib"),
    ("Kichiklar dam olish xonasi", "Dam olish xonasi", "Kichik yoshdagi bolalar uchun toza va osoyishta dam olish muhiti.", "/Sinfxonalar/maktabgacha-tayyorlov-yotoqxona-2.webp", "Dam olish • Tozalik • Nazorat"),
    ("Maktabgacha tayyorlov xonasi", "Tayyorlov", "Maktabga tayyorlov mashg'ulotlari o'tiladigan maxsus xona.", "/Sinfxonalar/maktabgacha-tayyorlovxonasi.webp", "Tayyorlov • Mashg'ulot • Bolalar muhiti"),
    ("Oshxona", "Ovqatlanish", "O'quvchilar uchun toza va tartibli ovqatlanish hududi.", "/Sinfxonalar/oshxona.webp", "Tozalik • Ovqatlanish • Keng xona"),
    ("Ovqatlanish zali", "Ovqatlanish", "Kunlik nonushta, tushlik va poldnik uchun xizmat qiladigan oshxona.", "/Sinfxonalar/oshxona-2.webp", "Sifat • Tartib • Gigiyena"),
    ("Oshxona hududi", "Ovqatlanish", "Bolalar ovqatlanishi uchun qulay joylashtirilgan oshxona hududi.", "/Sinfxonalar/oshxona-3.webp", "Qulaylik • Kundalik taom • Nazorat"),
    ("Sog'lom ovqatlanish zali", "Ovqatlanish", "Sog'lom ovqatlanish tartibi yo'lga qo'yilgan oshxona ko'rinishi.", "/Sinfxonalar/oshxona-4.webp", "Sog'lom taom • Tartib • Jamoa"),
    ("Shinam ovqatlanish muhiti", "Ovqatlanish", "O'quvchilar ovqatlanishi uchun toza va shinam muhit.", "/Sinfxonalar/oshxona-5.webp", "Shinam • Toza • Keng"),
    ("Maktab oshxonasi", "Ovqatlanish", "Maktab oshxonasi kunlik xizmatga mos tarzda tashkil qilingan.", "/Sinfxonalar/oshxona-6.webp", "Kunlik xizmat • Sifat • Gigiyena"),
    ("Sinfxona", "O'quv xona", "Ta'lim jarayoni uchun qulay va tartibli sinf xonasi.", "/Sinfxonalar/sinfxona.webp", "Dars • Partalar • Yorug'lik"),
    ("Zamonaviy sinfxona", "O'quv xona", "Zamonaviy ta'lim jarayonlariga moslashtirilgan xona.", "/Sinfxonalar/sinfxona-2.webp", "Ta'lim • Qulaylik • Tartib"),
    ("Yorug' o'quv xonasi", "O'quv xona", "O'quvchilar uchun diqqatni jamlashga qulay muhit.", "/Sinfxonalar/sinfxona-3.webp", "O'quv muhiti • Yorug'lik • Sokinlik"),
    ("Fan mashg'ulotlari xonasi", "O'quv xona", "Fan mashg'ulotlari uchun shinam va tayyor sinf xonasi.", "/Sinfxonalar/sinfxona-4.webp", "Fan darsi • Jihoz • Qulay xona"),
    ("Stol tennisi zali", "Sport", "O'quvchilarning sport mashg'ulotlari uchun ajratilgan zal.", "/Sinfxonalar/stoltennis-zali.webp", "Sport • Stol tennisi • Faollik"),
    ("Faol tanaffus hududi", "Sport", "Stol tennisi va faol tanaffuslar uchun qulay sport hududi.", "/Sinfxonalar/stoltennis-zali-2.webp", "Mashg'ulot • Sport zali • Harakat"),
    ("Tibbiyotxona", "Sog'liq nazorati", "O'quvchilar salomatligini nazorat qilish uchun tibbiyot xonasi.", "/Sinfxonalar/tibbiyotxona.webp", "Tibbiyot • Nazorat • Xavfsizlik"),
]


def load_design_settings():
    if not DESIGN_PATH.exists():
        return
    try:
        stored = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    for key in ("button_style", "premium_emoji_id", "target_group_id"):
        if key in stored:
            DESIGN[key] = stored[key]
    for key in ("button_designs", "message_emojis", "message_templates"):
        if isinstance(stored.get(key), dict):
            DESIGN[key].update(stored[key])


def save_design_settings():
    temporary_path = DESIGN_PATH.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(DESIGN, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary_path, DESIGN_PATH)


load_design_settings()


def infer_button_key(text: str):
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    icon, separator, without_icon = clean.partition(" ")
    clean_plain = (
        without_icon
        if separator and icon and not icon[0].isalnum()
        else clean
    )

    for key, label in BUTTON_CATALOG:
        label_icon, label_separator, label_without_icon = label.partition(" ")
        label_plain = (
            label_without_icon
            if label_separator and label_icon and not label_icon[0].isalnum()
            else label
        )
        if clean == label or clean.startswith(label + " ") or clean_plain == label_plain:
            return key

    if clean.startswith("⬅️"):
        return "back"
    if clean.startswith("🏠"):
        return "home"
    if clean.startswith("❌"):
        return "cancel"
    return None


def button_appearance(text: str, design_key=None):
    key = design_key or infer_button_key(text)
    custom = DESIGN["button_designs"].get(key, {}) if key else {}
    style = custom.get("style", DESIGN["button_style"])
    emoji_id = custom.get("emoji_id", DESIGN["premium_emoji_id"])
    return (None if style == "default" else style or None), emoji_id or None


def button_label(text: str, emoji_id):
    if not emoji_id:
        return text
    _icon, separator, label = str(text).partition(" ")
    return label if separator and label else text


def button_texts(label: str):
    _icon, separator, plain_label = label.partition(" ")
    return {label, plain_label} if separator else {label}


def InlineKeyboardButton(**kwargs):
    design_key = kwargs.pop("design_key", None)
    style, emoji_id = button_appearance(kwargs.get("text", ""), design_key)
    kwargs["text"] = button_label(kwargs.get("text", ""), emoji_id)
    kwargs["style"] = style
    kwargs["icon_custom_emoji_id"] = emoji_id
    return AiogramInlineKeyboardButton(**kwargs)


def utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def custom_emoji_id_from_message(message: Message):
    entities = tuple(message.entities or ()) + tuple(message.caption_entities or ())
    custom_ids = [
        str(entity.custom_emoji_id)
        for entity in entities
        if entity.type == MessageEntityType.CUSTOM_EMOJI and entity.custom_emoji_id
    ]
    if len(custom_ids) == 1:
        return custom_ids[0]

    raw_text = (message.text or message.caption or "").strip()
    if re.fullmatch(r"\d{10,24}", raw_text):
        return raw_text
    return None


async def custom_emoji_id_is_valid(custom_emoji_id: str) -> bool:
    try:
        stickers = await bot.get_custom_emoji_stickers(
            custom_emoji_ids=[str(custom_emoji_id)]
        )
    except TelegramBadRequest:
        return False
    return bool(stickers)


def apply_message_emoji_design(text: str):
    configured = DESIGN.get("message_emojis", {})
    replacements = {
        fallback: configured.get(key, {})
        for key, _label, fallback in MESSAGE_EMOJI_CATALOG
        if configured.get(key)
    }
    if not replacements:
        return text, []

    pattern = re.compile("|".join(map(re.escape, replacements)))
    chunks = []
    entities = []
    source_position = 0
    output_position = 0

    for match in pattern.finditer(text):
        prefix = text[source_position:match.start()]
        chunks.append(prefix)
        output_position += utf16_length(prefix)

        config = replacements[match.group(0)]
        replacement = str(config.get("text") or match.group(0))
        chunks.append(replacement)
        replacement_length = utf16_length(replacement)
        custom_id = config.get("custom_id")
        if custom_id:
            entities.append(MessageEntity(
                type=MessageEntityType.CUSTOM_EMOJI,
                offset=output_position,
                length=replacement_length,
                custom_emoji_id=str(custom_id),
            ))
        output_position += replacement_length
        source_position = match.end()

    chunks.append(text[source_position:])
    return "".join(chunks), entities


class DesignMessageMiddleware(BaseRequestMiddleware):
    async def __call__(self, make_request, bot_instance, method):
        text = getattr(method, "text", None)
        text_field = "text"
        entities_field = "entities"
        if not isinstance(text, str):
            text = getattr(method, "caption", None)
            text_field = "caption"
            entities_field = "caption_entities"
        if not isinstance(text, str):
            return await make_request(bot_instance, method)
        existing_entities = getattr(method, entities_field, None)

        if text_field == "text":
            for key, _label, prefix in MESSAGE_TEMPLATE_CATALOG:
                custom_text = DESIGN.get("message_templates", {}).get(key)
                if custom_text and text.startswith(prefix):
                    text = str(custom_text)
                    setattr(method, text_field, text)
                    existing_entities = None
                    setattr(method, entities_field, None)
                    break

        if existing_entities:
            return await make_request(bot_instance, method)

        text, entities = apply_message_emoji_design(text)
        setattr(method, text_field, text)
        if entities:
            setattr(method, entities_field, entities)
        return await make_request(bot_instance, method)


bot.session.middleware(DesignMessageMiddleware())


async def user_is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
    except Exception as error:
        print(f"Obunani tekshirishda xato: {error}")
        return False
    if member.status in {
        ChatMemberStatus.CREATOR,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.MEMBER,
    }:
        return True
    return bool(
        member.status == ChatMemberStatus.RESTRICTED
        and getattr(member, "is_member", False)
    )


class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        chat = getattr(event, "chat", None)
        if isinstance(event, CallbackQuery):
            chat = getattr(getattr(event, "message", None), "chat", None)
        if chat and chat.type != ChatType.PRIVATE:
            return await handler(event, data)
        user = getattr(event, "from_user", None)
        callback_data = getattr(event, "data", "")
        if not user or callback_data == "subscription:check":
            return await handler(event, data)
        if await user_is_subscribed(user.id):
            return await handler(event, data)
        text = (
            "🔒 Botdan foydalanish uchun avval BM Bekobod "
            "kanaliga obuna bo‘ling, so‘ng ‘Tekshirish’ni bosing."
        )
        if isinstance(event, CallbackQuery):
            await event.answer("Avval kanalga obuna bo‘ling", show_alert=True)
            await event.message.answer(text, reply_markup=subscription_keyboard())
        else:
            await event.answer(text, reply_markup=subscription_keyboard())
        return None


class GroupSilenceMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        chat = getattr(event, "chat", None)
        if isinstance(event, CallbackQuery):
            chat = getattr(getattr(event, "message", None), "chat", None)
        if not chat or chat.type == ChatType.PRIVATE:
            return await handler(event, data)
        text = getattr(event, "text", "") or ""
        user = getattr(event, "from_user", None)
        command = text.split(maxsplit=1)[0].split("@", 1)[0].lower()
        if isinstance(event, Message) and command == "/setgroup" and user and user.id == SUPERADMIN_ID:
            return await handler(event, data)
        return None


dp.message.outer_middleware(GroupSilenceMiddleware())
dp.callback_query.outer_middleware(GroupSilenceMiddleware())
dp.message.outer_middleware(SubscriptionMiddleware())
dp.callback_query.outer_middleware(SubscriptionMiddleware())


# ==================================================
# ASOSIY MENYU
# ==================================================

admin_button = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✈️ Administratorga yozish",
                url="https://t.me/bm_qabul",
            )
        ]
    ]
)


location_button = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🗺 Xaritada ko‘rish",
                url=(
                    "https://www.google.com/maps/search/"
                    "?api=1&query=Bekobod+Qishloq+Qurilish+banki"
                ),
            )
        ]
    ]
)


def refresh_keyboards():
    global main_menu, cancel_menu, back_cancel_menu, phone_menu
    global admin_button, location_button

    main_menu = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏫 Maktab haqida", callback_data="menu:about_school"), InlineKeyboardButton(text="👨‍🏫 Ustozlar", callback_data="menu:teachers")],
            [InlineKeyboardButton(text="📚 Yo‘nalishlar", callback_data="menu:directions"), InlineKeyboardButton(text="💰 Narxlar", callback_data="menu:prices")],
            [InlineKeyboardButton(text="📝 Qabulga yozilish", callback_data="menu:registration"), InlineKeyboardButton(text="📅 Tashrif buyurish", callback_data="menu:visit")],
            [InlineKeyboardButton(text="🎓 Ta’lim tizimi", callback_data="menu:education"), InlineKeyboardButton(text="🍽 Kun tartibi", callback_data="menu:schedule")],
            [InlineKeyboardButton(text="❓ Savol-javob", callback_data="menu:faq"), InlineKeyboardButton(text="📍 Manzil", callback_data="menu:location")],
            [InlineKeyboardButton(text="☎️ Bog‘lanish", callback_data="menu:contact")],
            [InlineKeyboardButton(text="🍽 Oshxona", callback_data="menu:kitchen")],
            [InlineKeyboardButton(text="🏫 Sinfxonalar", callback_data="menu:classrooms")],
            [InlineKeyboardButton(text="🤖 AI yordamchi", callback_data="menu:ai")],
        ],
    )
    cancel_menu = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="nav:home")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="nav:cancel")],
        ],
    )
    back_cancel_menu = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Orqaga qaytish", callback_data="nav:back"), InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="nav:home")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="nav:cancel")],
        ],
    )
    phone_menu = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📱 Telefon raqamni kiritish", callback_data="nav:phone_hint", design_key="send_phone")],
            [InlineKeyboardButton(text="⬅️ Orqaga qaytish", callback_data="nav:back"), InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="nav:home")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="nav:cancel")],
        ],
    )
    admin_button = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(
            text="✈️ Administratorga yozish",
            url="https://t.me/bm_qabul",
        )]],
    )
    location_button = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(
            text="🗺 Xaritada ko‘rish",
            url=(
                "https://www.google.com/maps/search/"
                "?api=1&query=Bekobod+Qishloq+Qurilish+banki"
            ),
        )]],
    )


refresh_keyboards()


def info_back_button(existing_markup=None):
    rows = []
    if existing_markup:
        rows.extend(existing_markup.inline_keyboard)
    _style, emoji_id = button_appearance("⬅️ Orqaga qaytish", "back")
    rows.append([
        AiogramInlineKeyboardButton(
            text=button_label("⬅️ Orqaga qaytish", emoji_id),
            callback_data="nav:home",
            style="success",
            icon_custom_emoji_id=emoji_id,
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscription_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [AiogramInlineKeyboardButton(
            text="📢 BM Bekobod kanaliga obuna bo‘lish",
            url=CHANNEL_URL,
            style="primary",
        )],
        [AiogramInlineKeyboardButton(
            text="✅ Obunani tekshirish",
            callback_data="subscription:check",
            style="success",
        )],
    ])


# ==================================================
# QABUL FORMASI HOLATLARI
# ==================================================

class RegistrationForm(StatesGroup):
    parent_name = State()
    phone = State()
    child_name = State()
    child_age = State()
    child_class = State()


# ==================================================
# TASHRIF FORMASI HOLATLARI
# ==================================================

class VisitForm(StatesGroup):
    parent_name = State()
    phone = State()
    visit_day = State()
    visit_time = State()


class DesignForm(StatesGroup):
    emoji_id = State()
    preview = State()


class MessageEmojiForm(StatesGroup):
    value = State()
    preview = State()


class MessageTemplateForm(StatesGroup):
    value = State()


class GroupPostForm(StatesGroup):
    text = State()
    caption = State()


class AIAssistantForm(StatesGroup):
    question = State()


AI_HISTORY = {}
AI_SYSTEM_PROMPT = """Siz Buxoro Maktabi Bekobod Telegram botining yordamchisisiz.
Foydalanuvchi qaysi tilda yozsa, o‘sha tilda javob bering: o‘zbekcha yoki ruscha.
Maktab haqida faqat botdagi ma’lum va tasdiqlangan ma’lumotlardan foydalaning.
Maktab kurslari haqida so‘ralsa, kurs narxi 400 000 so‘m ekanini ayting va batafsil ma’lumot uchun administratorga yo‘naltiring.
Savolga javob topa olmasangiz, taxmin qilmang; administratorga murojaat qilishni tavsiya qiling.
Javoblarni muloyim, to‘liq va tushunarli yozing. Kerak bo‘lsa sarlavha, punktlar va bosqichlardan foydalaning.
Ota-onaga muhim ma’lumotlarni to‘liq tushuntiring: narx, vaqt, manzil, qabul tartibi va keyingi qadamni alohida ko‘rsating.
Javobni odatda 3–8 ta mazmunli gap yoki punkt bilan bering; savol oddiy bo‘lsa, ortiqcha cho‘zmay javob bering.
Har bir javob oxirida kerak bo‘lsa administrator bilan bog‘lanish yo‘lini ko‘rsating.

Administrator: @bm_qabul, telefon: +998 94 835 66 66.
Maktab: Bekobod shahridagi Buxoro Maktabi, 1–11-sinflar, matematika va ingliz tili yo‘nalishlari, qabul va tashrif bot orqali amalga oshiriladi.
Maktabda malakali ustozlar, 08:00–17:00 ta’lim va 2 mahal issiq ovqat mavjud.
Oshxona bo‘yicha: Mamadaliyeva Ma’mura — oshxona boshlig‘i; Shoira Rahmatullayevna — bosh oshpaz, 33 yillik tajriba; Saydullayeva Sevara — bosh qandolatchi, 5 yillik tajriba.
"""
AI_SYSTEM_PROMPT += (
    "\nBotdagi narxlar: 0-sinf — 1 200 000 so‘m; 1–3-sinflar — 1 900 000 so‘m; "
    "4–11-sinflar — 2 000 000 so‘m.\n"
    "Ustozlar ro‘yxati: "
    + "; ".join(f"{item['name']} — {item['role']}" for item in TEAM_MEMBERS)
    + ".\n"
    "Oshxona galereyalari: nonushta, tushlik va poldnik.\n"
)


ALBUM_BUFFERS = {}
ALBUM_TASKS = {}
ALBUM_LOCK = asyncio.Lock()
ALBUM_COLLECT_DELAY = 1.0


# ==================================================
# YORDAMCHI FUNKSIYALAR
# ==================================================

def get_uzbekistan_time() -> str:
    uzbekistan_timezone = timezone(timedelta(hours=5))
    now = datetime.now(uzbekistan_timezone)

    return now.strftime("%d.%m.%Y | %H:%M")


def load_applications():
    if not APPLICATIONS_PATH.exists():
        return []
    try:
        data = json.loads(APPLICATIONS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_applications(applications):
    temporary_path = APPLICATIONS_PATH.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(applications, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary_path, APPLICATIONS_PATH)


def load_users():
    if not USERS_PATH.exists():
        return []
    try:
        data = json.loads(USERS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_users(users):
    temporary_path = USERS_PATH.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(users, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary_path, USERS_PATH)


def remember_user(user):
    users = load_users()
    now = get_uzbekistan_time()
    existing = next((item for item in users if item.get("telegram_id") == user.id), None)
    if existing:
        existing.update(
            full_name=user.full_name,
            username=user.username or "",
            last_seen=now,
        )
    else:
        users.append({
            "telegram_id": user.id,
            "full_name": user.full_name,
            "username": user.username or "",
            "first_seen": now,
            "last_seen": now,
        })
    save_users(users)


def statistics_text():
    users = load_users()
    applications = load_applications()
    known_ids = {
        item.get("telegram_id")
        for item in users
        if item.get("telegram_id")
    }
    known_ids.update(
        item.get("telegram_id")
        for item in applications
        if item.get("telegram_id")
    )
    return (
        "📊 BOT STATISTIKASI\n\n"
        f"👥 Botdan foydalangan jami odamlar: {len(known_ids)} ta\n"
        f"📝 Jami arizalar: {len(applications)} ta\n"
        f"🤖 AI suhbatlari: {len(AI_HISTORY)} ta"
    )


def remember_application(application_type: str, message: Message, data: dict):
    applications = load_applications()
    next_id = max((int(item.get("id", 0)) for item in applications), default=0) + 1
    applications.append({
        "id": next_id,
        "type": application_type,
        "created_at": get_uzbekistan_time(),
        "telegram_id": message.from_user.id,
        "telegram_name": message.from_user.full_name,
        "username": message.from_user.username or "",
        **data,
    })
    save_applications(applications)
    return next_id


def get_telegram_information(message: Message) -> str:
    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else "Username mavjud emas"
    )

    return (
        f"👤 Telegram nomi: {message.from_user.full_name}\n"
        f"🔗 Username: {username}\n"
        f"🆔 Telegram ID: {message.from_user.id}"
    )


async def cancel_process(message: Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "❌ Jarayon bekor qilindi.\n\n"
        "Quyidagi menyudan kerakli bo‘limni tanlang:",
        reply_markup=main_menu,
    )


# ==================================================
# START
# ==================================================

@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    remember_user(message.from_user)
    await state.clear()

    await message.answer(
        "Menyu yangilandi.",
        reply_markup=ReplyKeyboardRemove(),
    )

    await message.answer(
        "🎓 Assalomu alaykum!\n\n"
        "Buxoro Maktabining rasmiy Telegram botiga "
        "xush kelibsiz!\n\n"
        "Buxoro Maktabi — Bekobod shahridagi zamonaviy, "
        "sifatli va natijaga yo‘naltirilgan xususiy maktab.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "🏆 Zamonaviy ta’lim\n"
        "👨‍🏫 Malakali ustozlar\n"
        "📚 Individual yondashuv\n"
        "🇬🇧 Ingliz tili\n"
        "🧮 Matematika\n"
        "🤖 Robototexnika\n"
        "🍽 2 mahal issiq ovqat\n"
        "🕘 08:00 dan 17:00 gacha\n"
        "━━━━━━━━━━━━━━━\n\n"
        "Farzandingiz uchun kerakli bo‘limni tanlang:",
        reply_markup=main_menu,
    )

    if message.from_user.id == SUPERADMIN_ID:
        await send_superadmin_panel(message, message.from_user.id)


# ==================================================
# NAVIGATSIYA VA BEKOR QILISH
# ==================================================

@dp.message(F.text.in_(button_texts("🏠 Bosh menyu")))
async def home_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🏠 Bosh menyu ochildi. Kerakli bo‘limni tanlang:",
        reply_markup=main_menu,
    )

@dp.message(F.text.in_(button_texts("❌ Bekor qilish")))
async def cancel_handler(message: Message, state: FSMContext):
    await cancel_process(message, state)


# ==================================================
# MAKTAB HAQIDA
# ==================================================

@dp.message(F.text.in_(button_texts("🏫 Maktab haqida")))
async def school_info(message: Message):
    await message.answer(
        "🏫 BUXORO MAKTABI\n\n"
        "Buxoro Maktabi — Bekobod shahrida faoliyat "
        "yuritayotgan zamonaviy xususiy maktab.\n\n"
        "Maktabimizning asosiy maqsadi — har bir "
        "o‘quvchiga sifatli ta’lim berish, uning "
        "qobiliyatini aniqlash va kelajakka puxta "
        "tayyorlash.\n\n"
        "✅ Malakali va tajribali ustozlar\n"
        "✅ Milliy va xalqaro sertifikatlarga tayyorlash\n"
        "✅ Zamonaviy va interfaol darslar\n"
        "✅ Har bir o‘quvchiga individual yondashuv\n"
        "✅ Ota-onalar bilan doimiy aloqa\n"
        "✅ O‘quvchilar natijasini doimiy nazorat qilish\n"
        "✅ Ingliz tili va matematika chuqurlashtirilgan\n"
        "✅ Robototexnika va mental arifmetika\n"
        "✅ Sport va qo‘shimcha mashg‘ulotlar\n"
        "✅ 2 mahal issiq ovqat\n"
        "✅ 08:00 dan 17:00 gacha ta’lim\n\n"
        "🎓 Buxoro Maktabi — farzandingiz kelajagi "
        "uchun ishonchli tanlov!",
        reply_markup=info_back_button(),
    )


# ==================================================
# USTOZLAR
# ==================================================

def teachers_intro_text():
    return (
        "👨‍🏫 BUXORO MAKTABI JAMOASI\n\n"
        "Saytdagi jamoamiz bilan tanishing. Kerakli ustozni tanlasangiz, "
        "uning rasmi va batafsil ma'lumotlari chiqadi."
    )


def styled_new_button(text, callback_data, design_key=None):
    return InlineKeyboardButton(
        text=text,
        callback_data=callback_data,
        design_key=design_key,
    )


def teachers_keyboard():
    buttons = [
        styled_new_button(
            text=f"{index + 1}. {member['name']}",
            callback_data=f"teacher:{index}",
        )
        for index, member in enumerate(TEAM_MEMBERS)
    ]
    rows = [buttons[index:index + 2] for index in range(0, len(buttons), 2)]
    rows.append([styled_new_button("🏠 Bosh menyu", "nav:home", "home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def teacher_detail_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [styled_new_button("⬅️ Orqaga qaytish", "teachers:list", "back")],
        [styled_new_button("🏠 Bosh menyu", "nav:home", "home")],
    ])


@dp.message(F.text.in_(button_texts("👨‍🏫 Ustozlar")))
async def teachers(message: Message):
    await message.answer(teachers_intro_text(), reply_markup=teachers_keyboard())


@dp.message(F.text.in_(button_texts("🤖 AI yordamchi")))
async def ai_start(message: Message, state: FSMContext):
    await state.set_state(AIAssistantForm.question)
    if not gemini_client:
        return await message.answer(
            "AI yordamchi hali ulanmagan. Administratorga murojaat qiling.",
            reply_markup=info_back_button(),
        )
    await message.answer(
        "🤖 Savolingizni yozing. Men maktab, qabul, narxlar va ustozlar haqida yordam beraman.\n\n"
        "Kurslar bo‘yicha batafsil ma’lumot uchun administratorga yo‘naltiraman.\n"
        "Bekor qilish uchun /cancel yuboring.",
        reply_markup=info_back_button(),
    )


@dp.message(AIAssistantForm.question, Command("cancel"))
async def ai_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("AI yordamchi yopildi.", reply_markup=main_menu)


@dp.message(AIAssistantForm.question)
async def ai_question(message: Message, state: FSMContext):
    if not gemini_client:
        await state.clear()
        return await message.answer(
            "AI yordamchi hozircha sozlanmagan. Administrator: @bm_qabul",
            reply_markup=main_menu,
        )
    question = (message.text or "").strip()
    if not question:
        return await message.answer("Iltimos, savolingizni matn ko‘rinishida yuboring.")

    user_id = message.from_user.id
    history = AI_HISTORY.setdefault(user_id, [])
    history.append({"role": "user", "content": question})
    history[:] = history[-8:]
    try:
        contents = [
            {
                "role": "model" if item["role"] == "assistant" else "user",
                "parts": [{"text": item["content"]}],
            }
            for item in history
        ]
        response = await asyncio.to_thread(
            gemini_client.models.generate_content,
            model=GEMINI_MODEL,
            contents=contents,
            config=genai_types.GenerateContentConfig(
                system_instruction=AI_SYSTEM_PROMPT,
                max_output_tokens=900,
                temperature=0.35,
            ),
        )
        answer = (response.text or "").strip()
    except Exception as error:
        print(f"AI javobida xato: {error}", flush=True)
        answer = "Savolga javob berishda xatolik yuz berdi. Administratorga murojaat qiling: @bm_qabul"
    if not answer:
        answer = "Bu savol bo‘yicha administratorga murojaat qiling: @bm_qabul"
    history.append({"role": "assistant", "content": answer})
    history[:] = history[-8:]
    await message.answer(answer, reply_markup=info_back_button())


def kitchen_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [styled_new_button("👩‍🍳 Oshxona jamoasi", "kitchen:staff:list")],
        [styled_new_button("🥣 Nonushta galereyasi", "kitchen:gallery:0:0")],
        [styled_new_button("🍲 Tushlik galereyasi", "kitchen:gallery:1:0")],
        [styled_new_button("🍪 Poldnik galereyasi", "kitchen:gallery:2:0")],
        [styled_new_button("⬅️ Orqaga qaytish", "nav:home", "back")],
    ])


def kitchen_staff_keyboard():
    rows = [[styled_new_button(
        text=f"{index + 1}. {member['name']}",
        callback_data=f"kitchen:staff:{index}",
    )] for index, member in enumerate(KITCHEN_STAFF)]
    rows.append([styled_new_button("⬅️ Oshxona bo‘limiga", "kitchen:menu", "back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kitchen_detail_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [styled_new_button("⬅️ Orqaga qaytish", "kitchen:staff:list", "back")],
        [styled_new_button("🍽 Oshxona bo‘limi", "kitchen:menu")],
    ])


def kitchen_gallery_keyboard(gallery_index, page, total_pages):
    rows = []
    navigation = []
    if total_pages > 1:
        previous = (page - 1) % total_pages
        next_page = (page + 1) % total_pages
        navigation.extend([
            styled_new_button("⬅️", f"kitchen:gallery:{gallery_index}:{previous}", "back"),
            styled_new_button(f"{page + 1}/{total_pages}", "noop"),
            styled_new_button("➡️", f"kitchen:gallery:{gallery_index}:{next_page}"),
        ])
        rows.append(navigation)
    rows.append([styled_new_button("⬅️ Oshxona bo‘limiga", "kitchen:menu", "back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(F.text.in_(button_texts("🍽 Oshxona")))
async def kitchen(message: Message):
    await message.answer(
        "🍽 BUXORO MAKTABI OSHXONASI\n\n"
        "Sog‘lom va mazali taomlar o‘quvchilarimizning energiyasi va diqqat-e’tibori garovidir.\n\n"
        "Oshxona jamoasi va taomlar galereyasini tanlang:",
        reply_markup=kitchen_menu_keyboard(),
    )


@dp.callback_query(F.data == "kitchen:menu")
async def kitchen_menu_callback(call: CallbackQuery):
    await call.message.answer(
        "🍽 Oshxona bo‘limi. Kerakli bo‘limni tanlang:",
        reply_markup=kitchen_menu_keyboard(),
    )
    await call.answer()


@dp.callback_query(F.data == "kitchen:staff:list")
async def kitchen_staff_list(call: CallbackQuery):
    await call.message.answer(
        "👩‍🍳 OSHXONA JAMOASI\n\nOshxona xodimlari haqida ma’lumot olish uchun ismni tanlang:",
        reply_markup=kitchen_staff_keyboard(),
    )
    await call.answer()


@dp.callback_query(F.data.startswith("kitchen:staff:"))
async def kitchen_staff_detail(call: CallbackQuery):
    try:
        index = int(call.data.rsplit(":", 1)[1])
        member = KITCHEN_STAFF[index]
    except (ValueError, IndexError):
        return await call.answer("Oshxona xodimi topilmadi", show_alert=True)
    image_url = TEAM_PAGE_BASE + quote(member["image"], safe="/")
    caption = f"👩‍🍳 {member['name']}\n📚 {member['role']}\n\n{member['full']}"
    try:
        await call.message.answer_photo(
            photo=image_url,
            caption=caption,
            reply_markup=kitchen_detail_keyboard(),
        )
    except Exception as error:
        print(f"Oshxona xodimi rasmi yuborilmadi: {error}", flush=True)
        await call.message.answer(caption, reply_markup=kitchen_detail_keyboard())
    await call.answer()


@dp.callback_query(F.data.startswith("kitchen:gallery:"))
async def kitchen_gallery(call: CallbackQuery):
    try:
        parts = call.data.split(":")
        gallery_index = int(parts[2])
        page = int(parts[3])
        gallery = KITCHEN_GALLERIES[gallery_index]
    except (ValueError, IndexError):
        return await call.answer("Galereya topilmadi", show_alert=True)
    page_size = 10
    total_pages = max(1, (len(gallery["images"]) + page_size - 1) // page_size)
    page %= total_pages
    images = gallery["images"][page * page_size:(page + 1) * page_size]
    media = [InputMediaPhoto(media=TEAM_PAGE_BASE + quote(path, safe="/")) for path in images]
    try:
        await bot.send_media_group(
            chat_id=call.message.chat.id,
            media=media,
        )
        await call.message.answer(
            f"🍽 {gallery['title']}\n{gallery['subtitle']}",
            reply_markup=kitchen_gallery_keyboard(gallery_index, page, total_pages),
        )
    except Exception as error:
        print(f"Oshxona galereyasi yuborilmadi: {error}", flush=True)
        await call.answer("Galereyani yuborishda xatolik yuz berdi", show_alert=True)
        return
    await call.answer()


# ==================================================
# YO‘NALISHLAR
# ==================================================

def classrooms_keyboard():
    buttons = [
        styled_new_button(
            text=f"{index + 1}. {classroom[0]}",
            callback_data=f"classroom:{index}",
        )
        for index, classroom in enumerate(CLASSROOMS)
    ]
    rows = [buttons[index:index + 2] for index in range(0, len(buttons), 2)]
    rows.append([styled_new_button("⬅️ Orqaga qaytish", "nav:home", "back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def classroom_detail_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [styled_new_button("⬅️ Orqaga qaytish", "classrooms:list", "back")],
        [styled_new_button("🏠 Bosh menyu", "nav:home", "home")],
    ])


@dp.message(F.text.in_(button_texts("🏫 Sinfxonalar")))
async def classrooms(message: Message):
    await message.answer(
        "🏫 BUXORO MAKTABI SINFXONALARI\n\n"
        "Har bir xona zamonaviy ta'lim, qulaylik va xavfsizlik talablariga mos tashkil qilingan. "
        "Kerakli xonani tanlab, rasmi va ma'lumotlarini ko'ring:",
        reply_markup=classrooms_keyboard(),
    )


@dp.callback_query(F.data == "classrooms:list")
async def classrooms_list_callback(call: CallbackQuery):
    await call.message.answer(
        "🏫 SINFXONALAR RO'YXATI",
        reply_markup=classrooms_keyboard(),
    )
    await call.answer()


@dp.callback_query(F.data.startswith("classroom:"))
async def classroom_detail_callback(call: CallbackQuery):
    try:
        index = int(call.data.rsplit(":", 1)[1])
        name, room_type, description, image, features = CLASSROOMS[index]
    except (ValueError, IndexError):
        return await call.answer("Sinfxona ma'lumoti topilmadi", show_alert=True)
    image_url = TEAM_PAGE_BASE + quote(image, safe="/")
    caption = (
        f"🏫 {name}\n"
        f"📚 Turi: {room_type}\n\n"
        f"{description}\n\n"
        f"✅ {features.replace(' • ', chr(10) + '✅ ')}"
    )
    try:
        await call.message.answer_photo(
            photo=image_url,
            caption=caption,
            reply_markup=classroom_detail_keyboard(),
        )
    except Exception as error:
        print(f"Sinfxona rasmi yuborilmadi: {error}", flush=True)
        await call.message.answer(caption, reply_markup=classroom_detail_keyboard())
    await call.answer()


@dp.message(F.text.in_(button_texts("📚 Yo‘nalishlar")))
async def directions(message: Message):
    await message.answer(
        "📚 BUXORO MAKTABI YO‘NALISHLARI\n\n"
        "🧮 Matematika\n"
        "🇬🇧 Ingliz tili\n"
        "🧪 Biologiya\n"
        "⚛️ Fizika\n"
        "📖 Ona tili va adabiyot\n"
        "🌍 Tarix\n"
        "⚖️ Huquq\n"
        "🤖 Robototexnika\n"
        "🧠 Mental arifmetika\n"
        "♟ Shaxmat va shashka\n"
        "⚽ Futbol va sport mashg‘ulotlari\n\n"
        "O‘quvchilar uchun qo‘shimcha kurslar, "
        "to‘garaklar va amaliy mashg‘ulotlar ham mavjud.",
        reply_markup=info_back_button(),
    )


# ==================================================
# NARXLAR
# ==================================================

@dp.message(F.text.in_(button_texts("💰 Narxlar")))
async def prices(message: Message):
    await message.answer(
        "💰 YANGI O‘QUV YILI UCHUN OYLIK TO‘LOVLAR\n\n"
        "🎒 0-sinf — 1 200 000 so‘m\n"
        "📘 1–3-sinflar — 1 900 000 so‘m\n"
        "📗 4–11-sinflar — 2 000 000 so‘m\n\n"
        "🍽 Oylik to‘lovga 2 mahal issiq ovqat ham kiradi.\n\n"
        "Narxlar va qabul haqida batafsil ma’lumot "
        "olish uchun administrator bilan bog‘laning.\n\n"
        f"📞 {ADMIN_PHONE}\n"
        f"✈️ {ADMIN_USERNAME}",
        reply_markup=info_back_button(admin_button),
    )


# ==================================================
# TA’LIM TIZIMI
# ==================================================

@dp.message(F.text.in_(button_texts("🎓 Ta’lim tizimi")))
async def education_system(message: Message):
    await message.answer(
        "🎓 BUXORO MAKTABI TA’LIM TIZIMI\n\n"
        "Maktabimizda ta’lim an’anaviy va zamonaviy "
        "metodlarni birlashtirgan holda olib boriladi.\n\n"
        "✅ Darslarni chuqur va tushunarli o‘rgatish\n"
        "✅ Amaliy mashg‘ulotlar\n"
        "✅ O‘quvchilarni muntazam sinovdan o‘tkazish\n"
        "✅ Bilimdagi kamchiliklarni aniqlash\n"
        "✅ Har bir o‘quvchi uchun individual ishlash\n"
        "✅ Milliy sertifikat va oliygoh imtihonlariga tayyorlash\n"
        "✅ Ingliz tilida erkin muloqot qilishga tayyorlash\n"
        "✅ Mantiqiy va mustaqil fikrlashni rivojlantirish\n\n"
        "Maqsadimiz faqat baho emas, balki o‘quvchining "
        "haqiqiy bilim va ko‘nikmaga ega bo‘lishidir.",
        reply_markup=info_back_button(),
    )


# ==================================================
# KUN TARTIBI
# ==================================================

@dp.message(F.text.in_(button_texts("🍽 Kun tartibi")))
async def daily_schedule(message: Message):
    await message.answer(
        "🍽 BUXORO MAKTABI KUN TARTIBI\n\n"
        "🕗 08:00 — o‘quvchilarni kutib olish\n"
        "📚 Asosiy fanlar bo‘yicha darslar\n"
        "🍲 Issiq tushlik\n"
        "📝 Mustahkamlash va qo‘shimcha darslar\n"
        "🤖 To‘garaklar va amaliy mashg‘ulotlar\n"
        "⚽ Sport mashg‘ulotlari\n"
        "🍽 Ikkinchi mahal ovqat\n"
        "🕔 17:00 — darslarning yakunlanishi\n\n"
        "O‘quvchilar kun davomida ustozlar nazorati ostida "
        "ta’lim oladi va bo‘sh vaqti mazmunli tashkil qilinadi.",
        reply_markup=info_back_button(),
    )


# ==================================================
# QABULGA YOZILISHNI BOSHLASH
# ==================================================

@dp.message(F.text.in_(button_texts("📝 Qabulga yozilish")))
async def registration_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(RegistrationForm.parent_name)

    await message.answer(
        "📝 QABULGA YOZILISH\n\n"
        "Arizani bosqichma-bosqich to‘ldiramiz.\n\n"
        "1️⃣ Ota-ona ism va familiyasini kiriting:",
        reply_markup=cancel_menu,
    )


# 1. Ota-ona ismi
@dp.message(RegistrationForm.parent_name)
async def registration_parent_name(
    message: Message,
    state: FSMContext,
):
    if not message.text or len(message.text.strip()) < 3:
        await message.answer(
            "Iltimos, ota-ona ism va familiyasini to‘liq yozing:"
        )
        return

    await state.update_data(parent_name=message.text.strip())
    await state.set_state(RegistrationForm.phone)

    await message.answer(
        "2️⃣ Telefon raqamingizni yuboring.\n\n"
        "Pastdagi tugmani bosishingiz yoki raqamni "
        "qo‘lda yozishingiz mumkin:",
        reply_markup=phone_menu,
    )


# 2. Telefon — kontakt orqali
@dp.message(RegistrationForm.phone, F.contact)
async def registration_phone_contact(
    message: Message,
    state: FSMContext,
):
    await state.update_data(phone=message.contact.phone_number)
    await state.set_state(RegistrationForm.child_name)

    await message.answer(
        "3️⃣ Farzandingizning ism va familiyasini kiriting:",
        reply_markup=back_cancel_menu,
    )


# 2. Telefon — matn orqali
@dp.message(RegistrationForm.phone)
async def registration_phone_text(
    message: Message,
    state: FSMContext,
):
    if message.text in button_texts("⬅️ Orqaga qaytish"):
        await state.set_state(RegistrationForm.parent_name)

        await message.answer(
            "1️⃣ Ota-ona ism va familiyasini qaytadan kiriting:",
            reply_markup=cancel_menu,
        )
        return

    if not message.text or len(message.text.strip()) < 7:
        await message.answer(
            "Telefon raqam noto‘g‘ri ko‘rinmoqda.\n\n"
            "Masalan: +998 90 123 45 67"
        )
        return

    await state.update_data(phone=message.text.strip())
    await state.set_state(RegistrationForm.child_name)

    await message.answer(
        "3️⃣ Farzandingizning ism va familiyasini kiriting:",
        reply_markup=back_cancel_menu,
    )


# 3. Farzand ismi
@dp.message(RegistrationForm.child_name)
async def registration_child_name(
    message: Message,
    state: FSMContext,
):
    if message.text in button_texts("⬅️ Orqaga qaytish"):
        await state.set_state(RegistrationForm.phone)

        await message.answer(
            "2️⃣ Telefon raqamingizni qaytadan yuboring:",
            reply_markup=phone_menu,
        )
        return

    if not message.text or len(message.text.strip()) < 3:
        await message.answer(
            "Farzandingizning ism va familiyasini to‘liq yozing:"
        )
        return

    await state.update_data(child_name=message.text.strip())
    await state.set_state(RegistrationForm.child_age)

    await message.answer(
        "4️⃣ Farzandingiz necha yoshda?\n\n"
        "Masalan: 8 yosh",
        reply_markup=back_cancel_menu,
    )


# 4. Farzand yoshi
@dp.message(RegistrationForm.child_age)
async def registration_child_age(
    message: Message,
    state: FSMContext,
):
    if message.text in button_texts("⬅️ Orqaga qaytish"):
        await state.set_state(RegistrationForm.child_name)

        await message.answer(
            "3️⃣ Farzandingizning ism va familiyasini "
            "qaytadan kiriting:",
            reply_markup=back_cancel_menu,
        )
        return

    if not message.text:
        await message.answer(
            "Farzandingiz yoshini kiriting.\n"
            "Masalan: 8 yosh"
        )
        return

    await state.update_data(child_age=message.text.strip())
    await state.set_state(RegistrationForm.child_class)

    await message.answer(
        "5️⃣ Farzandingiz qaysi sinfga qabul qilinadi?\n\n"
        "Masalan: 2-sinf yoki 0-sinf",
        reply_markup=back_cancel_menu,
    )


# 5. Sinf va arizani yuborish
@dp.message(RegistrationForm.child_class)
async def registration_child_class(
    message: Message,
    state: FSMContext,
):
    if message.text in button_texts("⬅️ Orqaga qaytish"):
        await state.set_state(RegistrationForm.child_age)

        await message.answer(
            "4️⃣ Farzandingiz yoshini qaytadan kiriting:",
            reply_markup=back_cancel_menu,
        )
        return

    if not message.text:
        await message.answer(
            "Qaysi sinfga qabul qilinishini yozing.\n"
            "Masalan: 2-sinf"
        )
        return

    await state.update_data(child_class=message.text.strip())
    data = await state.get_data()
    application_id = remember_application("qabul", message, data)

    admin_message = (
        f"🔔 YANGI QABUL ARIZASI #{application_id}\n\n"
        f"👤 Ota-ona: {data['parent_name']}\n"
        f"📱 Telefon: {data['phone']}\n"
        f"🧒 Farzand: {data['child_name']}\n"
        f"🎂 Yoshi: {data['child_age']}\n"
        f"🏫 Sinfi: {data['child_class']}\n\n"
        f"{get_telegram_information(message)}\n\n"
        f"🕒 Yuborilgan vaqt: {get_uzbekistan_time()}"
    )

    try:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_message,
        )

        await message.answer(
            "✅ ARIZANGIZ MUVAFFAQIYATLI YUBORILDI!\n\n"
            "Administratorimiz tez orada siz bilan "
            "bog‘lanadi.\n\n"
            "Buxoro Maktabiga qiziqish bildirganingiz "
            "uchun rahmat! 🎓",
            reply_markup=main_menu,
        )

    except Exception as error:
        print(f"Qabul arizasini yuborishda xato: {error}")

        await message.answer(
            "⚠️ Arizani yuborishda vaqtinchalik xatolik yuz berdi.\n\n"
            f"Administrator: {ADMIN_PHONE}\n"
            f"Telegram: {ADMIN_USERNAME}",
            reply_markup=main_menu,
        )

    await state.clear()


# ==================================================
# TASHRIF BUYURISH
# ==================================================

@dp.message(F.text.in_(button_texts("📅 Tashrif buyurish")))
async def visit_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(VisitForm.parent_name)

    await message.answer(
        "📅 MAKTABGA TASHRIF BUYURISH\n\n"
        "Maktabimizni ko‘rish va administrator bilan "
        "uchrashish uchun ma’lumotlarni kiriting.\n\n"
        "1️⃣ Ism va familiyangizni yozing:",
        reply_markup=cancel_menu,
    )


@dp.message(VisitForm.parent_name)
async def visit_parent_name(
    message: Message,
    state: FSMContext,
):
    if not message.text or len(message.text.strip()) < 3:
        await message.answer(
            "Ism va familiyangizni to‘liq yozing:"
        )
        return

    await state.update_data(parent_name=message.text.strip())
    await state.set_state(VisitForm.phone)

    await message.answer(
        "2️⃣ Telefon raqamingizni yuboring:",
        reply_markup=phone_menu,
    )


@dp.message(VisitForm.phone, F.contact)
async def visit_phone_contact(
    message: Message,
    state: FSMContext,
):
    await state.update_data(phone=message.contact.phone_number)
    await state.set_state(VisitForm.visit_day)

    await message.answer(
        "3️⃣ Qaysi kuni tashrif buyurmoqchisiz?\n\n"
        "Masalan: 28-iyul yoki dushanba",
        reply_markup=back_cancel_menu,
    )


@dp.message(VisitForm.phone)
async def visit_phone_text(
    message: Message,
    state: FSMContext,
):
    if message.text in button_texts("⬅️ Orqaga qaytish"):
        await state.set_state(VisitForm.parent_name)

        await message.answer(
            "1️⃣ Ism va familiyangizni qaytadan kiriting:",
            reply_markup=cancel_menu,
        )
        return

    if not message.text or len(message.text.strip()) < 7:
        await message.answer(
            "Telefon raqamni to‘g‘ri kiriting.\n"
            "Masalan: +998 90 123 45 67"
        )
        return

    await state.update_data(phone=message.text.strip())
    await state.set_state(VisitForm.visit_day)

    await message.answer(
        "3️⃣ Qaysi kuni tashrif buyurmoqchisiz?\n\n"
        "Masalan: 28-iyul yoki dushanba",
        reply_markup=back_cancel_menu,
    )


@dp.message(VisitForm.visit_day)
async def visit_day(
    message: Message,
    state: FSMContext,
):
    if message.text in button_texts("⬅️ Orqaga qaytish"):
        await state.set_state(VisitForm.phone)

        await message.answer(
            "2️⃣ Telefon raqamingizni qaytadan yuboring:",
            reply_markup=phone_menu,
        )
        return

    if not message.text:
        await message.answer(
            "Tashrif kunini yozing.\n"
            "Masalan: 28-iyul"
        )
        return

    await state.update_data(visit_day=message.text.strip())
    await state.set_state(VisitForm.visit_time)

    await message.answer(
        "4️⃣ Qaysi vaqtda kelmoqchisiz?\n\n"
        "Masalan: 11:00",
        reply_markup=back_cancel_menu,
    )


@dp.message(VisitForm.visit_time)
async def visit_time(
    message: Message,
    state: FSMContext,
):
    if message.text in button_texts("⬅️ Orqaga qaytish"):
        await state.set_state(VisitForm.visit_day)

        await message.answer(
            "3️⃣ Tashrif kunini qaytadan kiriting:",
            reply_markup=back_cancel_menu,
        )
        return

    if not message.text:
        await message.answer(
            "Tashrif vaqtini yozing.\n"
            "Masalan: 11:00"
        )
        return

    await state.update_data(visit_time=message.text.strip())
    data = await state.get_data()
    application_id = remember_application("tashrif", message, data)

    admin_message = (
        f"📅 YANGI TASHRIF SO‘ROVI #{application_id}\n\n"
        f"👤 Ism-familiya: {data['parent_name']}\n"
        f"📱 Telefon: {data['phone']}\n"
        f"📆 Tashrif kuni: {data['visit_day']}\n"
        f"🕐 Tashrif vaqti: {data['visit_time']}\n\n"
        f"{get_telegram_information(message)}\n\n"
        f"🕒 Yuborilgan vaqt: {get_uzbekistan_time()}"
    )

    try:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_message,
        )

        await message.answer(
            "✅ Tashrif so‘rovingiz yuborildi!\n\n"
            "Administratorimiz tashrif vaqtini tasdiqlash "
            "uchun siz bilan bog‘lanadi.",
            reply_markup=main_menu,
        )

    except Exception as error:
        print(f"Tashrif so‘rovini yuborishda xato: {error}")

        await message.answer(
            "⚠️ So‘rovni yuborishda xatolik yuz berdi.\n\n"
            f"Administrator: {ADMIN_PHONE}\n"
            f"Telegram: {ADMIN_USERNAME}",
            reply_markup=main_menu,
        )

    await state.clear()


# ==================================================
# SAVOL-JAVOB
# ==================================================

@dp.message(F.text.in_(button_texts("❓ Savol-javob")))
async def frequently_asked_questions(message: Message):
    await message.answer(
        "❓ KO‘P SO‘RALADIGAN SAVOLLAR\n\n"
        "1️⃣ Darslar qaysi vaqtda bo‘ladi?\n"
        "🕘 Darslar 08:00 dan 17:00 gacha davom etadi.\n\n"
        "2️⃣ Ovqat beriladimi?\n"
        "🍽 Ha, o‘quvchilarga 2 mahal issiq ovqat beriladi.\n\n"
        "3️⃣ Qaysi sinflarga qabul mavjud?\n"
        "🎒 Barcha sinflar uchun qabul ochiq.\n\n"
        "4️⃣ 0-sinf narxi qancha?\n"
        "💰 Yangi o‘quv yilidan 1 200 000 so‘m.\n\n"
        "5️⃣ Qabul qanday amalga oshiriladi?\n"
        "📝 Bot orqali ariza qoldirasiz. Administrator "
        "siz bilan bog‘lanadi.\n\n"
        "6️⃣ Maktabga tashrif buyurish mumkinmi?\n"
        "📅 Ha. Bot orqali tashrif kuni va vaqtini "
        "belgilashingiz mumkin.\n\n"
        f"📞 {ADMIN_PHONE}\n"
        f"✈️ {ADMIN_USERNAME}",
        reply_markup=info_back_button(admin_button),
    )


# ==================================================
# MANZIL
# ==================================================

@dp.message(F.text.in_(button_texts("📍 Manzil")))
async def location(message: Message):
    await message.answer(
        "📍 BUXORO MAKTABI MANZILI\n\n"
        "Bekobod shahri,\n"
        "sobiq Qishloq Qurilish banki binosi.\n\n"
        "Maktabga kelishdan oldin administrator bilan "
        "bog‘lanishingiz yoki tashrif uchun bot orqali "
        "ariza qoldirishingiz mumkin.\n\n"
        f"📞 {ADMIN_PHONE}\n"
        f"✈️ {ADMIN_USERNAME}",
        reply_markup=info_back_button(location_button),
    )


# ==================================================
# BOG‘LANISH
# ==================================================

@dp.message(F.text.in_(button_texts("☎️ Bog‘lanish")))
async def contact(message: Message):
    await message.answer(
        "☎️ ADMINISTRATOR BILAN BOG‘LANISH\n\n"
        f"📞 Telefon: {ADMIN_PHONE}\n"
        f"✈️ Telegram: {ADMIN_USERNAME}\n\n"
        "🕘 Ish vaqti: 08:30 dan 18:00 gacha\n\n"
        "Qabul, narxlar, sinflar va maktabga tashrif "
        "bo‘yicha administratorimizga murojaat qilishingiz mumkin.",
        reply_markup=info_back_button(admin_button),
    )


# ==================================================
# INLINE MENYU VA NAVIGATSIYA
# ==================================================

@dp.callback_query(F.data == "subscription:check")
async def subscription_check(call: CallbackQuery, state: FSMContext):
    if not await user_is_subscribed(call.from_user.id):
        return await call.answer(
            "Obuna tasdiqlanmadi. Kanalga obuna bo‘lib qayta tekshiring.",
            show_alert=True,
        )
    await state.clear()
    await call.message.answer(
        "✅ Obuna tasdiqlandi. Kerakli bo‘limni tanlang:",
        reply_markup=main_menu,
    )
    await call.answer("Obuna tasdiqlandi ✅")

@dp.callback_query(F.data.startswith("menu:"))
async def inline_main_menu_handler(call: CallbackQuery, state: FSMContext):
    action = call.data.split(":", 1)[1]
    handlers = {
        "about_school": school_info,
        "teachers": teachers,
        "directions": directions,
        "prices": prices,
        "registration": registration_start,
        "visit": visit_start,
        "education": education_system,
        "schedule": daily_schedule,
        "faq": frequently_asked_questions,
        "location": location,
        "contact": contact,
        "ai": ai_start,
        "kitchen": kitchen,
        "classrooms": classrooms,
    }
    handler = handlers.get(action)
    if not handler:
        return await call.answer("Bo‘lim topilmadi", show_alert=True)
    actor_message = call.message.model_copy(update={"from_user": call.from_user})
    if action in {"registration", "visit", "ai"}:
        await handler(actor_message, state)
    else:
        await handler(actor_message)
    await call.answer()


@dp.callback_query(F.data == "teachers:list")
async def teachers_list_callback(call: CallbackQuery):
    await call.message.answer(
        teachers_intro_text(),
        reply_markup=teachers_keyboard(),
    )
    await call.answer()


@dp.callback_query(F.data.startswith("teacher:"))
async def teacher_detail_callback(call: CallbackQuery):
    try:
        index = int(call.data.rsplit(":", 1)[1])
        member = TEAM_MEMBERS[index]
    except (ValueError, IndexError):
        return await call.answer("Ustoz ma'lumoti topilmadi", show_alert=True)

    image_url = TEAM_PAGE_BASE + quote(member["image"], safe="/")
    caption = (
        f"👨‍🏫 {member['name']}\n"
        f"📚 {member['role']}\n\n"
        f"✨ {member['short']}\n\n"
        f"{member['full']}"
    )
    try:
        await call.message.answer_photo(
            photo=image_url,
            caption=caption,
            reply_markup=teacher_detail_keyboard(),
        )
    except Exception as error:
        print(f"Ustoz rasmi yuborilmadi: {error}", flush=True)
        await call.message.answer(caption, reply_markup=teacher_detail_keyboard())
    await call.answer()


@dp.callback_query(F.data == "nav:home")
async def inline_home_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer(
        "🏠 Bosh menyu ochildi. Kerakli bo‘limni tanlang:",
        reply_markup=main_menu,
    )
    await call.answer()


@dp.callback_query(F.data == "nav:cancel")
async def inline_cancel_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer(
        "❌ Jarayon bekor qilindi. Kerakli bo‘limni tanlang:",
        reply_markup=main_menu,
    )
    await call.answer()


@dp.callback_query(F.data == "nav:phone_hint")
async def inline_phone_hint(call: CallbackQuery):
    await call.answer("Telefon raqamingizni xabar qilib yozing", show_alert=True)


@dp.callback_query(F.data == "nav:back")
async def inline_back_handler(call: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    handlers = {
        RegistrationForm.phone.state: registration_phone_text,
        RegistrationForm.child_name.state: registration_child_name,
        RegistrationForm.child_age.state: registration_child_age,
        RegistrationForm.child_class.state: registration_child_class,
        VisitForm.phone.state: visit_phone_text,
        VisitForm.visit_day.state: visit_day,
        VisitForm.visit_time.state: visit_time,
    }
    handler = handlers.get(current_state)
    if not handler:
        await state.clear()
        await call.message.answer(
            "🏠 Bosh menyu ochildi:",
            reply_markup=main_menu,
        )
        return await call.answer()
    actor_message = call.message.model_copy(update={
        "from_user": call.from_user,
        "text": "⬅️ Orqaga qaytish",
    })
    await handler(actor_message, state)
    await call.answer()


# ==================================================
# SUPERADMIN DIZAYN PANELI
# ==================================================

def is_superadmin(user_id: int) -> bool:
    return user_id == SUPERADMIN_ID


def is_admin(user_id: int) -> bool:
    return user_id in {ADMIN_ID, SUPERADMIN_ID}


def superadmin_panel_keyboard(user_id: int):
    rows = [
        [AiogramInlineKeyboardButton(
            text="📂 Arizalar ro‘yxati",
            callback_data="applications:list",
            style="success",
        )],
        [AiogramInlineKeyboardButton(
            text="📊 Statistika",
            callback_data="statistics:show",
            style="success",
        )],
        [AiogramInlineKeyboardButton(
            text="📝 Xabar matnlari",
            callback_data="templates:list",
            style="primary",
        )],
    ]
    rows.append([AiogramInlineKeyboardButton(
            text="🎨 Tugmalar dizayni",
            callback_data="design:list:0",
            style="primary",
    )])
    if is_superadmin(user_id):
        rows.extend([
        [AiogramInlineKeyboardButton(
            text="📣 Guruh posti",
            callback_data="group_post:start",
            style="success",
        )],
        [AiogramInlineKeyboardButton(
            text="📢 Kanal posti",
            callback_data="channel_post:start",
            style="success",
        )],
        [AiogramInlineKeyboardButton(
            text="✨ Xabar emojilari",
            callback_data="msgemoji:list",
            style="success",
        )],
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def group_post_keyboard():
    me = await bot.get_me()
    bot_label = BUTTON_LABELS["group_bot"]
    admin_label = BUTTON_LABELS["group_admin"]
    _bot_style, bot_emoji = button_appearance(bot_label, "group_bot")
    _admin_style, admin_emoji = button_appearance(admin_label, "group_admin")
    return InlineKeyboardMarkup(inline_keyboard=[[
        AiogramInlineKeyboardButton(
            text=button_label(bot_label, bot_emoji),
            url=f"https://t.me/{me.username}?start=group",
            style="success",
            icon_custom_emoji_id=bot_emoji,
        ),
        AiogramInlineKeyboardButton(
            text=button_label(admin_label, admin_emoji),
            url=f"https://t.me/{ADMIN_USERNAME.lstrip('@')}",
            style="success",
            icon_custom_emoji_id=admin_emoji,
        ),
    ]])


def group_post_payload(message: Message):
    payload = {
        "source_chat_id": message.chat.id,
        "source_message_id": message.message_id,
        "text": message.text,
        "caption": message.caption,
        "entities": serialize_message_entities(message.entities),
        "caption_entities": serialize_message_entities(message.caption_entities),
    }
    if message.video:
        payload.update(kind="video", file_id=message.video.file_id)
    elif message.photo:
        payload.update(kind="photo", file_id=message.photo[-1].file_id)
    elif message.animation:
        payload.update(kind="animation", file_id=message.animation.file_id)
    elif message.document:
        payload.update(kind="document", file_id=message.document.file_id)
    elif message.audio:
        payload.update(kind="audio", file_id=message.audio.file_id)
    elif message.text:
        payload.update(kind="text")
    else:
        payload.update(kind="copy")
    return payload


def serialize_message_entities(entities):
    return [
        entity.model_dump(mode="json", exclude_none=True)
        for entity in (entities or [])
    ]


def restore_message_entities(entities):
    return [MessageEntity.model_validate(entity) for entity in (entities or [])]


def album_post_payload(messages):
    items = []
    for message in sorted(messages, key=lambda item: item.message_id):
        payload = group_post_payload(message)
        if payload.get("kind") not in {"photo", "video", "document", "audio"}:
            continue
        items.append({
            "kind": payload["kind"],
            "file_id": payload["file_id"],
            "caption": payload.get("caption"),
            "caption_entities": payload.get("caption_entities", []),
        })
    return {"kind": "album", "items": items}


def album_input_media(payload):
    media_types = {
        "photo": InputMediaPhoto,
        "video": InputMediaVideo,
        "document": InputMediaDocument,
        "audio": InputMediaAudio,
    }
    result = []
    for item in payload.get("items", []):
        media_type = media_types.get(item.get("kind"))
        if not media_type:
            continue
        caption = item.get("caption")
        caption_entities = restore_message_entities(item.get("caption_entities"))
        if caption and not caption_entities:
            caption, caption_entities = apply_message_emoji_design(caption)
        result.append(media_type(
            media=item["file_id"],
            caption=caption,
            caption_entities=caption_entities,
        ))
    return result


def group_post_payload_has_text(payload):
    kind = payload.get("kind")
    if kind == "album":
        return any(item.get("caption") for item in payload.get("items", []))
    if kind == "text":
        return bool(payload.get("text"))
    return bool(payload.get("caption"))


def group_post_confirm_keyboard(destination_name, payload):
    edit_label = (
        "✏️ Matnni tahrirlash"
        if group_post_payload_has_text(payload)
        else "➕ Matn qo‘shish"
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [AiogramInlineKeyboardButton(
            text=f"✅ {destination_name.capitalize()} yuborish",
            callback_data="group_post:send",
            style="success",
        )],
        [AiogramInlineKeyboardButton(
            text=edit_label,
            callback_data="group_post:edit",
            style="primary",
        )],
        [AiogramInlineKeyboardButton(
            text="❌ Bekor qilish",
            callback_data="group_post:cancel",
            style="danger",
        )],
    ])


def group_post_payload_with_text(payload, text, entities=None):
    updated = dict(payload)
    serialized_entities = serialize_message_entities(entities)
    kind = updated.get("kind")
    if kind == "album":
        items = [dict(item) for item in updated.get("items", [])]
        if items:
            items[0]["caption"] = text
            items[0]["caption_entities"] = serialized_entities
        updated["items"] = items
    elif kind in {"photo", "video", "animation", "document", "audio"}:
        updated["caption"] = text
        updated["caption_entities"] = serialized_entities
    elif kind == "text":
        updated["text"] = text
        updated["entities"] = serialized_entities
    elif kind == "copy":
        updated["caption"] = text
        updated["caption_entities"] = serialized_entities
    else:
        return None
    return updated


async def send_group_post(chat_id, payload, reply_markup):
    kind = payload.get("kind")
    if kind == "album":
        media = album_input_media(payload)
        if len(media) < 2:
            raise ValueError("Albom uchun kamida 2 ta rasm yoki video kerak")
        sent_messages = await bot.send_media_group(chat_id=chat_id, media=media)
        if reply_markup:
            await bot.send_message(
                chat_id=chat_id,
                text="👇 Kerakli bo‘limni tanlang:",
                reply_markup=reply_markup,
            )
        return sent_messages
    common = {"chat_id": chat_id, "reply_markup": reply_markup}
    caption_entities = restore_message_entities(payload.get("caption_entities"))
    if kind == "video":
        return await bot.send_video(
            video=payload["file_id"],
            caption=payload.get("caption"),
            caption_entities=caption_entities,
            **common,
        )
    if kind == "photo":
        return await bot.send_photo(
            photo=payload["file_id"],
            caption=payload.get("caption"),
            caption_entities=caption_entities,
            **common,
        )
    if kind == "animation":
        return await bot.send_animation(
            animation=payload["file_id"],
            caption=payload.get("caption"),
            caption_entities=caption_entities,
            **common,
        )
    if kind == "document":
        return await bot.send_document(
            document=payload["file_id"],
            caption=payload.get("caption"),
            caption_entities=caption_entities,
            **common,
        )
    if kind == "audio":
        return await bot.send_audio(
            audio=payload["file_id"],
            caption=payload.get("caption"),
            caption_entities=caption_entities,
            **common,
        )
    if kind == "text":
        return await bot.send_message(
            text=payload["text"],
            entities=restore_message_entities(payload.get("entities")),
            **common,
        )
    return await bot.copy_message(
        from_chat_id=payload["source_chat_id"],
        message_id=payload["source_message_id"],
        caption=payload.get("caption"),
        caption_entities=caption_entities,
        **common,
    )


async def start_group_post(target, state: FSMContext, destination="group"):
    if destination == "group" and not int(DESIGN.get("target_group_id") or 0):
        return await target.answer(
            "Avval bot qo‘shilgan guruh ichida /setgroup buyrug‘ini yuboring."
        )
    await state.set_state(GroupPostForm.text)
    await state.update_data(post_destination=destination)
    destination_name = "kanalga" if destination == "channel" else "guruhga"
    await target.answer(
        f"{destination_name.capitalize()} yuboriladigan xabarni jo‘nating. "
        "Suriladigan albom uchun 2–10 ta rasmni bir vaqtda tanlab yuboring. "
        "Boshqa chatdagi xabar yoki albomni forward qilishingiz ham mumkin.\n\n"
        "Bekor qilish uchun /cancel yuboring."
    )


@dp.message(Command("setgroup"))
async def set_target_group(message: Message):
    if message.from_user.id != SUPERADMIN_ID or message.chat.type not in {
        ChatType.GROUP, ChatType.SUPERGROUP,
    }:
        return
    DESIGN["target_group_id"] = message.chat.id
    save_design_settings()
    await bot.send_message(
        SUPERADMIN_ID,
        f"✅ Guruh bog‘landi: {message.chat.title or message.chat.id}\n"
        "Endi private chatda /post orqali xabar yuborishingiz mumkin.",
    )


@dp.message(Command("post"))
async def group_post_command(message: Message, state: FSMContext):
    if message.from_user.id != SUPERADMIN_ID or message.chat.type != ChatType.PRIVATE:
        return
    await state.clear()
    await start_group_post(message, state)


@dp.message(Command("channelpost"))
async def channel_post_command(message: Message, state: FSMContext):
    if message.from_user.id != SUPERADMIN_ID or message.chat.type != ChatType.PRIVATE:
        return
    await state.clear()
    await start_group_post(message, state, "channel")


@dp.callback_query(F.data == "group_post:start")
async def group_post_start_callback(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != SUPERADMIN_ID:
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    await state.clear()
    await start_group_post(call.message, state)
    await call.answer()


@dp.callback_query(F.data == "channel_post:start")
async def channel_post_start_callback(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != SUPERADMIN_ID:
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    await state.clear()
    await start_group_post(call.message, state, "channel")
    await call.answer()


@dp.message(GroupPostForm.caption, Command("cancel"))
@dp.message(GroupPostForm.text, Command("cancel"))
async def group_post_cancel_command(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Guruh posti bekor qilindi.")


async def show_group_post_preview(message: Message, state: FSMContext, payload):
    data = await state.get_data()
    destination = data.get("post_destination", "group")
    destination_name = "kanalga" if destination == "channel" else "guruhga"
    await state.update_data(group_post_payload=payload)
    await message.answer("Ko‘rinishi:")
    try:
        await send_group_post(
            message.chat.id,
            payload,
            await group_post_keyboard(),
        )
    except Exception as error:
        return await message.answer(
            f"Bu xabarni nusxalab bo‘lmadi: {str(error)[:150]}"
        )
    await message.answer(
        f"Shu post {destination_name} yuborilsinmi?",
        reply_markup=group_post_confirm_keyboard(destination_name, payload),
    )


async def finish_album_collection(key):
    await asyncio.sleep(ALBUM_COLLECT_DELAY)
    async with ALBUM_LOCK:
        album = ALBUM_BUFFERS.pop(key, None)
        ALBUM_TASKS.pop(key, None)
    if not album:
        return
    messages = album["messages"]
    payload = album_post_payload(messages)
    if len(payload["items"]) < 2:
        return await messages[0].answer(
            "Albom to‘liq kelmadi. Iltimos, kamida 2 ta rasmni bir vaqtda tanlab qayta yuboring."
        )
    await album["processor"](messages[0], album["state"], payload)


async def collect_album(message: Message, state: FSMContext, processor):
    key = (message.chat.id, message.media_group_id)
    async with ALBUM_LOCK:
        album = ALBUM_BUFFERS.setdefault(key, {
            "messages": [],
            "state": state,
            "processor": processor,
        })
        album["messages"].append(message)
        if key not in ALBUM_TASKS:
            ALBUM_TASKS[key] = asyncio.create_task(finish_album_collection(key))


@dp.message(GroupPostForm.text)
async def group_post_preview(message: Message, state: FSMContext):
    if message.from_user.id != SUPERADMIN_ID:
        return
    if message.media_group_id:
        await collect_album(message, state, show_group_post_preview)
        return
    await show_group_post_preview(message, state, group_post_payload(message))


@dp.callback_query(F.data == "group_post:edit")
async def group_post_edit(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != SUPERADMIN_ID:
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    data = await state.get_data()
    payload = data.get("group_post_payload")
    if not payload:
        return await call.answer("Tahrirlanadigan post topilmadi", show_alert=True)
    await state.set_state(GroupPostForm.caption)
    await call.message.edit_text(
        "✏️ Yangi matnni yuboring. Rasm yoki albom bo‘lsa, matn uning tagiga yoziladi.\n\n"
        "Bekor qilish uchun /cancel yuboring."
    )
    await call.answer()


@dp.message(GroupPostForm.caption)
async def group_post_caption_receive(message: Message, state: FSMContext):
    if message.from_user.id != SUPERADMIN_ID:
        return
    if not message.text:
        return await message.answer("Iltimos, yangi matnni oddiy xabar shaklida yuboring.")
    data = await state.get_data()
    payload = data.get("group_post_payload")
    if not payload:
        await state.clear()
        return await message.answer("Tahrirlanadigan post topilmadi.")
    limit = 4096 if payload.get("kind") == "text" else 1024
    if len(message.text) > limit:
        return await message.answer(
            f"Matn juda uzun. Eng ko‘pi {limit} ta belgi bo‘lishi mumkin."
        )
    updated_payload = group_post_payload_with_text(
        payload,
        message.text,
        message.entities,
    )
    if not updated_payload:
        return await message.answer("Bu xabar turining matnini tahrirlab bo‘lmaydi.")
    await state.set_state(GroupPostForm.text)
    await show_group_post_preview(message, state, updated_payload)


@dp.callback_query(F.data == "group_post:send")
async def group_post_send(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != SUPERADMIN_ID:
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    data = await state.get_data()
    payload = data.get("group_post_payload")
    destination = data.get("post_destination", "group")
    target_chat = (
        CHANNEL_USERNAME
        if destination == "channel"
        else int(DESIGN.get("target_group_id") or 0)
    )
    destination_name = "kanalga" if destination == "channel" else "guruhga"
    if not payload or not target_chat:
        return await call.answer("Post yoki manzil topilmadi", show_alert=True)
    try:
        await send_group_post(
            target_chat,
            payload,
            await group_post_keyboard(),
        )
    except Exception as error:
        return await call.answer(f"Yuborilmadi: {str(error)[:120]}", show_alert=True)
    await state.clear()
    await call.message.edit_text(f"✅ Post {destination_name} yuborildi.")
    await call.answer()


@dp.callback_query(F.data == "group_post:cancel")
async def group_post_cancel_callback(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != SUPERADMIN_ID:
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    await state.clear()
    await call.message.edit_text("Guruh posti bekor qilindi.")
    await call.answer()


@dp.message(F.forward_origin)
async def direct_forwarded_post(message: Message, state: FSMContext):
    if message.from_user.id != SUPERADMIN_ID or message.chat.type != ChatType.PRIVATE:
        return
    await state.clear()
    await state.set_state(GroupPostForm.text)
    if message.media_group_id:
        await collect_album(message, state, show_forwarded_post_destination)
        return
    await show_forwarded_post_destination(message, state, group_post_payload(message))


async def show_forwarded_post_destination(message: Message, state: FSMContext, payload):
    await state.update_data(group_post_payload=payload)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [AiogramInlineKeyboardButton(
            text="📢 Kanalga chiqarish",
            callback_data="forward_post:channel",
            style="success",
        )],
        [AiogramInlineKeyboardButton(
            text="📣 Guruhga chiqarish",
            callback_data="forward_post:group",
            style="success",
        )],
        [AiogramInlineKeyboardButton(
            text="❌ Bekor qilish",
            callback_data="group_post:cancel",
            style="danger",
        )],
    ])
    await message.answer(
        "✅ Tayyor post qabul qilindi. Qayerga chiqarilsin?",
        reply_markup=keyboard,
    )


@dp.callback_query(F.data.startswith("forward_post:"))
async def direct_forwarded_post_destination(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != SUPERADMIN_ID:
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    destination = call.data.rsplit(":", 1)[1]
    data = await state.get_data()
    payload = data.get("group_post_payload")
    if not payload:
        return await call.answer("Forward qilingan post topilmadi", show_alert=True)
    if destination == "group" and not int(DESIGN.get("target_group_id") or 0):
        return await call.answer(
            "Avval guruhda /setgroup yuboring", show_alert=True
        )
    await state.update_data(post_destination=destination)
    destination_name = "kanalga" if destination == "channel" else "guruhga"
    await call.message.edit_text(
        f"Post tayyor. {destination_name.capitalize()} yuborilsinmi?",
        reply_markup=group_post_confirm_keyboard(destination_name, payload),
    )
    await call.answer()


async def send_superadmin_panel(target, user_id: int, edit=False):
    text = (
        "👑 ADMIN BOSHQARUV PANELI\n\n"
        "Arizalarni ko‘rish va bot xabarlarini boshqarish mumkin."
    )
    if edit:
        await target.edit_text(text, reply_markup=superadmin_panel_keyboard(user_id))
    else:
        await target.answer(text, reply_markup=superadmin_panel_keyboard(user_id))


@dp.message(Command("design"))
@dp.message(Command("admin"))
async def superadmin_panel_command(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return await message.answer("Bu bo‘lim faqat admin uchun.")
    await state.clear()
    await send_superadmin_panel(message, message.from_user.id)


@dp.callback_query(F.data == "design:home")
async def design_home(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    await state.clear()
    await send_superadmin_panel(call.message, call.from_user.id, edit=True)
    await call.answer()


@dp.callback_query(F.data == "noop")
async def design_noop(call: CallbackQuery):
    await call.answer()


@dp.callback_query(F.data == "applications:list")
async def applications_list(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    await state.clear()
    applications = load_applications()
    recent = list(reversed(applications[-20:]))
    rows = []
    for item in recent:
        kind = "Qabul" if item.get("type") == "qabul" else "Tashrif"
        name = item.get("parent_name") or item.get("telegram_name") or "Noma’lum"
        rows.append([AiogramInlineKeyboardButton(
            text=f"#{item.get('id')} · {kind} · {str(name)[:24]}",
            callback_data=f"applications:view:{item.get('id')}",
        )])
    rows.append([AiogramInlineKeyboardButton(text="🏠 Admin panel", callback_data="design:home")])
    text = (
        f"📂 ARIZALAR RO‘YXATI — jami {len(applications)} ta\n\n"
        + ("Oxirgi 20 ta ariza:" if recent else "Hozircha ariza yo‘q.")
    )
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@dp.callback_query(F.data == "statistics:show")
async def statistics_show(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    await call.message.edit_text(
        statistics_text(),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [AiogramInlineKeyboardButton(
                text="🏠 Admin panel",
                callback_data="design:home",
            )],
        ]),
    )
    await call.answer()


@dp.callback_query(F.data.startswith("applications:view:"))
async def application_view(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    application_id = int(call.data.rsplit(":", 1)[1])
    item = next((row for row in load_applications() if int(row.get("id", 0)) == application_id), None)
    if not item:
        return await call.answer("Ariza topilmadi", show_alert=True)
    if item.get("type") == "qabul":
        details = (
            f"📝 QABUL ARIZASI #{application_id}\n\n"
            f"Ota-ona: {item.get('parent_name', '—')}\n"
            f"Telefon: {item.get('phone', '—')}\n"
            f"Farzand: {item.get('child_name', '—')}\n"
            f"Yoshi: {item.get('child_age', '—')}\n"
            f"Sinfi: {item.get('child_class', '—')}"
        )
    else:
        details = (
            f"📅 TASHRIF SO‘ROVI #{application_id}\n\n"
            f"Ism: {item.get('parent_name', '—')}\n"
            f"Telefon: {item.get('phone', '—')}\n"
            f"Kun: {item.get('visit_day', '—')}\n"
            f"Vaqt: {item.get('visit_time', '—')}"
        )
    details += (
        f"\n\nTelegram: {item.get('telegram_name', '—')}"
        f"\nUsername: @{item.get('username') or 'yo‘q'}"
        f"\nTelegram ID: {item.get('telegram_id', '—')}"
        f"\nYuborilgan: {item.get('created_at', '—')}"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [AiogramInlineKeyboardButton(text="⬅️ Arizalar ro‘yxati", callback_data="applications:list")],
        [AiogramInlineKeyboardButton(text="🏠 Admin panel", callback_data="design:home")],
    ])
    await call.message.edit_text(details, reply_markup=keyboard)
    await call.answer()


def message_templates_keyboard():
    rows = [[AiogramInlineKeyboardButton(
        text=("✅ " if DESIGN["message_templates"].get(key) else "📝 ") + label,
        callback_data=f"templates:choose:{key}",
    )] for key, label, _prefix in MESSAGE_TEMPLATE_CATALOG]
    rows.append([AiogramInlineKeyboardButton(text="🏠 Admin panel", callback_data="design:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data == "templates:list")
async def message_templates_list(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    await state.clear()
    await call.message.edit_text(
        "📝 XABAR MATNLARI\n\nO‘zgartirmoqchi bo‘lgan xabarni tanlang. "
        "✅ belgisi o‘zgartirilgan xabarni bildiradi.",
        reply_markup=message_templates_keyboard(),
    )
    await call.answer()


@dp.callback_query(F.data.startswith("templates:choose:"))
async def message_template_choose(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    key = call.data.rsplit(":", 1)[1]
    item = next((row for row in MESSAGE_TEMPLATE_CATALOG if row[0] == key), None)
    if not item:
        return await call.answer("Xabar topilmadi", show_alert=True)
    await state.set_state(MessageTemplateForm.value)
    await state.update_data(message_template_key=key)
    current = DESIGN["message_templates"].get(key)
    preview = f"\n\nHozirgi maxsus matn:\n{current}" if current else "\n\nHozir standart matn ishlatilmoqda."
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [AiogramInlineKeyboardButton(text="♻️ Standartga qaytarish", callback_data=f"templates:reset:{key}", style="danger")],
        [AiogramInlineKeyboardButton(text="⬅️ Xabarlar ro‘yxati", callback_data="templates:list")],
    ])
    await call.message.edit_text(
        f"📝 {item[1]}\n\nYangi to‘liq xabar matnini yuboring.{preview}",
        reply_markup=keyboard,
    )
    await call.answer()


@dp.message(MessageTemplateForm.value)
async def message_template_receive(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    text = (message.text or "").strip()
    if not text or len(text) > 4000:
        return await message.answer("Xabar 1–4000 belgi oralig‘ida bo‘lishi kerak.")
    data = await state.get_data()
    key = data.get("message_template_key")
    if not any(item[0] == key for item in MESSAGE_TEMPLATE_CATALOG):
        await state.clear()
        return await message.answer("Tahrirlash sessiyasi tugagan.")
    DESIGN["message_templates"][key] = text
    save_design_settings()
    await state.clear()
    await message.answer(
        "✅ Xabar matni saqlandi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [AiogramInlineKeyboardButton(text="📝 Xabarlar ro‘yxati", callback_data="templates:list")],
            [AiogramInlineKeyboardButton(text="🏠 Admin panel", callback_data="design:home")],
        ]),
    )


@dp.callback_query(F.data.startswith("templates:reset:"))
async def message_template_reset(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    key = call.data.rsplit(":", 1)[1]
    DESIGN["message_templates"].pop(key, None)
    save_design_settings()
    await state.clear()
    await call.answer("Standart xabar qaytarildi ✅", show_alert=True)
    await call.message.edit_text(
        "📝 XABAR MATNLARI\n\nKerakli xabarni tanlang.",
        reply_markup=message_templates_keyboard(),
    )


def design_catalog_keyboard(page=0):
    pages = max(1, (len(BUTTON_CATALOG) + DESIGN_PAGE_SIZE - 1) // DESIGN_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    buttons = []
    start = page * DESIGN_PAGE_SIZE
    for key, label in BUTTON_CATALOG[start:start + DESIGN_PAGE_SIZE]:
        style, emoji_id = button_appearance(label, key)
        buttons.append(AiogramInlineKeyboardButton(
            text=button_label(label, emoji_id),
            callback_data=f"design:button:{key}",
            style=style,
            icon_custom_emoji_id=emoji_id,
        ))
    rows = [buttons[index:index + 2] for index in range(0, len(buttons), 2)]
    navigation = []
    if page:
        navigation.append(AiogramInlineKeyboardButton(text="⬅️", callback_data=f"design:list:{page - 1}"))
    navigation.append(AiogramInlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop"))
    if page + 1 < pages:
        navigation.append(AiogramInlineKeyboardButton(text="➡️", callback_data=f"design:list:{page + 1}"))
    rows.append(navigation)
    rows.append([AiogramInlineKeyboardButton(text="🏠 Panel", callback_data="design:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows), page


async def show_design_catalog(target, page=0, edit=False):
    keyboard, _page = design_catalog_keyboard(page)
    text = (
        "🎨 BARCHA TUGMALAR DIZAYNI\n\n"
        "O‘zgartirmoqchi bo‘lgan tugmani tanlang. "
        "Hozirgi rang va Premium emoji shu yerda ko‘rsatiladi."
    )
    if edit:
        await target.edit_text(text, reply_markup=keyboard)
    else:
        await target.answer(text, reply_markup=keyboard)


@dp.callback_query(F.data.startswith("design:list:"))
async def design_list_page(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    await state.clear()
    page = int(call.data.rsplit(":", 1)[1])
    await show_design_catalog(call.message, page, edit=True)
    await call.answer()


@dp.callback_query(F.data.startswith("design:button:"))
async def design_choose_button(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    key = call.data.rsplit(":", 1)[1]
    if key not in BUTTON_LABELS:
        return await call.answer("Tugma topilmadi", show_alert=True)
    page = next(i for i, item in enumerate(BUTTON_CATALOG) if item[0] == key) // DESIGN_PAGE_SIZE
    current = DESIGN["button_designs"].get(key, {})
    await state.update_data(
        design_key=key,
        design_style=current.get("style", DESIGN["button_style"]),
        design_emoji=current.get("emoji_id", DESIGN["premium_emoji_id"]),
        design_page=page,
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            AiogramInlineKeyboardButton(text="⚪ Standart", callback_data="design:style:default"),
            AiogramInlineKeyboardButton(text="🔵 Ko‘k", callback_data="design:style:primary", style="primary"),
        ],
        [
            AiogramInlineKeyboardButton(text="🟢 Yashil", callback_data="design:style:success", style="success"),
            AiogramInlineKeyboardButton(text="🔴 Qizil", callback_data="design:style:danger", style="danger"),
        ],
        [AiogramInlineKeyboardButton(text="♻️ Standartga qaytarish", callback_data=f"design:reset:{key}")],
        [AiogramInlineKeyboardButton(text="⬅️ Tugmalar ro‘yxati", callback_data=f"design:list:{page}")],
    ])
    await call.message.edit_text(
        f"{BUTTON_LABELS[key]}\n\n1/3 — Tugma rangini tanlang:",
        reply_markup=keyboard,
    )
    await call.answer()


@dp.callback_query(F.data.startswith("design:style:"))
async def design_choose_style(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    style = call.data.rsplit(":", 1)[1]
    if style not in {"default", "primary", "success", "danger"}:
        return await call.answer("Noto‘g‘ri rang", show_alert=True)
    await state.update_data(design_style=style)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [AiogramInlineKeyboardButton(text="✨ Premium emojini yuborish", callback_data="design:emoji:custom")],
        [AiogramInlineKeyboardButton(text="🙂 Hozirgi Unicode emoji", callback_data="design:emoji:none")],
    ])
    await call.message.edit_text(
        "2/3 — Tugma uchun emoji variantini tanlang:",
        reply_markup=keyboard,
    )
    await call.answer()


@dp.callback_query(F.data.startswith("design:emoji:"))
async def design_choose_emoji(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    choice = call.data.rsplit(":", 1)[1]
    if choice == "custom":
        await state.set_state(DesignForm.emoji_id)
        await call.message.edit_text(
            "Bitta Telegram Premium animatsion emojisini yoki uning raqamli ID sini yuboring. "
            "Masalan: 5204173037468952659"
        )
        return await call.answer()
    await state.update_data(design_emoji=None)
    await show_button_design_preview(call.message, state)
    await call.answer()


async def show_button_design_preview(message, state):
    data = await state.get_data()
    key = data.get("design_key")
    style = data.get("design_style", "default")
    emoji_id = data.get("design_emoji")
    if key not in BUTTON_LABELS:
        return await message.answer("Sozlash sessiyasi tugagan. /design ni qayta oching.")
    preview = AiogramInlineKeyboardButton(
        text=button_label(BUTTON_LABELS[key], emoji_id),
        callback_data="noop",
        style=None if style == "default" else style,
        icon_custom_emoji_id=emoji_id,
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [preview],
        [AiogramInlineKeyboardButton(text="💾 Saqlash", callback_data="design:save", style="success")],
    ])
    await state.set_state(DesignForm.preview)
    await message.edit_text("3/3 — Natijani tekshiring va saqlang:", reply_markup=keyboard)


@dp.message(DesignForm.emoji_id)
async def receive_button_premium_emoji(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    custom_emoji_id = custom_emoji_id_from_message(message)
    if not custom_emoji_id:
        return await message.answer(
            "Bitta Telegram Premium emoji yoki faqat uning raqamli ID sini yuboring."
        )
    if not await custom_emoji_id_is_valid(custom_emoji_id):
        return await message.answer("Bu Premium emoji ID Telegram tomonidan topilmadi.")
    await state.update_data(design_emoji=custom_emoji_id)
    data = await state.get_data()
    key = data.get("design_key")
    style = data.get("design_style", "default")
    preview = AiogramInlineKeyboardButton(
        text=button_label(BUTTON_LABELS[key], custom_emoji_id),
        callback_data="noop",
        style=None if style == "default" else style,
        icon_custom_emoji_id=custom_emoji_id,
    )
    await state.set_state(DesignForm.preview)
    await message.answer(
        "3/3 — Natijani tekshiring va saqlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [preview],
            [AiogramInlineKeyboardButton(text="💾 Saqlash", callback_data="design:save", style="success")],
        ]),
    )


@dp.callback_query(DesignForm.preview, F.data == "design:save")
async def save_button_design(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    data = await state.get_data()
    key = data.get("design_key")
    if key not in BUTTON_LABELS:
        return await call.answer("Sozlash sessiyasi tugagan", show_alert=True)
    DESIGN["button_designs"][key] = {
        "style": data.get("design_style", "default"),
        "emoji_id": data.get("design_emoji") or "",
    }
    save_design_settings()
    refresh_keyboards()
    page = int(data.get("design_page", 0))
    await state.clear()
    await call.answer("Dizayn saqlandi ✅", show_alert=True)
    await show_design_catalog(call.message, page, edit=True)


@dp.callback_query(F.data.startswith("design:reset:"))
async def reset_button_design(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    key = call.data.rsplit(":", 1)[1]
    DESIGN["button_designs"].pop(key, None)
    save_design_settings()
    refresh_keyboards()
    page = next((i for i, item in enumerate(BUTTON_CATALOG) if item[0] == key), 0) // DESIGN_PAGE_SIZE
    await state.clear()
    await call.answer("Standart holat qaytarildi ✅", show_alert=True)
    await show_design_catalog(call.message, page, edit=True)


def message_emoji_catalog_keyboard():
    buttons = []
    for key, label, fallback in MESSAGE_EMOJI_CATALOG:
        config = DESIGN["message_emojis"].get(key, {})
        marker = "✨" if config.get("custom_id") else config.get("text", fallback)
        buttons.append(AiogramInlineKeyboardButton(
            text=f"{marker} {label}",
            callback_data=f"msgemoji:choose:{key}",
        ))
    rows = [buttons[index:index + 2] for index in range(0, len(buttons), 2)]
    rows.append([AiogramInlineKeyboardButton(text="🏠 Panel", callback_data="design:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_message_emoji_catalog(target, edit=False):
    text = (
        "✨ XABARLARDAGI EMOJILAR\n\n"
        "O‘zgartirmoqchi bo‘lgan emoji turini tanlang. "
        "Oddiy yoki Telegram Premium emoji yuborish mumkin."
    )
    if edit:
        await target.edit_text(text, reply_markup=message_emoji_catalog_keyboard())
    else:
        await target.answer(text, reply_markup=message_emoji_catalog_keyboard())


@dp.callback_query(F.data == "msgemoji:list")
async def message_emoji_list(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    await state.clear()
    await show_message_emoji_catalog(call.message, edit=True)
    await call.answer()


@dp.callback_query(F.data.startswith("msgemoji:choose:"))
async def message_emoji_choose(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    key = call.data.rsplit(":", 1)[1]
    item = next((item for item in MESSAGE_EMOJI_CATALOG if item[0] == key), None)
    if not item:
        return await call.answer("Emoji turi topilmadi", show_alert=True)
    await state.set_state(MessageEmojiForm.value)
    await state.update_data(message_emoji_key=key)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [AiogramInlineKeyboardButton(text="♻️ Standartga qaytarish", callback_data=f"msgemoji:reset:{key}", style="danger")],
        [AiogramInlineKeyboardButton(text="⬅️ Ro‘yxat", callback_data="msgemoji:list")],
    ])
    await call.message.edit_text(
        f"{item[1]} uchun yangi oddiy emoji, Premium emoji yoki uning raqamli ID sini yuboring:",
        reply_markup=keyboard,
    )
    await call.answer()


@dp.message(MessageEmojiForm.value)
async def message_emoji_receive(message: Message, state: FSMContext):
    if not is_superadmin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    key = data.get("message_emoji_key")
    if key not in MESSAGE_EMOJI_DEFAULTS:
        await state.clear()
        return await message.answer("Sozlash sessiyasi tugagan.")
    raw_text = (message.text or message.caption or "").strip()
    custom_emoji_id = custom_emoji_id_from_message(message)
    if custom_emoji_id:
        if not await custom_emoji_id_is_valid(custom_emoji_id):
            return await message.answer("Bu Premium emoji ID Telegram tomonidan topilmadi.")
        has_custom_entity = any(
            entity.type == MessageEntityType.CUSTOM_EMOJI
            for entity in tuple(message.entities or ()) + tuple(message.caption_entities or ())
        )
        fallback_text = raw_text if has_custom_entity else MESSAGE_EMOJI_DEFAULTS[key]
        config = {"text": fallback_text, "custom_id": custom_emoji_id}
    else:
        if not raw_text or len(raw_text) > 16:
            return await message.answer(
                "Bitta oddiy emoji, Premium emoji yoki uning raqamli ID sini yuboring."
            )
        config = {"text": raw_text, "custom_id": None}
    await state.update_data(message_emoji_config=config)
    await state.set_state(MessageEmojiForm.preview)
    preview_button = AiogramInlineKeyboardButton(
        text="💾 Saqlash",
        callback_data="msgemoji:save",
        style="success",
    )
    try:
        preview_text = f"Namuna: {config['text']} Xabar dizayni"
        preview_entities = None
        if config["custom_id"]:
            preview_entities = [MessageEntity(
                type=MessageEntityType.CUSTOM_EMOJI,
                offset=utf16_length("Namuna: "),
                length=utf16_length(config["text"]),
                custom_emoji_id=config["custom_id"],
            )]
        await message.answer(
            preview_text,
            entities=preview_entities,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[preview_button]]),
        )
    except TelegramBadRequest:
        await state.set_state(MessageEmojiForm.value)
        await message.answer("Telegram bu emojini qabul qilmadi. Boshqasini yuboring.")


@dp.callback_query(MessageEmojiForm.preview, F.data == "msgemoji:save")
async def message_emoji_save(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    data = await state.get_data()
    key = data.get("message_emoji_key")
    config = data.get("message_emoji_config")
    if key not in MESSAGE_EMOJI_DEFAULTS or not config:
        return await call.answer("Sozlash sessiyasi tugagan", show_alert=True)
    DESIGN["message_emojis"][key] = config
    save_design_settings()
    await state.clear()
    await call.answer("Emoji saqlandi ✅", show_alert=True)
    await show_message_emoji_catalog(call.message, edit=True)


@dp.callback_query(F.data.startswith("msgemoji:reset:"))
async def message_emoji_reset(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    key = call.data.rsplit(":", 1)[1]
    DESIGN["message_emojis"].pop(key, None)
    save_design_settings()
    await state.clear()
    await call.answer("Standart emoji qaytarildi ✅", show_alert=True)
    await show_message_emoji_catalog(call.message, edit=True)


# ==================================================
# TUSHUNARSIZ XABAR
# ==================================================

@dp.message()
async def unknown_message(message: Message):
    await message.answer(
        "Bu xabarni tushunmadim 😊\n\n"
        "Iltimos, pastdagi menyudan kerakli bo‘limni tanlang:",
        reply_markup=main_menu,
    )


# ==================================================
# BOTNI ISHGA TUSHIRISH
# ==================================================

async def run_telegram_bot():
    try:
        print("Buxoro Maktabi bot ishga tushmoqda...", flush=True)
        await bot.delete_webhook(drop_pending_updates=True)
        SERVICE_STATE["bot"] = "running"
        SERVICE_STATE["bot_error"] = None
        print("Telegram polling ishga tushdi.", flush=True)
        await dp.start_polling(bot, handle_signals=False)
    except Exception as error:
        SERVICE_STATE["bot"] = "failed"
        SERVICE_STATE["bot_error"] = f"{type(error).__name__}: {error}"
        print(f"Telegram bot xatosi: {SERVICE_STATE['bot_error']}", flush=True)


def run_bot_thread():
    asyncio.run(run_telegram_bot())


def main():
    port = int(os.getenv("PORT", "10000"))
    bot_thread = threading.Thread(
        target=run_bot_thread,
        name="telegram-bot-polling",
        daemon=True,
    )
    bot_thread.start()

    SERVICE_STATE["web"] = "running"
    print(f"Flask web server ishga tushdi: 0.0.0.0:{port}", flush=True)
    serve(
        web_app,
        host="0.0.0.0",
        port=port,
        threads=6,
        connection_limit=100,
        channel_timeout=120,
        cleanup_interval=30,
    )


if __name__ == "__main__":
    main()
