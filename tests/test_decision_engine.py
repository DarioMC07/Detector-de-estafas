"""Pruebas del motor de decisión táctica en cascada (Nivel 1 → Nivel 2)."""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.decision_engine import ACCIONES, CATEGORIAS, DecisionEngine, laya_backend_from_env
from app.main import create_app
from app.predictor import Predictor

PHISHING = "BNB: tu cuenta fue bloqueada. Ingresa tu clave en http://bnb-seguro.info/login urgente"
NUEVOS = {"accion_tactica", "categoria_fraude", "confianza_calibrada", "motor_decision"}


class SpyBackend:
    """Backend de Nivel 2 falso que registra cuántas veces se le invoca."""

    def __init__(self, respuesta=None, error=None, retardo=0.0, bloqueo=None):
        self.respuesta = respuesta or {"accion": "ADVERTIR", "categoria": "PHISHING_BANCARIO", "confianza": 0.87}
        self.error, self.retardo, self.bloqueo = error, retardo, bloqueo
        self.llamadas = 0

    def decidir(self, caracteristicas):
        self.llamadas += 1
        self.ultimas = caracteristicas
        if self.bloqueo is not None:
            self.bloqueo.wait(5)
        if self.retardo:
            time.sleep(self.retardo)
        if self.error:
            raise self.error
        return self.respuesta


@pytest.fixture(scope="module")
def predictor(trained_artifact):
    return Predictor(trained_artifact[0])


def make_engine(predictor, backend=None, **kwargs):
    engine = DecisionEngine(predictor, backend_factory=(lambda: backend) if backend else None, **kwargs)
    engine.cargar_backend(timeout=5)
    return engine


# --------------------------------------------------------------------- fast-path

@pytest.mark.parametrize("texto", ["hola", "holaa", "bien y tu", "Bien, ¿y tú?"])
def test_fast_path_saludos_no_invoca_nivel2(predictor, texto):
    backend = SpyBackend()
    engine = make_engine(predictor, backend)
    ev = engine.evaluar(texto)
    assert ev.prediccion.puntuacion < 0.20 and ev.senales == []
    assert ev.decision.motor == "fast_path"
    assert ev.decision.accion == "PERMITIR"
    assert ev.decision.categoria == "CONVERSACION_GENUINA"
    assert backend.llamadas == 0
    engine.cerrar()


def test_fast_path_requiere_cero_senales(predictor):
    # Puntuación baja pero con enlace: no se toma el camino rápido.
    engine = make_engine(predictor)
    ev = engine.evaluar("Hola, aquí tienes los horarios https://biblioteca.example.org")
    assert ev.senales
    assert ev.decision.motor != "fast_path"
    engine.cerrar()


# ----------------------------------------------------------- decisión heurística

def test_phishing_bancario_con_enlace_bloquea_enlaces(predictor):
    engine = make_engine(predictor)  # sin Laya: árbitro heurístico
    resultado = engine.evaluar_mensaje(PHISHING, "+59170000001", "+59170000002")
    assert resultado["etiqueta_modelo"] == "fraudulento"
    assert resultado["nivel"] == "alto"
    assert resultado["accion_tactica"] == "BLOQUEAR_ENLACES"
    assert resultado["categoria_fraude"] == "PHISHING_BANCARIO"
    assert resultado["motor_decision"] == "heuristico"
    # La heurística no está calibrada: no inventa una probabilidad.
    assert resultado["confianza_calibrada"] is None
    assert {"enlace", "credenciales"} <= {s["codigo"] for s in resultado["senales"]}
    engine.cerrar()


@pytest.mark.parametrize("texto,categoria", [
    ("Ganaste un premio de 10.000 BS. Paga una tasa en https://premio.example.com", "PREMIO_FALSO"),
    ("Hola mamá, cambié de número, guarda este. Necesito que me transfieras 500 Bs", "SUPLANTACION_IDENTIDAD"),
])
def test_categorias_heuristicas(predictor, texto, categoria):
    engine = make_engine(predictor)
    ev = engine.evaluar(texto)
    assert ev.decision.categoria == categoria
    assert ev.decision.accion in ("ADVERTIR", "BLOQUEAR_ENLACES")
    engine.cerrar()


