"""Pruebas del motor de decisión en cascada: Nivel 1 → Laya (Nivel 2) → veredicto final.

Los mensajes de las listas de regresión NO están en data/mensajes_demo.csv: comprueban
que la cascada generaliza a frases cotidianas nuevas, no que memoriza el dataset.
"""

import threading
import time

import joblib
import pytest
from fastapi.testclient import TestClient

from app.decision_engine import CATEGORIAS, DecisionEngine, crear_backend_por_defecto
from app.main import create_app
from app.predictor import Predictor

PHISHING = "BNB: su cuenta fue bloqueada, ingrese a http://bnb-seguro.info/login urgente"
NUEVOS = {"accion_tactica", "categoria_fraude", "confianza_calibrada", "motor_decision"}

COTIDIANOS = [
    "holaa", "bien y tu", "q haces?", "jaja buenísimo", "me avisas cuando llegues",
    "te pasé los 20 bs por qr", "voy al banco y vuelvo", "urgente ven a la casa que llegó la abuela",
    "Felicidades por el premio de la feria de ciencias!", "¿Me prestas 10 bs para el micro? te devuelvo en clase",
    "Hola, soy Ana la del curso, este es mi número", "Nunca pases el código que te llega por SMS",
    "Mi contraseña del wifi cambió, es casa2025", "Confirma si vienes a la cena",
]
ENLACES_LEGITIMOS = [
    "sigueme en insta https://www.instagram.com/carla.rios.bo/",
    "mira este perfil instagram.com/foodie.scz",
    "te paso mi tiktok https://www.tiktok.com/@juanito_bo",
    "esta es la dirección https://maps.app.goo.gl/QwErTy",
    "el link de la clase https://meet.google.com/xyz-abcd-efg",
    "Qué lindo tu perfil de insta jaja https://www.instagram.com/p/Cz123/",
]
ESTAFAS = [
    "Te mandé un código por sms por error, me lo reenvías porfa",
    "Hola mamá, cambié de número, me prestas 300 bs? te devuelvo mañana",
    "BNB: su cuenta fue bloqueada, ingrese a https://bnb-bolivia-seguro.com para reactivar",
    "Ganaste un premio de 3000 bs, paga 50 bs de envío",
    "Invierte 200 bs y gana 1000 en 3 días, cupos limitados",
    "Su paquete está retenido, pague el arancel en https://bit.ly/aduana-bo",
    "Su cuenta Tigo Money será suspendida, envíe su PIN para verificar",
    "Soy tu hijo, robaron mi celular, mándame plata a este número urgente",
]


class SpyBackend:
    """Backend de Nivel 2 falso que registra las llamadas."""

    def __init__(self, respuesta=None, error=None, bloqueo=None):
        self.respuesta = respuesta if respuesta is not None else {"probabilidad_fraude": 0.9, "categoria": "PHISHING_BANCARIO"}
        self.error, self.bloqueo = error, bloqueo
        self.llamadas = 0

    def decidir(self, caracteristicas):
        self.llamadas += 1
        self.ultimas = caracteristicas
        if self.bloqueo is not None:
            self.bloqueo.wait(5)
        if self.error:
            raise self.error
        return self.respuesta


@pytest.fixture(scope="module")
def predictor(trained_artifact):
    return Predictor(trained_artifact[0])


@pytest.fixture(scope="module")
def engine(predictor):
    """Motor con el Laya real entrenado junto al Nivel 1."""
    motor = DecisionEngine(predictor)
    assert motor.cargar_backend() == "listo"
    yield motor
    motor.cerrar()


def make_engine(predictor, backend=None, **kwargs):
    motor = DecisionEngine(predictor, backend_factory=(lambda: backend) if backend else None, **kwargs)
    motor.cargar_backend()
    return motor


# ------------------------------------------------------- Laya entrenado y cargado

def test_laya_se_entrena_y_mejora_al_nivel1(trained_artifact):
    path, report = trained_artifact
    artefacto = joblib.load(path.parent / "laya.joblib")
    assert artefacto["tipo"] == "laya-local" and artefacto["formato"] == 1
    nivel2 = report["nivel2"]
    ev = nivel2["evaluacion_prueba"]
    assert "calibracion" in nivel2 and 0 <= ev["brier"] < 0.1 and 0 <= ev["ece"] < 0.2
    # La cascada no produce más falsos positivos que el Nivel 1 solo en el conjunto de prueba.
    assert ev["laya"]["falsos_positivos"] <= ev["nivel1_solo"]["falsos_positivos"]
    assert ev["laya"]["recall"] >= 0.85


