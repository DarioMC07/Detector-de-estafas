"""Manejadores de comandos y mensajes de Telegram."""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from bot.api_client import APIClientError, FraudDetectionAPIClient
from bot.config import MAX_TEXT_LENGTH
from bot.formatter import format_analysis_response

logger = logging.getLogger("mensaje_seguro_bot")

START_TEXT = (
    "👋 Bienvenido a *Mensaje Seguro*.\n\n"
    "Envíame un mensaje sospechoso y analizaré su contenido para identificar posibles señales de estafa.\n\n"
    "⚠️ El resultado es una evaluación automática y no garantiza que un mensaje sea seguro."
)

HELP_TEXT = (
    "📖 *Guía de uso de Mensaje Seguro:*\n\n"
    "1️⃣ *Enviar o reenviar:* Puedes copiar y pegar un mensaje dudoso (SMS, WhatsApp, correo, etc.) "
    "o reenviarlo directamente a este chat.\n"
    "2️⃣ *Evaluación:* El sistema analizará el texto utilizando el modelo de Machine Learning "
    "y reglas de detección de indicadores.\n"
    "3️⃣ *Resultado:* Recibirás una clasificación, el nivel de riesgo y recomendaciones preventivas.\n\n"
    "⚠️ *Puntos importantes:*\n"
    "• Solo se analiza contenido textual.\n"
    "• No envíes datos personales, claves ni contraseñas reales.\n"
    "• La evaluación es orientativa y sirve como apoyo preventivo."
)

NON_TEXT_TEXT = (
    "⚠️ Por ahora solo puedo analizar mensajes de texto. "
    "Envíame o reenvíame el texto que deseas verificar."
)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde al comando /start."""
    if update.message:
        await update.message.reply_text(START_TEXT, parse_mode="Markdown")


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde al comando /ayuda (o /help)."""
    if update.message:
        await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def non_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja contenido no soportado como imágenes, audios, stickers, documentos o videos."""
    if update.message:
        await update.message.reply_text(NON_TEXT_TEXT)


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja mensajes de texto normales y reenviados para análisis de estafas."""
    if not update.message or update.message.text is None:
        return

    text = update.message.text.strip()

    # Validación 1: Mensaje vacío o compuesto únicamente por espacios
    if not text:
        await update.message.reply_text(
            "⚠️ El mensaje está vacío. Por favor envía o reenvía un texto válido para analizar."
        )
        return

    # Validación 2: Longitud máxima de texto
    if len(text) > MAX_TEXT_LENGTH:
        await update.message.reply_text(
            f"⚠️ El texto es demasiado largo (máximo {MAX_TEXT_LENGTH} caracteres). "
            "Por favor envía un fragmento más corto."
        )
        return

    # Obtener el cliente API desde bot_data o instanciar uno por defecto
    api_client: FraudDetectionAPIClient = context.bot_data.get("api_client")
    if api_client is None:
        from bot.config import API_TIMEOUT_SECONDS, API_URL
        api_client = FraudDetectionAPIClient(base_url=API_URL, timeout=API_TIMEOUT_SECONDS)

    try:
        data = await api_client.analyze_message(text)
        formatted_message = format_analysis_response(data)
        await update.message.reply_text(formatted_message)
    except APIClientError as exc:
        # Errores controlados de la API (API caída, 503, timeout, etc.)
        await update.message.reply_text(exc.user_friendly_message)
    except Exception:
        # Fallback genérico para nunca filtrar trazas técnicas al usuario
        logger.exception("Error inesperado al procesar mensaje en el bot")
        await update.message.reply_text(
            "⚠️ No pude analizar el mensaje en este momento. Intenta nuevamente en unos segundos."
        )

