import asyncio
import json
import html
import os
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    KeyboardButton,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.dispatcher.middlewares.base import BaseMiddleware


DATABASE_URL = os.getenv("DATABASE_URL")
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise RuntimeError("Не задана змінна середовища TOKEN.")
if not DATABASE_URL:
    raise RuntimeError("Не задана змінна середовища DATABASE_URL. Додайте PostgreSQL у Railway.")

ADMIN_IDS = [
    2106920885,
    881840668,
]

SUPPORT_USERNAME = "@Nelia_pd"


DEFAULT_TEXTS = {
    "welcome": (
        "👋 Вітаємо!\n\n"
        "Через цього бота ви можете повідомити про випадок булінгу "
        "у школі №15 Тернопільського академічного медичного ліцею.\n\n"
        "Якщо ви стали свідком булінгу, постраждали від нього або "
        "знаєте про такий випадок — натисніть кнопку нижче та повідомте нам деталі.\n\n"
        "🔒 Повідомлення буде передано адміністрації школи."
    ),
    "report_prompt": (
        "📝 Розкажіть, будь ласка, про ситуацію.\n\n"
        "За можливості вкажіть:\n\n"
        "• що саме сталося;\n"
        "• де це відбувалося;\n"
        "• приблизну дату та час;\n"
        "• хто був учасником або свідком;\n"
        "• клас або іншу відому вам інформацію;\n"
        "• інші деталі, які можуть допомогти розібратися.\n\n"
        "📎 До повідомлення можна додати фото, відео, файл, голосове або відеоповідомлення.\n"
        "Надішліть інформацію одним або кількома повідомленнями.\n\n"
        "Не хвилюйтеся, якщо ви не знаєте всієї інформації — "
        "надішліть те, що вам відомо."
    ),
    "report_success": (
        "✅ Дякуємо за повідомлення!\n\n"
        "Вашу заяву записано та передано адміністрації школи "
        "для подальшого розгляду.\n\n"
        "Дякуємо, що не залишаєте такі ситуації без уваги. ❤️"
    ),
    "support": (
        "🛠 Технічна підтримка\n\n"
        "Якщо у вас виникли технічні проблеми з ботом, "
        "зверніться до технічної підтримки.\n\n"
        "💬 Зв'язатися з підтримкою: @Nelia_pd"
    ),
}


def db_connect():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_database():
    with db_connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                id INTEGER PRIMARY KEY,
                data JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        conn.commit()


def default_data():
    return {
        "admins": ADMIN_IDS.copy(),
        "texts": DEFAULT_TEXTS.copy(),
        "reports": [],
        "users": {},
        "username_index": {},
    }


def load_data():
    with db_connect() as conn:
        row = conn.execute(
            "SELECT data FROM bot_state WHERE id = 1"
        ).fetchone()

        if not row:
            data = default_data()
            conn.execute(
                """
                INSERT INTO bot_state (id, data)
                VALUES (1, %s::jsonb)
                """,
                (json.dumps(data, ensure_ascii=False),),
            )
            conn.commit()
            return data

        data = row["data"]

    data.setdefault("admins", ADMIN_IDS.copy())
    data.setdefault("texts", {})
    data.setdefault("reports", [])
    data.setdefault("users", {})
    data.setdefault("username_index", {})

    for key, value in DEFAULT_TEXTS.items():
        data["texts"].setdefault(key, value)

    if not data["admins"]:
        data["admins"] = ADMIN_IDS.copy()

    return data