# ------------------------------------------------------------------ nivel 2 OK

def test_laya_decide_cuando_esta_disponible(predictor):
    backend = SpyBackend({"accion": "BLOQUEAR_ENLACES", "categoria": "PHISHING_BANCARIO", "confianza": 0.93})
    engine = make_engine(predictor, backend)
    assert engine.estado_backend == "listo"
    ev = engine.evaluar(PHISHING, "+59170000001", "+59170000002")
    assert backend.llamadas == 1
    assert ev.decision.motor == "laya"
    assert ev.decision.confianza_calibrada == pytest.approx(0.93)
    # El backend recibe las características del Nivel 1.
    assert backend.ultimas["etiqueta_nivel1"] == "fraudulento"
    assert "enlace" in backend.ultimas["senales"]
    assert backend.ultimas["contexto_bancario"] is True
    engine.cerrar()


def test_laya_no_rebaja_el_piso_del_nivel1(predictor):
    backend = SpyBackend({"accion": "PERMITIR", "categoria": "CONVERSACION_GENUINA", "confianza": 0.6})
    engine = make_engine(predictor, backend)
    ev = engine.evaluar(PHISHING)
    assert ev.decision.motor == "laya"
    assert ev.decision.accion == "ADVERTIR"  # fraudulento en Nivel 1 → mínimo ADVERTIR
    assert ev.decision.categoria == "PHISHING_BANCARIO"
    engine.cerrar()


def test_bloquear_enlaces_sin_enlace_se_convierte_en_advertir(predictor):
    backend = SpyBackend({"accion": "BLOQUEAR_ENLACES", "categoria": "PHISHING_BANCARIO", "confianza": 0.8})
    engine = make_engine(predictor, backend)
    ev = engine.evaluar("URGENTE: envía tu contraseña y haz una transferencia ahora mismo.")
    assert ev.decision.accion == "ADVERTIR"
    engine.cerrar()


# --------------------------------------------------------------------- fallback

@pytest.mark.parametrize("backend", [
    SpyBackend(error=RuntimeError("fallo simulado")),
    SpyBackend(respuesta={"accion": "EXPLOTAR", "categoria": "PHISHING_BANCARIO", "confianza": 0.5}),
    SpyBackend(respuesta={"accion": "ADVERTIR", "categoria": "PHISHING_BANCARIO", "confianza": 1.7}),
    SpyBackend(respuesta={"accion": "ADVERTIR", "categoria": "PHISHING_BANCARIO", "confianza": float("nan")}),
    SpyBackend(respuesta="no es un dict"),
], ids=["excepcion", "accion_invalida", "confianza_fuera_rango", "confianza_nan", "tipo_invalido"])
def test_fallback_ante_errores_del_backend(predictor, backend):
    engine = make_engine(predictor, backend)
    ev = engine.evaluar(PHISHING)
    assert backend.llamadas == 1
    assert ev.decision.motor == "heuristico"
    assert ev.decision.accion == "BLOQUEAR_ENLACES"
    assert ev.decision.accion in ACCIONES and ev.decision.categoria in CATEGORIAS
    engine.cerrar()


def test_fallback_por_timeout_de_50ms(predictor):
    liberar = threading.Event()
    backend = SpyBackend(bloqueo=liberar)
    engine = make_engine(predictor, backend, timeout=0.05)
    try:
        inicio = time.perf_counter()
        ev = engine.evaluar(PHISHING)
        transcurrido = time.perf_counter() - inicio
        assert ev.decision.motor == "heuristico"
        assert transcurrido < 0.5
        # Mientras la inferencia lenta sigue en curso, no se encolan más llamadas.
        ev2 = engine.evaluar(PHISHING)
        assert ev2.decision.motor == "heuristico"
        assert backend.llamadas == 1
    finally:
        liberar.set()
        engine.cerrar()


