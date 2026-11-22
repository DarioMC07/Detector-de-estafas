"""Preprocesamiento y características compartidas por entrenamiento e inferencia.

- ``preprocesar_para_modelo``: se usa como ``preprocessor`` del TF-IDF del Nivel 1.
  Queda guardado dentro del pipeline, de modo que entrenamiento e inferencia aplican
  exactamente la misma transformación. Sustituye cada enlace por tokens que describen
  su nivel de riesgo (en vez de memorizar dominios concretos), quita tildes, colapsa
  alargamientos ("holaaaa") y unifica números.
- ``caracteristicas_laya``: vector estructurado y fijo que consume el modelo Laya
  (Nivel 2). Combina la puntuación del Nivel 1 con señales léxicas, análisis de
  enlaces y rasgos de estilo.
"""

from __future__ import annotations

import re
import unicodedata

from app.url_analysis import URL_RE, analizar_enlaces, analizar_url


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def colapsar_alargamientos(texto: str) -> str:
    texto = re.sub(r"([a-zñ])\1{2,}", r"\1", texto)
    return re.sub(r"\b(hol)a+\b", r"\1a", texto)


def _token_enlace(match: re.Match) -> str:
    enlace = analizar_url(match.group(0))
    tokens = [f"zenlace{enlace.nivel}"]
    if enlace.http_inseguro:
        tokens.append("zenlacehttp")
    tokens.extend(f"zmotivo{m.replace('_', '')}" for m in enlace.motivos)
    # Palabras del dominio (sin el TLD): "bnb-seguro.info" -> "bnb seguro".
    # Para dominios confiables solo se añade el nombre del servicio.
    partes = re.split(r"[.\-]", enlace.dominio)[:-1] if enlace.dominio else []
    if enlace.nivel == "confiable":
        partes = partes[:1]
    tokens.extend(p for p in partes if len(p) > 2 and p not in {"com", "gob", "edu", "org", "net"})
    return " " + " ".join(tokens) + " "


def preprocesar_para_modelo(texto: str) -> str:
    texto = URL_RE.sub(_token_enlace, texto)
    texto = _sin_tildes(texto.lower())
    texto = colapsar_alargamientos(texto)
    return re.sub(r"\d+(?:[.,]\d+)*", " znum ", texto)


# ----------------------------------------------------------------- Laya (Nivel 2)

