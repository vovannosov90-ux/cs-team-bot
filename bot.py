import sqlite3
import json
import re
import time
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

import os

TOKEN = os.getenv("TOKEN")
FACEIT_API_KEY = os.getenv("FACEIT_API_KEY")
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
        ["📈 Моя статистика"],
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
# СТАТИСТИКА FACEIT
# =========================

def get_faceit_history(faceit_id, limit=100):
    url = (
        f"https://open.faceit.com/data/v4/players/"
        f"{faceit_id}/history?game=cs2&limit={limit}"
    )
    data = faceit_request(url)
    return data.get("items", [])


def get_faceit_player_stats(faceit_id, limit=100):
    url = (
        f"https://open.faceit.com/data/v4/players/"
        f"{faceit_id}/games/cs2/stats?limit={limit}"
    )
    data = faceit_request(url)
    return data.get("items", [])


def _normalize_stats(item):
    stats = item.get("stats", {})

    if (
        isinstance(stats, dict)
        and isinstance(stats.get("stats"), dict)
    ):
        stats = stats["stats"]

    return stats if isinstance(stats, dict) else {}


def _get_number(stats, *keys):
    for key in keys:
        value = stats.get(key)
        if value is None:
            continue

        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            continue

    return None


def _get_int(stats, *keys):
    value = _get_number(stats, *keys)
    if value is None:
        return 0
    return int(value)


def _get_rating(stats):
    # Если FACEIT когда-нибудь начнёт отдавать
    # индивидуальный Rating через этот endpoint,
    # бот автоматически его подхватит.
    possible_keys = (
        "Rating",
        "rating",
        "FACEIT Rating",
        "Faceit Rating",
        "faceit_rating",
        "faceitRating",
    )

    for key in possible_keys:
        value = stats.get(key)

        if value is None:
            continue

        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            pass

    return None


def calculate_faceit_stats(faceit_id, limit=100):
    history = get_faceit_history(faceit_id, limit=limit)
    player_stats = get_faceit_player_stats(faceit_id, limit=limit)

    kills = 0
    deaths = 0
    wins = 0
    losses = 0
    processed = 0
    ratings = []

    for item in player_stats[:limit]:
        stats = _normalize_stats(item)

        if not stats:
            continue

        processed += 1

        kills += _get_int(stats, "Kills", "kills")
        deaths += _get_int(stats, "Deaths", "deaths")

        result = str(
            stats.get("Result", stats.get("result", ""))
        ).strip()

        if result == "1":
            wins += 1
        elif result == "0":
            losses += 1

        rating = _get_rating(stats)

        if rating is not None:
            ratings.append(rating)

    total = wins + losses

    kd = (
        kills / deaths
        if deaths > 0
        else 0
    )

    winrate = (
        wins / total * 100
        if total > 0
        else 0
    )

    average_rating = (
        sum(ratings) / len(ratings)
        if ratings
        else None
    )

    best_rating = (
        max(ratings)
        if ratings
        else None
    )

    return {
        "matches": len(history),
        "processed": processed,
        "kills": kills,
        "deaths": deaths,
        "kd": kd,
        "wins": wins,
        "losses": losses,
        "winrate": winrate,
        "ratings": ratings,
        "average_rating": average_rating,
        "best_rating": best_rating,
    }


async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id
    player = get_player(user_id)

    if player is None:
        await update.message.reply_text(
            "Сначала нажми /start",
            reply_markup=main_keyboard
        )
        return

    faceit_id = player[4]
    nickname = player[5]

    if not faceit_id:
        context.user_data["waiting_for_faceit"] = True

        await update.message.reply_text(
            "🔗 Сначала отправь ссылку на свой FACEIT-профиль.",
            reply_markup=main_keyboard
        )
        return

    await update.message.reply_text(
        "📊 Загружаю статистику последних 100 матчей...\n"
        "Это может занять несколько секунд."
    )

    try:
        result = calculate_faceit_stats(
            faceit_id,
            limit=100
        )

        ratings = result["ratings"]

        count_180 = sum(
            1 for x in ratings if x >= 1.80
        )
        count_170 = sum(
            1 for x in ratings if x >= 1.70
        )
        count_160 = sum(
            1 for x in ratings if x >= 1.60
        )
        count_150 = sum(
            1 for x in ratings if x >= 1.50
        )

        if result["average_rating"] is None:
            average_rating = "—"
            rating_note = (
                "\n\n⚠️ Личный FACEIT Rating пока не отдаётся "
                "через публичный Data API."
            )
        else:
            average_rating = f"{result['average_rating']:.2f}"
            rating_note = ""

        if result["best_rating"] is None:
            best_rating = "—"
        else:
            best_rating = f"{result['best_rating']:.2f}"

        message = (
            f"🎮 FACEIT Stats — {nickname}\n\n"
            f"📊 Последних матчей: {result['matches']}\n"
            f"🔎 Обработано матчей: {result['processed']}\n\n"

            f"🔥 Rating ≥ 1.80: {count_180}\n"
            f"⚡ Rating ≥ 1.70: {count_170}\n"
            f"📈 Rating ≥ 1.60: {count_160}\n"
            f"📊 Rating ≥ 1.50: {count_150}\n\n"

            f"📈 Средний Rating: {average_rating}\n"
            f"🚀 Лучший Rating: {best_rating}\n\n"

            f"🎯 K/D: {result['kd']:.2f}\n"
            f"🔫 Kills: {result['kills']}\n"
            f"💀 Deaths: {result['deaths']}\n\n"

            f"🏆 Победы: {result['wins']}\n"
            f"💀 Поражения: {result['losses']}\n"
            f"📌 Winrate: {result['winrate']:.1f}%"
            f"{rating_note}"
        )

        await update.message.reply_text(
            message,
            reply_markup=main_keyboard
        )

    except Exception as e:
        print("STATS ERROR:", repr(e))

        await update.message.reply_text(
            "❌ Не удалось получить статистику FACEIT.\n\n"
            "Попробуй ещё раз через несколько секунд.",
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


    # МОЯ СТАТИСТИКА

    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex("^📈 Моя статистика$"),
            my_stats
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
