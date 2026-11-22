"""Motor de decisión táctica en cascada.

Nivel 1 (sensor, ``app.predictor`` + ``app.signals``): clasificador TF-IDF y reglas
léxicas. Rápido (<2 ms) y siempre disponible si hay modelo entrenado.

Nivel 2 (árbitro): decide la acción táctica (PERMITIR / ADVERTIR / BLOQUEAR_ENLACES)
y la categoría de fraude. Usa un runtime local de decisión (Laya) si está instalado;
si no lo está, falla, devuelve algo inválido o tarda más del presupuesto (50 ms por
defecto), se usa el árbitro heurístico local. Esta capa nunca lanza excepciones
hacia el chat.

Garantías de compatibilidad:
- Los campos existentes (etiqueta_modelo, nivel, incertidumbre, senales,
  recomendaciones...) se calculan exactamente igual que antes. El Nivel 2 solo
  AÑADE campos nuevos; no reescribe la decisión del Nivel 1.
- El Nivel 2 no puede rebajar el riesgo por debajo de un "piso" derivado del
  Nivel 1 (si el clasificador dice fraudulento, la acción mínima es ADVERTIR).

Privacidad: no se registra el texto ni los números de teléfono.
"""

from __future__ import annotations

import importlib
import importlib.util
import math
import os
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from app.predictor import ModelUnavailable, Prediction, Predictor, clean_chat_elongation
from app.schemas import Signal
from app.signals import detect_signals, normalize, recommendations

ACCIONES = ("PERMITIR", "ADVERTIR", "BLOQUEAR_ENLACES")
CATEGORIAS = ("CONVERSACION_GENUINA", "PHISHING_BANCARIO", "SUPLANTACION_IDENTIDAD", "PREMIO_FALSO")
_SEVERIDAD = {accion: i for i, accion in enumerate(ACCIONES)}

# Fast-path: por debajo de esta puntuación y sin señales, no se invoca el Nivel 2.
FAST_PATH_MAX_SCORE = 0.20

# Contexto bancario (Bolivia y genérico). Texto ya normalizado (minúsculas, sin tildes).
_BANCARIO_RE = re.compile(
    r"\b(bancos?|bancari\w*|banca (?:movil|por internet)|homebanking|cuenta bancaria|tu cuenta|"
    r"tarjeta(?:s)? de (?:credito|debito)|bnb|bcp|bisa|mercantil|banco union|banco sol|"
    r"fassil|ganadero|economico|tigo money|billetera movil)\b"
)
# Patrones típicos de suplantación ("cambié de número", "soy tu hijo"...).
_SUPLANTACION_RE = re.compile(
    r"\b(cambie (?:de|mi) (?:numero|celular|cel)|(?:es|este es) mi nuevo (?:numero|celular|cel)|"
    r"nuevo numero|guarda (?:este|mi) numero|soy tu (?:hij[oa]|mama|papa|herman[oa]|prim[oa]|ti[oa]|jefe)|"
    r"adivina quien soy|no me reconoces|te escribo de (?:otro|este) numero)\b"
)


@dataclass(frozen=True)
class DecisionTactica:
    accion: str
    categoria: str
    # Solo tiene valor cuando lo produce un modelo calibrado (Laya). La heurística
    # no está calibrada, así que deja None en vez de inventar una probabilidad.
    confianza_calibrada: float | None
    motor: str  # "fast_path" | "laya" | "heuristico" | "heuristico_sin_modelo"


@dataclass(frozen=True)
class Evaluacion:
    prediccion: Prediction
    senales: list[Signal]
    decision: DecisionTactica


class TacticalBackend(Protocol):
    """Contrato mínimo de un árbitro de Nivel 2."""

    def decidir(self, caracteristicas: dict[str, Any]) -> dict[str, Any]:
        """Devuelve {"accion": ..., "categoria": ..., "confianza": float en [0, 1]}."""


class BackendUnavailable(RuntimeError):
    pass


