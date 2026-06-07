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

# Pool de API keys — rota automáticamente cuando una se agota
_api_keys: list[str] = []
_current_key_idx = 0

def _load_keys() -> list[str]:
    keys = []
    # Key principal
    k = os.getenv("API_FOOTBALL_KEY", "").strip()
    if k:
        keys.append(k)
    # Keys de respaldo: API_FOOTBALL_KEY_2, API_FOOTBALL_KEY_3, etc.
    for i in range(2, 10):
        k = os.getenv(f"API_FOOTBALL_KEY_{i}", "").strip()
        if k:
            keys.append(k)
    return keys


def _current_key() -> str:
    global _api_keys
    if not _api_keys:
        _api_keys = _load_keys()
    if not _api_keys:
        return ""
    return _api_keys[_current_key_idx % len(_api_keys)]


def _rotate_key() -> bool:
    global _current_key_idx, _api_keys
    if not _api_keys:
        _api_keys = _load_keys()
    next_idx = _current_key_idx + 1
    if next_idx >= len(_api_keys):
        logger.error("Todas las API keys agotadas por hoy")
        return False
    _current_key_idx = next_idx
    logger.warning(f"API key agotada — rotando a key #{_current_key_idx + 1}")
    return True


def _headers() -> dict:
    return {"x-apisports-key": _current_key()}


def _get(endpoint: str, params: dict) -> dict:
    cache_key = f"{endpoint}_{sorted(params.items())}"
    cached = cache_get(cache_key)
    if cached is not None:
        logger.debug(f"Cache HIT: {endpoint}")
        return cached

    time.sleep(REQUEST_DELAY)
    url = f"{API_BASE}/{endpoint}"

    for attempt in range(len(_load_keys()) + 1):
        with httpx.Client(timeout=20) as client:
            r = client.get(url, headers=_headers(), params=params)

        # 429 = rate limit por minuto → esperar
        if r.status_code == 429:
            logger.warning("Rate limit (429) — esperando 65s")
            time.sleep(65)
            continue

        data = r.json()
        # Detectar límite diario agotado
        errors = data.get("errors", {})
        if isinstance(errors, dict) and "requests" in errors:
            logger.warning(f"Key #{_current_key_idx + 1} agotada: {errors['requests']}")
            if not _rotate_key():
                return {"response": []}
            continue

        r.raise_for_status()
        cache_set(cache_key, data)
        return data

    return {"response": []}


def get_todays_fixtures(league_ids: list[int], target_date: str | None = None) -> list[dict]:
    from datetime import timedelta
    target = target_date or date.today().isoformat()

    # Si no hay partidos en la fecha exacta, buscar el día más próximo con partidos (hasta 7 días)
    base = date.fromisoformat(target)
    data = _get("fixtures", {"date": target})
    if not data.get("response"):
        for delta in range(1, 8):
            siguiente = (base + timedelta(days=delta)).isoformat()
            data_next = _get("fixtures", {"date": siguiente})
            if data_next.get("response"):
                logger.info(f"Sin partidos el {target}, usando {siguiente}")
                target = siguiente
                data = data_next
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


def get_fixture_statistics(fixture_id: int) -> dict:
    """Devuelve estadísticas de un fixture: corners, tarjetas, tiros."""
    data = _get("fixtures/statistics", {"fixture": fixture_id})
    result = {}
    for team_data in data.get("response", []):
        tid = team_data["team"]["id"]
        stats = {s["type"]: s["value"] for s in team_data.get("statistics", [])}
        result[tid] = stats
    return result


def _parse_stat(val) -> float:
    """Convierte valor de estadística a float (puede ser None, int o str)."""
    if val is None:
        return 0.0
    try:
        return float(str(val).replace("%", ""))
    except (ValueError, TypeError):
        return 0.0


