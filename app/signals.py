"""Reglas locales complementarias; no verifican hechos ni cambian la predicción."""

import re
import unicodedata

from app.schemas import Signal
from app.text_features import ROBO_CODIGO_RE
from app.url_analysis import analizar_enlaces


def normalize(text: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFD", text.lower())
                   if unicodedata.category(char) != "Mn")


# Son patrones léxicos, no un detector de intención; pueden activarse en advertencias legítimas.
RULES = [
    ("credenciales", "Mención de claves o códigos de acceso",
     r"\b(contrasenas?|pin|claves?|cvv|codigo(?:s)? (?:sms|de (?:acceso|verificacion|seguridad|whatsapp))|"
     r"codigo que te (?:llego|envie|mande|enviaron|llegara)|pasame (?:el|ese) codigo)\b",
     "El texto menciona contraseñas, claves o códigos. Puede estar solicitándolos o hablando de ellos; no los compartas."),
    ("urgencia", "Presión o plazo para actuar",
     r"\b(urgent\w*|inmediatamente|de inmediato|ahora mismo|ultimo aviso|ultima oportunidad|solo tienes|caduca hoy|"
     r"antes de medianoche|(?:tienes|quedan|dispones de|en menos de|solo) (?:\w+ ){0,1}(?:minutos|horas?)|"
     r"(?:sera\w*|se (?:cortara|cancelara|bloqueara|suspendera|eliminara)\w*)(?: \w+)? en (?:una hora|\w+ (?:minutos|horas)))\b",
     "Hay expresiones de urgencia o plazos. Son una señal para detenerse y revisar el contexto."),
    ("premio", "Promesas o referencias a premios",
     r"\b(premio\w*|has ganado|ganaste|te ganaste|ganador\w*|loteria|regalo\w*|donacion millonaria|herencia|"
     r"sorteo\w*|fuiste seleccionad\w*|has sido seleccionad\w*)\b",
     "El mensaje menciona premios, regalos o beneficios. Esta regla no permite saber si la oferta es auténtica."),
    ("dinero", "Pagos o movimientos de dinero",
     r"\b(transfer\w*|transfi\w*|bizum|paga\w*|pago\w*|ingresa|deposita\w*|criptomonedas|tarjetas regalo|"
     r"prest\w*(?: \w+){0,2}? (?:\d+|plata|dinero)|manda(?:me)? (?:plata|dinero)|qr)\b",
     "Se mencionan pagos o movimientos de dinero. Comprueba la solicitud por un canal conocido antes de actuar."),
    ("suplantacion", "Posible suplantación de identidad",
     r"\b(cambie (?:de|mi) (?:numero|celular|cel|chip)|(?:es|este es) mi nuevo (?:numero|celular|cel)|nuevo numero|"
     r"guarda (?:este|mi) numero|soy tu (?:hij[oa]|niet[oa]|sobrin[oa])|adivina quien soy|no me reconoces|"
     r"te escribo de (?:otro|este) numero)\b",
     "Alguien dice ser un conocido que cambió de número. Llámale al número de siempre antes de hacer nada."),
]

_DESCRIPCIONES_MOTIVO = {
    "http_sin_cifrar": "usa http:// sin cifrar (lo habitual es https://)",
    "acortador": "usa un acortador que oculta el destino real",
    "tld_sospechoso": "tiene una terminación de dominio muy usada en fraudes",
    "palabras_cebo": "contiene palabras cebo en el dominio (verificar, premio, desbloqueo...)",
    "dominio_enrevesado": "tiene un dominio enrevesado",
    "imita_marca": "imita el nombre de un banco o marca conocida pero no es su dominio oficial",
    "direccion_ip": "apunta a una dirección IP en lugar de un dominio",
    "punycode": "usa caracteres que imitan letras normales (punycode)",
    "arroba_oculta_destino": "usa «@» para ocultar el destino real",
}