def test_backend_por_defecto_encuentra_laya_junto_al_modelo(predictor):
    assert crear_backend_por_defecto(predictor) is not None


def test_laya_desactivable_por_entorno(predictor, monkeypatch):
    monkeypatch.setenv("LAYA_ENABLED", "0")
    assert crear_backend_por_defecto(predictor) is None


def test_artefacto_laya_incompatible_no_rompe(predictor, tmp_path, monkeypatch):
    malo = tmp_path / "laya.joblib"
    joblib.dump({"formato": 99}, malo)
    monkeypatch.setenv("LAYA_MODEL_PATH", str(malo))
    motor = DecisionEngine(predictor)
    assert motor.cargar_backend() == "no_disponible"
    assert motor.evaluar(PHISHING).decision.motor == "heuristico"
    motor.cerrar()


# ------------------------------------------------------------- comprensión real

@pytest.mark.parametrize("texto", COTIDIANOS + ENLACES_LEGITIMOS)
def test_mensajes_cotidianos_no_son_estafa(engine, texto):
    resultado = engine.evaluar_mensaje(texto)
    assert resultado["etiqueta_modelo"] == "legitimo", resultado
    assert resultado["nivel"] == "bajo", resultado
    assert resultado["accion_tactica"] == "PERMITIR"
    assert resultado["categoria_fraude"] == "CONVERSACION_GENUINA"


@pytest.mark.parametrize("texto", ENLACES_LEGITIMOS)
def test_enlaces_de_redes_sociales_no_generan_senales(engine, texto):
    assert engine.evaluar_mensaje(texto)["senales"] == []


@pytest.mark.parametrize("texto", ESTAFAS)
def test_estafas_nuevas_son_riesgo_alto(engine, texto):
    resultado = engine.evaluar_mensaje(texto)
    assert resultado["etiqueta_modelo"] == "fraudulento", resultado
    assert resultado["nivel"] == "alto"
    assert resultado["accion_tactica"] in ("ADVERTIR", "BLOQUEAR_ENLACES")
    assert resultado["categoria_fraude"] in CATEGORIAS[1:]


@pytest.mark.parametrize("texto", ["Mira mi página http://mitiendita.com", "descarga los apuntes en http://apuntes-u.net/calculo.pdf"])
def test_enlace_http_se_marca_como_riesgo(engine, texto):
    resultado = engine.evaluar_mensaje(texto)
    assert resultado["nivel"] in ("medio", "alto")
    assert resultado["accion_tactica"] in ("ADVERTIR", "BLOQUEAR_ENLACES")
    assert "enlace_inseguro" in {s["codigo"] for s in resultado["senales"]}
    if resultado["nivel"] == "medio":
        assert resultado["incertidumbre"] is True  # la app lo muestra en amarillo
        assert "http" in resultado["aviso_incertidumbre"]


def test_enlace_que_imita_banco_bloquea_enlaces(engine):
    resultado = engine.evaluar_mensaje(PHISHING, "+59170000001", "+59170000002")
    assert resultado["nivel"] == "alto"
    assert resultado["accion_tactica"] == "BLOQUEAR_ENLACES"
    assert resultado["categoria_fraude"] == "PHISHING_BANCARIO"
    assert resultado["motor_decision"] == "laya"
    assert 0.5 < resultado["confianza_calibrada"] <= 1


def test_laya_corrige_falsos_positivos_del_nivel1(engine):
    # "http" casi siempre aparece en fraudes del dataset: el Nivel 1 lo puntúa alto,
    # pero Laya no lo declara estafa; la regla de enlaces lo deja en advertencia.
    ev = engine.evaluar("Mira mi página http://mitiendita.com")
    assert ev.decision.etiqueta == "legitimo" and ev.decision.nivel == "medio"


# --------------------------------------------------------------------- fast-path

@pytest.mark.parametrize("texto", ["hola", "holaa", "bien y tu", "Bien, ¿y tú?"])
def test_fast_path_no_invoca_nivel2(predictor, texto):
    backend = SpyBackend()
    motor = make_engine(predictor, backend)
    ev = motor.evaluar(texto)
    assert ev.decision.motor == "fast_path"
    assert ev.decision.accion == "PERMITIR" and ev.decision.nivel == "bajo"
    assert backend.llamadas == 0
    motor.cerrar()


