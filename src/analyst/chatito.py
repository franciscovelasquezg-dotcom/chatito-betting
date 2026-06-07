from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from loguru import logger


@dataclass
class TeamStats:
    name: str
    # Forma
    form: list[str]                  # ['W','D','L',...] últimos 10
    # Goles
    goals_scored_avg: float
    goals_conceded_avg: float
    # Victorias
    home_win_rate: float
    away_win_rate: float
    win_rate_total: float            # % victorias totales
    draw_rate: float                 # % empates
    loss_rate: float                 # % derrotas
    # Corners
    corners_avg: float               # promedio corners a favor
    corners_against_avg: float
    # Tarjetas
    yellow_cards_avg: float
    red_cards_avg: float
    # Tiros
    shots_on_target_avg: float
    # Lesionados
    injured_key_players: int
    suspended_players: int
    # Moral (racha reciente — últimos 5)
    recent_form_score: float         # 0-1 basado en últimos 5 partidos
    # Sin goles en contra
    clean_sheets_pct: float          # % partidos sin goles en contra
    # Partidos con +2.5 goles
    over25_pct: float
    # Ambos anotan
    btts_pct: float


@dataclass
class MatchData:
    match_id: int
    league: str
    home_team: TeamStats
    away_team: TeamStats
    h2h_home_wins: int
    h2h_away_wins: int
    h2h_draws: int
    h2h_over25_pct: float            # % H2H con más de 2.5 goles
    h2h_btts_pct: float              # % H2H ambos anotan
    betano_home_odds: float
    betano_draw_odds: float
    betano_away_odds: float
    match_datetime: str


@dataclass
class PickResult:
    match_id: int
    league: str
    home_team: str
    away_team: str
    recommendation: str
    confidence_score: float
    confidence_level: str
    betano_odds: float
    implied_prob_betano: float
    chatito_prob: float
    value_pct: float
    breakdown: dict
    match_datetime: str
    emoji: str
    # Estadísticas clave para mostrar al usuario
    stats_summary: dict = field(default_factory=dict)


