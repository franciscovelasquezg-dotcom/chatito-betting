#!/bin/bash
# Setup inicial de Chatito en Oracle VPS — ejecutar una sola vez
set -e

echo "=== Chatito VPS Setup ==="

# Instalar Python 3.11+ si no está
python3 --version || sudo dnf install -y python3.11 python3.11-pip

# Clonar repo
cd /home/opc
if [ -d "chatito-betting" ]; then
    cd chatito-betting && git pull
else
    git clone https://github.com/franciscovelasquezg-dotcom/chatito-betting.git
    cd chatito-betting
fi

# Instalar dependencias
pip3 install -r requirements.txt

# Crear .env en el VPS
cat > .env << 'ENVEOF'
TELEGRAM_BOT_TOKEN=COMPLETAR
TELEGRAM_CHAT_ID=7089130086
API_FOOTBALL_KEY=COMPLETAR
ANTHROPIC_API_KEY=COMPLETAR
ALLOWED_CHAT_IDS=7089130086
PICKS_HORA=08:00
RUN_NOW=false
MODO=ambos
ENVEOF

echo "✅ Edita /home/opc/chatito-betting/.env con tus claves reales"
