from dotenv import load_dotenv
load_dotenv()
from src.data.api_football import get_todays_fixtures

fixtures = get_todays_fixtures([39,140,135,78,61,71,98,262], target_date="2026-06-07")
print(f"\nPartidos encontrados mañana: {len(fixtures)}")
for f in fixtures[:10]:
    home = f["teams"]["home"]["name"]
    away = f["teams"]["away"]["name"]
    league = f["league"]["name"]
    print(f"  {home} vs {away} — {league}")
