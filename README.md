# Chatito — Bot de Picks de Fútbol

Bot Telegram que analiza partidos diarios y entrega los 5 mejores picks.

## Setup

1. Copiar `.env.example` → `.env` y completar las claves
2. Instalar dependencias: `pip install -r requirements.txt`
3. Obtener API key en https://www.api-football.com/ (free tier: 100 req/día)
4. Crear bot Telegram con @BotFather y obtener token
5. Obtener tu chat_id iniciando conversación con el bot y visitando `https://api.telegram.org/bot<TOKEN>/getUpdates`

## Ejecutar

```bash
# Correr ahora (modo prueba)
RUN_NOW=true python main.py

# Modo producción (corre diario a las 08:00)
python main.py
```

## Estructura

```
chatito-betting/
├── main.py                    # Orquestador
├── src/
│   ├── analyst/chatito.py     # Motor de análisis
│   ├── data/api_football.py   # Cliente API-Football
│   └── bot/telegram_bot.py    # Envío a Telegram
└── .env                       # Claves (no commitear)
```
