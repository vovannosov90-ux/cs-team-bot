import sqlite3
import json
import re
from urllib.request import Request, urlopen
from urllib.parse import quote

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# =========================
# НАСТРОЙКИ
# =========================

TOKEN = "твой_токен"
FACEIT_API_KEY = "твой_ключ"
MAX_PLAYERS = 10
DB_NAME = "cs_team.db"


# =========================
# БАЗА ДАННЫХ
# =========================

def init_db():

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            elo INTEGER,
            status TEXT DEFAULT '⚪ Пока не знаю'
        )
    """)

    # Добавляем новые поля в старую базу,
    # если их там ещё нет.

    cursor.execute("PRAGMA table_info(players)")
    columns = [row[1] for row in cursor.fetchall()]

    if "faceit_id" not in columns:
        cursor.execute(
            "ALTER TABLE players ADD COLUMN faceit_id TEXT"
        )

    if "faceit_nickname" not in columns:
        cursor.execute(
            "ALTER TABLE players ADD COLUMN faceit_nickname TEXT"
        )

    if "faceit_url" not in columns:
        cursor.execute(
            "ALTER TABLE players ADD COLUMN faceit_url TEXT"
        )

    conn.commit()
    conn.close()


def get_player(user_id):

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            user_id,
            name,
            elo,
            status,
            faceit_id,
            faceit_nickname,
            faceit_url
        FROM players
        WHERE user_id = ?
        """,
        (user_id,)
    )

    player = cursor.fetchone()

    conn.close()

    return player


def get_players():

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            name,
            elo,
            status,
            faceit_nickname
        FROM players
        ORDER BY name
        """
    )

    players = cursor.fetchall()

    conn.close()

    return players


def add_player(user_id, name):

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO players (user_id, name)
        VALUES (?, ?)
        """,
        (user_id, name)
    )

    conn.commit()
    conn.close()


def save_faceit(
    user_id,
    faceit_id,
    faceit_nickname,
    faceit_url,
    elo
):

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE players
        SET
            faceit_id = ?,
            faceit_nickname = ?,
            faceit_url = ?,
            elo = ?
        WHERE user_id = ?
        """,
        (
            faceit_id,
            faceit_nickname,
            faceit_url,
            elo,
            user_id
        )
    )

    conn.commit()
    conn.close()


def update_elo(user_id, elo):

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE players
        SET elo = ?
        WHERE user_id = ?
        """,
        (elo, user_id)
    )

    conn.commit()
    conn.close()


