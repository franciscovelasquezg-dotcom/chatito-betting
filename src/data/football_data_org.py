"""
Cliente para football-data.org — API gratuita sin límite diario.
Cubre: CL, EL, PL, La Liga, Serie A, Bundesliga, Ligue 1, Eredivisie,
       Primeira Liga, MLS, Brasileirao, Copa Libertadores y más.
Usada como fuente primaria / fallback cuando API-Football se agota.
"""

from __future__ import annotations
import os
import time
import httpx
from loguru import logger
from src.analyst.chatito import MatchData, TeamStats
from src.data.cache import get as cache_get, set as cache_set

BASE = "https://api.football-data.org/v4"
REQUEST_DELAY = 6.0  # 10 req/min permitidos

# Mapeo competition code → nombre legible
COMPETITION_NAMES = {
    "CL":  "Champions League",
    "EL":  "Europa League",
    "EC":  "Conference League",
    "PL":  "Premier League",
    "PD":  "La Liga",
    "SA":  "Serie A",
    "BL1": "Bundesliga",
    "FL1": "Ligue 1",
    "DED": "Eredivisie",
    "PPL": "Primeira Liga",
    "BSA": "Brasileirao",
    "MLS": "MLS",
    "CLI": "Copa Libertadores",
    "CSA": "Copa Sudamericana",
    "PPD": "Primera División Chile",
}

# Competiciones activas (las que tienen partidos regulares)
ACTIVE_COMPETITIONS = list(COMPETITION_NAMES.keys())


def _headers() -> dict:
    token = os.getenv("FOOTBALL_DATA_TOKEN", "")
    return {"X-Auth-Token": token}


def _get(endpoint: str, params: dict | None = None) -> dict:
    params = params or {}
    cache_key = f"fdo_{endpoint}_{sorted(params.items())}"
    cached = cache_get(cache_key)
    if cached is not None:
        logger.debug(f"FDO Cache HIT: {endpoint}")
        return cached

    time.sleep(REQUEST_DELAY)
    url = f"{BASE}/{endpoint}"
    try:
        with httpx.Client(timeout=20) as client:
            r = client.get(url, headers=_headers(), params=params)
        if r.status_code == 429:
            logger.warning("FDO rate limit — esperando 65s")
            time.sleep(65)
            with httpx.Client(timeout=20) as client:
                r = client.get(url, headers=_headers(), params=params)
        if r.status_code == 403:
            logger.warning(f"FDO 403 en {endpoint} — competición no incluida en plan free")
            return {}
        r.raise_for_status()
        data = r.json()
        cache_set(cache_key, data)
        return data
    except Exception as e:
        logger.error(f"FDO error {endpoint}: {e}")
        return {}


def get_todays_fixtures(target_date: str) -> list[dict]:
    """Retorna partidos del día en formato normalizado compatible con el resto del sistema."""
    from datetime import date, timedelta

    base = date.fromisoformat(target_date)
    for delta in range(8):
        check = (base + timedelta(days=delta)).isoformat()
        data = _get("matches", {"dateFrom": check, "dateTo": check})
        matches = data.get("matches", [])
        if matches:
            if delta > 0:
                logger.info(f"FDO: sin partidos el {target_date}, usando {check}")
            logger.info(f"FDO: {len(matches)} partidos encontrados para {check}")
            return [_normalize_fixture(m) for m in matches]

    logger.warning("FDO: sin partidos en los próximos 7 días")
    return []


def get_team_matches(team_id: int, limit: int = 10) -> list[dict]:
    data = _get(f"teams/{team_id}/matches", {"limit": limit, "status": "FINISHED"})
    return data.get("matches", [])


def get_h2h(match_id: int) -> list[dict]:
    data = _get(f"matches/{match_id}/head2head", {"limit": 10})
    return data.get("matches", [])


def _normalize_fixture(m: dict) -> dict:
    """Convierte un match de football-data.org al formato interno usado por build_match_data_fdo."""
    return {
        "_source": "fdo",
        "fixture": {
            "id": m["id"],
            "date": m.get("utcDate", ""),
        },
        "league": {
            "id": m.get("competition", {}).get("id", 0),
            "name": COMPETITION_NAMES.get(
                m.get("competition", {}).get("code", ""),
                m.get("competition", {}).get("name", "?")
            ),
            "country": m.get("area", {}).get("name", ""),
            "type": "League",
        },
        "teams": {
            "home": {
                "id": m["homeTeam"]["id"],
                "name": m["homeTeam"]["name"],
            },
            "away": {
                "id": m["awayTeam"]["id"],
                "name": m["awayTeam"]["name"],
            },
        },
        "goals": {
            "home": (m.get("score", {}).get("fullTime", {}) or {}).get("home"),
            "away": (m.get("score", {}).get("fullTime", {}) or {}).get("away"),
        },
    }


