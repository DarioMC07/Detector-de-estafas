"""Pruebas para el bot de Telegram de Mensaje Seguro."""

import pytest
from unittest.mock import AsyncMock, MagicMock
import httpx

from app.main import create_app
from app.predictor import Predictor
from bot.api_client import (
    APIClientError,
    APIModelUnavailableError,
    APINotAvailableError,
    APITimeoutError,
    FraudDetectionAPIClient,
)
from bot.config import MAX_TEXT_LENGTH
from bot.formatter import format_analysis_response
from bot.handlers import (
    HELP_TEXT,
    NON_TEXT_TEXT,
    START_TEXT,
    help_handler,
    non_text_handler,
    start_handler,
    text_message_handler,
)


@pytest.fixture
def real_api_client(trained_artifact):
    """Cliente HTTP que apunta directamente a la app FastAPI real cargada con el modelo."""
    model_path, _ = trained_artifact
    app = create_app(model_path)
    app.state.predictor = Predictor(model_path)
    transport = httpx.ASGITransport(app=app)
    async_client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return FraudDetectionAPIClient(base_url="http://testserver", async_client=async_client)


def create_fake_update(text=None, is_command=False, has_message=True):
    """Crea un objeto Update simulado para pruebas de handlers."""
    update = MagicMock()
    if not has_message:
        update.message = None
        return update

    message = MagicMock()
    message.text = text
    message.reply_text = AsyncMock()
    update.message = message
    return update


# ============================================================================
# 1. PRUEBAS DE COMANDOS BÁSICOS Y TIPOS DE CONTENIDO
# ============================================================================

@pytest.mark.anyio
async def test_start_command():
    update = create_fake_update("/start")
    context = MagicMock()
    await start_handler(update, context)
    update.message.reply_text.assert_awaited_once_with(START_TEXT, parse_mode="Markdown")


@pytest.mark.anyio
async def test_help_command():
    update = create_fake_update("/ayuda")
    context = MagicMock()
    await help_handler(update, context)
    update.message.reply_text.assert_awaited_once_with(HELP_TEXT, parse_mode="Markdown")


@pytest.mark.anyio
async def test_non_text_content():
    """Imágenes, audios, stickers, documentos o videos deben recibir aviso amigable."""
    update = create_fake_update(text=None)
    context = MagicMock()
    await non_text_handler(update, context)
    update.message.reply_text.assert_awaited_once_with(NON_TEXT_TEXT)


# ============================================================================
# 2. PRUEBAS DE VALIDACIÓN DE ENTRADA (VACÍO Y EXCESO DE LONGITUD)
# ============================================================================

@pytest.mark.anyio
async def test_empty_message_validation():
    update = create_fake_update("   \n\t  ")
    context = MagicMock()
    await text_message_handler(update, context)
    update.message.reply_text.assert_awaited_once()
    reply = update.message.reply_text.await_args[0][0]
    assert "está vacío" in reply


@pytest.mark.anyio
async def test_message_too_long_validation():
    too_long = "A" * (MAX_TEXT_LENGTH + 1)
    update = create_fake_update(too_long)
    context = MagicMock()
    await text_message_handler(update, context)
    update.message.reply_text.assert_awaited_once()
    reply = update.message.reply_text.await_args[0][0]
    assert "demasiado largo" in reply
    assert str(MAX_TEXT_LENGTH) in reply


# ============================================================================
# 3. PRUEBAS CON EL MODELO REAL Y LA API REAL
# ============================================================================

@pytest.mark.anyio
async def test_safe_message_with_real_model(real_api_client):
    """Mensaje seguro: debe clasificarse como legítimo y nivel de riesgo bajo."""
    safe_text = "Hola, nos vemos mañana para comer en el restaurante."
    result = await real_api_client.analyze_message(safe_text)
    assert result["etiqueta_modelo"] == "legitimo"
    assert result["nivel"] == "bajo"

    formatted = format_analysis_response(result)
    assert "MENSAJE APARENTEMENTE LEGÍTIMO" in formatted
    assert "Nivel de riesgo: BAJO" in formatted
    assert "Recomendación:" in formatted


