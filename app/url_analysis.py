"""Análisis local de enlaces (sin abrirlos ni consultar servicios externos).

Clasifica cada enlace en uno de cuatro niveles:
- "confiable": dominio conocido y legítimo (Instagram, YouTube, bancos oficiales...)
  servido por https o sin esquema explícito.
- "neutral": dominio desconocido sin rasgos de riesgo. No se puede afirmar nada.
- "sospechoso": http sin cifrar, acortadores, TLD de bajo coste muy usados en fraude,
  palabras cebo en el dominio ("verificar", "premio", "desbloqueo"...).
- "peligroso": imita a una marca o banco con un dominio que no es el oficial,
  usa una IP en lugar de dominio, punycode (xn--) o "@" para ocultar el destino.
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from dataclasses import dataclass, field

NIVELES = ("confiable", "neutral", "sospechoso", "peligroso")
_ORDEN = {nivel: i for i, nivel in enumerate(NIVELES)}

# Para dominios escritos sin "http(s)://" ni "www." solo se aceptan TLD inequívocos,
# para no confundir errores de tipeo ("ok.me voy", "llegue.es tarde") con enlaces.
_TLDS_SUELTOS = (
    "com|org|net|bo|io|app|info|online|site|xyz|top|click|shop|store|live|link|ly|gl|gle|"
    "tk|ml|ga|cf|gq|buzz|icu|cfd|vip|win|loan|club|fun|space|website|support|rest|work"
)
URL_RE = re.compile(
    r"(?:(?:https?://)[^\s<>\"']+)"                                  # con esquema
    r"|(?:\bwww\.[^\s<>\"']+)"                                        # www.
    r"|(?:\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)*[a-z0-9][a-z0-9-]*[a-z0-9]\."
    r"(?:" + _TLDS_SUELTOS + r")\b(?:/[^\s<>\"']*)?)",                 # dominio suelto
    re.IGNORECASE,
)

# Dominios registrables conocidos y legítimos (se aceptan sus subdominios).
DOMINIOS_CONFIABLES = frozenset({
    # Redes sociales y mensajería
    "instagram.com", "instagr.am", "facebook.com", "fb.com", "fb.me", "fb.watch", "messenger.com",
    "whatsapp.com", "wa.me", "tiktok.com", "youtube.com", "youtu.be", "x.com", "twitter.com",
    "t.me", "telegram.org", "linkedin.com", "pinterest.com", "reddit.com", "threads.net",
    "snapchat.com", "twitch.tv", "discord.com", "discord.gg",
    # Google, Microsoft, Apple y productividad
    "google.com", "google.com.bo", "goo.gl", "forms.gle", "gmail.com", "microsoft.com",
    "office.com", "live.com", "outlook.com", "apple.com", "icloud.com", "zoom.us",
    "canva.com", "notion.so", "dropbox.com", "github.com", "gitlab.com", "wikipedia.org",
    "spotify.com", "netflix.com", "amazon.com", "mercadolibre.com", "aliexpress.com",
    "temu.com", "shein.com", "booking.com", "airbnb.com", "uber.com", "chatgpt.com",
    "openai.com", "claude.ai", "anthropic.com", "duolingo.com", "coursera.org", "udemy.com",
    # Bolivia: bancos, operadoras, Estado, universidades y medios
    "bnb.com.bo", "bcp.com.bo", "bancounion.com.bo", "bmsc.com.bo", "bancosol.com.bo",
    "bisa.com", "bancoganadero.com.bo", "baneco.com.bo", "bancofie.com.bo", "fassil.com.bo",
    "tigo.com.bo", "entel.bo", "viva.com.bo", "asfi.gob.bo", "impuestos.gob.bo", "gob.bo",
    "edu.bo", "eldeber.com.bo", "lostiempos.com", "opinion.com.bo", "la-razon.com",
    "paginasiete.bo", "correodelsur.com", "unitel.bo", "reduno.com.bo", "eju.tv",
    "infobae.com", "bbc.com", "cnn.com", "elpais.com",
})

ACORTADORES = frozenset({
    "bit.ly", "tinyurl.com", "cutt.ly", "is.gd", "ow.ly", "rebrand.ly", "shorturl.at",
    "acortar.link", "rb.gy", "tiny.cc", "t.ly", "shorturl.com", "s.id", "v.gd", "bl.ink",
    "short.io", "tny.im", "clck.ru", "qrco.de", "linktr.ee",
})

TLD_SOSPECHOSOS = frozenset({
    "xyz", "top", "online", "site", "click", "info", "live", "shop", "buzz", "icu", "cfd",
    "rest", "vip", "win", "loan", "work", "support", "club", "fun", "space", "website",
    "tk", "ml", "ga", "cf", "gq",
})

# Marcas que se suplantan a menudo -> dominios oficiales donde es legítimo verlas.
MARCAS = {
    "bnb": {"bnb.com.bo"}, "bcp": {"bcp.com.bo"}, "bancounion": {"bancounion.com.bo"},
    "mercantil": {"bmsc.com.bo"}, "bancosol": {"bancosol.com.bo"}, "bisa": {"bisa.com"},
    "ganadero": {"bancoganadero.com.bo"}, "fassil": {"fassil.com.bo"},
    "tigo": {"tigo.com.bo"}, "tigomoney": {"tigo.com.bo"}, "entel": {"entel.bo"},
    "impuestos": {"impuestos.gob.bo"}, "asfi": {"asfi.gob.bo"},
    "instagram": {"instagram.com"}, "facebook": {"facebook.com", "fb.com"},
    "whatsapp": {"whatsapp.com", "wa.me"}, "tiktok": {"tiktok.com"}, "netflix": {"netflix.com"},
    "paypal": {"paypal.com"}, "amazon": {"amazon.com"}, "apple": {"apple.com"},
    "icloud": {"icloud.com"}, "google": {"google.com", "google.com.bo"},
    "microsoft": {"microsoft.com"}, "banco": set(), "bank": set(),
}

PALABRAS_CEBO = (
    "login", "signin", "verifica", "verify", "seguro", "secure", "segura", "desbloque", "bloqueo",
    "premio", "gratis", "free", "cobra", "reembolso", "actualiza", "update", "valida", "soporte",
    "support", "confirm", "cuenta", "account", "regalo", "bono", "sorteo", "ganador", "promo",
    "pago", "multa", "rastreo", "entrega", "recompensa", "billetera", "wallet",
)

# Segundo nivel genérico de dominios con código de país (com.bo, gob.bo, co.uk...).
_SLD = {"com", "gob", "gov", "edu", "org", "net", "co", "mil", "ac", "nom"}


@dataclass(frozen=True)
class EnlaceAnalizado:
    url: str
    host: str
    dominio: str
    https: bool
    http_inseguro: bool
    nivel: str
    motivos: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ReporteEnlaces:
    enlaces: tuple[EnlaceAnalizado, ...]

    @property
    def total(self) -> int:
        return len(self.enlaces)

    @property
    def nivel_maximo(self) -> str | None:
        if not self.enlaces:
            return None
        return max((e.nivel for e in self.enlaces), key=_ORDEN.__getitem__)

    def cuenta(self, nivel: str) -> int:
        return sum(1 for e in self.enlaces if e.nivel == nivel)

    def tiene_motivo(self, motivo: str) -> bool:
        return any(motivo in e.motivos for e in self.enlaces)

    @property
    def solo_confiables(self) -> bool:
        return bool(self.enlaces) and all(e.nivel == "confiable" for e in self.enlaces)


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def dominio_registrable(host: str) -> str:
    partes = host.split(".")
    if len(partes) >= 3 and len(partes[-1]) == 2 and partes[-2] in _SLD:
        return ".".join(partes[-3:])
    return ".".join(partes[-2:])


def _es_confiable(host: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in DOMINIOS_CONFIABLES)


def analizar_url(url: str) -> EnlaceAnalizado:
    bruto = url.strip().rstrip(".,;:!?)]}»\"'")
    minus = bruto.lower()
    https = minus.startswith("https://")
    http_inseguro = minus.startswith("http://")
    resto = re.sub(r"^https?://", "", minus)
    autoridad = re.split(r"[/?#]", resto, maxsplit=1)[0]
    motivos: list[str] = []
    if "@" in autoridad:
        motivos.append("arroba_oculta_destino")
        autoridad = autoridad.rsplit("@", 1)[1]
    host = autoridad.split(":")[0].strip(".")
    if host.startswith("www."):
        host = host[4:]
    dominio = dominio_registrable(host) if host else ""

    es_ip = False
    try:
        ipaddress.ip_address(host)
        es_ip = True
    except ValueError:
        pass

    confiable = bool(host) and not es_ip and _es_confiable(host)
    marca_imitada = None
    if http_inseguro:
        motivos.append("http_sin_cifrar")
    if es_ip:
        motivos.append("direccion_ip")
    if "xn--" in host:
        motivos.append("punycode")
    if not confiable and host:
        if dominio in ACORTADORES or host in ACORTADORES:
            motivos.append("acortador")
        tld = host.rsplit(".", 1)[-1]
        if tld in TLD_SOSPECHOSOS:
            motivos.append("tld_sospechoso")
        # Coincidencia por inicio de segmento: "bnb-seguro", "tigomoney-bo", "instagram.verify"
        # sí; "contigo" o "pineapple" no.
        segmentos = re.split(r"[.\-_]", _sin_tildes(host))
        marca_imitada = None
        for marca, oficiales in MARCAS.items():
            if dominio not in oficiales and any(s.startswith(marca) for s in segmentos):
                marca_imitada = marca
                motivos.append("imita_marca")
                break
        if any(p in host for p in PALABRAS_CEBO):
            motivos.append("palabras_cebo")
        if host.count("-") >= 2 or host.count(".") >= 4:
            motivos.append("dominio_enrevesado")

    if {"imita_marca", "direccion_ip", "punycode", "arroba_oculta_destino"} & set(motivos):
        nivel = "peligroso"
    elif motivos:
        nivel = "sospechoso"
    elif confiable:
        nivel = "confiable"
    else:
        nivel = "neutral"
    # "banco"/"bank" genéricos solos en un dominio desconocido: sospechoso, no peligroso.
    if nivel == "peligroso" and motivos == ["imita_marca"] and marca_imitada in ("banco", "bank"):
        nivel = "sospechoso"
    return EnlaceAnalizado(bruto, host, dominio, https, http_inseguro, nivel, tuple(motivos))


def analizar_enlaces(texto: str) -> ReporteEnlaces:
    vistos, enlaces = set(), []
    for match in URL_RE.finditer(texto):
        url = match.group(0)
        # Evitar falsos enlaces como "s.a" o "etc.com" dentro de correos (usuario@dominio).
        inicio = match.start()
        if inicio > 0 and texto[inicio - 1] == "@":
            continue
        analizado = analizar_url(url)
        if not analizado.host or analizado.url.lower() in vistos:
            continue
        vistos.add(analizado.url.lower())
        enlaces.append(analizado)
    return ReporteEnlaces(tuple(enlaces))
