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

# Crear /etc/chatito.env (fuera del repo, permisos restringidos)
if [ ! -f /etc/chatito.env ]; then
    sudo tee /etc/chatito.env > /dev/null << 'ENVEOF'
TELEGRAM_BOT_TOKEN=COMPLETAR
TELEGRAM_CHAT_ID=COMPLETAR
API_FOOTBALL_KEY=COMPLETAR
ANTHROPIC_API_KEY=COMPLETAR
ALLOWED_CHAT_IDS=COMPLETAR
PICKS_HORA=08:00
RUN_NOW=false
MODO=ambos
ENVEOF
    sudo chmod 600 /etc/chatito.env
    sudo chown opc:opc /etc/chatito.env
    echo "✅ Creado /etc/chatito.env — edítalo con tus claves reales: sudo nano /etc/chatito.env"
else
    echo "ℹ️  /etc/chatito.env ya existe — no sobreescrito"
fi