_BANCARIO_RE = re.compile(
    r"\b(bancos?|bancari\w*|banca (?:movil|por internet)|homebanking|cuenta bancaria|tu cuenta|"
    r"tarjeta(?:s)? de (?:credito|debito)|tu tarjeta|bnb|bcp|bisa|mercantil|banco union|banco sol|"
    r"bancosol|fassil|ganadero|tigo money|billetera movil|asfi)\b"
)
_SUPLANTACION_RE = re.compile(
    r"\b(cambie (?:de|mi) (?:numero|celular|cel|chip)|(?:es|este es) mi nuevo (?:numero|celular|cel)|"
    r"nuevo numero|guarda (?:este|mi) numero|soy tu (?:hij[oa]|mama|papa|herman[oa]|prim[oa]|ti[oa]|"
    r"niet[oa]|sobrin[oa]|jefe|amig[oa])|adivina quien soy|no me reconoces|"
    r"te escribo de (?:otro|este) numero|se me (?:perdio|arruino|robaron|rompio) (?:el|mi) (?:celular|cel|telefono)|"
    r"(?:me )?robaron (?:el|mi) (?:celular|cel|telefono)|no le digas a nadie|no llames)\b"
)
# Verbos en forma "tú" y "usted" (envía/envíe, pasa/pase, ingresa/ingrese...).
_PETICION_DATOS_RE = re.compile(
    r"\b(envi\w*|mand\w*|pas[ae]\w*|compart\w*|confirm\w*|ingres\w*|introduc\w*|escrib\w*|"
    r"dict\w*|respond\w*|verifi\w*|actualiz\w*|actualic\w*|valid\w*|dame|deme|reenvi\w*|"
    r"facilit\w*|proporcion\w*|registr\w*)\b"
    r"(?:\W+\w+){0,5}?\W+(?:tu |tus |el |la |los |las |su )?"
    r"(clave\w*|contrasena\w*|pin|codigo\w*|datos|tarjeta\w*|cvv|usuario|token|ci|carnet)\b"
)
# Robo de cuentas de WhatsApp/Telegram: "te llegó un código por error, pásamelo".
ROBO_CODIGO_RE = re.compile(
    r"\bcodigo\w*\b(?:\W+\w+){0,8}?\W+(?:por error|por equivocacion|sin querer|equivocad\w*)"
    r"|\b(?:pasa|reenvia|manda|dicta|envia|dame|comparte)\w*\b(?:\W+\w+){0,4}?\W+(?:el |ese |los )?codigo\w*"
    r"|\bcodigo\w*\b(?:\W+\w+){0,10}?\W+(?:me lo |me los )?(?:pasa|reenvia|manda|dicta|envia|comparte)\w*"
    r"|\bcodigo\w* (?:que te (?:llego|envie|mande|enviaron|llegara)|de \w+ digitos)"
)
_PAGO_PREVIO_RE = re.compile(
    r"\b(pag[aeu]\w*|deposit\w*|transfi\w*|transfer\w*|abon\w*|ingres\w*|envi\w*|mand\w*|cancel\w*)\b"
    r"(?:\W+\w+){0,6}?\W+(?:una? )?(tasa|comision|impuesto\w*|tarifa|envio|matricula|garantia|"
    r"adelanto|anticipo|seguro|activacion|desbloqueo|liberacion|tramite|arancel|membresia|inscripcion|"
    r"recarga|costos? de (?:envio|reenvio|entrega))\b"
)
_AMENAZA_RE = re.compile(
    r"\b(bloquead\w*|suspendid\w*|cancelad\w*|embargo|detenid\w*|denuncia\w*|demanda\w*|"
    r"eliminad\w*|cerrad\w*|cortara\w*|perderas|arrestad\w*|orden de captura|multa\w*)\b"
)
_INVERSION_EMPLEO_RE = re.compile(
    r"\b(inversion\w*|invierte|duplica\w*|triplica\w*|rentabilidad|ganancias? (?:diarias|garantizadas|seguras)|"
    r"cripto\w*|bitcoin|usdt|trading|forex|trabajo desde casa|gana (?:znum|dinero|desde)|"
    r"empleo|vacante|sueldo de|ingresos extra|like\w* pagad\w*|tareas pagadas)\b"
)
_ENVIO_RE = re.compile(r"\b(paquete|envio|encomienda|courier|aduana|dhl|fedex|correos|rastreo|retenid\w*)\b")
_MONTO_RE = re.compile(r"(\b(?:bs|usd|\$us|\$|dolares|bolivianos|euros|soles)\s*\.?\s*znum\b|\bznum\s*(?:bs|usd|\$us|dolares|bolivianos|euros|soles|mil)\b)")
_SALUDO_RE = re.compile(r"^\W*(hola|buen[oa]s?|que tal|que onda|hey|ola|wena|saludos)\b")

CARACTERISTICAS = (
    "puntuacion_nivel1", "logit_nivel1",
    "senal_credenciales", "senal_urgencia", "senal_premio", "senal_dinero", "senal_suplantacion",
    "contexto_bancario", "patron_suplantacion", "peticion_datos", "robo_codigo", "pago_previo", "amenaza",
    "inversion_empleo", "envio_paquete", "monto",
    "n_enlaces", "enlace_confiable", "enlace_neutral", "enlace_sospechoso", "enlace_peligroso",
    "enlace_http", "enlace_acortador", "enlace_imita_marca", "solo_enlaces_confiables",
    "longitud_log", "n_palabras_log", "proporcion_mayusculas", "exclamaciones", "es_saludo",
    "es_pregunta",
)


