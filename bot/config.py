"""Configuración y variables de entorno para el bot de Telegram."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Ruta raíz del proyecto
ROOT_DIR = Path(__file__).resolve().parents[1]

# Cargar variables de entorno desde el archivo .env si existe
ENV_PATH = ROOT_DIR / ".env"
if ENV_PATH.is_file():
    load_dotenv(ENV_PATH)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")
API_TIMEOUT_SECONDS = float(os.getenv("API_TIMEOUT_SECONDS", "10.0"))
MAX_TEXT_LENGTH = int(os.getenv("MAX_TEXT_LENGTH", "5000"))

PLACEHOLDER_TOKENS = {
    "",
    "token_del_bot",
    "tu_token_aqui_obtenido_de_botfather",
    "pon_aqui_tu_token_de_botfather",
    "your_token_here",
}


def is_token_configured() -> bool:
    """Verifica si el token configurado es válido y no un valor por defecto/ejemplo."""
    return bool(TELEGRAM_BOT_TOKEN) and (TELEGRAM_BOT_TOKEN.lower() not in PLACEHOLDER_TOKENS)

