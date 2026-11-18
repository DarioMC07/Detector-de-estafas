"""Punto de entrada para ejecutar el bot de Telegram de Mensaje Seguro."""

import logging
import sys
from telegram.ext import Application, ApplicationBuilder, CommandHandler, MessageHandler, filters
from telegram.request import HTTPXRequest

from bot.api_client import FraudDetectionAPIClient
from bot.config import (
    API_TIMEOUT_SECONDS,
    API_URL,
    TELEGRAM_BOT_TOKEN,
    is_token_configured,
)
from bot.handlers import (
    help_handler,
    non_text_handler,
    start_handler,
    text_message_handler,
)

# Configurar logging seguro (no muestra tokens ni datos privados)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("mensaje_seguro_bot")


def build_bot_app(token: str, api_client: FraudDetectionAPIClient | None = None) -> Application:
    """Construye y configura la aplicación de Telegram con sus manejadores y timeouts ampliados."""
    # Ampliar timeouts de conexión y lectura para evitar caídas por latencia de red
    request_config = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )
    application = ApplicationBuilder().token(token).request(request_config).build()

    client = api_client or FraudDetectionAPIClient(base_url=API_URL, timeout=API_TIMEOUT_SECONDS)
    application.bot_data["api_client"] = client

    # Registro de comandos
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler(["ayuda", "help"], help_handler))

    # Manejador de texto (normal y reenviado, excluyendo comandos)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler)
    )

    # Manejador para contenido no textual (fotos, audios, documentos, stickers, etc.)
    application.add_handler(
        MessageHandler(~filters.TEXT & ~filters.COMMAND, non_text_handler)
    )

    return application


def main() -> None:
    """Valida la configuración e inicia el bot con long polling."""
    if not is_token_configured():
        sys.stderr.write(
            "\n[ERROR] TELEGRAM_BOT_TOKEN no está configurado o contiene un valor de ejemplo.\n"
            "Por favor crea o edita el archivo .env en la raíz del proyecto y define tu token:\n"
            "TELEGRAM_BOT_TOKEN=tu_token_real_de_BotFather\n\n"
        )
        sys.exit(1)

    logger.info("Iniciando Bot de Telegram 'Mensaje Seguro' con long polling...")
    logger.info("Conectando con la API en: %s", API_URL)

    app = build_bot_app(TELEGRAM_BOT_TOKEN)
    # bootstrap_retries=5 permite reintentar si hay micro-cortes o latencia en el inicio
    app.run_polling(bootstrap_retries=5, drop_pending_updates=True)


if __name__ == "__main__":
    main()