def _senales_enlaces(text: str) -> list[Signal]:
    reporte = analizar_enlaces(text)
    if not reporte.total:
        return []
    signals = []
    peligrosos = [e for e in reporte.enlaces if e.nivel == "peligroso"]
    sospechosos = [e for e in reporte.enlaces if e.nivel == "sospechoso"]
    if reporte.tiene_motivo("http_sin_cifrar"):
        signals.append(Signal(
            codigo="enlace_inseguro", titulo="Enlace sin cifrar (http)",
            descripcion="El enlace usa http:// sin la «s». La conexión no está cifrada y es habitual en páginas "
                        "fraudulentas. No ingreses datos personales ni bancarios en ella."))
    if peligrosos:
        motivos = sorted({m for e in peligrosos for m in e.motivos if m != "http_sin_cifrar"})
        signals.append(Signal(
            codigo="enlace_suplantacion", titulo="Enlace que imita a una entidad o marca",
            descripcion="El enlace " + "; ".join(_DESCRIPCIONES_MOTIVO[m] for m in motivos) +
                        ". No lo abras: entra al servicio desde su aplicación oficial."))
    elif sospechosos and any(set(e.motivos) - {"http_sin_cifrar"} for e in sospechosos):
        motivos = sorted({m for e in sospechosos for m in e.motivos if m != "http_sin_cifrar"})
        signals.append(Signal(
            codigo="enlace_sospechoso", titulo="Enlace con características sospechosas",
            descripcion="El enlace " + "; ".join(_DESCRIPCIONES_MOTIVO[m] for m in motivos) + "."))
    if reporte.cuenta("neutral") and not signals:
        signals.append(Signal(
            codigo="enlace", titulo="Presencia de enlaces",
            descripcion="Hay una dirección web. Un enlace por sí solo no demuestra fraude; no se ha abierto ni "
                        "comprobado su reputación."))
    # Enlaces de dominios conocidos (Instagram, YouTube, bancos oficiales...) por https: sin señal.
    return signals


def detect_signals(text: str) -> list[Signal]:
    normalized = normalize(text)
    signals = [Signal(codigo=code, titulo=title, descripcion=description)
               for code, title, pattern, description in RULES
               if re.search(pattern, normalized)]
    # "Te llegó un código por error, pásamelo": robo de cuentas de mensajería.
    if not any(s.codigo == "credenciales" for s in signals) and ROBO_CODIGO_RE.search(normalized):
        code, title, _, description = RULES[0]
        signals.insert(0, Signal(codigo=code, titulo=title, descripcion=description))
    return signals + _senales_enlaces(text)


CODIGOS_ENLACE_RIESGO = {"enlace_inseguro", "enlace_sospechoso", "enlace_suplantacion"}


def recommendations(level: str, signals: list[Signal]) -> list[str]:
    items = ["Comprueba quién te escribe usando un teléfono o una aplicación que ya conozcas."]
    if level != "bajo":
        items.insert(0, "Detente antes de responder o realizar la acción solicitada. Pide ayuda a alguien de confianza.")
    codes = {signal.codigo for signal in signals}
    if "credenciales" in codes:
        items.append("No compartas contraseñas, PIN ni códigos de verificación por mensaje.")
    if "dinero" in codes or "premio" in codes:
        items.append("No envíes dinero ni pagues para recibir premios sin comprobar la solicitud por otra vía.")
    if "suplantacion" in codes:
        items.append("Si dice ser un familiar o conocido, llámale a su número de siempre antes de responder.")
    if codes & CODIGOS_ENLACE_RIESGO:
        items.append("No abras el enlace. Accede al servicio desde su aplicación oficial o escribiendo tú la dirección.")
    elif "enlace" in codes:
        items.append("Accede al servicio desde su aplicación habitual o una dirección conocida, en lugar del enlace recibido.")
    items.append("Un resultado de bajo riesgo no garantiza que el mensaje sea seguro.")
    return items
