"""Pruebas del análisis local de enlaces y de las señales derivadas."""

import pytest

from app.signals import detect_signals
from app.url_analysis import analizar_enlaces, analizar_url


@pytest.mark.parametrize("url", [
    "https://www.instagram.com/dario.montano/",
    "instagram.com/p/abc123",
    "https://www.tiktok.com/@juanito_bo/video/123",
    "https://youtu.be/abc123",
    "https://maps.app.goo.gl/AbCdEf",
    "https://wa.me/59171234567",
    "https://www.bnb.com.bo/",
    "https://www.impuestos.gob.bo",
    "eldeber.com.bo/noticia",
])
def test_dominios_conocidos_son_confiables(url):
    enlace = analizar_url(url)
    assert enlace.nivel == "confiable", enlace


@pytest.mark.parametrize("url", ["http://miblog.com", "http://instagram.com/perfil", "http://www.example.org/x"])
def test_http_sin_cifrar_siempre_es_riesgo(url):
    enlace = analizar_url(url)
    assert enlace.http_inseguro
    assert "http_sin_cifrar" in enlace.motivos
    assert enlace.nivel in ("sospechoso", "peligroso")


@pytest.mark.parametrize("url,motivo", [
    ("https://bit.ly/3xYz", "acortador"),
    ("https://premios-gratis.xyz", "tld_sospechoso"),
    ("https://premio.example.com", "palabras_cebo"),
])
def test_enlaces_sospechosos(url, motivo):
    enlace = analizar_url(url)
    assert enlace.nivel == "sospechoso"
    assert motivo in enlace.motivos


@pytest.mark.parametrize("url", [
    "http://bnb-seguro.info/login",
    "https://instagram-verificar-cuenta.com",
    "https://bancounion-seguro.online/pago",
    "http://192.168.0.1/admin",
    "https://xn--bnb-ssa.com",
    "https://www.bnb.com.bo@evil.example.com/login",
])
def test_enlaces_peligrosos(url):
    assert analizar_url(url).nivel == "peligroso"


@pytest.mark.parametrize("texto", ["ok.me voy", "llegue.es tarde", "escribe a juan@gmail.com", "nos vemos a las 5.30"])
def test_no_confunde_texto_con_enlaces(texto):
    assert analizar_enlaces(texto).total == 0


def test_marca_dentro_de_otra_palabra_no_es_suplantacion():
    # "contigo" contiene "tigo" pero no imita a la operadora.
    assert analizar_url("https://hablacontigo.com").nivel == "neutral"


def test_senales_por_tipo_de_enlace():
    assert detect_signals("mira mi perfil https://www.instagram.com/carla.rios/") == []
    assert [s.codigo for s in detect_signals("Consulta https://biblioteca.example.org")] == ["enlace"]
    assert "enlace_inseguro" in {s.codigo for s in detect_signals("entra a http://mitienda.com")}
    codigos = {s.codigo for s in detect_signals("Reactiva tu cuenta en http://bnb-seguro.info")}
    assert {"enlace_inseguro", "enlace_suplantacion"} <= codigos
    assert "enlace" not in codigos


def test_urgencia_no_salta_con_planes_cotidianos():
    assert "urgencia" not in {s.codigo for s in detect_signals("Estoy en camino, llego en 10 minutos")}
    assert "urgencia" in {s.codigo for s in detect_signals("Solo tienes 10 minutos para reclamar")}


def test_robo_de_codigo_es_senal_de_credenciales():
    codigos = {s.codigo for s in detect_signals("Te mandé un código por sms por error, me lo reenvías porfa")}
    assert "credenciales" in codigos