class LayaBackend:
    """Adaptador al runtime local de Laya.

    Interfaz supuesta (ajústala a la API real del paquete que instales):
    el módulo expone ``load_decision_model(path)`` (o ``load(path)``) y el objeto
    devuelto tiene ``decide(features: dict) -> dict``.
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


def laya_backend_from_env() -> TacticalBackend | None:
    """Crea el backend Laya según variables de entorno, o None si no procede."""
    if os.getenv("LAYA_ENABLED", "1").strip().lower() in ("0", "false", "no", "off"):
        return None
    module_name = os.getenv("LAYA_MODULE", "laya").strip() or "laya"
    try:
        if importlib.util.find_spec(module_name) is None:
            return None
    except (ImportError, ValueError):
        return None
    return LayaBackend(module_name, os.getenv("LAYA_MODEL_PATH") or None)


def _max_accion(a: str, b: str) -> str:
    return a if _SEVERIDAD[a] >= _SEVERIDAD[b] else b


class DecisionEngine:
    """Orquesta la cascada Nivel 1 → (fast-path | Nivel 2 | fallback heurístico)."""

    def __init__(
        self,
        predictor: Predictor,
        backend_factory: Callable[[], TacticalBackend | None] | None = laya_backend_from_env,
        timeout: float | None = None,
        max_fallos: int = 3,
        enfriamiento: float = 60.0,
    ) -> None:
        self.predictor = predictor
        self._factory = backend_factory
        if timeout is None:
            try:
                timeout = float(os.getenv("LAYA_TIMEOUT_MS", "50")) / 1000
            except ValueError:
                timeout = 0.05
        self.timeout = timeout if math.isfinite(timeout) and timeout > 0 else 0.05
        self.max_fallos = max_fallos
        self.enfriamiento = enfriamiento

        self._lock = threading.Lock()
        # Un solo hilo: si una inferencia se cuelga, las siguientes van directas al
        # fallback en vez de acumular una cola (ver _invocar_backend).
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nivel2")
        self._backend: TacticalBackend | None = None
        self._estado = "pendiente"  # pendiente | cargando | listo | no_disponible
        self._carga: Future | None = None
        self._en_curso: Future | None = None
        self._fallos = 0
        self._pausado_hasta = 0.0

    # ------------------------------------------------------------------ backend

    @property
    def estado_backend(self) -> str:
        if self._estado == "listo" and time.monotonic() < self._pausado_hasta:
            return "en_pausa"
        return self._estado

    def iniciar(self) -> None:
        """Lanza la carga diferida del backend en segundo plano (no bloquea)."""
        with self._lock:
            if self._estado != "pendiente" or self._factory is None:
                if self._factory is None:
                    self._estado = "no_disponible"
                return
            self._estado = "cargando"
            self._carga = self._executor.submit(self._cargar)

    def cargar_backend(self, timeout: float | None = None) -> str:
        """Carga el backend y espera el resultado (útil en pruebas y scripts)."""
        self.iniciar()
        carga = self._carga
        if carga is not None:
            try:
                carga.result(timeout=timeout)
            except Exception:
                pass
        return self.estado_backend

    def _cargar(self) -> None:
        try:
            backend = self._factory() if self._factory else None
        except Exception:
            backend = None
        with self._lock:
            self._backend = backend
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

    def _invocar_backend(self, backend: TacticalBackend, caracteristicas: dict[str, Any]) -> DecisionTactica | None:
        with self._lock:
            if self._en_curso is not None and not self._en_curso.done():
                return None  # ocupado con una inferencia lenta: no encolar
            futuro = self._executor.submit(backend.decidir, dict(caracteristicas))
            self._en_curso = futuro
        try:
            bruto = futuro.result(timeout=self.timeout)
            decision = self._validar_salida(bruto)
        except (FutureTimeout, Exception):
            self._registrar_fallo()
            return None
        with self._lock:
            self._fallos = 0
        return decision

    @staticmethod
    def _validar_salida(bruto: Any) -> DecisionTactica:
        if not isinstance(bruto, dict):
            raise ValueError("Salida no es un dict")
        accion = bruto.get("accion", bruto.get("accion_tactica"))
        categoria = bruto.get("categoria", bruto.get("categoria_fraude"))
        confianza = bruto.get("confianza", bruto.get("confianza_calibrada"))
        if accion not in ACCIONES or categoria not in CATEGORIAS:
            raise ValueError("Acción o categoría desconocida")
        if isinstance(confianza, bool) or not isinstance(confianza, (int, float)):
            raise ValueError("Confianza inválida")
        confianza = float(confianza)
        if not math.isfinite(confianza) or not 0.0 <= confianza <= 1.0:
            raise ValueError("Confianza fuera de rango")
        return DecisionTactica(accion, categoria, round(confianza, 4), "laya")

    def cerrar(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # -------------------------------------------------------------- heurística

    @staticmethod
    def _contexto(texto: str) -> tuple[bool, bool]:
        norm = normalize(clean_chat_elongation(texto))
        return bool(_BANCARIO_RE.search(norm)), bool(_SUPLANTACION_RE.search(norm))

    @classmethod
    def decision_heuristica(cls, texto: str, prediccion: Prediction | None, senales: list[Signal]) -> DecisionTactica:
        """Árbitro local de respaldo. Reglas transparentes, sin confianza calibrada."""
        codigos = {s.codigo for s in senales}
        bancario, suplantacion = cls._contexto(texto)
        fraudulento = prediccion is not None and prediccion.etiqueta == "fraudulento"
        incierto = prediccion is None or prediccion.incertidumbre

        if "premio" in codigos:
            categoria = "PREMIO_FALSO"
        elif bancario and codigos & {"credenciales", "enlace", "urgencia", "dinero"}:
            categoria = "PHISHING_BANCARIO"
        elif suplantacion:
            categoria = "SUPLANTACION_IDENTIDAD"
        elif fraudulento and codigos & {"credenciales", "enlace"}:
            categoria = "PHISHING_BANCARIO"
        elif fraudulento and "dinero" in codigos:
            categoria = "SUPLANTACION_IDENTIDAD"
        else:
            categoria = "CONVERSACION_GENUINA"

        sospechoso = fraudulento or categoria != "CONVERSACION_GENUINA"
        if "enlace" in codigos and sospechoso:
            accion = "BLOQUEAR_ENLACES"
        elif sospechoso or incierto or codigos & {"credenciales", "dinero", "urgencia"}:
            accion = "ADVERTIR"
        else:
            accion = "PERMITIR"
        motor = "heuristico" if prediccion is not None else "heuristico_sin_modelo"
        return DecisionTactica(accion, categoria, None, motor)

    @staticmethod
    def _armonizar(decision: DecisionTactica, respaldo: DecisionTactica,
                   prediccion: Prediction, senales: list[Signal]) -> DecisionTactica:
        """Evita conflictos entre niveles: el Nivel 2 no rebaja el piso del Nivel 1."""
        piso = "ADVERTIR" if prediccion.etiqueta == "fraudulento" else "PERMITIR"
        accion = _max_accion(decision.accion, piso)
        if accion == "BLOQUEAR_ENLACES" and "enlace" not in {s.codigo for s in senales}:
            accion = "ADVERTIR"  # no hay enlaces que bloquear
        categoria = decision.categoria
        if accion != "PERMITIR" and categoria == "CONVERSACION_GENUINA":
            categoria = respaldo.categoria
        return DecisionTactica(accion, categoria, decision.confianza_calibrada, decision.motor)

    # ------------------------------------------------------------------ cascada

    @staticmethod
    def es_fast_path(prediccion: Prediction, senales: list[Signal]) -> bool:
        return (not senales and prediccion.puntuacion is not None
                and prediccion.puntuacion < FAST_PATH_MAX_SCORE)

    def evaluar(self, texto: str, remitente: str | None = None, destinatario: str | None = None) -> Evaluacion:
        """Evaluación completa. Lanza ModelUnavailable si el Nivel 1 no está disponible."""
        prediccion = self.predictor.classify(texto)
        senales = detect_signals(texto)

        if self.es_fast_path(prediccion, senales):
            decision = DecisionTactica("PERMITIR", "CONVERSACION_GENUINA", None, "fast_path")
            return Evaluacion(prediccion, senales, decision)

        respaldo = self.decision_heuristica(texto, prediccion, senales)
        decision = respaldo
        try:
            backend = self._backend_disponible()
            if backend is not None:
                bancario, suplantacion = self._contexto(texto)
                caracteristicas = {
                    "texto": clean_chat_elongation(texto),
                    "probabilidad_lexica": prediccion.puntuacion,
                    "etiqueta_nivel1": prediccion.etiqueta,
                    "incertidumbre_nivel1": prediccion.incertidumbre,
                    "senales": sorted(s.codigo for s in senales),
                    "contexto_bancario": bancario,
                    "patron_suplantacion": suplantacion,
                    "remitente": remitente,
                    "destinatario": destinatario,
                }
                laya = self._invocar_backend(backend, caracteristicas)
                if laya is not None:
                    decision = self._armonizar(laya, respaldo, prediccion, senales)
        except Exception:
            decision = respaldo
        return Evaluacion(prediccion, senales, decision)

    def evaluar_mensaje(self, texto: str, remitente: str | None = None, destinatario: str | None = None) -> dict[str, Any]:
        """Payload de seguridad para el chat. Nunca lanza excepciones."""
        try:
            evaluacion = self.evaluar(texto, remitente, destinatario)
        except ModelUnavailable:
            return self._payload_sin_modelo(texto)
        except Exception:
            return self._payload_sin_modelo(texto)

        prediccion, senales, decision = evaluacion.prediccion, evaluacion.senales, evaluacion.decision
        # Misma lógica de nivel que la versión anterior del chat (compatibilidad).
        if prediccion.etiqueta == "fraudulento":
            nivel = "alto" if senales else ("medio" if prediccion.incertidumbre else "alto")
        else:
            nivel = "medio" if prediccion.incertidumbre else "bajo"
        incierto = prediccion.incertidumbre and not senales
        return {
            "etiqueta_modelo": prediccion.etiqueta,
            "nivel": nivel,
            "incertidumbre": incierto,
            "aviso_incertidumbre": "Resultado incierto: la puntuación está en la zona intermedia." if incierto else None,
            "senales": [{"codigo": s.codigo, "titulo": s.titulo, "descripcion": s.descripcion} for s in senales],
            "recomendaciones": recommendations(nivel, senales),
            "datos_demostrativos": self.predictor.metadata.get("datos_demostrativos", False),
            **self.campos_decision(decision),
        }

    def _payload_sin_modelo(self, texto: str) -> dict[str, Any]:
        try:
            senales = detect_signals(texto)
            decision = self.decision_heuristica(texto, None, senales)
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