def update_status(user_id, status):

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE players
        SET status = ?
        WHERE user_id = ?
        """,
        (status, user_id)
    )

    conn.commit()
    conn.close()


# =========================
# FACEIT API
# =========================

def faceit_request(url):

    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {FACEIT_API_KEY}",
            "Accept": "application/json",
        }
    )

    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def extract_faceit_nickname(text):

    text = text.strip()

    # Если пользователь вставил ссылку FACEIT
    if "faceit.com" in text.lower():

        match = re.search(
            r"faceit\.com/(?:[a-z]{2}/)?players/([^/?#]+)",
            text,
            re.IGNORECASE
        )

        if match:
            return match.group(1)

    # Если вместо ссылки написал просто ник
    if re.fullmatch(r"[A-Za-z0-9_\-\.]+", text):
        return text

    return None


def get_faceit_player(identifier):

    nickname = extract_faceit_nickname(identifier)

    if not nickname:
        return None, "❌ Не смог распознать FACEIT-профиль."

    encoded_nickname = quote(nickname)

    url = (
        "https://open.faceit.com/data/v4/players"
        f"?nickname={encoded_nickname}"
        "&game=cs2"
    )

    try:

        data = faceit_request(url)

    except Exception as e:

        print("FACEIT API ERROR:", e)

        return None, (
            "❌ Не удалось получить данные FACEIT.\n\n"
            "Проверь API-ключ или попробуй ещё раз."
        )

    if not data:

        return None, (
            "❌ Игрок не найден на FACEIT.\n\n"
            "Проверь ссылку на профиль."
        )

    # API может вернуть профиль напрямую
    # либо список результатов поиска.

    if isinstance(data, dict) and "player_id" in data:

        player = data

    elif isinstance(data, dict) and data.get("items"):

        player = data["items"][0]

        # Если поиск вернул только краткую информацию,
        # получаем полный профиль.

        if "games" not in player:

            player_id = player.get("player_id")

            if not player_id:
                return None, "❌ Не найден ID игрока."

            player = faceit_request(
                f"https://open.faceit.com/data/v4/players/{player_id}"
            )

    else:

        return None, (
            "❌ Не удалось найти игрока.\n"
            "Проверь ссылку FACEIT."
        )

    player_id = player.get("player_id")
    faceit_nickname = player.get("nickname")

    games = player.get("games", {})

    cs2 = games.get("cs2")

    if cs2 is None:

        # На случай старого обозначения CS:GO
        cs2 = games.get("csgo")

    if cs2 is None:

        return None, (
            "❌ Профиль найден, но у него нет "
            "данных по CS2."
        )

    elo = cs2.get("faceit_elo")

    if elo is None:

        return None, (
            "❌ Не удалось получить ELO этого игрока."
        )

    faceit_url = player.get("faceit_url", "")

    return {
        "player_id": player_id,
        "nickname": faceit_nickname,
        "elo": int(elo),
        "url": faceit_url
    }, None


# =========================
# КЛАВИАТУРЫ
# =========================

main_keyboard = ReplyKeyboardMarkup(
    [
        ["👤 Мой профиль"],
        ["🔄 Обновить ELO", "🎮 Сегодня играю"],
        ["👥 Кто сегодня играет"],
        ["📊 Все ELO"],
    ],
    resize_keyboard=True
)


status_keyboard = ReplyKeyboardMarkup(
    [
        ["🟢 Буду играть"],
        ["🔴 Не буду играть"],
        ["⚪ Пока не знаю"],
        ["⬅️ Назад"],
    ],
    resize_keyboard=True
)


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user
    user_id = user.id
    name = user.first_name

    player = get_player(user_id)

    if player is None:

        players = get_players()

        if len(players) >= MAX_PLAYERS:

            await update.message.reply_text(
                "❌ Команда уже заполнена.\n"
                f"Максимум игроков: {MAX_PLAYERS}."
            )

            return

        add_player(user_id, name)

        context.user_data["waiting_for_faceit"] = True

        await update.message.reply_text(
            f"🎮 Добро пожаловать, {name}!\n\n"
            "Ты добавлен в CS-команду.\n\n"
            "Теперь отправь ссылку на свой "
            "FACEIT-профиль.\n\n"
            "Например:\n"
            "https://www.faceit.com/ru/players/USERNAME\n\n"
            "Можно также просто написать свой FACEIT-ник."
        )

        return

    # Если игрок уже есть, но FACEIT ещё не привязан

    faceit_id = player[4]

    if not faceit_id:

        context.user_data["waiting_for_faceit"] = True

        await update.message.reply_text(
            f"🎮 С возвращением, {name}!\n\n"
            "Твой FACEIT-профиль ещё не привязан.\n\n"
            "Отправь ссылку на свой FACEIT-профиль."
        )

        return

    await update.message.reply_text(
        f"🎮 С возвращением, {name}!",
        reply_markup=main_keyboard
    )


# =========================
# ПРИВЯЗКА FACEIT
# =========================

async def process_faceit(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.user_data.get("waiting_for_faceit"):
        return False

    text = update.message.text.strip()

    await update.message.reply_text(
        "🔎 Ищу профиль на FACEIT..."
    )

    result, error = get_faceit_player(text)

    if error:

        await update.message.reply_text(
            error + "\n\n"
            "Попробуй отправить ссылку ещё раз."
        )

        return True

    save_faceit(
        update.effective_user.id,
        result["player_id"],
        result["nickname"],
        result["url"],
        result["elo"]
    )

    context.user_data["waiting_for_faceit"] = False

    await update.message.reply_text(
        "✅ FACEIT-профиль подключён!\n\n"
        f"👤 Ник: {result['nickname']}\n"
        f"🎯 ELO: {result['elo']}\n\n"
        "Теперь ELO можно обновлять автоматически.",
        reply_markup=main_keyboard
    )

    return True


# =========================
# МОЙ ПРОФИЛЬ
# =========================

async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    player = get_player(user_id)

    if player is None:

        await update.message.reply_text(
            "Сначала нажми /start"
        )

        return

    _, name, elo, status, faceit_id, faceit_nickname, faceit_url = player

    elo_text = str(elo) if elo is not None else "не указан"

    faceit_text = (
        faceit_nickname
        if faceit_nickname
        else "не подключён"
    )

    await update.message.reply_text(
        f"👤 {name}\n\n"
        f"🎮 FACEIT: {faceit_text}\n"
        f"🎯 ELO: {elo_text}\n"
        f"📅 Сегодня: {status}",
        reply_markup=main_keyboard
    )


# =========================
# ОБНОВЛЕНИЕ ELO
# =========================

async def refresh_elo(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    player = get_player(user_id)

    if player is None:

        await update.message.reply_text(
            "Сначала нажми /start"
        )

        return

    faceit_id = player[4]
    faceit_nickname = player[5]

    if not faceit_id:

        context.user_data["waiting_for_faceit"] = True

        await update.message.reply_text(
            "🔗 Сначала отправь ссылку на свой "
            "FACEIT-профиль."
        )

        return

    await update.message.reply_text(
        "🔄 Получаю актуальный ELO с FACEIT..."
    )

    try:

        data = faceit_request(
            f"https://open.faceit.com/data/v4/players/{faceit_id}"
        )

        games = data.get("games", {})

        cs2 = games.get("cs2")

        if cs2 is None:
            cs2 = games.get("csgo")

        if cs2 is None:

            await update.message.reply_text(
                "❌ Не нашёл CS2 в профиле FACEIT."
            )

            return

        elo = cs2.get("faceit_elo")

        if elo is None:

            await update.message.reply_text(
                "❌ FACEIT не вернул ELO."
            )

            return

        nickname = data.get(
            "nickname",
            faceit_nickname
        )

        update_elo(user_id, int(elo))

        await update.message.reply_text(
            "✅ ELO обновлён!\n\n"
            f"👤 {nickname}\n"
            f"🎯 FACEIT ELO: {elo}",
            reply_markup=main_keyboard
        )

    except Exception as e:

        print("REFRESH ERROR:", e)

        await update.message.reply_text(
            "❌ Не удалось обновить ELO.\n\n"
            "Попробуй ещё раз через несколько секунд."
        )


# =========================
# СТАТУС
# =========================

async def change_status(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🎮 Будешь сегодня играть?",
        reply_markup=status_keyboard
    )


async def process_status(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text

    statuses = {
        "🟢 Буду играть": "🟢 Буду играть",
        "🔴 Не буду играть": "🔴 Не буду играть",
        "⚪ Пока не знаю": "⚪ Пока не знаю",
    }

    if text not in statuses:
        return

    update_status(
        update.effective_user.id,
        statuses[text]
    )

    await update.message.reply_text(
        f"✅ Статус сохранён:\n{statuses[text]}",
        reply_markup=main_keyboard
    )


# =========================
# КТО СЕГОДНЯ ИГРАЕТ
# =========================

async def who_plays(update: Update, context: ContextTypes.DEFAULT_TYPE):

    players = get_players()

    if not players:

        await update.message.reply_text(
            "Пока никто не зарегистрирован."
        )

        return

    text = "🎮 КТО СЕГОДНЯ ИГРАЕТ\n\n"

    for name, elo, status, faceit_nickname in players:

        elo_text = (
            str(elo)
            if elo is not None
            else "ELO не указан"
        )

        display_name = (
            faceit_nickname
            if faceit_nickname
            else name
        )

        text += (
            f"{status} "
            f"{display_name} — "
            f"{elo_text}\n"
        )

    await update.message.reply_text(
        text,
        reply_markup=main_keyboard
    )


# =========================
# ВСЕ ELO
# =========================

async def all_elo(update: Update, context: ContextTypes.DEFAULT_TYPE):

    players = get_players()

    if not players:

        await update.message.reply_text(
            "Пока никто не зарегистрирован."
        )

        return

    players_sorted = sorted(
        players,
        key=lambda x: x[1] if x[1] is not None else -1,
        reverse=True
    )

    text = "📊 РЕЙТИНГ КОМАНДЫ\n\n"

    for i, (name, elo, status, faceit_nickname) in enumerate(
        players_sorted,
        1
    ):

        display_name = (
            faceit_nickname
            if faceit_nickname
            else name
        )

        if elo is None:
            elo_text = "ELO не указан"
        else:
            elo_text = f"{elo} ELO"

        if i == 1:
            place = "🥇"
        elif i == 2:
            place = "🥈"
        elif i == 3:
            place = "🥉"
        else:
            place = f"{i}."

        text += (
            f"{place} "
            f"{display_name} — "
            f"{elo_text} "
            f"{status}\n"
        )

    await update.message.reply_text(
        text,
        reply_markup=main_keyboard
    )


# =========================
# НАЗАД
# =========================

async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "Главное меню:",
        reply_markup=main_keyboard
    )


# =========================
# ОБРАБОТКА ТЕКСТА
# =========================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # Сначала проверяем, ждём ли FACEIT-профиль

    if context.user_data.get("waiting_for_faceit"):

        await process_faceit(update, context)

        return


# =========================
# ЗАПУСК
# =========================

def main():

    init_db()

    app = Application.builder().token(TOKEN).build()

    # START

    app.add_handler(
        CommandHandler("start", start)
    )

    # МОЙ ПРОФИЛЬ

    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex("^👤 Мой профиль$"),
            my_profile
        )
    )

    # ОБНОВИТЬ ELO

    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex("^🔄 Обновить ELO$"),
            refresh_elo
        )
    )

    # СТАТУС

    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex("^🎮 Сегодня играю$"),
            change_status
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(
                "^(🟢 Буду играть|🔴 Не буду играть|⚪ Пока не знаю)$"
            ),
            process_status
        )
    )

    # КТО ИГРАЕТ

    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(
                "^👥 Кто сегодня играет$"
            ),
            who_plays
        )
    )

    # ВСЕ ELO

    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex("^📊 Все ELO$"),
            all_elo
        )
    )

    # НАЗАД

    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex("^⬅️ Назад$"),
            back
        )
    )

    # FACEIT / ПРОЧИЙ ТЕКСТ

    app.add_handler(
        MessageHandler(
            filters.TEXT,
            text_handler
        )
    )

    print("Бот запущен!")

    app.run_polling()


if __name__ == "__main__":
    main()
