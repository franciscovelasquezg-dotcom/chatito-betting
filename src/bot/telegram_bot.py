"""
Bot de Telegram — Chatito Picks del Día.
Envía los 5 mejores picks cada mañana.
"""

import os
import asyncio
from telegram import Bot
from telegram.constants import ParseMode
from loguru import logger
from src.analyst.chatito import PickResult


def format_estrella(pick: PickResult) -> str:
    return (
        "🌟 *PICK ESTRELLA DEL DÍA* 🌟\n"
        "╔══════════════════════╗\n"
        f"  {pick.league}\n"
        f"  {pick.home_team} vs {pick.away_team}\n"
        f"  Pick: *{pick.recommendation}*\n"
        f"  Confianza: *{pick.confidence_score}/100*\n"
        f"  Cuota Betano: *{pick.betano_odds}*\n"
        f"  Value: *+{pick.value_pct}%* 🔥\n"
        f"  🕐 {pick.match_datetime[:16].replace('T', ' ')}\n"
        "╚══════════════════════╝"
    )


def format_pick(pick: PickResult, rank: int) -> str:
    return (
        f"{pick.emoji} *#{rank} — {pick.league}*\n"
        f"🏟️ {pick.home_team} vs {pick.away_team}\n"
        f"📌 Pick: *{pick.recommendation}*\n"
        f"🎯 Confianza: *{pick.confidence_score}/100* ({pick.confidence_level})\n"
        f"💰 Cuota Betano: *{pick.betano_odds}*\n"
        f"📊 Chatito: {pick.chatito_prob}% | Betano: {pick.implied_prob_betano}%\n"
        f"⚡ Value: *+{pick.value_pct}%*\n"
        f"🕐 {pick.match_datetime[:16].replace('T', ' ')}"
    )


def format_daily_message(picks: list[PickResult]) -> str:
    estrella = picks[0]
    resto = picks[1:]

    header = (
        "🤖 *CHATITO — PICKS DEL DÍA* ⚽\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    cuerpo_estrella = format_estrella(estrella)
    cuerpo_resto = "\n\n".join(format_pick(p, i + 2) for i, p in enumerate(resto))
    footer = (
        "\n\n━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ Elige tus 3 favoritos\n"
        "⚠️ _Apuesta con responsabilidad_"
    )
    return header + cuerpo_estrella + "\n\n" + cuerpo_resto + footer


async def send_picks(picks: list[PickResult]) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.error("TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no configurados")
        return

    bot = Bot(token=token)
    message = format_daily_message(picks)

    await bot.send_message(
        chat_id=chat_id,
        text=message,
        parse_mode=ParseMode.MARKDOWN,
    )
    logger.info(f"Picks enviados a Telegram ({len(picks)} picks)")
