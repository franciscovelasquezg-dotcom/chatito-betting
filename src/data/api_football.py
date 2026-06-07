"""
Cliente para API-Football (api-football.com).
Obtiene partidos del día, estadísticas, lesionados y H2H.
"""

import httpx
import os
import time
from datetime import date
from loguru import logger
from src.analyst.chatito import MatchData, TeamStats


API_BASE = "https://v3.football.api-sports.io"
REQUEST_DELAY = 6.5  # segundos entre requests (plan free: 10 req/min)


def _headers() -> dict:
    return {
        "x-apisports-key": os.getenv("API_FOOTBALL_KEY", ""),
    }


def _get(endpoint: str, params: dict) -> dict:
    url = f"{API_BASE}/{endpoint}"
    time.sleep(REQUEST_DELAY)
    with httpx.Client(timeout=20) as client:
        r = client.get(url, headers=_headers(), params=params)
        r.raise_for_status()
        return r.json()


def get_todays_fixtures(league_ids: list[int], target_date: str | None = None) -> list[dict]:
    """
    Retorna partidos del día. Busca todos los partidos de la fecha
    y filtra por las ligas configuradas o por tier mínimo de calidad.
    """
    target = target_date or date.today().isoformat()

    # Traer TODOS los partidos del día de una sola llamada
    data = _get("fixtures", {"date": target})
    all_fixtures = data.get("response", [])
    logger.info(f"API devolvió {len(all_fixtures)} partidos totales para {target}")

    # Filtrar: ligas conocidas O partidos internacionales de selecciones
    filtered = []
    for f in all_fixtures:
        lid = f["league"]["id"]
        country = f["league"]["country"]
        fixture_type = f["league"].get("type", "")
        # Incluir si está en nuestra lista o es partido internacional (Copa/World)
        if lid in league_ids or fixture_type == "Cup" or country == "World":
            filtered.append(f)

    logger.info(f"Partidos en ligas configuradas: {len(filtered)}")
    return filtered


def get_team_stats(team_id: int, league_id: int, season: int = 2025) -> dict:
    data = _get("teams/statistics", {
        "team": team_id,
        "league": league_id,
        "season": season,
    })
    return data.get("response", {})


def get_last_fixtures(team_id: int, last: int = 10) -> list[dict]:
    data = _get("fixtures", {"team": team_id, "last": last})
    return data.get("response", [])


def search_fixture_by_teams(home: str, away: str) -> dict | None:
    """Busca un fixture próximo por nombre de equipos."""
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
    # Búsqueda parcial flexible
    for f in fixtures:
        h = f["teams"]["home"]["name"].lower()
        a = f["teams"]["away"]["name"].lower()
        if any(w in h for w in home_l.split()) and any(w in a for w in away_l.split()):
            return f
    return None


def get_injuries(fixture_id: int) -> list[dict]:
    data = _get("injuries", {"fixture": fixture_id})
    return data.get("response", [])


def get_h2h(home_id: int, away_id: int, last: int = 10) -> list[dict]:
    data = _get("fixtures/headtohead", {
        "h2h": f"{home_id}-{away_id}",
        "last": last,
    })
    return data.get("response", [])


def build_team_stats(team_id: int, team_name: str, league_id: int, last_fixtures: list[dict], injuries: list[dict], is_home: bool) -> TeamStats:
    """Construye TeamStats a partir de los datos crudos de la API."""

    # Forma: últimos 10 resultados
    form = []
    for fix in last_fixtures:
        home_id = fix["teams"]["home"]["id"]
        home_goals = fix["goals"]["home"] or 0
        away_goals = fix["goals"]["away"] or 0
        is_home_team = (home_id == team_id)
        if home_goals == away_goals:
            form.append("D")
        elif is_home_team and home_goals > away_goals:
            form.append("W")
        elif not is_home_team and away_goals > home_goals:
            form.append("W")
        else:
            form.append("L")

    # Promedios de goles
    scored = []
    conceded = []
    for fix in last_fixtures:
        home_id = fix["teams"]["home"]["id"]
        hg = fix["goals"]["home"] or 0
        ag = fix["goals"]["away"] or 0
        if home_id == team_id:
            scored.append(hg)
            conceded.append(ag)
        else:
            scored.append(ag)
            conceded.append(hg)

    goals_scored_avg = sum(scored) / len(scored) if scored else 1.2
    goals_conceded_avg = sum(conceded) / len(conceded) if conceded else 1.2

    # Win rate local/visitante
    home_wins = away_wins = home_total = away_total = 0
    for fix in last_fixtures:
        hid = fix["teams"]["home"]["id"]
        hg = fix["goals"]["home"] or 0
        ag = fix["goals"]["away"] or 0
        if hid == team_id:
            home_total += 1
            if hg > ag:
                home_wins += 1
        else:
            away_total += 1
            if ag > hg:
                away_wins += 1

    home_win_rate = home_wins / home_total if home_total else 0.5
    away_win_rate = away_wins / away_total if away_total else 0.3

    # Lesionados clave (titulares)
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


def get_odds(fixture_id: int) -> tuple[float, float, float]:
    """Retorna cuotas (local, empate, visitante) del fixture."""
    try:
        data = _get("odds", {"fixture": fixture_id, "bookmaker": 8})  # bookmaker 8 = Bet365
        resp = data.get("response", [])
        if not resp:
            return 2.0, 3.2, 3.5
        for bookmaker in resp[0].get("bookmakers", []):
            for bet in bookmaker.get("bets", []):
                if bet["name"] == "Match Winner":
                    values = {v["value"]: float(v["odd"]) for v in bet["values"]}
                    return (
                        values.get("Home", 2.0),
                        values.get("Draw", 3.2),
                        values.get("Away", 3.5),
                    )
    except Exception:
        pass
    return 2.0, 3.2, 3.5


def build_match_data(fixture: dict, league_id: int) -> MatchData | None:
    """Construye el MatchData completo para que Chatito lo analice."""
    try:
        fix_id = fixture["fixture"]["id"]
        home = fixture["teams"]["home"]
        away = fixture["teams"]["away"]
        league_name = fixture["league"]["name"]
        match_dt = fixture["fixture"]["date"]

        # Cuotas reales desde API
        home_odds, draw_odds, away_odds = get_odds(fix_id)

        # Datos históricos
        home_fixtures = get_last_fixtures(home["id"])
        away_fixtures = get_last_fixtures(away["id"])
        injuries = get_injuries(fix_id)
        h2h = get_h2h(home["id"], away["id"])

        # H2H stats
        h2h_home_wins = h2h_away_wins = h2h_draws = 0
        for h in h2h:
            hid = h["teams"]["home"]["id"]
            hg = h["goals"]["home"] or 0
            ag = h["goals"]["away"] or 0
            if hg > ag:
                if hid == home["id"]:
                    h2h_home_wins += 1
                else:
                    h2h_away_wins += 1
            elif ag > hg:
                if hid == away["id"]:
                    h2h_away_wins += 1
                else:
                    h2h_home_wins += 1
            else:
                h2h_draws += 1

        home_stats = build_team_stats(home["id"], home["name"], league_id, home_fixtures, injuries, is_home=True)
        away_stats = build_team_stats(away["id"], away["name"], league_id, away_fixtures, injuries, is_home=False)

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