@pytest.mark.anyio
async def test_fraudulent_message_with_real_model(real_api_client):
    """Mensaje claramente fraudulento: debe clasificarse como fraudulento y nivel de riesgo alto."""
    fraud_text = "URGENTE: Tu cuenta bancaria está bloqueada. Paga y transfiere tu clave ahora mismo."
    result = await real_api_client.analyze_message(fraud_text)
    assert result["etiqueta_modelo"] == "fraudulento"
    assert result["nivel"] == "alto"
    assert len(result["senales"]) > 0

    formatted = format_analysis_response(result)
    assert "POSIBLE ESTAFA" in formatted
    assert "Nivel de riesgo: ALTO" in formatted
    assert "Indicadores detectados:" in formatted
    assert "Recomendación:" in formatted


@pytest.mark.anyio
async def test_suspicious_message_with_signals(real_api_client):
    """Mensaje sospechoso con señales claras como premios o enlaces."""
    suspicious_text = "Felicidades, ganaste un premio de 5000. Entra a https://premio.example.com"
    result = await real_api_client.analyze_message(suspicious_text)
    formatted = format_analysis_response(result)
    assert "Indicadores detectados:" in formatted
    assert ("premio" in formatted.lower() or "enlace" in formatted.lower() or "Premios" in formatted)


def test_uncertainty_formatting():
    """Verifica que el formateador maneje adecuadamente avisos de incertidumbre."""
    mock_data = {
        "categoria": "Fraudulento según el modelo",
        "etiqueta_modelo": "fraudulento",
        "nivel": "alto",
        "incertidumbre": True,
        "aviso_incertidumbre": "Puntuación en zona intermedia.",
        "senales": [{"codigo": "urgencia", "titulo": "Presión o plazo para actuar"}],
        "recomendaciones": ["Pide ayuda antes de actuar."],
        "datos_demostrativos": True,
        "aviso": "Esta evaluación es orientativa",
    }
    formatted = format_analysis_response(mock_data)
    assert "RESULTADO INCIERTO" in formatted
    assert "Nivel de riesgo: MEDIO" in formatted
    assert "Nota de incertidumbre:" in formatted
    assert "Puntuación en zona intermedia." in formatted


# ============================================================================
# 4. PRUEBAS DE MANEJO DE ERRORES (API APAGADA, MODELO NO DISPONIBLE, ETC.)
# ============================================================================

@pytest.mark.anyio
async def test_api_offline_handling():
    """Simula que la API no está disponible / apagada."""
    mock_api_client = MagicMock()
    mock_api_client.analyze_message = AsyncMock(
        side_effect=APINotAvailableError(
            "Conexión rechazada",
            "⚠️ No pude conectar con el servicio de análisis en este momento. Intenta nuevamente en unos segundos.",
        )
    )

    update = create_fake_update("Revisa este texto sospechoso")
    context = MagicMock()
    context.bot_data = {"api_client": mock_api_client}

    await text_message_handler(update, context)
    update.message.reply_text.assert_awaited_once()
    reply = update.message.reply_text.await_args[0][0]
    assert "No pude conectar con el servicio de análisis" in reply


@pytest.mark.anyio
async def test_model_unavailable_handling():
    """Simula que la API responde 503 (modelo no disponible)."""
    mock_api_client = MagicMock()
    mock_api_client.analyze_message = AsyncMock(
        side_effect=APIModelUnavailableError(
            "503",
            "⚠️ El modelo de detección no está disponible temporalmente. Intenta nuevamente en unos minutos.",
        )
    )

    update = create_fake_update("Hola, qué tal?")
    context = MagicMock()
    context.bot_data = {"api_client": mock_api_client}

    await text_message_handler(update, context)
    update.message.reply_text.assert_awaited_once()
    reply = update.message.reply_text.await_args[0][0]
    assert "modelo de detección no está disponible" in reply


@pytest.mark.anyio
async def test_unexpected_error_does_not_leak_details():
    """Un error inesperado nunca debe exponer trazas técnicas al usuario."""
    mock_api_client = MagicMock()
    mock_api_client.analyze_message = AsyncMock(side_effect=Exception("Database password: secret123"))

    update = create_fake_update("Mensaje que causa error interno")
    context = MagicMock()
    context.bot_data = {"api_client": mock_api_client}

    await text_message_handler(update, context)
    update.message.reply_text.assert_awaited_once()
    reply = update.message.reply_text.await_args[0][0]
    assert "secret123" not in reply
    assert "Database password" not in reply
    assert "No pude analizar el mensaje en este momento" in reply