def _build_team_stats_fdo(team_id: int, team_name: str, matches: list[dict]) -> TeamStats:
    """Construye TeamStats desde partidos de football-data.org (sin corners/tarjetas)."""
    form, scored, conceded = [], [], []
    home_wins = away_wins = home_total = away_total = 0
    draws = losses = 0
    over25 = btts = clean = 0

    for m in matches:
        if m.get("status") != "FINISHED":
            continue
        hid = m["homeTeam"]["id"]
        score = m.get("score", {}).get("fullTime", {}) or {}
        hg = score.get("home") or 0
        ag = score.get("away") or 0
        is_home = (hid == team_id)
        team_scored = hg if is_home else ag
        team_conceded = ag if is_home else hg

        if hg == ag:
            form.append("D"); draws += 1
        elif (is_home and hg > ag) or (not is_home and ag > hg):
            form.append("W")
        else:
            form.append("L"); losses += 1

        scored.append(team_scored)
        conceded.append(team_conceded)

        if is_home:
            home_total += 1
            if hg > ag: home_wins += 1
        else:
            away_total += 1
            if ag > hg: away_wins += 1

        if hg + ag > 2.5: over25 += 1
        if hg > 0 and ag > 0: btts += 1
        if team_conceded == 0: clean += 1

    n = len([m for m in matches if m.get("status") == "FINISHED"]) or 1
    wins = n - draws - losses

    gsa = sum(scored) / len(scored) if scored else 1.2
    gca = sum(conceded) / len(conceded) if conceded else 1.2

    weights = [1, 1.5, 2, 2.5, 3]
    pts_map = {"W": 1, "D": 0.4, "L": 0}
    last5 = form[-5:]
    ms = sum(pts_map.get(r, 0) * weights[i] for i, r in enumerate(last5))
    mm = sum(weights[:len(last5)])

    return TeamStats(
        name=team_name,
        form=form,
        goals_scored_avg=round(gsa, 2),
        goals_conceded_avg=round(gca, 2),
        home_win_rate=round(home_wins / home_total if home_total else 0.5, 2),
        away_win_rate=round(away_wins / away_total if away_total else 0.3, 2),
        win_rate_total=round(wins / n, 2),
        draw_rate=round(draws / n, 2),
        loss_rate=round(losses / n, 2),
        corners_avg=4.5,           # no disponible en FDO
        corners_against_avg=4.2,
        yellow_cards_avg=1.8,
        red_cards_avg=0.1,
        shots_on_target_avg=3.5,
        injured_key_players=0,
        suspended_players=0,
        recent_form_score=round(ms / mm if mm else 0.5, 2),
        clean_sheets_pct=round(clean / n * 100, 1),
        over25_pct=round(over25 / n * 100, 1),
        btts_pct=round(btts / n * 100, 1),
    )


def build_match_data_fdo(fixture: dict) -> MatchData | None:
    """Construye MatchData completo usando football-data.org."""
    try:
        fix_id = fixture["fixture"]["id"]
        home = fixture["teams"]["home"]
        away = fixture["teams"]["away"]
        league_name = fixture["league"]["name"]
        match_dt = fixture["fixture"]["date"]

        home_matches = get_team_matches(home["id"], limit=10)
        away_matches = get_team_matches(away["id"], limit=10)
        h2h_matches = get_h2h(fix_id)

        home_stats = _build_team_stats_fdo(home["id"], home["name"], home_matches)
        away_stats = _build_team_stats_fdo(away["id"], away["name"], away_matches)

        h2h_home_wins = h2h_away_wins = h2h_draws = 0
        h2h_over25 = h2h_btts = 0
        pure = [m for m in h2h_matches if m.get("status") == "FINISHED"][:10]
        for m in pure:
            hid = m["homeTeam"]["id"]
            score = m.get("score", {}).get("fullTime", {}) or {}
            hg = score.get("home") or 0
            ag = score.get("away") or 0
            if hg > ag:
                if hid == home["id"]: h2h_home_wins += 1
                else: h2h_away_wins += 1
            elif ag > hg:
                if hid == away["id"]: h2h_away_wins += 1
                else: h2h_home_wins += 1
            else:
                h2h_draws += 1
            if hg + ag > 2.5: h2h_over25 += 1
            if hg > 0 and ag > 0: h2h_btts += 1

        h2h_n = len(pure) or 1

        return MatchData(
            match_id=fix_id,
            league=league_name,
            home_team=home_stats,
            away_team=away_stats,
            h2h_home_wins=h2h_home_wins,
            h2h_away_wins=h2h_away_wins,
            h2h_draws=h2h_draws,
            h2h_over25_pct=round(h2h_over25 / h2h_n * 100, 1),
            h2h_btts_pct=round(h2h_btts / h2h_n * 100, 1),
            betano_home_odds=2.0,
            betano_draw_odds=3.2,
            betano_away_odds=3.5,
            match_datetime=match_dt,
        )
    except Exception as e:
        logger.error(f"FDO error construyendo MatchData {fixture.get('fixture', {}).get('id')}: {e}")
        return None