def test_fast_path_requiere_cero_senales(predictor):
    backend = SpyBackend({"probabilidad_fraude": 0.05, "categoria": None})
    motor = make_engine(predictor, backend)
    ev = motor.evaluar("Hola, aquí tienes los horarios https://biblioteca.example.org")
    assert ev.senales and ev.decision.motor == "laya" and backend.llamadas == 1
    motor.cerrar()


# --------------------------------------------------------------------- política

@pytest.mark.parametrize("p,nivel,accion", [
    (0.10, "bajo", "PERMITIR"), (0.50, "medio", "ADVERTIR"), (0.90, "alto", "BLOQUEAR_ENLACES"),
])
def test_politica_umbrales_sobre_probabilidad_calibrada(predictor, p, nivel, accion):
    # Un enlace neutral evita el fast-path sin activar reglas adicionales.
    motor = make_engine(predictor, SpyBackend({"probabilidad_fraude": p, "categoria": "OTRO_FRAUDE"}))
    ev = motor.evaluar("Los horarios están en https://biblioteca.example.org")
    assert ev.decision.motor == "laya"
    assert (ev.decision.nivel, ev.decision.accion) == (nivel, accion)
    motor.cerrar()


def test_regla_robo_de_codigo_aunque_laya_dude(predictor):
    motor = make_engine(predictor, SpyBackend({"probabilidad_fraude": 0.2, "categoria": None}))
    ev = motor.evaluar("Te mandé un código por error, pásamelo porfa")
    assert ev.decision.etiqueta == "fraudulento" and ev.decision.nivel == "alto"
    assert ev.decision.confianza_calibrada is None  # lo decidió una regla, no el modelo
    motor.cerrar()


def test_enlace_peligroso_nunca_queda_en_bajo(predictor):
    motor = make_engine(predictor, SpyBackend({"probabilidad_fraude": 0.01, "categoria": None}))
    ev = motor.evaluar("mira esto https://instagram-verificar-cuenta.com")
    assert ev.decision.nivel in ("medio", "alto")
    assert ev.decision.accion == "BLOQUEAR_ENLACES"
    motor.cerrar()


# --------------------------------------------------------------------- fallback

@pytest.mark.parametrize("backend", [
    SpyBackend(error=RuntimeError("fallo simulado")),
    SpyBackend(respuesta={"probabilidad_fraude": 1.7}),
    SpyBackend(respuesta={"probabilidad_fraude": float("nan")}),
    SpyBackend(respuesta={"probabilidad_fraude": 0.9, "categoria": "INVENTADA"}),
    SpyBackend(respuesta="no es un dict"),
], ids=["excepcion", "fuera_rango", "nan", "categoria_invalida", "tipo_invalido"])
def test_fallback_ante_errores_del_backend(predictor, backend):
    motor = make_engine(predictor, backend)
    ev = motor.evaluar(PHISHING)
    assert backend.llamadas == 1
    assert ev.decision.motor == "heuristico"
    assert ev.decision.nivel == "alto" and ev.decision.accion == "BLOQUEAR_ENLACES"
    motor.cerrar()


def test_fallback_por_timeout_de_50ms(predictor):
    liberar = threading.Event()
    backend = SpyBackend(bloqueo=liberar)
    motor = make_engine(predictor, backend, timeout=0.05, max_workers=1)
    try:
        inicio = time.perf_counter()
        ev = motor.evaluar(PHISHING)
        assert ev.decision.motor == "heuristico"
        assert time.perf_counter() - inicio < 0.5
        # Con todos los hilos ocupados no se encolan más inferencias.
        assert motor.evaluar(PHISHING).decision.motor == "heuristico"
        assert backend.llamadas == 1
    finally:
        liberar.set()
        motor.cerrar()


def test_circuit_breaker_tras_fallos_repetidos(predictor):
    backend = SpyBackend(error=RuntimeError("caído"))
    motor = make_engine(predictor, backend, max_fallos=3, enfriamiento=60)
    for _ in range(5):
        assert motor.evaluar(PHISHING).decision.motor == "heuristico"
    assert backend.llamadas == 3
    assert motor.estado_backend == "en_pausa"
    motor.cerrar()


