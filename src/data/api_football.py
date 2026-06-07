"""
Cliente para API-Football con caché local y requests optimizados.
Plan free: 10 req/min — caché reduce llamadas en ~70%.
"""

from __future__ import annotations
import httpx
import os
import time
from datetime import date
from loguru import logger
from src.analyst.chatito import MatchData, TeamStats
from src.data.cache import get as cache_get, set as cache_set

API_BASE = "https://v3.football.api-sports.io"
REQUEST_DELAY = 6.5  # seg entre requests cuando no hay caché


def _headers() -> dict:
    return {"x-apisports-key": os.getenv("API_FOOTBALL_KEY", "")}


def _get(endpoint: str, params: dict) -> dict:
    key = f"{endpoint}_{sorted(params.items())}"
    cached = cache_get(key)
    if cached is not None:
        logger.debug(f"Cache HIT: {endpoint}")
        return cached

    time.sleep(REQUEST_DELAY)
    url = f"{API_BASE}/{endpoint}"
    with httpx.Client(timeout=20) as client:
        r = client.get(url, headers=_headers(), params=params)
        r.raise_for_status()
        result = r.json()

    cache_set(key, result)
    return result


def get_todays_fixtures(league_ids: list[int], target_date: str | None = None) -> list[dict]:
    from datetime import timedelta
    target = target_date or date.today().isoformat()

    # Si no hay partidos en la fecha exacta, buscar el día más próximo con partidos (hasta 7 días)
    base = date.fromisoformat(target)
    data = _get("fixtures", {"date": target})
    if not data.get("response"):
        for delta in range(1, 8):
            siguiente = (base + timedelta(days=delta)).isoformat()
            data = _get("fixtures", {"date": siguiente})
            if data.get("response"):
                logger.info(f"Sin partidos el {target}, usando {siguiente}")
                target = siguiente
                break
    all_fixtures = data.get("response", [])
    logger.info(f"API devolvió {len(all_fixtures)} partidos para {target}")

    filtered = []
    for f in all_fixtures:
        lid = f["league"]["id"]
        country = f["league"]["country"]
        fixture_type = f["league"].get("type", "")
        league_name = f["league"].get("name", "")
        # Excluir categorías muy bajas o femeninas sub-16
        skip_keywords = ["U16", "U15", "U14", "Reserve", "Youth", "Amateur"]
        if any(k in league_name for k in skip_keywords):
            continue
        if lid in league_ids or fixture_type == "Cup" or country == "World" or fixture_type == "League":
            filtered.append(f)

    logger.info(f"Partidos filtrados: {len(filtered)}")
    return filtered


def get_last_fixtures(team_id: int, last: int = 10) -> list[dict]:
    data = _get("fixtures", {"team": team_id, "last": last})
    return data.get("response", [])


def search_fixture_by_teams(home: str, away: str) -> dict | None:
    from datetime import timedelta, date as d
    today = d.today().isoformat()
    in_7 = (d.today() + timedelta(days=7)).isoformat()
    data = _get("fixtures", {"from": today, "to": in_7})
    fixtures = data.get("response", [])
    home_l = home.lower()
    away_l = away.lower()
    for f in fixtures:
        h = f["teams"]["home"]["name"].lower()
        a = f["teams"]["away"]["name"].lower()
        if home_l in h and away_l in a:
            return f
    for f in fixtures:
        h = f["teams"]["home"]["name"].lower()
        a = f["teams"]["away"]["name"].lower()
        if any(w in h for w in home_l.split()) and any(w in a for w in away_l.split()):
            return f
    return None


def get_h2h(home_id: int, away_id: int, last: int = 10) -> list[dict]:
    # H2H incluye historial de ambos equipos — reemplaza get_last_fixtures + get_h2h
    data = _get("fixtures/headtohead", {"h2h": f"{home_id}-{away_id}", "last": last})
    return data.get("response", [])


def get_odds(fixture_id: int) -> tuple[float, float, float]:
    try:
        data = _get("odds", {"fixture": fixture_id, "bookmaker": 8})
        resp = data.get("response", [])
        if not resp:
            return 2.0, 3.2, 3.5
        for bookmaker in resp[0].get("bookmakers", []):
            for bet in bookmaker.get("bets", []):
                if bet["name"] == "Match Winner":
                    values = {v["value"]: float(v["odd"]) for v in bet["values"]}
                    return values.get("Home", 2.0), values.get("Draw", 3.2), values.get("Away", 3.5)
    except Exception:
        pass
    return 2.0, 3.2, 3.5


