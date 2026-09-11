# =========================
# СТАТИСТИКА FACEIT
# =========================

def get_faceit_player_stats(faceit_id, limit=100):
    url = (
        f"https://open.faceit.com/data/v4/players/"
        f"{faceit_id}/games/cs2/stats"
        f"?offset=0&limit={limit}"
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
            return float(
                str(value).replace(",", ".")
            )

        except (TypeError, ValueError):
            continue

    return None


def _get_int(stats, *keys):

    value = _get_number(stats, *keys)

    if value is None:
        return 0

    return int(value)


def _get_rating(stats):

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

            return float(
                str(value).replace(",", ".")
            )

        except (TypeError, ValueError):
            pass

    return None


def calculate_faceit_stats(faceit_id, limit=100):

    player_stats = get_faceit_player_stats(
        faceit_id,
        limit=limit
    )

    kills = 0
    deaths = 0

    wins = 0
    losses = 0

    ratings = []

    processed = 0

    for item in player_stats:

        stats = _normalize_stats(item)

        if not stats:
            continue

        processed += 1

        # =========================
        # KILLS / DEATHS
        # =========================

        kills += _get_int(
            stats,
            "Kills",
            "kills"
        )

        deaths += _get_int(
            stats,
            "Deaths",
            "deaths"
        )

        # =========================
        # RESULT
        # =========================

        result = str(
            stats.get(
                "Result",
                stats.get("result", "")
            )
        ).strip()

        if result == "1":
            wins += 1

        elif result == "0":
            losses += 1

        # =========================
        # RATING
        # =========================

        rating = _get_rating(stats)

        if rating is not None:
            ratings.append(rating)

    # =========================
    # ОБЩИЕ ПОКАЗАТЕЛИ
    # =========================

    total_matches = wins + losses

    if deaths > 0:
        kd = kills / deaths
    else:
        kd = 0

    if total_matches > 0:
        winrate = (
            wins / total_matches
        ) * 100
    else:
        winrate = 0

    if ratings:

        average_rating = (
            sum(ratings) /
            len(ratings)
        )

        best_rating = max(ratings)

    else:

        average_rating = None
        best_rating = None

    return {
        "matches": len(player_stats),
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


# =========================
# МОЯ СТАТИСТИКА
# =========================

async def my_stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

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

    # =========================
    # ПРОВЕРКА FACEIT
    # =========================

    if not faceit_id:

        context.user_data[
            "waiting_for_faceit"
        ] = True

        await update.message.reply_text(
            "🔗 Сначала отправь ссылку "
            "на свой FACEIT-профиль.",
            reply_markup=main_keyboard
        )

        return

    # =========================
    # ЗАГРУЗКА
    # =========================

    await update.message.reply_text(
        "📊 Загружаю статистику FACEIT...\n\n"
        "Считаю последние 100 матчей."
    )

    try:

        result = calculate_faceit_stats(
            faceit_id,
            limit=100
        )

        ratings = result["ratings"]

        # =========================
        # РЕЙТИНГИ
        # =========================

        count_180 = sum(
            1
            for x in ratings
            if x >= 1.80
        )

        count_170 = sum(
            1
            for x in ratings
            if x >= 1.70
        )

        count_160 = sum(
            1
            for x in ratings
            if x >= 1.60
        )

        count_150 = sum(
            1
            for x in ratings
            if x >= 1.50
        )

        # =========================
        # СРЕДНИЙ RATING
        # =========================

        if result["average_rating"] is None:

            average_rating = "—"

            rating_note = (
                "\n\n"
                "⚠️ FACEIT не передал "
                "личный Rating через API."
            )

        else:

            average_rating = (
                f"{result['average_rating']:.2f}"
            )

            rating_note = ""

        # =========================
        # ЛУЧШИЙ RATING
        # =========================

        if result["best_rating"] is None:

            best_rating = "—"

        else:

            best_rating = (
                f"{result['best_rating']:.2f}"
            )

        # =========================
        # ФОРМИРУЕМ СООБЩЕНИЕ
        # =========================

        message = (

            f"🎮 FACEIT Stats — {nickname}\n"
            f"━━━━━━━━━━━━━━\n\n"

            f"📊 Матчей: "
            f"{result['matches']}\n"

            f"🔎 Обработано: "
            f"{result['processed']}\n\n"

            f"🔥 Rating ≥ 1.80: "
            f"{count_180}\n"

            f"⚡ Rating ≥ 1.70: "
            f"{count_170}\n"

            f"📈 Rating ≥ 1.60: "
            f"{count_160}\n"

            f"📊 Rating ≥ 1.50: "
            f"{count_150}\n\n"

            f"📈 Средний Rating: "
            f"{average_rating}\n"

            f"🚀 Лучший Rating: "
            f"{best_rating}\n\n"

            f"🎯 K/D: "
            f"{result['kd']:.2f}\n"

            f"🔫 Kills: "
            f"{result['kills']}\n"

            f"💀 Deaths: "
            f"{result['deaths']}\n\n"

            f"🏆 Победы: "
            f"{result['wins']}\n"

            f"💀 Поражения: "
            f"{result['losses']}\n"

            f"📌 Winrate: "
            f"{result['winrate']:.1f}%"

            f"{rating_note}"
        )

        await update.message.reply_text(
            message,
            reply_markup=main_keyboard
        )

    except Exception as e:

        print(
            "STATS ERROR:",
            repr(e)
        )

        await update.message.reply_text(
            "❌ Не удалось получить "
            "статистику FACEIT.\n\n"
            "Попробуй ещё раз через "
            "несколько секунд.",
            reply_markup=main_keyboard
        )