def test_circuit_breaker_tras_fallos_repetidos(predictor):
    backend = SpyBackend(error=RuntimeError("caído"))
    engine = make_engine(predictor, backend, max_fallos=3, enfriamiento=60)
    for _ in range(5):
        assert engine.evaluar(PHISHING).decision.motor == "heuristico"
    assert backend.llamadas == 3
    assert engine.estado_backend == "en_pausa"
    engine.cerrar()


def test_fabrica_que_falla_deja_backend_no_disponible(predictor):
    def fabrica():
        raise ImportError("laya no instalada")
    engine = DecisionEngine(predictor, backend_factory=fabrica)
    assert engine.cargar_backend(timeout=5) == "no_disponible"
    assert engine.evaluar(PHISHING).decision.motor == "heuristico"
    engine.cerrar()


def test_laya_no_instalada_devuelve_none(monkeypatch):
    monkeypatch.setenv("LAYA_MODULE", "modulo_laya_inexistente_xyz")
    assert laya_backend_from_env() is None
    monkeypatch.setenv("LAYA_ENABLED", "0")
    assert laya_backend_from_env() is None


def test_evaluar_mensaje_nunca_lanza(predictor, tmp_path):
    sin_modelo = DecisionEngine(Predictor(tmp_path / "ausente.joblib"), backend_factory=None)
    resultado = sin_modelo.evaluar_mensaje(PHISHING)
    assert resultado["etiqueta_modelo"] == "desconocido"
    assert resultado["accion_tactica"] in ("ADVERTIR", "BLOQUEAR_ENLACES")
    assert resultado["motor_decision"] == "heuristico_sin_modelo"
    sin_modelo.cerrar()

    roto = make_engine(predictor)
    roto.evaluar = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("inesperado"))
    resultado = roto.evaluar_mensaje("hola")
    assert resultado["nivel"] == "desconocido" and NUEVOS <= resultado.keys()
    roto.cerrar()


# ------------------------------------------------------------------ integración

def test_websocket_conserva_campos_y_anade_los_nuevos(trained_artifact):
    with TestClient(create_app(trained_artifact[0])) as client:
        with client.websocket_connect("/ws/chat/+59170000001") as ws1:
            ws1.receive_json()
            with client.websocket_connect("/ws/chat/+59170000002") as ws2:
                ws2.receive_json()
                ws1.receive_json()
                ws1.send_json({"tipo": "mensaje", "destinatario": "+59170000002", "texto": PHISHING})
                enviado = ws1.receive_json()
                recibido = ws2.receive_json()
                for msg in (enviado, recibido):
                    assert {"etiqueta_modelo", "nivel", "incertidumbre", "senales", "recomendaciones"} <= msg.keys()
                    assert NUEVOS <= msg.keys()
                    assert msg["accion_tactica"] == "BLOQUEAR_ENLACES"
                    assert msg["categoria_fraude"] == "PHISHING_BANCARIO"


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
            assert enviado["tipo"] == "mensaje_enviado"
            assert enviado["nivel"] == "desconocido"
            assert ws1.receive_json()["tipo"] == "info"  # destinatario desconectado
            # La conexión sigue viva
            ws1.send_json({"tipo": "ping"})
            assert ws1.receive_json()["tipo"] == "pong"


def test_analizar_y_estado_exponen_nivel2(trained_artifact):
    with TestClient(create_app(trained_artifact[0])) as client:
        data = client.post("/analizar", json={"texto": PHISHING}).json()
        assert data["etiqueta_modelo"] == "fraudulento" and data["nivel"] == "alto"
        assert data["accion_tactica"] == "BLOQUEAR_ENLACES"
        assert data["categoria_fraude"] == "PHISHING_BANCARIO"
        saludo = client.post("/analizar", json={"texto": "hola"}).json()
        assert saludo["motor_decision"] == "fast_path" and saludo["accion_tactica"] == "PERMITIR"
        assert client.get("/estado").json()["motor_decision"] in ("no_disponible", "cargando", "listo")
