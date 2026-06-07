from dotenv import load_dotenv
load_dotenv()
from src.data.api_football import _get

# Ver qué partidos hay esta semana sin filtrar liga
for fecha in ["2026-06-06", "2026-06-07", "2026-06-08"]:
    data = _get("fixtures", {"date": fecha})
    partidos = data.get("response", [])
    print(f"\n{fecha}: {len(partidos)} partidos totales")
    for f in partidos[:8]:
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]
        league = f["league"]["name"]
        country = f["league"]["country"]
        print(f"  [{country}] {home} vs {away} — {league}")
