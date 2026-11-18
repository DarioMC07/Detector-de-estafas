"""Reglas locales complementarias; no verifican hechos ni cambian la predicción."""

import re
import unicodedata

from app.schemas import Signal


def normalize(text: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFD", text.lower())
                   if unicodedata.category(char) != "Mn")


# Son patrones léxicos, no un detector de intención; pueden activarse en advertencias legítimas.
RULES = [
    ("credenciales", "Mención de claves o códigos de acceso",
     r"\b(contrasenas?|pin|claves?|codigo(?:s)? (?:sms|de (?:acceso|verificacion|seguridad)))\b",
     "El texto menciona contraseñas, claves o códigos. Puede estar solicitándolos o hablando de ellos; no los compartas."),
    ("urgencia", "Presión o plazo para actuar",
     r"\b(urgent\w*|inmediatamente|ahora mismo|ultimo aviso|ultima oportunidad|solo tienes|caduca hoy|en (?:una hora|\w+ minutos)|antes de medianoche)\b",
     "Hay expresiones de urgencia o plazos. Son una señal para detenerse y revisar el contexto."),
    ("premio", "Promesas o referencias a premios",
     r"\b(premio\w*|has ganado|ganaste|ganador\w*|loteria|regalo\w*|donacion millonaria|herencia)\b",
     "El mensaje menciona premios, regalos o beneficios. Esta regla no permite saber si la oferta es auténtica."),
    ("dinero", "Pagos o movimientos de dinero",
     r"\b(transfer\w*|transfi\w*|bizum|paga\w*|pago\w*|ingresa|deposita|criptomonedas|tarjetas regalo)\b",
     "Se mencionan pagos o movimientos de dinero. Comprueba la solicitud por un canal conocido antes de actuar."),
    ("enlace", "Presencia de enlaces",
     r"(?:https?://|www\.)\S+|\b(?:[a-z0-9-]+\.)+(?:com|org|net|es|info|io)\b(?:/\S*)?",
     "Hay una dirección web. Un enlace por sí solo no demuestra fraude; no se ha abierto ni comprobado su reputación."),
]


def detect_signals(text: str) -> list[Signal]:
    normalized = normalize(text)
    return [Signal(codigo=code, titulo=title, descripcion=description)
            for code, title, pattern, description in RULES
            if re.search(pattern, normalized)]


def recommendations(level: str, signals: list[Signal]) -> list[str]:
    items = ["Comprueba quién te escribe usando un teléfono o una aplicación que ya conozcas."]
    if level != "bajo":
        items.insert(0, "Detente antes de responder o realizar la acción solicitada. Pide ayuda a alguien de confianza.")
    codes = {signal.codigo for signal in signals}
    if "credenciales" in codes:
        items.append("No compartas contraseñas, PIN ni códigos de verificación por mensaje.")
    if "dinero" in codes or "premio" in codes:
        items.append("No envíes dinero ni pagues para recibir premios sin comprobar la solicitud por otra vía.")
    if "enlace" in codes:
        items.append("Accede al servicio desde su aplicación habitual o una dirección conocida, en lugar del enlace recibido.")
    items.append("Un resultado de bajo riesgo no garantiza que el mensaje sea seguro.")
    return items