def build_team_stats(team_id: int, team_name: str, last_fixtures: list[dict], injuries: list[dict]) -> TeamStats:
    form, scored, conceded = [], [], []
    home_wins = away_wins = home_total = away_total = 0

    for fix in last_fixtures:
        hid = fix["teams"]["home"]["id"]
        hg = fix["goals"]["home"] or 0
        ag = fix["goals"]["away"] or 0
        is_home = (hid == team_id)

        # Forma
        if hg == ag:
            form.append("D")
        elif (is_home and hg > ag) or (not is_home and ag > hg):
            form.append("W")
        else:
            form.append("L")

        # Goles
        if is_home:
            scored.append(hg); conceded.append(ag)
            home_total += 1
            if hg > ag: home_wins += 1
        else:
            scored.append(ag); conceded.append(hg)
            away_total += 1
            if ag > hg: away_wins += 1

    goals_scored_avg = sum(scored) / len(scored) if scored else 1.2
    goals_conceded_avg = sum(conceded) / len(conceded) if conceded else 1.2
    home_win_rate = home_wins / home_total if home_total else 0.5
    away_win_rate = away_wins / away_total if away_total else 0.3

    team_injuries = [i for i in injuries if i["team"]["id"] == team_id]
    injured_key = sum(1 for i in team_injuries if i["player"]["reason"] in ["Injury", "Muscle Injury"])
    suspended = sum(1 for i in team_injuries if i["player"]["reason"] == "Suspended")

    return TeamStats(
        name=team_name,
        form=form,
        goals_scored_avg=round(goals_scored_avg, 2),
        goals_conceded_avg=round(goals_conceded_avg, 2),
        home_win_rate=round(home_win_rate, 2),
        away_win_rate=round(away_win_rate, 2),
        injured_key_players=injured_key,
        suspended_players=suspended,
    )


def build_match_data(fixture: dict, league_id: int) -> MatchData | None:
    try:
        fix_id = fixture["fixture"]["id"]
        home = fixture["teams"]["home"]
        away = fixture["teams"]["away"]
        league_name = fixture["league"]["name"]
        match_dt = fixture["fixture"]["date"]

        # Opción B+C: H2H incluye historial de ambos — 1 sola llamada en vez de 3
        h2h_fixtures = get_h2h(home["id"], away["id"], last=20)

        # Separar fixtures por equipo desde el H2H
        home_fixtures = [f for f in h2h_fixtures if
                         f["teams"]["home"]["id"] == home["id"] or
                         f["teams"]["away"]["id"] == home["id"]][:10]
        away_fixtures = [f for f in h2h_fixtures if
                         f["teams"]["home"]["id"] == away["id"] or
                         f["teams"]["away"]["id"] == away["id"]][:10]

        # Lesionados — 1 llamada
        inj_data = _get("injuries", {"fixture": fix_id})
        injuries = inj_data.get("response", [])

        # Cuotas — 1 llamada (con caché)
        home_odds, draw_odds, away_odds = get_odds(fix_id)

        # H2H stats
        h2h_home_wins = h2h_away_wins = h2h_draws = 0
        pure_h2h = h2h_fixtures[:10]
        for h in pure_h2h:
            hid = h["teams"]["home"]["id"]
            hg = h["goals"]["home"] or 0
            ag = h["goals"]["away"] or 0
            if hg > ag:
                h2h_home_wins += 1 if hid == home["id"] else 0
                h2h_away_wins += 1 if hid == away["id"] else 0
            elif ag > hg:
                h2h_away_wins += 1 if hid != home["id"] else 0
                h2h_home_wins += 1 if hid != away["id"] else 0
            else:
                h2h_draws += 1

        home_stats = build_team_stats(home["id"], home["name"], home_fixtures, injuries)
        away_stats = build_team_stats(away["id"], away["name"], away_fixtures, injuries)

        return MatchData(
            match_id=fix_id,
            league=league_name,
            home_team=home_stats,
            away_team=away_stats,
            h2h_home_wins=h2h_home_wins,
            h2h_away_wins=h2h_away_wins,
            h2h_draws=h2h_draws,
            betano_home_odds=home_odds,
            betano_draw_odds=draw_odds,
            betano_away_odds=away_odds,
            match_datetime=match_dt,
        )
    except Exception as e:
        logger.error(f"Error construyendo MatchData fixture {fixture.get('fixture', {}).get('id')}: {e}")
        return None