class Chatito:
    """
    Analista principal v2 — 8 factores ponderados con estadísticas avanzadas.
    """

    WEIGHTS = {
        "forma_reciente":    0.20,
        "moral_racha":       0.10,   # últimos 5 partidos
        "h2h":               0.15,
        "lesionados":        0.10,
        "local_visitante":   0.10,
        "goles_corners":     0.15,   # análisis ofensivo/defensivo
        "tarjetas_faltas":   0.05,   # agresividad
        "value_betano":      0.15,
    }

    MIN_SCORE = 0.0

    def analyze(self, match: MatchData) -> Optional[PickResult]:
        logger.info(f"Chatito v2 analizando: {match.home_team.name} vs {match.away_team.name}")

        scores = {
            "forma_reciente":   self._score_form(match),
            "moral_racha":      self._score_morale(match),
            "h2h":              self._score_h2h(match),
            "lesionados":       self._score_injuries(match),
            "local_visitante":  self._score_home_away(match),
            "goles_corners":    self._score_goals_corners(match),
            "tarjetas_faltas":  self._score_cards(match),
        }

        pick, chatito_prob = self._best_pick(match, scores)
        betano_odds = self._odds_for_pick(pick, match)
        implied_prob = self._implied_prob(betano_odds)
        value_pct = chatito_prob - implied_prob
        scores["value_betano"] = self._score_value(value_pct)

        total = sum(scores[k] * 100 * self.WEIGHTS[k] for k in scores)
        total = round(total, 1)

        if total < self.MIN_SCORE:
            logger.info(f"Score {total} < {self.MIN_SCORE} — descartado")
            return None

        stats_summary = self._build_stats_summary(match)

        return PickResult(
            match_id=match.match_id,
            league=match.league,
            home_team=match.home_team.name,
            away_team=match.away_team.name,
            recommendation=pick,
            confidence_score=total,
            confidence_level=self._level(total),
            betano_odds=betano_odds,
            implied_prob_betano=round(implied_prob, 1),
            chatito_prob=round(chatito_prob, 1),
            value_pct=round(value_pct, 1),
            breakdown=scores,
            match_datetime=match.match_datetime,
            emoji=self._emoji(total),
            stats_summary=stats_summary,
        )

    # ── Factores ───────────────────────────────────────────

    def _score_form(self, match: MatchData) -> float:
        def pts(form):
            p = {"W": 3, "D": 1, "L": 0}
            total = sum(p.get(r, 0) for r in form[-10:])
            mx = len(form[-10:]) * 3
            return total / mx if mx else 0.5
        if not match.home_team.form and not match.away_team.form:
            # Sin historial: usar win rate
            diff = match.home_team.win_rate_total - match.away_team.win_rate_total
            return 0.5 + (diff * 0.4)
        h = pts(match.home_team.form)
        a = pts(match.away_team.form)
        return 0.5 + ((h - a) * 0.5)

    def _score_morale(self, match: MatchData) -> float:
        """Moral basada en racha de los últimos 5 partidos (más peso a lo reciente)."""
        def recent(form):
            if not form:
                return 0.5
            weights = [1, 1.5, 2, 2.5, 3]  # más peso al partido más reciente
            pts = {"W": 1, "D": 0.4, "L": 0}
            last5 = form[-5:]
            score = sum(pts.get(r, 0) * weights[i] for i, r in enumerate(last5))
            max_score = sum(weights[:len(last5)])
            return score / max_score if max_score else 0.5
        h = recent(match.home_team.form)
        a = recent(match.away_team.form)
        return 0.5 + ((h - a) * 0.5)

    def _score_h2h(self, match: MatchData) -> float:
        total = match.h2h_home_wins + match.h2h_away_wins + match.h2h_draws
        if total == 0:
            return 0.5
        return 0.5 + ((match.h2h_home_wins - match.h2h_away_wins) / total * 0.5)

    def _score_injuries(self, match: MatchData) -> float:
        home_pen = min(match.home_team.injured_key_players + match.home_team.suspended_players, 5) / 5
        away_pen = min(match.away_team.injured_key_players + match.away_team.suspended_players, 5) / 5
        return 0.5 + ((away_pen - home_pen) * 0.5)

    def _score_home_away(self, match: MatchData) -> float:
        return 0.5 + ((match.home_team.home_win_rate - match.away_team.away_win_rate) * 0.5)

    def _score_goals_corners(self, match: MatchData) -> float:
        """Potencial ofensivo combinado — goles, corners, tiros."""
        home = match.home_team
        away = match.away_team
        # Ventaja ofensiva local
        home_att = (home.goals_scored_avg * 0.5 +
                    home.shots_on_target_avg * 0.1 +
                    home.corners_avg * 0.05)
        away_att = (away.goals_scored_avg * 0.5 +
                    away.shots_on_target_avg * 0.1 +
                    away.corners_avg * 0.05)
        # Ventaja defensiva (menos goles en contra = mejor)
        home_def = 1 - min(home.goals_conceded_avg / 3, 1)
        away_def = 1 - min(away.goals_conceded_avg / 3, 1)
        home_score = (home_att + home_def) / 2
        away_score = (away_att + away_def) / 2
        diff = home_score - away_score
        return max(0.0, min(1.0, 0.5 + diff * 0.4))

    def _score_cards(self, match: MatchData) -> float:
        """Equipos más agresivos pueden recibir más tarjetas — ligeramente negativo."""
        home_agg = match.home_team.yellow_cards_avg + match.home_team.red_cards_avg * 3
        away_agg = match.away_team.yellow_cards_avg + match.away_team.red_cards_avg * 3
        # Local con menos tarjetas = ventaja leve
        if home_agg == away_agg:
            return 0.5
        diff = (away_agg - home_agg) / max(home_agg + away_agg, 1)
        return max(0.0, min(1.0, 0.5 + diff * 0.3))

    def _score_value(self, value_pct: float) -> float:
        if value_pct >= 15: return 1.0
        elif value_pct >= 8: return 0.8
        elif value_pct >= 3: return 0.6
        elif value_pct >= 0: return 0.4
        else: return 0.1

    # ── Pick selector ──────────────────────────────────────

    def _best_pick(self, match: MatchData, scores: dict) -> tuple[str, float]:
        home = match.home_team
        away = match.away_team

        # Probabilidades base
        partial_w = sum(self.WEIGHTS[k] for k in scores)
        home_strength = sum(scores[k] * self.WEIGHTS[k] for k in scores) / partial_w
        home_prob = home_strength * 100
        away_prob = (1 - home_strength) * 80
        draw_prob = 100 - home_prob - away_prob

        # Over 2.5 — basado en promedios de goles + H2H + historial
        expected_goals = home.goals_scored_avg + away.goals_scored_avg
        over25_prob = (
            (home.over25_pct + away.over25_pct) / 2 * 0.4 +
            match.h2h_over25_pct * 0.3 +
            min(expected_goals / 3.5, 1) * 100 * 0.3
        )

        # Ambos anotan
        btts_prob = (
            (home.btts_pct + away.btts_pct) / 2 * 0.4 +
            match.h2h_btts_pct * 0.3 +
            min(home.goals_scored_avg * away.goals_scored_avg / 2.5, 1) * 100 * 0.3
        )

        # Corners totales altos (+9.5)
        expected_corners = home.corners_avg + away.corners_avg
        corners_high_prob = min(expected_corners / 11 * 100, 85)

        options = {
            "Gana Local":        max(home_prob, 0),
            "Gana Visitante":    max(away_prob, 0),
            "Empate":            max(draw_prob, 0),
            "Más de 2.5 goles":  over25_prob,
            "Ambos Anotan":      btts_prob,
            "Más de 9.5 corners": corners_high_prob,
        }

        best = max(options, key=options.get)
        return best, round(options[best], 1)

    def _build_stats_summary(self, match: MatchData) -> dict:
        h = match.home_team
        a = match.away_team
        return {
            "forma_home":        h.form[-5:],
            "forma_away":        a.form[-5:],
            "goles_favor_home":  h.goals_scored_avg,
            "goles_contra_home": h.goals_conceded_avg,
            "goles_favor_away":  a.goals_scored_avg,
            "goles_contra_away": a.goals_conceded_avg,
            "win_pct_home":      round(h.win_rate_total * 100, 1),
            "win_pct_away":      round(a.win_rate_total * 100, 1),
            "corners_home":      h.corners_avg,
            "corners_away":      a.corners_avg,
            "yellows_home":      h.yellow_cards_avg,
            "yellows_away":      a.yellow_cards_avg,
            "over25_home":       round(h.over25_pct, 1),
            "over25_away":       round(a.over25_pct, 1),
            "btts_home":         round(h.btts_pct, 1),
            "btts_away":         round(a.btts_pct, 1),
            "clean_sheets_home": round(h.clean_sheets_pct, 1),
            "clean_sheets_away": round(a.clean_sheets_pct, 1),
            "h2h_over25":        round(match.h2h_over25_pct, 1),
            "h2h_btts":          round(match.h2h_btts_pct, 1),
            "lesionados_home":   h.injured_key_players,
            "lesionados_away":   a.injured_key_players,
        }

    def _odds_for_pick(self, pick: str, match: MatchData) -> float:
        mapping = {
            "Gana Local":         match.betano_home_odds,
            "Gana Visitante":     match.betano_away_odds,
            "Empate":             match.betano_draw_odds,
            "Más de 2.5 goles":   1.80,
            "Ambos Anotan":       1.75,
            "Más de 9.5 corners": 1.90,
        }
        return mapping.get(pick, 2.0)

    def _implied_prob(self, odds: float) -> float:
        return round((1 / odds) * 100, 1) if odds > 0 else 50.0

    def _level(self, score: float) -> str:
        if score >= 75: return "Alta"
        elif score >= 60: return "Media"
        return "Baja"

    def _emoji(self, score: float) -> str:
        if score >= 75: return "🟢"
        elif score >= 60: return "🟡"
        return "🔴"
