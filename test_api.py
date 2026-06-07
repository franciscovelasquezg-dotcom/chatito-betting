import os
import httpx
from dotenv import load_dotenv

load_dotenv()

key = os.getenv("API_FOOTBALL_KEY")
if not key or "PONER_API_KEY_AQUI" in key:
    print("❌ Error: API_FOOTBALL_KEY no está configurada en el archivo .env")
    exit(1)

print(f"Probando conexión con API-Football usando la clave: {key[:6]}...{key[-4:] if len(key) > 10 else ''}")

url = "https://v3.football.api-sports.io/status"
headers = {
    "x-apisports-key": key
}

try:
    with httpx.Client(timeout=10) as client:
        r = client.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        
        errors = data.get("errors")
        if errors:
            print(f"❌ La API retornó un error: {errors}")
        else:
            account = data.get("response", {}).get("account", {})
            requests_limit = data.get("response", {}).get("requests", {})
            print("✅ Conexión exitosa!")
            print(f"Usuario: {account.get('firstname')} {account.get('lastname')} ({account.get('email')})")
            print(f"Suscripción: {data.get('response', {}).get('subscription', {}).get('name')}")
            print(f"Límite diario: {requests_limit.get('limit_day')} solicitudes")
            print(f"Solicitudes hoy: {requests_limit.get('current')}")
except Exception as e:
    print(f"❌ Error al conectar a la API: {e}")
