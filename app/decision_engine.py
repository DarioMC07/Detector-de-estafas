"""Motor de decisión táctica en cascada.

Nivel 1 (sensor, ``app.predictor`` + ``app.signals``): clasificador TF-IDF y reglas
léxicas. Rápido (<2 ms). Su puntuación es una CARACTERÍSTICA para el Nivel 2.

Nivel 2 (árbitro, Laya): modelo entrenado en ``training/train_laya.py`` que combina la
puntuación del Nivel 1 con señales, análisis de enlaces y rasgos de estilo, y devuelve
una probabilidad de fraude CALIBRADA. Sobre esa probabilidad se aplica una política
explícita que decide el veredicto final que ve la app:

    p < 0.40            -> legítimo (nivel bajo)        -> PERMITIR
    0.40 <= p < 0.65    -> dudoso   (nivel medio)       -> ADVERTIR
    p >= 0.65           -> fraude   (nivel alto)        -> ADVERTIR / BLOQUEAR_ENLACES

Reglas de seguridad deterministas sobre enlaces (aplican siempre):
- Enlace "peligroso" (imita un banco/marca, IP, punycode): como mínimo nivel medio y
  BLOQUEAR_ENLACES; si además hay otra evidencia, fraude.
- Enlace "sospechoso" (http sin cifrar, acortador, TLD de riesgo): como mínimo
  nivel medio y ADVERTIR.
- Enlaces "confiables" (Instagram, YouTube, bancos oficiales...): no suman riesgo.

Fast-path: puntuación del Nivel 1 < 0.20 y cero señales -> PERMITIR sin invocar Laya.
Fallback: si Laya no está disponible, falla o tarda más de 50 ms, se usa la decisión
del Nivel 1 con las mismas reglas de enlaces. ``evaluar_mensaje`` nunca lanza.

Privacidad: no se registra el texto ni los números de teléfono.
"""

from __future__ import annotations

import importlib
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

import joblib
import sklearn
from threadpoolctl import ThreadpoolController

from app.predictor import ModelUnavailable, Prediction, Predictor, clean_chat_elongation
from app.schemas import Signal
from app.signals import CODIGOS_ENLACE_RIESGO, detect_signals, recommendations
from app.text_features import CARACTERISTICAS, caracteristicas_laya, contexto_rapido
from app.url_analysis import ReporteEnlaces, analizar_enlaces

ACCIONES = ("PERMITIR", "ADVERTIR", "BLOQUEAR_ENLACES")
CATEGORIAS = ("CONVERSACION_GENUINA", "PHISHING_BANCARIO", "SUPLANTACION_IDENTIDAD", "PREMIO_FALSO", "OTRO_FRAUDE")
FAST_PATH_MAX_SCORE = 0.20
UMBRAL_ADVERTENCIA = 0.40
UMBRAL_FRAUDE = 0.65
_SENALES_FUERTES = frozenset({"credenciales", "dinero", "urgencia", "premio", "suplantacion"})

_MOTIVO_TEXTO = {
    "http_sin_cifrar": "que usa http:// sin cifrar (lo habitual es https://)",
    "acortador": "acortado que oculta su destino real",
    "tld_sospechoso": "con una terminación de dominio muy usada en fraudes",
    "palabras_cebo": "con palabras cebo en el dominio",
    "dominio_enrevesado": "con un dominio enrevesado",
    "imita_marca": "que imita a un banco o marca conocida",
    "direccion_ip": "que apunta a una dirección IP",
    "punycode": "con caracteres que imitan letras normales",
    "arroba_oculta_destino": "que oculta su destino real",
}


@dataclass(frozen=True)
class DecisionTactica:
    accion: str
    categoria: str
    # Probabilidad calibrada de la clase elegida. Solo existe cuando decide Laya;
    # la heurística no está calibrada y deja None en vez de inventar un número.
    confianza_calibrada: float | None
    motor: str  # "fast_path" | "laya" | "heuristico" | "heuristico_sin_modelo"
    etiqueta: str = "legitimo"      # veredicto final: "legitimo" | "fraudulento"
    nivel: str = "bajo"             # "bajo" | "medio" | "alto"
    incierto: bool = False
    aviso: str | None = None


