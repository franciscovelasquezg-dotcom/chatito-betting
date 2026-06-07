"""
Handlers de comandos del bot Telegram.
/start, /analizar, /picks
"""

from __future__ import annotations
import os
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
from loguru import logger
from dotenv import load_dotenv

from src.analyst.chatito import Chatito
from src.data.api_football import search_fixture_by_teams, build_match_data
from src.bot.telegram_bot import format_daily_message, format_pick

load_dotenv()
chatito = Chatito()

# Chat IDs autorizados (privado)
_ALLOWED = set(
    int(x.strip())
    for x in os.getenv("ALLOWED_CHAT_IDS", "").split(",")
    if x.strip()
)

def _autorizado(update: Update) -> bool:
    return not _ALLOWED or update.message.chat_id in _ALLOWED

# Memoria de últimos picks enviados por chat_id
_ultimos_picks: dict[int, list] = {}
# Historial de conversación por chat_id
_historial: dict[int, list[dict]] = {}


async def _bloquear(update: Update) -> bool:
    if not _autorizado(update):
        await update.message.reply_text("⛔ Bot privado.")
        return True
    return False


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _bloquear(update): return
    await update.message.reply_text(
        "🤖 *Hola, soy Chatito* — tu analista de apuestas de fútbol.\n\n"
        "📋 *Comandos disponibles:*\n"
        "/picks — top 5 mejores partidos de hoy\n"
        "/manana — top 5 mejores partidos de mañana\n"
        "/analizar `Local vs Visitante` — análisis detallado de un partido\n"
        "/ayuda — ver esta guía\n\n"
        "_Ejemplo: /analizar Real Madrid vs Barcelona_",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _bloquear(update): return
    await cmd_start(update, context)


async def cmd_analizar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _bloquear(update): return
    if not context.args:
        await update.message.reply_text(
            "⚠️ Uso correcto:\n`/analizar Equipo Local vs Equipo Visitante`\n\n"
            "Ejemplo: `/analizar Chile vs Argentina`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    query = " ".join(context.args)
    if " vs " not in query.lower():
        await update.message.reply_text(
            "⚠️ Formato inválido. Usa:\n`/analizar Equipo Local vs Equipo Visitante`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    partes = query.lower().split(" vs ")
    local = partes[0].strip().title()
    visitante = partes[1].strip().title()

    await update.message.reply_text(
        f"🔍 Buscando *{local} vs {visitante}*...\n_Esto puede tomar 20-30 segundos_",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        fixture = await asyncio.to_thread(search_fixture_by_teams, local, visitante)

        if not fixture:
            await update.message.reply_text(
                f"❌ No encontré el partido *{local} vs {visitante}*.\n\n"
                "Verifica los nombres de los equipos (en inglés si es liga extranjera).\n"
                "Ejemplo: `/analizar Manchester City vs Arsenal`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        league_id = fixture["league"]["id"]
        match_data = await asyncio.to_thread(build_match_data, fixture, league_id)

        if not match_data:
            await update.message.reply_text("❌ Error obteniendo estadísticas del partido.")
            return

        result = chatito.analyze(match_data)
        report = _format_analisis(match_data, result)
        await update.message.reply_text(report, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Error en /analizar: {e}")
        await update.message.reply_text("❌ Error al analizar el partido. Intenta de nuevo en unos minutos.")


async def msg_libre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _bloquear(update): return
    """Responde a mensajes de texto libre usando Claude como cerebro."""
    from src.analyst.cerebro import detectar_intencion, responder
    from src.data.api_football import search_fixture_by_teams, build_match_data

    texto = update.message.text.strip()
    texto_lower = texto.lower()
    chat_id = update.message.chat_id

    # Guardar en historial
    hist = _historial.setdefault(chat_id, [])
    hist.append({"role": "user", "content": texto})
    if len(hist) > 10:
        hist.pop(0)

    intencion = detectar_intencion(texto_lower)

    # — Picks de mañana por texto libre —
    if intencion == "picks_manana":
        from datetime import date, timedelta
        manana = (date.today() + timedelta(days=1)).isoformat()
        await update.message.reply_text(
            f"⏳ Buscando los mejores partidos para mañana...\n_Puede tardar 1-2 minutos_",
            parse_mode=ParseMode.MARKDOWN,
        )
        await _enviar_picks_fecha(update, manana)
        return

    # — Picks de hoy por texto libre —
    if intencion == "picks_hoy":
        await update.message.reply_text(
            "⏳ Buscando los mejores partidos de hoy...\n_Puede tardar 1-2 minutos_",
            parse_mode=ParseMode.MARKDOWN,
        )
        await _enviar_picks_fecha(update, None)
        return

    # — Saludos simples — respuesta rápida sin API
    if any(w in texto_lower for w in ["hola", "hi", "buenas", "hey", "ola"]):
        await update.message.reply_text(
            "👋 ¡Hola! Soy *Chatito*, tu analista de apuestas.\n\n"
            "/picks — mejores de hoy\n"
            "/manana — mejores de mañana\n"
            "/analizar `Local vs Visitante` — análisis específico\n\n"
            "O escríbeme directamente, por ejemplo:\n_\"analiza Argentina vs Honduras\"_",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # — Recomendar 3 de los últimos picks —
    if intencion == "recomendar":
        picks = _ultimos_picks.get(chat_id)
        if not picks:
            await update.message.reply_text(
                "🎯 Primero necesito analizar los partidos.\nEscribe /picks o /manana.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        top3 = picks[:3]
        contexto = "Últimos picks analizados:\n" + "\n".join(
            f"- {p.home_team} vs {p.away_team}: pick={p.recommendation}, score={p.confidence_score}, cuota={p.betano_odds}, value={p.value_pct}%"
            for p in top3
        )
        respuesta = await asyncio.to_thread(responder, texto, contexto)
        await update.message.reply_text(respuesta)
        return

    # — Analizar partido específico —
    if intencion == "analizar_partido" or " vs " in texto_lower:
        partes = texto_lower.split(" vs ")
        local = partes[0].replace("analiza", "").replace("analizar", "").strip().title()
        visitante = partes[1].strip().title()
        await update.message.reply_text(f"🔍 Buscando *{local} vs {visitante}*...", parse_mode=ParseMode.MARKDOWN)
        try:
            fixture = await asyncio.to_thread(search_fixture_by_teams, local, visitante)
            if not fixture:
                respuesta = await asyncio.to_thread(
                    responder,
                    f"No encontré el partido {local} vs {visitante} en los próximos 7 días. ¿Qué le digo al usuario?",
                    ""
                )
                await update.message.reply_text(respuesta)
                return
            league_id = fixture["league"]["id"]
            match_data = await asyncio.to_thread(build_match_data, fixture, league_id)
            if match_data:
                result = chatito.analyze(match_data)
                reporte = _format_analisis(match_data, result)
                await update.message.reply_text(reporte, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Error analizando partido: {e}")
            await update.message.reply_text("❌ Error buscando el partido. Intenta con /analizar Equipo1 vs Equipo2")
        return

    # — Cualquier otra pregunta — Claude responde con contexto
    contexto = ""
    picks = _ultimos_picks.get(chat_id)
    if picks:
        contexto = "Últimos picks analizados:\n" + "\n".join(
            f"- {p.home_team} vs {p.away_team}: {p.recommendation}, score={p.confidence_score}"
            for p in picks
        )

    await update.message.reply_text("💭 _Analizando..._", parse_mode=ParseMode.MARKDOWN)
    respuesta = await asyncio.to_thread(responder, texto, contexto)
    await update.message.reply_text(respuesta)


async def cmd_picks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _bloquear(update): return
    await update.message.reply_text(
        "⏳ Analizando los mejores partidos de hoy...\n_Puede tardar 1-2 minutos_",
        parse_mode=ParseMode.MARKDOWN,
    )
    await _enviar_picks_fecha(update, None)


async def cmd_manana(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _bloquear(update): return
    from datetime import date, timedelta
    manana = (date.today() + timedelta(days=1)).isoformat()
    await update.message.reply_text(
        f"⏳ Analizando mejores partidos para mañana ({manana})...\n_Puede tardar 1-2 minutos_",
        parse_mode=ParseMode.MARKDOWN,
    )
    await _enviar_picks_fecha(update, manana)


async def _enviar_picks_fecha(update: Update, fecha: str | None) -> None:
    from src.data.api_football import get_todays_fixtures, build_match_data
    from src.analyst.chatito import Chatito
    from src.bot.telegram_bot import format_daily_message

    TOP_N = 5
    LIGAS = {
        2, 3, 848, 39, 40, 140, 141, 135, 136, 78, 79, 61, 62,
        88, 94, 179, 103, 113, 106, 144, 197, 203, 235,
        11, 13, 14, 71, 72, 262, 239, 242, 244,
        207, 208, 209, 253, 254, 98, 169, 10,
    }

    try:
        chatito = Chatito()
        fixtures = await asyncio.to_thread(get_todays_fixtures, list(LIGAS), fecha)

        if not fixtures:
            await update.message.reply_text("❌ No encontré partidos para esa fecha.")
            return

        picks = []
        for fixture in fixtures:
            league_id = fixture["league"]["id"]
            match_data = await asyncio.to_thread(build_match_data, fixture, league_id)
            if not match_data:
                continue
            result = chatito.analyze(match_data)
            if result:
                picks.append(result)

        picks.sort(key=lambda p: p.confidence_score, reverse=True)
        top = picks[:TOP_N]

        if not top:
            await update.message.reply_text(
                "🔴 Chatito no encontró partidos con suficiente confianza para esa fecha.\n"
                "_Prueba mañana cuando haya más ligas activas._",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Guardar en memoria para poder recomendar 3 después
        _ultimos_picks[update.message.chat_id] = top

        mensaje = format_daily_message(top)
        await update.message.reply_text(mensaje, parse_mode=ParseMode.MARKDOWN)
        await update.message.reply_text(
            "💬 Escríbeme _\"elige 3\"_ y te digo cuáles apostar.",
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.error(f"Error en picks por fecha: {e}")
        await update.message.reply_text("❌ Error obteniendo picks. Intenta de nuevo en unos minutos.")


def _format_analisis(match, result) -> str:
    home = match.home_team
    away = match.away_team

    def forma_str(form: list) -> str:
        iconos = {"W": "✅", "D": "➖", "L": "❌"}
        return " ".join(iconos.get(r, "?") for r in form[-10:])

    lines = [
        f"🔍 *ANÁLISIS: {home.name} vs {away.name}*",
        f"🏆 {match.league}",
        "─────────────────────────",
        f"📊 *Forma {home.name}:*",
        f"  {forma_str(home.form)}",
        f"📊 *Forma {away.name}:*",
        f"  {forma_str(away.form)}",
        "",
        "⚽ *Promedios de goles:*",
        f"  {home.name}: {home.goals_scored_avg} a favor / {home.goals_conceded_avg} en contra",
        f"  {away.name}: {away.goals_scored_avg} a favor / {away.goals_conceded_avg} en contra",
        "",
        "🤕 *Lesionados/Suspendidos:*",
        f"  {home.name}: {home.injured_key_players} lesionados, {home.suspended_players} suspendidos",
        f"  {away.name}: {away.injured_key_players} lesionados, {away.suspended_players} suspendidos",
        "",
        f"🔄 *H2H últimos partidos:*",
        f"  {home.name} {match.h2h_home_wins} | Empate {match.h2h_draws} | {away.name} {match.h2h_away_wins}",
        "",
        f"💰 *Cuotas Betano:*",
        f"  {home.name}: {match.betano_home_odds} | Empate: {match.betano_draw_odds} | {away.name}: {match.betano_away_odds}",
        "─────────────────────────",
    ]

    if result:
        veredicto = "✅ BUENA APUESTA" if result.confidence_score >= 70 else "⚠️ APUESTA RIESGOSA"
        lines += [
            f"🎯 *VEREDICTO CHATITO: {veredicto}*",
            f"  Pick: *{result.recommendation}*",
            f"  Score: *{result.confidence_score}/100* ({result.confidence_level} confianza)",
            f"  Chatito estima: {result.chatito_prob}% | Betano implica: {result.implied_prob_betano}%",
            f"  Value: *+{result.value_pct}%*",
        ]
    else:
        lines += [
            "🔴 *VEREDICTO CHATITO: NO RECOMENDADA*",
            f"  Score bajo el umbral mínimo — demasiada incertidumbre.",
        ]

    lines.append("\n⚠️ _Apuesta con responsabilidad_")
    return "\n".join(lines)


def run_bot() -> None:
    import asyncio
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN no configurado")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ayuda", cmd_ayuda))
    app.add_handler(CommandHandler("analizar", cmd_analizar))
    app.add_handler(CommandHandler("picks", cmd_picks))
    app.add_handler(CommandHandler("manana", cmd_manana))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_libre))

    logger.info("Bot Chatito escuchando comandos...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
