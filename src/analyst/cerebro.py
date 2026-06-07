"""
Cerebro de Chatito — usa Claude API para responder preguntas
en lenguaje natural basadas en datos de API-Football.
"""

from __future__ import annotations
import os
import anthropic
from loguru import logger


_client = None

def _get_client() -> anthropic.Anthropic:
    global _client
    if not _client:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


SYSTEM_PROMPT = """Eres Chatito, un analista experto en apuestas deportivas de fútbol.
Tu trabajo es responder preguntas sobre partidos, estadísticas y probabilidades de forma clara y directa.

Reglas:
- Responde siempre en español
- Sé conciso pero informativo (máximo 200 palabras)
- Si los datos son insuficientes, dilo claramente y sugiere qué información faltaría
- Usa emojis para hacer la respuesta más legible
- Siempre termina con una recomendación concreta si te preguntan si vale la pena apostar
- Nunca inventes estadísticas — solo usa los datos que se te proporcionan
- Si no hay datos suficientes para recomendar, dilo honestamente
"""


def responder(pregunta: str, contexto_datos: str = "") -> str:
    """
    Genera una respuesta conversacional usando Claude.
    contexto_datos: string con los datos relevantes de la API para esta pregunta.
    """
    try:
        cliente = _get_client()

        mensaje_usuario = pregunta
        if contexto_datos:
            mensaje_usuario = f"Datos disponibles:\n{contexto_datos}\n\nPregunta del usuario: {pregunta}"

        respuesta = cliente.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": mensaje_usuario}],
        )
        return respuesta.content[0].text

    except Exception as e:
        logger.error(f"Error en cerebro Claude: {e}")
        return "❌ No pude procesar esa consulta en este momento. Intenta de nuevo."


def detectar_intencion(texto: str) -> str:
    """
    Detecta qué quiere hacer el usuario.
    Retorna: 'analizar_partido' | 'estadisticas' | 'recomendar' | 'picks_hoy' | 'picks_manana' | 'chat'
    """
    t = texto.lower()
    if " vs " in t or "contra" in t:
        return "analizar_partido"
    if any(w in t for w in ["goles", "estadística", "estadisticas", "historial", "forma", "promedio"]):
        return "estadisticas"
    if any(w in t for w in ["elige", "elije", "recomienda", "cuál apostar", "vale la pena", "conviene"]):
        return "recomendar"
    # Mañana — detectar antes que "hoy"
    if any(w in t for w in ["mañana", "manana", "tomorrow", "siguiente", "próximo", "proximo"]):
        return "picks_manana"
    if any(w in t for w in ["picks", "hoy", "partidos", "apuesta", "apuestas", "segur", "dame", "dame", "3 ", "cinco"]):
        return "picks_hoy"
    return "chat"
