"""
Cliente ESPN API (no oficial) — sin registro, sin límite diario.
Cubre amistosos internacionales, todas las ligas activas y partidos en vivo.
"""

from __future__ import annotations
import httpx
import time
from datetime import date, timedelta
from loguru import logger
from src.analyst.chatito import MatchData, TeamStats
from src.data.cache import get as cache_get, set as cache_set

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
REQUEST_DELAY = 2.0  # sin límite oficial — igual espaciamos


def _get(league_slug: str, params: dict | None = None) -> dict:
    params = params or {}
    cache_key = f"espn_{league_slug}_{sorted(params.items())}"
    cached = cache_get(cache_key)
    if cached is not None:
        logger.debug(f"ESPN Cache HIT: {league_slug}")
        return cached

    time.sleep(REQUEST_DELAY)
    url = f"{BASE}/{league_slug}/scoreboard"
    try:
        with httpx.Client(timeout=15) as client:
            r = client.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            logger.warning(f"ESPN {league_slug}: HTTP {r.status_code}")
            return {}
        data = r.json()
        cache_set(cache_key, data)
        return data
    except Exception as e:
        logger.error(f"ESPN error {league_slug}: {e}")
        return {}


# Slugs de ESPN que cubren lo más relevante
ESPN_LEAGUES = [
    "all",              # todos los partidos del día (amistosos incluidos)
    "usa.1",            # MLS
    "bra.1",            # Brasileirao
    "mex.1",            # Liga MX
    "arg.1",            # Liga Argentina
    "col.1",            # Liga Colombia
    "chi.1",            # Primera División Chile
    "jpn.1",            # J1 League
    "nor.1",            # Eliteserien Noruega
    "swe.1",            # Allsvenskan Suecia
    "tur.1",            # Süper Lig Turquía
    "int.friendlies",   # Amistosos internacionales
]


def _normalize_event(event: dict, league_name: str) -> dict | None:
    """Convierte evento ESPN al formato interno."""
    try:
        comp = event.get("competitions", [{}])[0]
        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            return None

        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

        status = event.get("status", {}).get("type", {}).get("name", "")
        # Solo partidos programados o en vivo
        if status not in ("STATUS_SCHEDULED", "STATUS_IN_PROGRESS", "STATUS_HALFTIME", "STATUS_FINAL"):
            return None

        return {
            "_source": "espn",
            "fixture": {
                "id": int(event.get("id", 0)),
                "date": event.get("date", ""),
                "status": status,
            },
            "league": {
                "id": 0,
                "name": league_name,
                "country": "",
                "type": "League",
            },
            "teams": {
                "home": {
                    "id": int(home.get("id", 0)),
                    "name": home.get("team", {}).get("displayName", "?"),
                    "espn_id": home.get("id"),
                },
                "away": {
                    "id": int(away.get("id", 0)) + 1_000_000,  # namespace para no colisionar con API-Football IDs
                    "name": away.get("team", {}).get("displayName", "?"),
                    "espn_id": away.get("id"),
                },
            },
            "goals": {
                "home": int(home.get("score", 0)) if status == "STATUS_FINAL" else None,
                "away": int(away.get("score", 0)) if status == "STATUS_FINAL" else None,
            },
            "_espn_home_id": home.get("id"),
            "_espn_away_id": away.get("id"),
            "_espn_event_id": event.get("id"),
        }
    except Exception as e:
        logger.debug(f"ESPN normalize error: {e}")
        return None


def get_todays_fixtures(target_date: str) -> list[dict]:
    """Retorna partidos del día desde ESPN, buscando hasta 7 días adelante si no hay."""
    base = date.fromisoformat(target_date)

    for delta in range(8):
        check = base + timedelta(days=delta)
        date_str = check.strftime("%Y%m%d")

        fixtures = []
        seen_ids = set()

        for slug in ESPN_LEAGUES:
            data = _get(slug, {"dates": date_str, "limit": 100})
            events = data.get("events", [])
            league_name = data.get("leagues", [{}])[0].get("name", slug) if data.get("leagues") else slug

            for event in events:
                norm = _normalize_event(event, league_name)
                if norm and norm["fixture"]["id"] not in seen_ids:
                    seen_ids.add(norm["fixture"]["id"])
                    fixtures.append(norm)

        if fixtures:
            if delta > 0:
                logger.info(f"ESPN: sin partidos el {target_date}, usando {check.isoformat()}")
            logger.info(f"ESPN: {len(fixtures)} partidos encontrados para {check.isoformat()}")
            return fixtures

    logger.warning("ESPN: sin partidos en los próximos 7 días")
    return []


def get_team_recent_matches(espn_team_id: str, league_slug: str = "all") -> list[dict]:
    """Obtiene últimos partidos de un equipo desde ESPN."""
    cache_key = f"espn_team_{espn_team_id}_recent"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    time.sleep(REQUEST_DELAY)
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league_slug}/teams/{espn_team_id}/schedule"
    try:
        with httpx.Client(timeout=15) as client:
            r = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []
        events = r.json().get("events", [])
        finished = [e for e in events if e.get("status", {}).get("type", {}).get("name") == "STATUS_FINAL"][-10:]
        cache_set(cache_key, finished)
        return finished
    except Exception:
        return []


def _build_team_stats_espn(team_name: str, team_id: str, events: list[dict], is_home_team: bool) -> TeamStats:
    """Construye TeamStats desde historial ESPN."""
    form, scored, conceded = [], [], []
    home_wins = away_wins = home_total = away_total = 0
    draws = losses = 0
    over25 = btts = clean = 0

    for event in events:
        try:
            comp = event.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])
            home_c = next((c for c in competitors if c.get("homeAway") == "home"), None)
            away_c = next((c for c in competitors if c.get("homeAway") == "away"), None)
            if not home_c or not away_c:
                continue

            hg = int(home_c.get("score", 0) or 0)
            ag = int(away_c.get("score", 0) or 0)
            is_home = home_c.get("id") == team_id

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
        except Exception:
            continue

    n = len(form) or 1
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
        corners_avg=4.5,
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


def build_match_data_espn(fixture: dict) -> MatchData | None:
    """Construye MatchData desde un fixture ESPN."""
    try:
        home = fixture["teams"]["home"]
        away = fixture["teams"]["away"]
        espn_home_id = fixture.get("_espn_home_id", str(home["id"]))
        espn_away_id = fixture.get("_espn_away_id", str(away["id"]))

        home_events = get_team_recent_matches(espn_home_id)
        away_events = get_team_recent_matches(espn_away_id)

        home_stats = _build_team_stats_espn(home["name"], espn_home_id, home_events, True)
        away_stats = _build_team_stats_espn(away["name"], espn_away_id, away_events, False)

        return MatchData(
            match_id=fixture["fixture"]["id"],
            league=fixture["league"]["name"],
            home_team=home_stats,
            away_team=away_stats,
            h2h_home_wins=0,
            h2h_away_wins=0,
            h2h_draws=0,
            h2h_over25_pct=50.0,
            h2h_btts_pct=50.0,
            betano_home_odds=2.0,
            betano_draw_odds=3.2,
            betano_away_odds=3.5,
            match_datetime=fixture["fixture"]["date"],
        )
    except Exception as e:
        logger.error(f"ESPN build_match_data error: {e}")
        return None
