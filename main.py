import asyncio
import json
import os
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.enums import MessageEntityType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton as AiogramInlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    MessageEntity,
    ReplyKeyboardRemove,
)


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

# Administrator ma’lumotlari
ADMIN_PHONE = "+998 94 835 66 66"
ADMIN_USERNAME = "@bm_qabul"


bot = Bot(token=TOKEN)
dp = Dispatcher()


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


def load_design_settings():
    if not DESIGN_PATH.exists():
        return
    try:
        stored = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    for key in ("button_style", "premium_emoji_id"):
        if key in stored:
            DESIGN[key] = stored[key]
    for key in ("button_designs", "message_emojis"):
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


class DesignMessageMiddleware(BaseRequestMiddleware):
    async def __call__(self, make_request, bot_instance, method):
        text = getattr(method, "text", None)
        existing_entities = getattr(method, "entities", None)
        if not isinstance(text, str) or existing_entities:
            return await make_request(bot_instance, method)

        configured = DESIGN.get("message_emojis", {})
        replacements = {
            fallback: configured.get(key, {})
            for key, _label, fallback in MESSAGE_EMOJI_CATALOG
            if configured.get(key)
        }
        if not replacements:
            return await make_request(bot_instance, method)

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
                entities.append(
                    MessageEntity(
                        type=MessageEntityType.CUSTOM_EMOJI,
                        offset=output_position,
                        length=replacement_length,
                        custom_emoji_id=str(custom_id),
                    )
                )
            output_position += replacement_length
            source_position = match.end()

        chunks.append(text[source_position:])
        method.text = "".join(chunks)
        if entities:
            method.entities = entities
        return await make_request(bot_instance, method)


bot.session.middleware(DesignMessageMiddleware())


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


# ==================================================
# YORDAMCHI FUNKSIYALAR
# ==================================================

def get_uzbekistan_time() -> str:
    uzbekistan_timezone = timezone(timedelta(hours=5))
    now = datetime.now(uzbekistan_timezone)

    return now.strftime("%d.%m.%Y | %H:%M")


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
        await send_superadmin_panel(message)


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
        "uchun ishonchli tanlov!"
    )


# ==================================================
# USTOZLAR
# ==================================================

@dp.message(F.text.in_(button_texts("👨‍🏫 Ustozlar")))
async def teachers(message: Message):
    await message.answer(
        "👨‍🏫 BUXORO MAKTABI USTOZLARI\n\n"
        "Maktabimizda tajribali, malakali va o‘z fanini "
        "mukammal biladigan ustozlar faoliyat yuritadi.\n\n"
        "✅ Milliy va xalqaro sertifikatlarga ega ustozlar\n"
        "✅ Ko‘p yillik pedagogik tajriba\n"
        "✅ Zamonaviy o‘qitish metodlari\n"
        "✅ O‘quvchilarga individual yondashuv\n"
        "✅ Natijaga yo‘naltirilgan darslar\n"
        "✅ Doimiy nazorat va tahlil\n"
        "✅ Ota-onalar bilan muntazam aloqa\n\n"
        "Har bir o‘quvchining bilim darajasi va "
        "qobiliyatidan kelib chiqib alohida yondashiladi."
    )


# ==================================================
# YO‘NALISHLAR
# ==================================================

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
        "to‘garaklar va amaliy mashg‘ulotlar ham mavjud."
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
        reply_markup=admin_button,
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
        "haqiqiy bilim va ko‘nikmaga ega bo‘lishidir."
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
        "ta’lim oladi va bo‘sh vaqti mazmunli tashkil qilinadi."
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

    admin_message = (
        "🔔 YANGI QABUL ARIZASI\n\n"
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

    admin_message = (
        "📅 YANGI TASHRIF SO‘ROVI\n\n"
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
        reply_markup=admin_button,
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
        reply_markup=location_button,
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
        reply_markup=admin_button,
    )


# ==================================================
# INLINE MENYU VA NAVIGATSIYA
# ==================================================

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
    }
    handler = handlers.get(action)
    if not handler:
        return await call.answer("Bo‘lim topilmadi", show_alert=True)
    actor_message = call.message.model_copy(update={"from_user": call.from_user})
    if action in {"registration", "visit"}:
        await handler(actor_message, state)
    else:
        await handler(actor_message)
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