@dataclass(frozen=True)
class Evaluacion:
    prediccion: Prediction
    senales: list[Signal]
    decision: DecisionTactica


class TacticalBackend(Protocol):
    """Contrato del árbitro de Nivel 2."""

    def decidir(self, caracteristicas: dict[str, Any]) -> dict[str, Any]:
        """Devuelve {"probabilidad_fraude": float en [0, 1], "categoria": str | None}."""


class BackendUnavailable(RuntimeError):
    pass


_CONTROLADOR_HILOS: ThreadpoolController | None = None


def _hilos() -> ThreadpoolController:
    """Controlador de hilos nativos creado una vez (escanear librerías en cada llamada es caro)."""
    global _CONTROLADOR_HILOS
    if _CONTROLADOR_HILOS is None:
        _CONTROLADOR_HILOS = ThreadpoolController()
    return _CONTROLADOR_HILOS


class LayaLocalBackend:
    """Laya entrenado localmente (artefacto ``laya.joblib`` de training/train_laya.py)."""

    def __init__(self, path: Path) -> None:
        # Solo artefactos propios: joblib puede ejecutar código al deserializar.
        artefacto = joblib.load(path)
        if not isinstance(artefacto, dict) or artefacto.get("formato") != 1 or artefacto.get("tipo") != "laya-local":
            raise BackendUnavailable("Artefacto Laya incompatible.")
        if artefacto.get("caracteristicas") != list(CARACTERISTICAS):
            raise BackendUnavailable("Las características del artefacto no coinciden; reentrena.")
        riesgo = artefacto.get("riesgo")
        if not hasattr(riesgo, "predict_proba"):
            raise BackendUnavailable("Modelo de riesgo inválido.")
        self._riesgo = riesgo
        self._categoria = artefacto.get("categoria")
        umbrales = artefacto.get("umbrales") or {}
        self.umbrales = {
            "advertencia": float(umbrales.get("advertencia", UMBRAL_ADVERTENCIA)),
            "fraude": float(umbrales.get("fraude", UMBRAL_FRAUDE)),
        }
        # Calentamiento: la primera inferencia de sklearn es más lenta.
        self.decidir({"texto": "hola, nos vemos mañana", "probabilidad_lexica": 0.1, "senales": []})

    def decidir(self, caracteristicas: dict[str, Any]) -> dict[str, Any]:
        texto = caracteristicas["texto"]
        x = caracteristicas_laya(texto, caracteristicas["probabilidad_lexica"],
                                 frozenset(caracteristicas.get("senales", ())))
        # Una sola fila: arrancar hilos OpenMP cuesta más que la propia predicción.
        with _hilos().limit(limits=1), sklearn.config_context(assume_finite=True):
            p = float(self._riesgo.predict_proba([x])[0][1])
            categoria = None
            if self._categoria is not None and p >= self.umbrales["advertencia"]:
                categoria = str(self._categoria.predict([texto])[0])
        return {"probabilidad_fraude": p, "categoria": categoria}


class LayaModuleBackend:
    """Adaptador para un runtime Laya externo (``LAYA_MODULE``).

    Interfaz esperada: el módulo expone ``load_decision_model(path)`` (o ``load``) y el
    objeto devuelto tiene ``decide(features: dict) -> dict`` con el mismo contrato que
    ``TacticalBackend`` (probabilidad_fraude calibrada + categoria).
    """

    def __init__(self, module_name: str, model_path: str | None = None) -> None:
        module = importlib.import_module(module_name)
        loader = getattr(module, "load_decision_model", None) or getattr(module, "load", None)
        if not callable(loader):
            raise BackendUnavailable("El módulo no expone un cargador de modelo compatible.")
        model = loader(model_path) if model_path else loader()
        decide = getattr(model, "decide", None)
        if not callable(decide):
            raise BackendUnavailable("El modelo cargado no expone decide().")
        self._decide = decide

    def decidir(self, caracteristicas: dict[str, Any]) -> dict[str, Any]:
        return self._decide(caracteristicas)


