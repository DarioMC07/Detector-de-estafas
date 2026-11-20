import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.chat_manager import (
    MAX_CHAT_TEXT,
    ChatMessage,
    ConnectionManager,
    DeviceRegistry,
    normalize_phone,
)
from app.predictor import ModelUnavailable, Predictor
from app.schemas import AnalyzeRequest, AnalyzeResponse, MAX_TEXT_LENGTH
from app.signals import detect_signals, recommendations

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"


def create_app(model_path: Path | None = None, low: float | None = None, high: float | None = None):
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.predictor = Predictor(
            model_path if model_path is not None else Path(os.getenv("MODEL_PATH", str(ROOT / "artifacts" / "modelo.joblib"))),
            low if low is not None else float(os.getenv("UMBRAL_BAJO", "0.35")),
            high if high is not None else float(os.getenv("UMBRAL_ALTO", "0.70")),
        )
        registry_path = Path(os.getenv("CHAT_DEVICES_PATH", str(ROOT / "data" / "dispositivos_chat.json")))
        application.state.chat_manager = ConnectionManager(DeviceRegistry(registry_path))
        yield

    # El esquema JSON es local; no cargar Swagger/ReDoc desde CDN de terceros.
    application = FastAPI(title="Mensaje Seguro", version="2.0.0", lifespan=lifespan,
                          docs_url=None, redoc_url=None)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # El error de Pydantic incluye input por defecto: no devolver el mensaje enviado.
        return JSONResponse(status_code=422, content={
            "detail": f"Envía un objeto JSON con texto: una cadena no vacía de hasta {MAX_TEXT_LENGTH} caracteres, sin campos adicionales."
        })

    @application.exception_handler(ModelUnavailable)
    async def unavailable(request: Request, exc: ModelUnavailable):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @application.middleware("http")
    async def privacy_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; connect-src 'self' ws: wss:; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        return response

    @application.get("/", include_in_schema=False)
    def home():
        return FileResponse(STATIC / "index.html")

    @application.get("/chat", include_in_schema=False)
    def chat_page():
        return FileResponse(STATIC / "chat.html")

    @application.get("/estado")
    def status(request: Request):
        predictor = request.app.state.predictor
        return {
            "modelo_disponible": predictor.available,
            "datos_demostrativos": predictor.metadata.get("datos_demostrativos") if predictor.available else None,
            "longitud_maxima": MAX_TEXT_LENGTH,
        }

    @application.post("/analizar", response_model=AnalyzeResponse)
    def analyze(payload: AnalyzeRequest, request: Request):
        predictor = request.app.state.predictor
        prediction = predictor.classify(payload.texto)
        label = prediction.etiqueta
        category = "Legítimo según el modelo" if label == "legitimo" else "Fraudulento según el modelo"
        level = "bajo" if label == "legitimo" else "alto"
        signals = detect_signals(payload.texto)
        explanations = {
            "legitimo": "El clasificador ha elegido la clase legítimo. Es una predicción del modelo, no una verificación de autenticidad ni una garantía de seguridad.",
            "fraudulento": "El clasificador ha elegido la clase fraudulento. Es una predicción del modelo, no una confirmación de fraude. Comprueba la solicitud por otra vía antes de actuar.",
        }
        explanation = explanations[label] + " La puntuación interna no es una probabilidad real de estafa."
        uncertainty_notice = (
            "Resultado incierto: la puntuación está en la zona intermedia de los umbrales provisionales. "
            "La clase indicada sigue siendo la predicción binaria; no la tomes como concluyente y revisa el mensaje con ayuda."
            if prediction.incertidumbre else None
        )
        if signals:
            explanation += " Las señales siguientes se detectan mediante reglas independientes y no determinan la categoría del modelo."
        else:
            explanation += " Las reglas no encontraron las señales previstas; esto tampoco descarta un fraude."
        return AnalyzeResponse(
            categoria=category, nivel=level, senales=signals, explicacion=explanation,
            etiqueta_modelo=label, incertidumbre=prediction.incertidumbre,
            aviso_incertidumbre=uncertainty_notice,
            recomendaciones=recommendations("medio" if prediction.incertidumbre else level, signals),
            datos_demostrativos=predictor.metadata["datos_demostrativos"],
        )

    def _analyze_for_chat(predictor: Predictor, text: str) -> dict:
        """Ejecuta el análisis ML y devuelve los campos relevantes para el chat."""
        try:
            prediction = predictor.classify(text)
        except ModelUnavailable:
            return {
                "etiqueta_modelo": "desconocido",
                "nivel": "desconocido",
                "incertidumbre": False,
                "aviso_incertidumbre": None,
                "senales": [],
                "recomendaciones": ["El modelo no está disponible. Sé precavido con este mensaje."],
                "datos_demostrativos": False,
            }
        label = prediction.etiqueta
        level = "bajo" if label == "legitimo" else "alto"
        signals = detect_signals(text)
        if label == "fraudulento":
            effective_level = "alto" if signals else ("medio" if prediction.incertidumbre else "alto")
        else:
            effective_level = "medio" if prediction.incertidumbre else "bajo"
        uncertainty_notice = (
            "Resultado incierto: la puntuación está en la zona intermedia."
            if (prediction.incertidumbre and not signals) else None
        )
        return {
            "etiqueta_modelo": label,
            "nivel": effective_level,
            "incertidumbre": prediction.incertidumbre and not bool(signals),
            "aviso_incertidumbre": uncertainty_notice,
            "senales": [{"codigo": s.codigo, "titulo": s.titulo, "descripcion": s.descripcion} for s in signals],
            "recomendaciones": recommendations(effective_level, signals),
            "datos_demostrativos": predictor.metadata.get("datos_demostrativos", False),
        }

    @application.websocket("/ws/chat/{telefono}")
    async def websocket_chat(websocket: WebSocket, telefono: str):
        manager: ConnectionManager = websocket.app.state.chat_manager
        predictor: Predictor = websocket.app.state.predictor

        try:
            phone = normalize_phone(telefono)
        except ValueError:
            await websocket.close(code=4000, reason="Número telefónico inválido")
            return

        # Solo el dispositivo que registró el número puede usarlo (evita suplantación).
        token = (websocket.query_params.get("token") or "").strip()[:200] or None
        if not manager.registry.authorize(phone, token):
            await websocket.accept()
            await websocket.close(code=4003, reason="Este número ya está registrado en otro dispositivo")
            return

        await manager.connect(phone, websocket)
        # Notificar al usuario su conexión exitosa, con su número normalizado
        # y las conversaciones guardadas en el servidor.
        await manager.send_to(phone, {
            "tipo": "sistema",
            "mensaje": f"Conectado como {phone}",
            "telefono": phone,
            "usuarios_online": manager.active_users,
            "conversaciones": manager.get_conversations(phone),
        })
        # Notificar a todos los demás que un usuario se conectó
        for user in manager.active_users:
            if user != phone:
                await manager.send_to(user, {
                    "tipo": "usuario_conectado",
                    "telefono": phone,
                    "usuarios_online": manager.active_users,
                })

        try:
            while True:
                data = await websocket.receive_json()
                tipo = data.get("tipo", "")

                if tipo == "mensaje":
                    dest_raw = data.get("destinatario", "")
                    texto = (data.get("texto") or "").strip()

                    # Validar destinatario
                    try:
                        dest = normalize_phone(dest_raw)
                    except ValueError:
                        await manager.send_to(phone, {
                            "tipo": "error",
                            "mensaje": "Número de destinatario inválido. Usa formato internacional, ej: +59170011223.",
                        })
                        continue

                    # Validar texto vacío
                    if not texto:
                        await manager.send_to(phone, {
                            "tipo": "error",
                            "mensaje": "El mensaje está vacío.",
                        })
                        continue

                    # Validar longitud
                    if len(texto) > MAX_CHAT_TEXT:
                        await manager.send_to(phone, {
                            "tipo": "error",
                            "mensaje": f"El mensaje excede el límite de {MAX_CHAT_TEXT} caracteres.",
                        })
                        continue

                    # No permitir enviarse mensajes a uno mismo
                    if dest == phone:
                        await manager.send_to(phone, {
                            "tipo": "error",
                            "mensaje": "No puedes enviarte un mensaje a ti mismo.",
                        })
                        continue

                    # Ejecutar análisis ML
                    analysis = _analyze_for_chat(predictor, texto)

                    client_id = data.get("client_id")
                    client_id = client_id[:64] if isinstance(client_id, str) and client_id else None

                    # Crear el mensaje con resultados del análisis
                    msg = ChatMessage(
                        id=manager.next_id(),
                        remitente=phone,
                        destinatario=dest,
                        texto=texto,
                        timestamp=time.time(),
                        client_id=client_id,
                        **analysis,
                    )
                    manager.store_message(msg)

                    msg_data = msg.to_dict()

                    # Enviar al destinatario (si está conectado)
                    delivered = await manager.send_to(dest, {"tipo": "mensaje_recibido", **msg_data})

                    # Confirmación al remitente. client_id (incluido en msg_data) permite
                    # a la app sustituir su mensaje provisional por el definitivo.
                    await manager.send_to(phone, {
                        "tipo": "mensaje_enviado",
                        **msg_data,
                        "entregado": delivered,
                    })

                    if not delivered:
                        await manager.send_to(phone, {
                            "tipo": "info",
                            "mensaje": f"El usuario {dest} no está conectado. El mensaje se guardó en el historial.",
                        })

                elif tipo == "historial":
                    dest_raw = data.get("destinatario", "")
                    try:
                        dest = normalize_phone(dest_raw)
                    except ValueError:
                        await manager.send_to(phone, {
                            "tipo": "error",
                            "mensaje": "Número inválido para cargar historial.",
                        })
                        continue
                    history = manager.get_history(phone, dest)
                    await manager.send_to(phone, {
                        "tipo": "historial",
                        "mensajes": history,
                        "con": dest,
                    })

                elif tipo == "ping":
                    await manager.send_to(phone, {"tipo": "pong"})

        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            # Si esta sesión fue reemplazada por una reconexión, la nueva sigue activa:
            # no se elimina ni se anuncia una desconexión falsa.
            removed = manager.disconnect(phone, websocket)
            # Notificar a todos que un usuario se desconectó
            for user in (manager.active_users if removed else []):
                await manager.send_to(user, {
                    "tipo": "usuario_desconectado",
                    "telefono": phone,
                    "usuarios_online": manager.active_users,
                })

    application.mount("/static", StaticFiles(directory=STATIC), name="static")
    return application


app = create_app()
