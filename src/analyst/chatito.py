"""
Chatito — Analista de viabilidad de apuestas de fútbol.
Evalúa cada partido y devuelve un score de confianza 0-100.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from loguru import logger


@dataclass
class TeamStats:
    name: str
    form: list[str]           # Últimos 10 resultados: ['W','D','L',...]
    goals_scored_avg: float
    goals_conceded_avg: float
    home_win_rate: float      # 0.0 - 1.0
    away_win_rate: float
    injured_key_players: int  # Cantidad de titulares lesionados
    suspended_players: int


@dataclass
class MatchData:
    match_id: int
    league: str
    home_team: TeamStats
    away_team: TeamStats
    h2h_home_wins: int        # Head-to-head últimos 10
    h2h_away_wins: int
    h2h_draws: int
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
    recommendation: str       # "Gana Local" | "Gana Visitante" | "Empate" | "Ambos Anotan" | "Más de 2.5"
    confidence_score: float   # 0-100
    confidence_level: str     # "Alta" | "Media" | "Baja"
    betano_odds: float
    implied_prob_betano: float  # % que implica la cuota de Betano
    chatito_prob: float         # % que calcula Chatito
    value_pct: float            # diferencia (ventaja sobre la casa)
    breakdown: dict             # detalle de puntajes por factor
    match_datetime: str
    emoji: str


class Chatito:
    """
    Analista principal. Pondera 5 factores y entrega el pick más fuerte del partido.
    """

    WEIGHTS = {
        "forma_reciente":   0.25,
        "h2h":              0.20,
        "lesionados":       0.20,
        "local_visitante":  0.15,
        "value_betano":     0.20,
    }

    MIN_SCORE = 0.0    # Sin umbral — prueba de envío a Telegram

    def analyze(self, match: MatchData) -> Optional[PickResult]:
        logger.info(f"Chatito analizando: {match.home_team.name} vs {match.away_team.name}")

        scores = {
            "forma_reciente":  self._score_form(match),
            "h2h":             self._score_h2h(match),
            "lesionados":      self._score_injuries(match),
            "local_visitante": self._score_home_away(match),
        }

        # Determinar el pick más fuerte antes de evaluar value
        pick, chatito_prob = self._best_pick(match, scores)
        betano_odds = self._odds_for_pick(pick, match)
        implied_prob = self._implied_prob(betano_odds)
        value_pct = chatito_prob - implied_prob

        scores["value_betano"] = self._score_value(value_pct)

        total = sum(scores[k] * 100 * self.WEIGHTS[k] for k in scores)
        total = round(total, 1)

        if total < self.MIN_SCORE:
            logger.info(f"Score {total} < {self.MIN_SCORE} — partido descartado")
            return None

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
        )

    # ──────────────────────────────────────────────
    # Factores de análisis
    # ──────────────────────────────────────────────

    def _has_data(self, match: MatchData) -> bool:
        """Detecta si hay datos reales de historial."""
        return bool(match.home_team.form) and bool(match.away_team.form)

    def _score_form(self, match: MatchData) -> float:
        """Puntúa la forma reciente de ambos equipos (últimos 10 partidos)."""
        if not self._has_data(match):
            # Sin historial: usar promedios de goles como proxy de forma
            home_att = min(match.home_team.goals_scored_avg / 2.5, 1.0)
            away_att = min(match.away_team.goals_scored_avg / 2.5, 1.0)
            if home_att == away_att:
                return 0.5
            return 0.5 + ((home_att - away_att) * 0.3)

        def form_points(form: list[str]) -> float:
            pts = {"W": 3, "D": 1, "L": 0}
            total_pts = sum(pts.get(r, 0) for r in form[-10:])
            max_pts = len(form[-10:]) * 3
            return total_pts / max_pts if max_pts else 0.5

        home_form = form_points(match.home_team.form)
        away_form = form_points(match.away_team.form)
        diff = home_form - away_form
        return 0.5 + (diff * 0.5)

    def _score_h2h(self, match: MatchData) -> float:
        """Historial head-to-head."""
        total = match.h2h_home_wins + match.h2h_away_wins + match.h2h_draws
        if total == 0:
            return 0.5
        home_rate = match.h2h_home_wins / total
        away_rate = match.h2h_away_wins / total
        return 0.5 + ((home_rate - away_rate) * 0.5)

    def _score_injuries(self, match: MatchData) -> float:
        """Penaliza al equipo con más lesionados clave."""
        home_pen = min(match.home_team.injured_key_players + match.home_team.suspended_players, 5) / 5
        away_pen = min(match.away_team.injured_key_players + match.away_team.suspended_players, 5) / 5
        # Si el local tiene más lesionados, score baja; si el visitante, sube
        return 0.5 + ((away_pen - home_pen) * 0.5)

    def _score_home_away(self, match: MatchData) -> float:
        """Ventaja de jugar de local."""
        home_rate = match.home_team.home_win_rate
        away_rate = match.away_team.away_win_rate
        return 0.5 + ((home_rate - away_rate) * 0.5)

    def _score_value(self, value_pct: float) -> float:
        """Qué tan buena es la cuota de Betano vs nuestra probabilidad."""
        if value_pct >= 15:
            return 1.0
        elif value_pct >= 8:
            return 0.8
        elif value_pct >= 3:
            return 0.6
        elif value_pct >= 0:
            return 0.4
        else:
            return 0.1  # Betano paga menos de lo que vale → sin value

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────

    def _best_pick(self, match: MatchData, scores: dict) -> tuple[str, float]:
        """Decide cuál resultado tiene más probabilidad según Chatito."""
        partial = (
            scores["forma_reciente"] * self.WEIGHTS["forma_reciente"] +
            scores["h2h"] * self.WEIGHTS["h2h"] +
            scores["lesionados"] * self.WEIGHTS["lesionados"] +
            scores["local_visitante"] * self.WEIGHTS["local_visitante"]
        )
        total_w = sum(v for k, v in self.WEIGHTS.items() if k != "value_betano")
        home_prob = partial / total_w * 100

        # Probabilidad ajustada con promedios de goles para "Ambos Anotan"
        home_goals = match.home_team.goals_scored_avg
        away_goals = match.away_team.goals_scored_avg
        both_score_prob = min((home_goals * away_goals) / 2.5 * 100, 85)
        over_25_prob = min((home_goals + away_goals) / 3.5 * 100, 85)

        away_prob = 100 - home_prob - 15  # ~15% para empate base
        draw_prob = 15

        options = {
            "Gana Local":      home_prob,
            "Gana Visitante":  away_prob,
            "Empate":          draw_prob,
            "Ambos Anotan":    both_score_prob,
            "Más de 2.5":      over_25_prob,
        }
        best = max(options, key=options.get)
        return best, options[best]

    def _odds_for_pick(self, pick: str, match: MatchData) -> float:
        mapping = {
            "Gana Local":     match.betano_home_odds,
            "Gana Visitante": match.betano_away_odds,
            "Empate":         match.betano_draw_odds,
            "Ambos Anotan":   1.75,  # Cuota típica — se reemplaza con scraping real
            "Más de 2.5":     1.80,
        }
        return mapping.get(pick, 2.0)

    def _implied_prob(self, odds: float) -> float:
        if odds <= 0:
            return 50.0
        return round((1 / odds) * 100, 1)

    def _level(self, score: float) -> str:
        if score >= 85:
            return "Alta"
        elif score >= 70:
            return "Media"
        return "Baja"

    def _emoji(self, score: float) -> str:
        if score >= 85:
            return "🟢"
        elif score >= 70:
            return "🟡"
        return "🔴"