def crear_backend_por_defecto(predictor: Predictor) -> TacticalBackend | None:
    """Laya externo si LAYA_MODULE está definido; si no, el artefacto local laya.joblib."""
    if os.getenv("LAYA_ENABLED", "1").strip().lower() in ("0", "false", "no", "off"):
        return None
    module_name = (os.getenv("LAYA_MODULE") or "").strip()
    model_path = (os.getenv("LAYA_MODEL_PATH") or "").strip() or None
    if module_name:
        return LayaModuleBackend(module_name, model_path)
    base = getattr(predictor, "path", None)
    path = Path(model_path) if model_path else (Path(base).parent / "laya.joblib" if base else None)
    if path is None or not path.exists():
        return None
    return LayaLocalBackend(path)


def categoria_heuristica(texto: str, codigos: set[str] | frozenset[str]) -> str:
    ctx = contexto_rapido(texto)
    if ctx["robo_codigo"]:
        return "PHISHING_BANCARIO"  # robo de credenciales (código de verificación)
    if "premio" in codigos:
        return "PREMIO_FALSO"
    if ctx["suplantacion"] or "suplantacion" in codigos:
        return "SUPLANTACION_IDENTIDAD"
    if ctx["bancario"] or ctx["peticion_datos"] or "credenciales" in codigos or "enlace_suplantacion" in codigos:
        return "PHISHING_BANCARIO"
    return "OTRO_FRAUDE"


def _aviso_enlace(reporte: ReporteEnlaces) -> str:
    motivos = []
    for enlace in reporte.enlaces:
        if enlace.nivel in ("sospechoso", "peligroso"):
            motivos.extend(m for m in enlace.motivos if m not in motivos)
    detalle = " y ".join(_MOTIVO_TEXTO[m] for m in motivos[:2]) if motivos else "con riesgo"
    return (f"Precaución: el mensaje contiene un enlace {detalle}. "
            "No lo abras ni ingreses datos personales o bancarios.")


_SENTINEL = object()


