"""
Chatito — Orquestador principal.
Corre diariamente a la hora configurada y envía los picks del día.
"""

import asyncio
import os
import schedule
import time
from dotenv import load_dotenv
from loguru import logger

from src.analyst.chatito import Chatito
from src.data.api_football import get_todays_fixtures, build_match_data
from src.bot.telegram_bot import send_picks

load_dotenv()

# Ligas soportadas (IDs de API-Football)
# Junio = receso europeo → priorizamos Américas, ligas de verano y amistosos
LIGAS = {
    # ── Grandes europeas (activas en verano/otoño) ─
    2:   "Champions League",
    3:   "Europa League",
    848: "Conference League",
    39:  "Premier League",
    40:  "Championship (Inglaterra)",
    140: "La Liga",
    141: "La Liga 2",
    135: "Serie A",
    136: "Serie B",
    78:  "Bundesliga",
    79:  "Bundesliga 2",
    61:  "Ligue 1",
    62:  "Ligue 2",
    88:  "Eredivisie (Holanda)",
    94:  "Primeira Liga (Portugal)",
    179: "Scottish Premiership",
    103: "Eliteserien (Noruega)",
    113: "Allsvenskan (Suecia)",
    106: "Veikkausliiga (Finlandia)",
    144: "Pro League (Bélgica)",
    197: "Super League (Grecia)",
    203: "Süper Lig (Turquía)",
    235: "Premier Liga (Rusia)",
    # ── Sudamérica ────────────────────────────────
    11:  "Copa América",
    13:  "Copa Libertadores",
    14:  "Copa Sudamericana",
    71:  "Brasileirao Serie A",
    72:  "Brasileirao Serie B",
    262: "Liga MX",
    239: "Primera División (Colombia)",
    242: "Liga 1 (Perú)",
    244: "Primera División (Ecuador)",
    253: "Primera Nacional (Argentina)",
    # ── Chile ─────────────────────────────────────
    207: "Primera División Chile",
    208: "Primera B Chile",
    209: "Copa de la Liga Chile",
    # ── USA / resto ───────────────────────────────
    253: "MLS",
    254: "MLS Next Pro",
    98:  "J1 League (Japón)",
    169: "A-League (Australia)",
    # ── Amistosos internacionales ─────────────────
    10:  "Friendlies Internacionales",
}

TOP_N = 5  # Picks diarios a enviar


def run_analysis() -> None:
    logger.info("━━━ Chatito iniciando análisis del día ━━━")
    chatito = Chatito()

    fixtures = get_todays_fixtures(list(LIGAS.keys()))
    logger.info(f"Total partidos encontrados: {len(fixtures)}")

    picks = []
    for fixture in fixtures:
        league_id = fixture["league"]["id"]
        match_data = build_match_data(fixture, league_id)
        if not match_data:
            continue
        result = chatito.analyze(match_data)
        if result:
            picks.append(result)

    # Ordenar por score descendente y tomar top N
    picks.sort(key=lambda p: p.confidence_score, reverse=True)
    top_picks = picks[:TOP_N]

    if not top_picks:
        logger.warning("No se encontraron picks con suficiente confianza hoy.")
        return

    logger.info(f"Picks seleccionados: {len(top_picks)}")
    for p in top_picks:
        logger.info(f"  {p.emoji} {p.home_team} vs {p.away_team} — {p.recommendation} ({p.confidence_score})")

    asyncio.run(send_picks(top_picks))
    logger.info("━━━ Análisis completado ━━━")


def main() -> None:
    import sys
    from src.bot.handlers import run_bot

    modo = os.getenv("MODO", "picks")  # "picks" | "bot" | "ambos"
    hora = os.getenv("PICKS_HORA", "08:00")

    # Modo test: corre análisis ahora y sale
    if os.getenv("RUN_NOW", "false").lower() == "true":
        run_analysis()
        return

    # Modo bot interactivo (escucha /analizar y otros comandos)
    if modo == "bot":
        logger.info("Chatito iniciado en modo BOT INTERACTIVO")
        run_bot()
        return

    # Modo picks diarios automáticos
    logger.info(f"Chatito iniciado en modo PICKS DIARIOS — envío a las {hora}")
    schedule.every().day.at(hora).do(run_analysis)

    # Modo ambos: schedule corre en background, bot en thread principal
    if modo == "ambos":
        import threading
        logger.info("Chatito iniciado en modo AMBOS (picks + bot interactivo)")
        def _schedule_loop():
            while True:
                schedule.run_pending()
                time.sleep(60)
        t = threading.Thread(target=_schedule_loop, daemon=True)
        t.start()
        run_bot()  # bot corre en thread principal
        return

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