def caracteristicas_laya(texto: str, puntuacion_nivel1: float, codigos_senales: set[str] | frozenset[str]) -> list[float]:
    import math

    norm = colapsar_alargamientos(_sin_tildes(texto.lower()))
    norm_num = re.sub(r"\d+(?:[.,]\d+)*", " znum ", norm)
    reporte = analizar_enlaces(texto)
    p = min(max(float(puntuacion_nivel1), 1e-4), 1 - 1e-4)
    letras = [c for c in texto if c.isalpha()]
    mayus = sum(1 for c in letras if c.isupper()) / len(letras) if letras else 0.0
    palabras = len(norm.split())
    valores = {
        "puntuacion_nivel1": p,
        "logit_nivel1": math.log(p / (1 - p)),
        "senal_credenciales": "credenciales" in codigos_senales,
        "senal_urgencia": "urgencia" in codigos_senales,
        "senal_premio": "premio" in codigos_senales,
        "senal_dinero": "dinero" in codigos_senales,
        "senal_suplantacion": "suplantacion" in codigos_senales,
        "contexto_bancario": bool(_BANCARIO_RE.search(norm)),
        "patron_suplantacion": bool(_SUPLANTACION_RE.search(norm)),
        "peticion_datos": bool(_PETICION_DATOS_RE.search(norm)),
        "robo_codigo": bool(ROBO_CODIGO_RE.search(norm)),
        "pago_previo": bool(_PAGO_PREVIO_RE.search(norm)),
        "amenaza": bool(_AMENAZA_RE.search(norm)),
        "inversion_empleo": bool(_INVERSION_EMPLEO_RE.search(norm_num)),
        "envio_paquete": bool(_ENVIO_RE.search(norm)),
        "monto": bool(_MONTO_RE.search(norm_num)),
        "n_enlaces": min(reporte.total, 3),
        "enlace_confiable": reporte.cuenta("confiable") > 0,
        "enlace_neutral": reporte.cuenta("neutral") > 0,
        "enlace_sospechoso": reporte.cuenta("sospechoso") > 0,
        "enlace_peligroso": reporte.cuenta("peligroso") > 0,
        "enlace_http": reporte.tiene_motivo("http_sin_cifrar"),
        "enlace_acortador": reporte.tiene_motivo("acortador"),
        "enlace_imita_marca": reporte.tiene_motivo("imita_marca"),
        "solo_enlaces_confiables": reporte.solo_confiables,
        "longitud_log": math.log1p(len(texto)),
        "n_palabras_log": math.log1p(palabras),
        "proporcion_mayusculas": mayus if len(letras) >= 8 else 0.0,
        "exclamaciones": min(texto.count("!"), 5),
        "es_saludo": bool(_SALUDO_RE.search(norm)),
        "es_pregunta": "?" in texto,
    }
    return [float(valores[nombre]) for nombre in CARACTERISTICAS]


def contexto_rapido(texto: str) -> dict[str, bool]:
    """Subconjunto booleano usado por la heurística de respaldo y la categoría."""
    norm = colapsar_alargamientos(_sin_tildes(texto.lower()))
    norm_num = re.sub(r"\d+(?:[.,]\d+)*", " znum ", norm)
    return {
        "bancario": bool(_BANCARIO_RE.search(norm)),
        "suplantacion": bool(_SUPLANTACION_RE.search(norm)),
        "peticion_datos": bool(_PETICION_DATOS_RE.search(norm)) or bool(ROBO_CODIGO_RE.search(norm)),
        "pago_previo": bool(_PAGO_PREVIO_RE.search(norm)),
        "amenaza": bool(_AMENAZA_RE.search(norm)),
        "inversion_empleo": bool(_INVERSION_EMPLEO_RE.search(norm_num)),
        # Robo de código salvo que sea un consejo ("nunca pases el código...").
        "robo_codigo": bool(ROBO_CODIGO_RE.search(norm)) and not _CONSEJO_RE.search(norm),
    }


_CONSEJO_RE = re.compile(r"\b(nunca|jamas|no (?:le )?(?:pases|compartas|des|envies|reenvies|digas|mandes))\b")