def test_fabrica_que_falla_deja_backend_no_disponible(predictor):
    def fabrica():
        raise ImportError("laya no instalada")
    motor = DecisionEngine(predictor, backend_factory=fabrica)
    assert motor.cargar_backend() == "no_disponible"
    assert motor.evaluar(PHISHING).decision.motor == "heuristico"
    motor.cerrar()


def test_evaluar_mensaje_nunca_lanza(predictor, tmp_path):
    sin_modelo = DecisionEngine(Predictor(tmp_path / "ausente.joblib"), backend_factory=None)
    resultado = sin_modelo.evaluar_mensaje(PHISHING)
    assert resultado["etiqueta_modelo"] == "desconocido"
    assert resultado["motor_decision"] == "heuristico_sin_modelo"
    assert resultado["accion_tactica"] in ("ADVERTIR", "BLOQUEAR_ENLACES")
    sin_modelo.cerrar()

    roto = make_engine(predictor)
    roto.evaluar = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("inesperado"))
    resultado = roto.evaluar_mensaje("hola")
    assert resultado["nivel"] == "desconocido" and NUEVOS <= resultado.keys()
    roto.cerrar()


# ------------------------------------------------------------------ integración

def test_websocket_perfil_instagram_es_seguro_y_phishing_es_alto(trained_artifact):
    with TestClient(create_app(trained_artifact[0])) as client:
        with client.websocket_connect("/ws/chat/+59170000001") as ws1:
            ws1.receive_json()
            with client.websocket_connect("/ws/chat/+59170000002") as ws2:
                ws2.receive_json()
                ws1.receive_json()
                ws1.send_json({"tipo": "mensaje", "destinatario": "+59170000002",
                               "texto": "sigueme en insta https://www.instagram.com/carla.rios.bo/"})
                ws1.receive_json()
                seguro = ws2.receive_json()
                assert seguro["etiqueta_modelo"] == "legitimo" and seguro["nivel"] == "bajo"
                assert seguro["senales"] == [] and seguro["incertidumbre"] is False

                ws1.send_json({"tipo": "mensaje", "destinatario": "+59170000002", "texto": PHISHING})
                ws1.receive_json()
                fraude = ws2.receive_json()
                assert {"etiqueta_modelo", "nivel", "incertidumbre", "senales", "recomendaciones"} <= fraude.keys()
                assert NUEVOS <= fraude.keys()
                assert fraude["etiqueta_modelo"] == "fraudulento" and fraude["nivel"] == "alto"
                assert fraude["accion_tactica"] == "BLOQUEAR_ENLACES"


def test_websocket_sigue_funcionando_si_el_motor_falla(trained_artifact):
    app = create_app(trained_artifact[0])
    with TestClient(app) as client:
        def explota(*a, **k):
            raise RuntimeError("fallo simulado")
        app.state.decision_engine.evaluar = explota
        with client.websocket_connect("/ws/chat/+59170000001") as ws1:
            ws1.receive_json()
            ws1.send_json({"tipo": "mensaje", "destinatario": "+59170000002", "texto": "hola"})
            enviado = ws1.receive_json()
            assert enviado["tipo"] == "mensaje_enviado" and enviado["nivel"] == "desconocido"
            assert ws1.receive_json()["tipo"] == "info"  # destinatario desconectado
            ws1.send_json({"tipo": "ping"})
            assert ws1.receive_json()["tipo"] == "pong"


def test_analizar_y_estado_usan_laya(trained_artifact):
    with TestClient(create_app(trained_artifact[0])) as client:
        assert client.get("/estado").json()["motor_decision"] == "listo"
        data = client.post("/analizar", json={"texto": PHISHING}).json()
        assert data["etiqueta_modelo"] == "fraudulento" and data["nivel"] == "alto"
        assert data["accion_tactica"] == "BLOQUEAR_ENLACES" and data["motor_decision"] == "laya"
        perfil = client.post("/analizar", json={"texto": "mira mi perfil https://www.instagram.com/lu.foto/"}).json()
        assert perfil["nivel"] == "bajo" and perfil["incertidumbre"] is False and perfil["senales"] == []
        http = client.post("/analizar", json={"texto": "Mira mi página http://mitiendita.com"}).json()
        assert http["incertidumbre"] is True or http["nivel"] == "alto"
