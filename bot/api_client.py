"""Cliente HTTP para comunicarse con el endpoint /analizar de FastAPI."""

from typing import Any, Dict, Optional
import httpx


class APIClientError(Exception):
    """Excepción base para errores de comunicación con la API."""
    def __init__(self, message: str, user_friendly_message: str):
        super().__init__(message)
        self.user_friendly_message = user_friendly_message


class APINotAvailableError(APIClientError):
    """La API está apagada, inalcanzable o falla la red."""
    pass


class APIModelUnavailableError(APIClientError):
    """El modelo ML no está disponible (HTTP 503)."""
    pass


class APIValidationError(APIClientError):
    """El mensaje enviado falló la validación en la API (HTTP 422)."""
    pass


class APITimeoutError(APIClientError):
    """La API tardó más tiempo del configurado en responder."""
    pass


class FraudDetectionAPIClient:
    """Cliente para interactuar de forma desacoplada y segura con la API de análisis."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        timeout: float = 10.0,
        async_client: Optional[httpx.AsyncClient] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._async_client = async_client

    async def analyze_message(self, text: str) -> Dict[str, Any]:
        """
        Envía un texto a la API de detección de estafas (/analizar).
        
        Devuelve el diccionario con los resultados del análisis.
        Lanza subtipos de APIClientError con un mensaje claro y seguro para el usuario.
        """
        url = f"{self.base_url}/analizar"
        payload = {"texto": text}

        if self._async_client is not None:
            return await self._execute_request(self._async_client, url, payload)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await self._execute_request(client, url, payload)

    async def _execute_request(
        self, client: httpx.AsyncClient, url: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        try:
            response = await client.post(url, json=payload)
        except (httpx.ConnectError, httpx.NetworkError):
            raise APINotAvailableError(
                "No se pudo conectar con la API de análisis.",
                "⚠️ No pude conectar con el servicio de análisis en este momento. Intenta nuevamente en unos segundos.",
            )
        except (httpx.TimeoutException, httpx.ReadTimeout, httpx.ConnectTimeout):
            raise APITimeoutError(
                "Tiempo de espera agotado al consultar la API.",
                "⚠️ El análisis tardó demasiado tiempo en responder. Intenta nuevamente en unos segundos.",
            )
        except Exception as exc:
            raise APINotAvailableError(
                f"Error general de conexión: {type(exc).__name__}",
                "⚠️ Ocurrió un inconveniente al contactar el servicio de análisis. Intenta nuevamente más tarde.",
            )

        if response.status_code == 200:
            try:
                data = response.json()
            except Exception:
                raise APIClientError(
                    "Respuesta JSON mal formada por parte de la API.",
                    "⚠️ La respuesta del servicio de análisis no tuvo el formato esperado. Intenta nuevamente.",
                )
            if not isinstance(data, dict) or "categoria" not in data:
                raise APIClientError(
                    "Estructura inesperada en la respuesta de la API.",
                    "⚠️ La respuesta del servicio de análisis no tuvo el formato esperado. Intenta nuevamente.",
                )
            return data

        if response.status_code == 503:
            raise APIModelUnavailableError(
                "El modelo de Machine Learning no está cargado o no se encuentra disponible (503).",
                "⚠️ El modelo de detección no está disponible temporalmente. Intenta nuevamente en unos minutos.",
            )

        if response.status_code == 422:
            raise APIValidationError(
                "Error de validación 422 devuelto por la API.",
                "⚠️ El mensaje no cumple con los requisitos para ser analizado (puede estar vacío o ser demasiado largo).",
            )

        raise APIClientError(
            f"Error HTTP {response.status_code} inesperado desde la API.",
            "⚠️ No pude analizar el mensaje en este momento. Intenta nuevamente en unos segundos.",
        )

