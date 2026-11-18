import math
import re
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
from sklearn.pipeline import Pipeline


def clean_chat_elongation(text: str) -> str:
    """Colapsa repeticiones informales de letras comunes en chats (ej: holaaaaa -> hola, siiii -> si)."""
    cleaned = re.sub(r'([a-zA-ZáéíóúÁÉÍÓÚñÑ])\1{2,}', r'\1', text)
    cleaned = re.sub(r'\b(hol)a+\b', r'\1a', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b(chau)u+\b', r'\1', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b(dale)e+\b', r'\1', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b(si)i+\b', r'\1', cleaned, flags=re.IGNORECASE)
    return cleaned


class ModelUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Prediction:
    etiqueta: str
    incertidumbre: bool


class Predictor:
    def __init__(self, path: Path, low: float = 0.35, high: float = 0.70):
        if not (math.isfinite(low) and math.isfinite(high) and 0 < low < high < 1):
            raise ValueError("Los umbrales deben cumplir 0 < UMBRAL_BAJO < UMBRAL_ALTO < 1.")
        self.low, self.high = low, high
        self.pipeline = None
        self.metadata = {}
        # Solo cargar artefactos propios: joblib puede ejecutar código al deserializar.
        try:
            artifact = joblib.load(path)
            pipeline = artifact["pipeline"]
            metadata = artifact["metadata"]
            if not isinstance(pipeline, Pipeline) or not hasattr(pipeline, "predict_proba"):
                raise ValueError("Pipeline incompatible")
            if set(pipeline.classes_) != {"legitimo", "fraudulento"}:
                raise ValueError("Clases incompatibles")
            if metadata.get("formato") != 1 or type(metadata.get("datos_demostrativos")) is not bool:
                raise ValueError("Metadatos incompatibles")
            sample = pipeline.predict_proba(["comprobación local de carga"])
            if sample.shape != (1, 2) or not np.isfinite(sample).all():
                raise ValueError("Salida incompatible")
            self.pipeline, self.metadata = pipeline, metadata
        except Exception:
            # Sin trazas con datos de usuario ni errores internos en respuestas públicas.
            self.pipeline = None

    @property
    def available(self) -> bool:
        return self.pipeline is not None

    def classify(self, text: str):
        if not self.available:
            raise ModelUnavailable("Modelo no disponible. Ejecuta python -m training.train y reinicia la API.")
        try:
            cleaned = clean_chat_elongation(text)
            index = list(self.pipeline.classes_).index("fraudulento")
            probabilities = self.pipeline.predict_proba([cleaned])[0]
            score = float(probabilities[index])
            if not np.isfinite(probabilities).all() or not 0 <= score <= 1:
                raise ValueError("Puntuación inválida")
            # Ambos modelos comparados eligen la clase de mayor puntuación.
            label = str(self.pipeline.classes_[int(np.argmax(probabilities))])
        except Exception:
            raise ModelUnavailable("No se pudo usar el modelo. Vuelve a entrenarlo y reinicia la API.") from None
        # La incertidumbre es un aviso independiente; nunca una tercera clase.
        return Prediction(label, self.low <= score < self.high)
