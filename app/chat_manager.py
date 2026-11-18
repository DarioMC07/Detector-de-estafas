"""Gestor de conexiones WebSocket y almacén temporal de mensajes de chat."""

import re
import time
from dataclasses import asdict, dataclass, field
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


class ConnectionManager:
    """Gestor en memoria de conexiones WebSocket activas y mensajes de chat."""

    def __init__(self) -> None:
        # Mapa: número normalizado → WebSocket activo
        self._connections: dict[str, WebSocket] = {}
        # Mapa: clave de conversación → lista de mensajes
        self._history: dict[str, list[ChatMessage]] = {}
        # Contador global para IDs de mensajes
        self._counter: int = 0

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

    def disconnect(self, phone: str) -> None:
        """Elimina la conexión de un número telefónico."""
        self._connections.pop(phone, None)

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

    async def send_to(self, phone: str, data: dict[str, Any]) -> bool:
        """Envía un mensaje JSON a un número conectado. Devuelve True si se pudo enviar."""
        ws = self._connections.get(phone)
        if ws is None:
            return False
        try:
            await ws.send_json(data)
            return True
        except Exception:
            self.disconnect(phone)
            return False