def superadmin_panel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [AiogramInlineKeyboardButton(
            text="🎨 Tugmalar dizayni",
            callback_data="design:list:0",
            style="primary",
        )],
        [AiogramInlineKeyboardButton(
            text="✨ Xabar emojilari",
            callback_data="msgemoji:list",
            style="success",
        )],
    ])


async def send_superadmin_panel(target, edit=False):
    text = (
        "👑 SUPERADMIN DIZAYN PANELI\n\n"
        "Tugmalar rangi va Premium emojilarini yoki "
        "xabarlardagi emojilarni o‘zgartirishingiz mumkin."
    )
    if edit:
        await target.edit_text(text, reply_markup=superadmin_panel_keyboard())
    else:
        await target.answer(text, reply_markup=superadmin_panel_keyboard())


@dp.message(Command("design"))
@dp.message(Command("admin"))
async def superadmin_panel_command(message: Message, state: FSMContext):
    if not is_superadmin(message.from_user.id):
        return await message.answer("Bu bo‘lim faqat superadmin uchun.")
    await state.clear()
    await send_superadmin_panel(message)


@dp.callback_query(F.data == "design:home")
async def design_home(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    await state.clear()
    await send_superadmin_panel(call.message, edit=True)
    await call.answer()


@dp.callback_query(F.data == "noop")
async def design_noop(call: CallbackQuery):
    await call.answer()


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
    if not is_superadmin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    await state.clear()
    page = int(call.data.rsplit(":", 1)[1])
    await show_design_catalog(call.message, page, edit=True)
    await call.answer()


@dp.callback_query(F.data.startswith("design:button:"))
async def design_choose_button(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
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
    if not is_superadmin(call.from_user.id):
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
    if not is_superadmin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    choice = call.data.rsplit(":", 1)[1]
    if choice == "custom":
        await state.set_state(DesignForm.emoji_id)
        await call.message.edit_text(
            "Bitta Telegram Premium animatsion emojisini yuboring. "
            "Emoji ID avtomatik aniqlanadi."
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
    if not is_superadmin(message.from_user.id):
        await state.clear()
        return
    entities = tuple(message.entities or ()) + tuple(message.caption_entities or ())
    custom_ids = [
        entity.custom_emoji_id
        for entity in entities
        if entity.type == MessageEntityType.CUSTOM_EMOJI and entity.custom_emoji_id
    ]
    if len(custom_ids) != 1:
        return await message.answer("Faqat bitta Telegram Premium emoji yuboring.")
    await state.update_data(design_emoji=custom_ids[0])
    data = await state.get_data()
    key = data.get("design_key")
    style = data.get("design_style", "default")
    preview = AiogramInlineKeyboardButton(
        text=button_label(BUTTON_LABELS[key], custom_ids[0]),
        callback_data="noop",
        style=None if style == "default" else style,
        icon_custom_emoji_id=custom_ids[0],
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
    if not is_superadmin(call.from_user.id):
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
    if not is_superadmin(call.from_user.id):
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
        f"{item[1]} uchun yangi oddiy emoji yoki bitta Premium emoji yuboring:",
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
    entities = tuple(message.entities or ()) + tuple(message.caption_entities or ())
    custom_ids = [
        entity.custom_emoji_id
        for entity in entities
        if entity.type == MessageEntityType.CUSTOM_EMOJI and entity.custom_emoji_id
    ]
    raw_text = (message.text or message.caption or "").strip()
    if custom_ids:
        config = {"text": raw_text or MESSAGE_EMOJI_DEFAULTS[key], "custom_id": custom_ids[0]}
    else:
        if not raw_text or len(raw_text) > 16:
            return await message.answer("Faqat bitta emoji yuboring.")
        config = {"text": raw_text, "custom_id": None}
    await state.update_data(message_emoji_config=config)
    await state.set_state(MessageEmojiForm.preview)
    preview_button = AiogramInlineKeyboardButton(
        text="💾 Saqlash",
        callback_data="msgemoji:save",
        style="success",
    )
    try:
        await message.answer(
            f"Namuna: {config['text']} Xabar dizayni",
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

async def main():
    print("Buxoro Maktabi bot ishga tushdi...")

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