def save_data(data):
    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO bot_state (id, data, updated_at)
            VALUES (1, %s::jsonb, NOW())
            ON CONFLICT (id)
            DO UPDATE SET data = EXCLUDED.data, updated_at = NOW()
            """,
            (json.dumps(data, ensure_ascii=False),),
        )
        conn.commit()


init_database()
data = load_data()


def is_admin(user_id):
    return int(user_id) in data["admins"]


def register_user(user):
    if not user:
        return

    user_id = str(user.id)
    username = user.username.lower() if user.username else None

    old_record = data["users"].get(user_id, {})
    usernames = old_record.get("usernames", [])

    if username and username not in usernames:
        usernames.append(username)

    data["users"][user_id] = {
        "id": user.id,
        "username": username,
        "usernames": usernames,
        "name": user.full_name,
    }

    if username:
        data["username_index"][username] = user.id

    save_data(data)


class UserRegistrationMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data_context):
        user = getattr(event, "from_user", None)

        if user:
            register_user(user)

        return await handler(event, data_context)


class AdminStates(StatesGroup):
    waiting_admin_username = State()
    waiting_text = State()


class BullyingReport(StatesGroup):
    waiting_for_report = State()


bot = Bot(token=TOKEN)
dp = Dispatcher()

dp.message.outer_middleware(UserRegistrationMiddleware())
dp.callback_query.outer_middleware(UserRegistrationMiddleware())


def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Повідомити про булінг")],
            [KeyboardButton(text="🛠 Технічна підтримка")],
        ],
        resize_keyboard=True,
    )


def admin_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👤 Додати адміністратора",
                    callback_data="admin_add",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📋 Список адміністрації",
                    callback_data="admin_list",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Видалити адміністратора",
                    callback_data="admin_remove",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📋 Переглянути усі форми",
                    callback_data="admin_reports",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Змінити інформацію",
                    callback_data="admin_texts",
                )
            ],
        ]
    )


def text_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👋 Вітальне повідомлення",
                    callback_data="edit_welcome",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📝 Повідомлення форми",
                    callback_data="edit_report_prompt",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Після відправки",
                    callback_data="edit_report_success",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🛠 Технічна підтримка",
                    callback_data="edit_support",
                )
            ],
        ]
    )


def report_navigation(index, total):
    buttons = []

    if index > 0:
        buttons.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"report_{index - 1}",
            )
        )

    buttons.append(
        InlineKeyboardButton(
            text=f"{index + 1}/{total}",
            callback_data="noop",
        )
    )

    if index < total - 1:
        buttons.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"report_{index + 1}",
            )
        )

    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def get_user_name(user_id):
    user = data["users"].get(str(user_id), {})

    username = user.get("username")
    name = user.get("name", "Невідомий користувач")

    if username:
        return f"@{username}"

    return name

@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        data["texts"]["welcome"],
        reply_markup=main_keyboard(),
    )


@dp.message(Command("admin"))
async def admin_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас немає доступу до адмін-панелі.")
        return

    await message.answer(
        "⚙️ <b>Адмін-панель</b>\n\n"
        "Оберіть потрібну дію:",
        reply_markup=admin_keyboard(),
        parse_mode="HTML",
    )


@dp.message(F.text == "📝 Повідомити про булінг")
async def report_start(message: Message, state: FSMContext):
    await state.set_state(BullyingReport.waiting_for_report)
    await message.answer(data["texts"]["report_prompt"])


@dp.message(F.text == "🛠 Технічна підтримка")
async def support_handler(message: Message):
    await message.answer(data["texts"]["support"])


async def send_report_to_admins(message: Message, report_id):
    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else "Нікнейм не вказаний"
    )

    header = (
        "Заявка про булінг\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Користувач: {username}\n"
        "📝 Текст повідомлення:\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

    if message.text:
        content = f"{header}\n{message.text}"

        for admin_id in data["admins"]:
            try:
                await bot.send_message(admin_id, content)
            except Exception as e:
                print(f"Помилка адміну {admin_id}: {e}")

    elif message.caption:
        caption = f"{header}\n{message.caption}"

        for admin_id in data["admins"]:
            try:
                await message.copy_to(admin_id, caption=caption)
            except Exception as e:
                print(f"Помилка адміну {admin_id}: {e}")

    else:
        for admin_id in data["admins"]:
            try:
                await bot.send_message(admin_id, header)
                await message.copy_to(admin_id)
            except Exception as e:
                print(f"Помилка адміну {admin_id}: {e}")


@dp.message(BullyingReport.waiting_for_report)
async def receive_report(message: Message, state: FSMContext):
    report_id = len(data["reports"]) + 1

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else "Нікнейм не вказаний"
    )

    data["reports"].append(
        {
            "id": report_id,
            "user_id": message.from_user.id,
            "username": username,
            "name": message.from_user.full_name,
            "text": message.text or message.caption or "",
            "type": (
                "text" if message.text
                else "media" if message.caption
                else "file/media"
            ),
        }
    )

    save_data(data)

    await send_report_to_admins(message, report_id)

    await message.answer(
        data["texts"]["report_success"],
        reply_markup=main_keyboard(),
    )

    await state.clear()


# ==========================================
# ДОДАВАННЯ АДМІНІСТРАТОРА
# ==========================================

@dp.callback_query(F.data == "admin_add")
async def admin_add(callback, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Немає доступу.", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_admin_username)

    await callback.message.answer(
        "👤 Перешліть повідомлення від користувача, якого бажаєте додати до адміністрації бота\n\n"
    )

    await callback.answer()


@dp.message(AdminStates.waiting_admin_username)
async def receive_admin_username(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    user_id = None
    username = None

    # Варіант 1: переслане повідомлення
    if message.forward_origin:
        sender_user = getattr(
            message.forward_origin,
            "sender_user",
            None,
        )

        if sender_user:
            user_id = sender_user.id
            register_user(sender_user)
            username = sender_user.username

    # Варіант 2: відповідь на повідомлення користувача
    if not user_id and message.reply_to_message:
        replied_user = message.reply_to_message.from_user

        if replied_user:
            user_id = replied_user.id
            register_user(replied_user)
            username = replied_user.username

    # Варіант 3: пошук за username
    if not user_id and message.text:
        username = message.text.strip().lstrip("@").lower()

        if username:
            user_id = data["username_index"].get(username)

            # Додаткова спроба через Telegram API.
            # Для звичайних користувачів цей метод не гарантує результату.
            if not user_id:
                try:
                    chat = await bot.get_chat(f"@{username}")

                    if chat.type == "private":
                        user_id = chat.id
                        register_user(chat)

                except Exception:
                    pass

    if not user_id:
        await message.answer(
            "❌ Не вдалося знайти цього користувача.\n\n"
            "Можливі причини:\n"
            "• Користувач ще не взаємодіяв із ботом після оновлення.\n"
            "• Username введено неправильно.\n"
            "• Telegram не дозволяє отримати ID за цим username.\n\n"
            "💡 Попросіть користувача надіслати /start боту, "
            "а потім повторіть спробу.\n\n"
            "Також можна переслати його повідомлення."
        )
        return

    user_id = int(user_id)

    if user_id in data["admins"]:
        await message.answer(
            "ℹ️ Цей користувач уже є адміністратором.",
            reply_markup=admin_keyboard(),
        )
        await state.clear()
        return

    data["admins"].append(user_id)
    save_data(data)

    display_name = f"@{username}" if username else get_user_name(user_id)

    await message.answer(
        "✅ <b>Адміністратора успішно додано!</b>\n\n"
        f"👤 Користувач: {html.escape(display_name)}\n"
        f"🆔 Telegram ID: <code>{user_id}</code>\n\n"
        "🔒 Права адміністратора закріплені за Telegram ID. "
        "Зміна username не вплине на доступ.",
        reply_markup=admin_keyboard(),
        parse_mode="HTML",
    )

    await state.clear()


# ==========================================
# СПИСОК АДМІНІСТРАЦІЇ
# ==========================================

@dp.callback_query(F.data == "admin_list")
async def admin_list(callback):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Немає доступу.", show_alert=True)
        return

    admins = data["admins"]

    if not admins:
        await callback.message.answer("📭 Адміністраторів поки немає.")
        await callback.answer()
        return

    text = "📋 <b>Список адміністрації</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"

    for index, admin_id in enumerate(admins, start=1):
        name = html.escape(get_user_name(admin_id))

        text += (
            f"<b>{index}.</b> {name}\n"
            f"🆔 ID: <code>{admin_id}</code>\n\n"
        )

    text += "━━━━━━━━━━━━━━━━━━━━\n"
    text += f"👥 Усього адміністраторів: {len(admins)}"

    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 До адмін-панелі",
                        callback_data="admin_back",
                    )
                ]
            ]
        ),
    )

    await callback.answer()


# ==========================================
# ВИДАЛЕННЯ АДМІНІСТРАТОРА
# ==========================================

@dp.callback_query(F.data == "admin_remove")
async def admin_remove(callback):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Немає доступу.", show_alert=True)
        return

    admins = data["admins"]

    if not admins:
        await callback.message.answer("📭 Немає адміністраторів для видалення.")
        await callback.answer()
        return

    buttons = []

    for admin_id in admins:
        name = get_user_name(admin_id)

        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 {name} ({admin_id})",
                    callback_data=f"admin_remove_user:{admin_id}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="🔙 Назад",
                callback_data="admin_back",
            )
        ]
    )

    await callback.message.answer(
        "🗑 <b>Видалення адміністратора</b>\n\n"
        "Оберіть адміністратора, якого потрібно видалити:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML",
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("admin_remove_user:"))
async def admin_remove_user(callback):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Немає доступу.", show_alert=True)
        return

    try:
        user_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("❌ Некоректний ID.")
        return

    if user_id not in data["admins"]:
        await callback.answer(
            "Цей користувач уже не є адміністратором.",
            show_alert=True,
        )
        return

    if len(data["admins"]) <= 1:
        await callback.answer(
            "⚠️ Не можна видалити останнього адміністратора!",
            show_alert=True,
        )
        return

    name = get_user_name(user_id)

    data["admins"].remove(user_id)
    save_data(data)

    await callback.message.edit_text(
        "✅ <b>Адміністратора видалено!</b>\n\n"
        f"👤 Користувач: {html.escape(name)}\n"
        f"🆔 ID: <code>{user_id}</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 До адмін-панелі",
                        callback_data="admin_back",
                    )
                ]
            ]
        ),
    )

    await callback.answer("Адміністратора видалено!")


@dp.callback_query(F.data == "admin_back")
async def admin_back(callback):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Немає доступу.", show_alert=True)
        return

    await callback.message.edit_text(
        "⚙️ <b>Адмін-панель</b>\n\n"
        "Оберіть потрібну дію:",
        reply_markup=admin_keyboard(),
        parse_mode="HTML",
    )

    await callback.answer()


# ==========================================
# ПЕРЕГЛЯД ЗАЯВОК
# ==========================================

@dp.callback_query(F.data == "admin_reports")
async def admin_reports(callback):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Немає доступу.", show_alert=True)
        return

    total = len(data["reports"])

    if total == 0:
        await callback.message.answer("📭 Заявок поки немає.")
        await callback.answer()
        return

    await show_report(callback.message, 0)
    await callback.answer()


async def show_report(message, index):
    reports = data["reports"]

    if not reports:
        await message.answer("📭 Заявок поки немає.")
        return

    if index < 0 or index >= len(reports):
        await message.answer("❌ Заявку не знайдено.")
        return

    report = reports[index]

    username = html.escape(str(report.get("username", "Невідомо")))
    name = html.escape(str(report.get("name", "Невідомо")))
    report_text = html.escape(
        str(report.get("text", "") or "Медіа без тексту")
    )

    text = (
        f"📋 <b>Заявка №{report['id']}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Користувач: {username}\n"
        f"👤 Ім'я: {name}\n"
        f"🆔 ID: <code>{report['user_id']}</code>\n"
        "📝 Текст:\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{report_text}"
    )

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=report_navigation(index, len(reports)),
    )


@dp.callback_query(F.data.startswith("report_"))
async def report_page(callback):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Немає доступу.", show_alert=True)
        return

    try:
        index = int(callback.data.split("_")[1])
    except (ValueError, IndexError):
        await callback.answer("❌ Некоректний номер заявки.")
        return

    if index < 0 or index >= len(data["reports"]):
        await callback.answer("Заявку не знайдено.")
        return

    await show_report(callback.message, index)
    await callback.answer()


@dp.callback_query(F.data == "noop")
async def noop(callback):
    await callback.answer()


# ==========================================
# РЕДАГУВАННЯ ТЕКСТІВ
# ==========================================

@dp.callback_query(F.data == "admin_texts")
async def admin_texts(callback):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Немає доступу.", show_alert=True)
        return

    await callback.message.answer(
        "✏️ <b>Зміна інформації</b>\n\n"
        "Оберіть повідомлення, яке хочете змінити:",
        reply_markup=text_keyboard(),
        parse_mode="HTML",
    )

    await callback.answer()


TEXT_NAMES = {
    "welcome": "👋 Вітальне повідомлення",
    "report_prompt": "📝 Повідомлення форми",
    "report_success": "✅ Повідомлення після відправки",
    "support": "🛠 Технічна підтримка",
}


async def begin_text_edit(callback, state, key):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Немає доступу.", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_text)
    await state.update_data(edit_key=key)

    await callback.message.answer(
        f"{TEXT_NAMES[key]}\n\n"
        "Надішліть новий текст одним повідомленням.\n\n"
        "💡 Підтримується звичайний текст та емоджі.\n"
        "Для складнішого оформлення можна використовувати HTML-розмітку."
    )

    await callback.answer()


@dp.callback_query(F.data == "edit_welcome")
async def edit_welcome(callback, state):
    await begin_text_edit(callback, state, "welcome")


@dp.callback_query(F.data == "edit_report_prompt")
async def edit_report_prompt(callback, state):
    await begin_text_edit(callback, state, "report_prompt")


@dp.callback_query(F.data == "edit_report_success")
async def edit_report_success(callback, state):
    await begin_text_edit(callback, state, "report_success")


@dp.callback_query(F.data == "edit_support")
async def edit_support(callback, state):
    await begin_text_edit(callback, state, "support")


@dp.message(AdminStates.waiting_text)
async def save_new_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    state_data = await state.get_data()
    key = state_data.get("edit_key")

    if not key or key not in TEXT_NAMES:
        await state.clear()
        return

    if not message.text:
        await message.answer(
            "⚠️ Для цього поля потрібно надіслати саме текстове повідомлення."
        )
        return

    data["texts"][key] = message.text
    save_data(data)

    await message.answer(
        f"✅ «{TEXT_NAMES[key]}» успішно змінено!\n\n"
        "Новий текст:\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{message.text}\n"
        "━━━━━━━━━━━━━━━━━━━━",
        reply_markup=admin_keyboard(),
    )

    await state.clear()


# ==========================================
# ЗАПУСК БОТА
# ==========================================

async def main():
    print("Бот запущено...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