def build_team_stats(
    team_id: int,
    team_name: str,
    last_fixtures: list[dict],
    injuries: list[dict],
    fetch_stats: bool = True,
) -> TeamStats:
    form, scored, conceded = [], [], []
    home_wins = away_wins = home_total = away_total = 0
    draws = losses = 0
    over25_count = btts_count = clean_sheets = 0

    corners_list, yellow_list, red_list, shots_list = [], [], [], []

    for fix in last_fixtures:
        hid = fix["teams"]["home"]["id"]
        hg = fix["goals"]["home"] or 0
        ag = fix["goals"]["away"] or 0
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

        total_goals = hg + ag
        if total_goals > 2.5:
            over25_count += 1
        if hg > 0 and ag > 0:
            btts_count += 1
        if team_conceded == 0:
            clean_sheets += 1

        # Estadísticas de fixture (corners, tarjetas, tiros) — solo primeros 5 para ahorrar requests
        if fetch_stats and len(corners_list) < 5:
            fix_id = fix["fixture"]["id"]
            try:
                stats = get_fixture_statistics(fix_id)
                if team_id in stats:
                    ts = stats[team_id]
                    corners_list.append(_parse_stat(ts.get("Corner Kicks")))
                    yellow_list.append(_parse_stat(ts.get("Yellow Cards")))
                    red_list.append(_parse_stat(ts.get("Red Cards")))
                    shots_list.append(_parse_stat(ts.get("Shots on Goal")))
            except Exception:
                pass

    n = len(last_fixtures) or 1
    wins_total = n - draws - losses

    goals_scored_avg = sum(scored) / len(scored) if scored else 1.2
    goals_conceded_avg = sum(conceded) / len(conceded) if conceded else 1.2
    home_win_rate = home_wins / home_total if home_total else 0.5
    away_win_rate = away_wins / away_total if away_total else 0.3

    corners_avg = sum(corners_list) / len(corners_list) if corners_list else 4.5
    corners_against_avg = corners_avg * 0.9  # approx
    yellow_cards_avg = sum(yellow_list) / len(yellow_list) if yellow_list else 1.8
    red_cards_avg = sum(red_list) / len(red_list) if red_list else 0.1
    shots_on_target_avg = sum(shots_list) / len(shots_list) if shots_list else 3.5

    # Moral: weighted last 5
    weights = [1, 1.5, 2, 2.5, 3]
    pts_map = {"W": 1, "D": 0.4, "L": 0}
    last5 = form[-5:]
    morale_score = sum(pts_map.get(r, 0) * weights[i] for i, r in enumerate(last5))
    morale_max = sum(weights[:len(last5)])
    recent_form_score = morale_score / morale_max if morale_max else 0.5

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
        win_rate_total=round(wins_total / n, 2),
        draw_rate=round(draws / n, 2),
        loss_rate=round(losses / n, 2),
        corners_avg=round(corners_avg, 2),
        corners_against_avg=round(corners_against_avg, 2),
        yellow_cards_avg=round(yellow_cards_avg, 2),
        red_cards_avg=round(red_cards_avg, 2),
        shots_on_target_avg=round(shots_on_target_avg, 2),
        injured_key_players=injured_key,
        suspended_players=suspended,
        recent_form_score=round(recent_form_score, 2),
        clean_sheets_pct=round(clean_sheets / n * 100, 1),
        over25_pct=round(over25_count / n * 100, 1),
        btts_pct=round(btts_count / n * 100, 1),
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

        # H2H over25 y btts
        h2h_over25 = sum(1 for h in pure_h2h if (h["goals"]["home"] or 0) + (h["goals"]["away"] or 0) > 2.5)
        h2h_btts = sum(1 for h in pure_h2h if (h["goals"]["home"] or 0) > 0 and (h["goals"]["away"] or 0) > 0)
        h2h_n = len(pure_h2h) or 1

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
            betano_home_odds=home_odds,
            betano_draw_odds=draw_odds,
            betano_away_odds=away_odds,
            match_datetime=match_dt,
        )
    except Exception as e:
        logger.error(f"Error construyendo MatchData fixture {fixture.get('fixture', {}).get('id')}: {e}")
        return None