class DecisionEngine:
    """Orquesta la cascada Nivel 1 → (fast-path | Laya | fallback)."""

    def __init__(
        self,
        predictor: Predictor,
        backend_factory: Callable[[], TacticalBackend | None] | None | object = _SENTINEL,
        timeout: float | None = None,
        max_fallos: int = 3,
        enfriamiento: float = 60.0,
        max_workers: int = 4,
    ) -> None:
        self.predictor = predictor
        if backend_factory is _SENTINEL:
            backend_factory = lambda: crear_backend_por_defecto(predictor)  # noqa: E731
        self._factory = backend_factory
        if timeout is None:
            try:
                timeout = float(os.getenv("LAYA_TIMEOUT_MS", "50")) / 1000
            except ValueError:
                timeout = 0.05
        self.timeout = timeout if math.isfinite(timeout) and timeout > 0 else 0.05
        self.max_fallos = max_fallos
        self.enfriamiento = enfriamiento
        self.umbral_advertencia = UMBRAL_ADVERTENCIA
        self.umbral_fraude = UMBRAL_FRAUDE

        self._lock = threading.Lock()
        self._max_workers = max(1, max_workers)
        self._executor = ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix="laya")
        self._backend: TacticalBackend | None = None
        self._estado = "pendiente"  # pendiente | cargando | listo | no_disponible
        self._carga = None
        self._en_vuelo = 0
        self._fallos = 0
        self._pausado_hasta = 0.0

    # ------------------------------------------------------------------ backend

    @property
    def estado_backend(self) -> str:
        if self._estado == "listo" and time.monotonic() < self._pausado_hasta:
            return "en_pausa"
        return self._estado

    def iniciar(self, espera: float = 0.0) -> None:
        """Carga el backend en segundo plano; ``espera`` segundos como máximo de bloqueo."""
        with self._lock:
            if self._estado == "pendiente":
                if self._factory is None:
                    self._estado = "no_disponible"
                else:
                    self._estado = "cargando"
                    self._carga = self._executor.submit(self._cargar)
            carga = self._carga
        if espera > 0 and carga is not None:
            try:
                carga.result(timeout=espera)
            except Exception:
                pass

    def cargar_backend(self, timeout: float | None = 10.0) -> str:
        """Carga el backend y espera el resultado (útil en pruebas y scripts)."""
        self.iniciar(espera=timeout or 10.0)
        return self.estado_backend

    def _cargar(self) -> None:
        try:
            backend = self._factory() if self._factory else None
        except Exception:
            backend = None
        with self._lock:
            self._backend = backend
            umbrales = getattr(backend, "umbrales", None)
            if isinstance(umbrales, dict):
                self.umbral_advertencia = float(umbrales.get("advertencia", UMBRAL_ADVERTENCIA))
                self.umbral_fraude = float(umbrales.get("fraude", UMBRAL_FRAUDE))
            self._estado = "listo" if backend is not None else "no_disponible"

    def _backend_disponible(self) -> TacticalBackend | None:
        if self._estado == "pendiente":
            self.iniciar()  # carga diferida en el primer uso
        if self._estado != "listo" or time.monotonic() < self._pausado_hasta:
            return None
        return self._backend

    def _registrar_fallo(self) -> None:
        with self._lock:
            self._fallos += 1
            if self._fallos >= self.max_fallos:
                # Circuit breaker: deja de llamar al backend durante un tiempo.
                self._pausado_hasta = time.monotonic() + self.enfriamiento
                self._fallos = 0

    def _terminado(self, _futuro) -> None:
        with self._lock:
            self._en_vuelo -= 1

    def _invocar_backend(self, backend: TacticalBackend, caracteristicas: dict[str, Any]) -> tuple[float, str | None] | None:
        with self._lock:
            if self._en_vuelo >= self._max_workers:
                return None  # todos los hilos ocupados (inferencias lentas): no encolar
            self._en_vuelo += 1
        try:
            futuro = self._executor.submit(backend.decidir, dict(caracteristicas))
        except RuntimeError:  # executor cerrado
            self._terminado(None)
            return None
        futuro.add_done_callback(self._terminado)
        try:
            salida = self._validar_salida(futuro.result(timeout=self.timeout))
        except (FutureTimeout, Exception):
            self._registrar_fallo()
            return None
        with self._lock:
            self._fallos = 0
        return salida

    @staticmethod
    def _validar_salida(bruto: Any) -> tuple[float, str | None]:
        if not isinstance(bruto, dict):
            raise ValueError("Salida no es un dict")
        p = bruto.get("probabilidad_fraude")
        if isinstance(p, bool) or not isinstance(p, (int, float)):
            raise ValueError("Probabilidad inválida")
        p = float(p)
        if not math.isfinite(p) or not 0.0 <= p <= 1.0:
            raise ValueError("Probabilidad fuera de rango")
        categoria = bruto.get("categoria")
        if categoria is not None and categoria not in CATEGORIAS:
            raise ValueError("Categoría desconocida")
        return p, categoria

    def cerrar(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------ políticas

    def politica_laya(self, texto: str, p: float, categoria_modelo: str | None, prediccion: Prediction,
                      senales: list[Signal], reporte: ReporteEnlaces) -> DecisionTactica:
        codigos = {s.codigo for s in senales}
        fuertes = codigos & _SENALES_FUERTES
        enlace = reporte.nivel_maximo
        fraude = p >= self.umbral_fraude
        dudoso = self.umbral_advertencia <= p < self.umbral_fraude
        aviso = None
        ctx = contexto_rapido(texto)
        fraude_modelo = fraude
        # Regla de seguridad: pedir que reenvíen un código recibido = robo de cuenta.
        if ctx["robo_codigo"]:
            fraude = True
        # Zona dudosa + patrón de alto riesgo inequívoco (pedir claves/PIN, pagar antes de
        # recibir, "número nuevo" pidiendo dinero, acortador con dinero/urgencia) -> fraude.
        alto_riesgo = ctx["peticion_datos"] or ctx["pago_previo"] or (
            (ctx["suplantacion"] or "suplantacion" in codigos) and "dinero" in codigos) or (
            reporte.tiene_motivo("acortador") and bool(fuertes))
        if dudoso and alto_riesgo:
            fraude, dudoso = True, False
        # Salvaguarda ante un posible error de Laya: Nivel 1 muy seguro + varias señales fuertes.
        if not fraude and not dudoso and prediccion.etiqueta == "fraudulento" \
                and (prediccion.puntuacion or 0) >= 0.9 and len(fuertes) >= 2:
            dudoso = True
        if enlace == "peligroso":
            if p >= self.umbral_advertencia or fuertes:
                fraude = True
            else:
                dudoso = True
        elif enlace == "sospechoso" and not fraude:
            dudoso = True
            aviso = _aviso_enlace(reporte)
        if enlace == "peligroso" and not fraude:
            aviso = _aviso_enlace(reporte)

        if fraude:
            # Si el fraude lo decidió una regla (no el modelo), no hay confianza calibrada.
            etiqueta, nivel, confianza = "fraudulento", "alto", (p if fraude_modelo else None)
        elif dudoso:
            etiqueta, nivel, confianza = "legitimo", "medio", max(p, 1 - p)
            if aviso is None:
                aviso = ("Resultado incierto: el motor de decisión no tiene certeza suficiente. "
                         "Revisa el mensaje con calma antes de actuar.")
        else:
            etiqueta, nivel, confianza = "legitimo", "bajo", 1 - p

        enlace_riesgo = bool(codigos & CODIGOS_ENLACE_RIESGO)
        if enlace == "peligroso" or (fraude and reporte.total and not reporte.solo_confiables):
            accion = "BLOQUEAR_ENLACES"
        elif fraude or dudoso or enlace_riesgo:
            accion = "ADVERTIR"
        else:
            accion = "PERMITIR"

        # La categoría de fraude solo se informa con evidencia (no por un simple enlace http).
        if fraude or (p >= self.umbral_advertencia and fuertes):
            categoria = categoria_modelo if categoria_modelo in CATEGORIAS[1:] else categoria_heuristica(texto, codigos)
        else:
            categoria = "CONVERSACION_GENUINA"
        return DecisionTactica(accion, categoria, None if confianza is None else round(confianza, 4), "laya",
                               etiqueta, nivel, nivel == "medio", aviso)

    @staticmethod
    def politica_respaldo(texto: str, prediccion: Prediction | None, senales: list[Signal],
                          reporte: ReporteEnlaces, motor: str = "heuristico") -> DecisionTactica:
        """Sin Laya: decisión del Nivel 1 (como antes) + las mismas reglas de enlaces."""
        codigos = {s.codigo for s in senales}
        enlace = reporte.nivel_maximo
        if prediccion is None:
            etiqueta, nivel, incierto = "desconocido", "desconocido", False
        else:
            etiqueta = prediccion.etiqueta
            if etiqueta == "fraudulento":
                nivel = "alto" if senales else ("medio" if prediccion.incertidumbre else "alto")
            else:
                nivel = "medio" if prediccion.incertidumbre else "bajo"
            incierto = prediccion.incertidumbre and not senales
        aviso = "Resultado incierto: la puntuación está en la zona intermedia." if incierto else None
        if prediccion is not None and contexto_rapido(texto)["robo_codigo"]:
            etiqueta, nivel, incierto, aviso = "fraudulento", "alto", False, None
        if enlace == "peligroso" and prediccion is not None:
            if codigos & _SENALES_FUERTES:
                etiqueta, nivel = "fraudulento", "alto"
            elif nivel == "bajo":
                nivel, incierto, aviso = "medio", True, _aviso_enlace(reporte)
        elif enlace == "sospechoso" and nivel == "bajo":
            nivel, incierto, aviso = "medio", True, _aviso_enlace(reporte)

        fraude = etiqueta == "fraudulento"
        if enlace == "peligroso" or (fraude and reporte.total and not reporte.solo_confiables):
            accion = "BLOQUEAR_ENLACES"
        elif fraude or nivel in ("medio", "desconocido") or codigos & CODIGOS_ENLACE_RIESGO:
            accion = "ADVERTIR"
        else:
            accion = "PERMITIR"
        categoria = categoria_heuristica(texto, codigos) if (fraude or nivel == "medio") else "CONVERSACION_GENUINA"
        if prediccion is None:
            categoria = categoria_heuristica(texto, codigos) if codigos else "CONVERSACION_GENUINA"
        return DecisionTactica(accion, categoria, None, motor, etiqueta, nivel, incierto, aviso)

    # ------------------------------------------------------------------ cascada

    @staticmethod
    def es_fast_path(prediccion: Prediction, senales: list[Signal]) -> bool:
        return (not senales and prediccion.puntuacion is not None
                and prediccion.puntuacion < FAST_PATH_MAX_SCORE)

    def evaluar(self, texto: str, remitente: str | None = None, destinatario: str | None = None) -> Evaluacion:
        """Evaluación completa. Lanza ModelUnavailable si el Nivel 1 no está disponible."""
        prediccion = self.predictor.classify(texto)
        senales = detect_signals(texto)
        reporte = analizar_enlaces(texto)

        if self.es_fast_path(prediccion, senales):
            decision = self.politica_respaldo(texto, prediccion, senales, reporte, motor="fast_path")
            return Evaluacion(prediccion, senales, decision)

        decision = self.politica_respaldo(texto, prediccion, senales, reporte)
        try:
            backend = self._backend_disponible()
            if backend is not None:
                salida = self._invocar_backend(backend, {
                    "texto": clean_chat_elongation(texto),
                    "probabilidad_lexica": prediccion.puntuacion if prediccion.puntuacion is not None else 0.5,
                    "senales": sorted(s.codigo for s in senales),
                    "remitente": remitente,
                    "destinatario": destinatario,
                })
                if salida is not None:
                    decision = self.politica_laya(texto, salida[0], salida[1], prediccion, senales, reporte)
        except Exception:
            pass  # se conserva la decisión de respaldo
        return Evaluacion(prediccion, senales, decision)

    def evaluar_mensaje(self, texto: str, remitente: str | None = None, destinatario: str | None = None) -> dict[str, Any]:
        """Payload de seguridad para el chat. Nunca lanza excepciones."""
        try:
            evaluacion = self.evaluar(texto, remitente, destinatario)
        except Exception:
            return self._payload_sin_modelo(texto)
        prediccion, senales, decision = evaluacion.prediccion, evaluacion.senales, evaluacion.decision
        return {
            "etiqueta_modelo": decision.etiqueta,
            "nivel": decision.nivel,
            "incertidumbre": decision.incierto,
            "aviso_incertidumbre": decision.aviso,
            "senales": [{"codigo": s.codigo, "titulo": s.titulo, "descripcion": s.descripcion} for s in senales],
            "recomendaciones": recommendations(decision.nivel, senales),
            "datos_demostrativos": self.predictor.metadata.get("datos_demostrativos", False),
            "etiqueta_nivel1": prediccion.etiqueta,
            **self.campos_decision(decision),
        }

    def _payload_sin_modelo(self, texto: str) -> dict[str, Any]:
        try:
            senales = detect_signals(texto)
            decision = self.politica_respaldo(texto, None, senales, analizar_enlaces(texto), "heuristico_sin_modelo")
        except Exception:
            decision = DecisionTactica("ADVERTIR", "CONVERSACION_GENUINA", None, "heuristico_sin_modelo")
        return {
            "etiqueta_modelo": "desconocido",
            "nivel": "desconocido",
            "incertidumbre": False,
            "aviso_incertidumbre": None,
            "senales": [],
            "recomendaciones": ["El modelo no está disponible. Sé precavido con este mensaje."],
            "datos_demostrativos": False,
            "etiqueta_nivel1": "desconocido",
            **self.campos_decision(decision),
        }

    @staticmethod
    def campos_decision(decision: DecisionTactica) -> dict[str, Any]:
        return {
            "accion_tactica": decision.accion,
            "categoria_fraude": decision.categoria,
            "confianza_calibrada": decision.confianza_calibrada,
            "motor_decision": decision.motor,
        }
