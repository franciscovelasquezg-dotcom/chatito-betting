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
    stats = _stats_line(pick)
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
        f"{stats}"
    )


def _stats_line(pick: PickResult) -> str:
    s = pick.stats_summary
    if not s:
        return ""
    home_form = " ".join({"W": "✅", "D": "➖", "L": "❌"}.get(r, "?") for r in (s.get("forma_home") or []))
    away_form = " ".join({"W": "✅", "D": "➖", "L": "❌"}.get(r, "?") for r in (s.get("forma_away") or []))
    lines = [
        f"  📋 Forma: {home_form} | {away_form}",
        f"  ⚽ Goles/partido: {s.get('goles_favor_home', '?')} vs {s.get('goles_favor_away', '?')}",
        f"  🔝 +2.5 goles: {s.get('over25_home', '?')}% / {s.get('over25_away', '?')}%",
        f"  🎯 BTTS: {s.get('btts_home', '?')}% / {s.get('btts_away', '?')}%",
        f"  🚩 Corners: {s.get('corners_home', '?')} / {s.get('corners_away', '?')} prom",
        f"  🟨 Amarillas: {s.get('yellows_home', '?')} / {s.get('yellows_away', '?')} prom",
    ]
    return "\n" + "\n".join(lines)


def format_pick(pick: PickResult, rank: int) -> str:
    stats = _stats_line(pick)
    return (
        f"{pick.emoji} *#{rank} — {pick.league}*\n"
        f"🏟️ {pick.home_team} vs {pick.away_team}\n"
        f"📌 Pick: *{pick.recommendation}*\n"
        f"🎯 Confianza: *{pick.confidence_score}/100* ({pick.confidence_level})\n"
        f"💰 Cuota Betano: *{pick.betano_odds}*\n"
        f"📊 Chatito: {pick.chatito_prob}% | Betano: {pick.implied_prob_betano}%\n"
        f"⚡ Value: *+{pick.value_pct}%*\n"
        f"🕐 {pick.match_datetime[:16].replace('T', ' ')}"
        f"{stats}"
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
