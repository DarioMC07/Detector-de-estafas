"""Gestor de conexiones WebSocket y almacén temporal de mensajes de chat."""

import hashlib
import hmac
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from fastapi import WebSocket


@dataclass
class ChatMessage:
    """Un mensaje de chat con los resultados del análisis de seguridad incorporados."""
    id: str
    remitente: str
    destinatario: str
    texto: str
    timestamp: float
    # Resultados del análisis ML
    etiqueta_modelo: str = "legitimo"
    nivel: str = "bajo"
    incertidumbre: bool = False
    aviso_incertidumbre: str | None = None
    senales: list[dict[str, str]] = field(default_factory=list)
    recomendaciones: list[str] = field(default_factory=list)
    datos_demostrativos: bool = False
    # Decisión táctica de Nivel 2 (campos nuevos; la app actual los ignora sin problema)
    accion_tactica: str = "PERMITIR"
    categoria_fraude: str = "CONVERSACION_GENUINA"
    confianza_calibrada: float | None = None
    motor_decision: str = "fast_path"
    # Identificador provisional que asigna la app al enviar (para evitar duplicados al reconectar)
    client_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Formato internacional simple: + seguido de 7-15 dígitos (cubre +591, +54, +34, etc.)
_PHONE_RE = re.compile(r"^\+\d{7,15}$")

# Límite de caracteres de un mensaje de chat (mismo que el analizador)
MAX_CHAT_TEXT = 5000

# Historial máximo por conversación (en memoria; sin base de datos)
MAX_HISTORY = 200


def normalize_phone(raw: str) -> str:
    """Normaliza un número telefónico eliminando espacios y guiones.
    
    Acepta formato internacional (+59177004938) o números locales de 8 dígitos (ej. 77004938),
    añadiendo automáticamente el prefijo +591 si no tiene código de país.
    """
    cleaned = re.sub(r"[\s\-().]", "", raw.strip())
    if not cleaned:
        raise ValueError("El número no puede estar vacío.")
    
    # Si el usuario no escribió el '+'
    if not cleaned.startswith("+"):
        if len(cleaned) == 8 and cleaned.isdigit():
            cleaned = "+591" + cleaned
        elif cleaned.isdigit() and 7 <= len(cleaned) <= 15:
            cleaned = "+" + cleaned

    if not _PHONE_RE.match(cleaned):
        raise ValueError(
            f"Formato de número inválido: {cleaned!r}. "
            "Usa un número telefónico válido (ej: 77004938 o +59177004938)."
        )
    return cleaned


def conversation_key(a: str, b: str) -> str:
    """Genera una clave de conversación ordenada entre dos números."""
    return "|".join(sorted([a, b]))


class DeviceRegistry:
    """Vincula cada número con el dispositivo que lo registró primero.

    La app móvil genera un token aleatorio por instalación y lo envía al conectarse.
    Se guarda solo su hash SHA-256. Si un número ya está vinculado, solo ese mismo
    dispositivo puede volver a usarlo: así nadie puede escribir haciéndose pasar
    por otro número. Las conexiones sin token (interfaz web de demostración) solo
    pueden usar números que no estén vinculados a un dispositivo.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._hashes: dict[str, str] = {}
        if path is not None and path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._hashes = {str(k): str(v) for k, v in data.items()}
            except (OSError, ValueError):
                self._hashes = {}

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def is_registered(self, phone: str) -> bool:
        return phone in self._hashes

    def authorize(self, phone: str, token: str | None) -> bool:
        """Devuelve True si la conexión puede usar el número (y lo vincula si es nuevo)."""
        stored = self._hashes.get(phone)
        if not token:
            return stored is None
        token_hash = self._hash(token)
        if stored is None:
            self._hashes[phone] = token_hash
            self._save()
            return True
        return hmac.compare_digest(stored, token_hash)

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._hashes, indent=2), encoding="utf-8")
        except OSError:
            pass


class ConnectionManager:
    """Gestor en memoria de conexiones WebSocket activas y mensajes de chat."""

    def __init__(self, registry: DeviceRegistry | None = None) -> None:
        # Mapa: número normalizado → WebSocket activo
        self._connections: dict[str, WebSocket] = {}
        # Mapa: clave de conversación → lista de mensajes
        self._history: dict[str, list[ChatMessage]] = {}
        # Contador global para IDs de mensajes
        self._counter: int = 0
        self.registry = registry or DeviceRegistry()

    @property
    def active_users(self) -> list[str]:
        """Lista de números conectados actualmente."""
        return list(self._connections.keys())

    async def connect(self, phone: str, websocket: WebSocket) -> None:
        """Registra una conexión WebSocket para un número telefónico."""
        await websocket.accept()
        # Si ya hay una conexión previa para este número, la cierra silenciosamente
        old = self._connections.get(phone)
        if old is not None:
            try:
                await old.close(code=4001, reason="Sesión reemplazada por otra conexión")
            except Exception:
                pass
        self._connections[phone] = websocket

    def disconnect(self, phone: str, websocket: WebSocket | None = None) -> bool:
        """Elimina la conexión de un número telefónico.

        Si se indica ``websocket``, solo se elimina cuando sigue siendo la conexión
        activa. Así, al cerrarse una sesión antigua (reemplazada por una reconexión),
        no se borra por error la conexión nueva. Devuelve True si se eliminó.
        """
        current = self._connections.get(phone)
        if current is None:
            return False
        if websocket is not None and current is not websocket:
            return False
        del self._connections[phone]
        return True

    def is_online(self, phone: str) -> bool:
        """Comprueba si un número tiene conexión WebSocket activa."""
        return phone in self._connections

    def next_id(self) -> str:
        """Genera un ID único para un mensaje."""
        self._counter += 1
        return f"msg-{self._counter}-{int(time.time() * 1000)}"

    def store_message(self, msg: ChatMessage) -> None:
        """Almacena un mensaje en el historial de la conversación."""
        key = conversation_key(msg.remitente, msg.destinatario)
        history = self._history.setdefault(key, [])
        history.append(msg)
        # Recortar historial si excede el límite
        if len(history) > MAX_HISTORY:
            self._history[key] = history[-MAX_HISTORY:]

    def get_history(self, phone_a: str, phone_b: str) -> list[dict[str, Any]]:
        """Devuelve el historial de mensajes entre dos números."""
        key = conversation_key(phone_a, phone_b)
        return [m.to_dict() for m in self._history.get(key, [])]

    def get_conversations(self, phone: str) -> dict[str, list[dict[str, Any]]]:
        """Devuelve todas las conversaciones de un número: {otro_número: [mensajes]}."""
        result: dict[str, list[dict[str, Any]]] = {}
        for key, messages in self._history.items():
            a, _, b = key.partition("|")
            if phone not in (a, b):
                continue
            peer = b if a == phone else a
            result[peer] = [m.to_dict() for m in messages]
        return result

    async def send_to(self, phone: str, data: dict[str, Any]) -> bool:
        """Envía un mensaje JSON a un número conectado. Devuelve True si se pudo enviar."""
        ws = self._connections.get(phone)
        if ws is None:
            return False
        try:
            await ws.send_json(data)
            return True
        except Exception:
            self.disconnect(phone, ws)
            return False

