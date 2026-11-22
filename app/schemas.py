from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_TEXT_LENGTH = 5000
DISCLAIMER = "Esta evaluación es orientativa y puede cometer errores"


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    texto: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH, strict=True)

    @field_validator("texto")
    @classmethod
    def reject_whitespace(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Escribe un mensaje que no esté vacío.")
        return value.strip()


class Signal(BaseModel):
    codigo: str
    titulo: str
    descripcion: str


class AnalyzeResponse(BaseModel):
    categoria: Literal["Legítimo según el modelo", "Fraudulento según el modelo"]
    etiqueta_modelo: Literal["legitimo", "fraudulento"]
    nivel: Literal["bajo", "alto"]
    incertidumbre: bool
    aviso_incertidumbre: str | None
    senales: list[Signal]
    explicacion: str
    recomendaciones: list[str]
    datos_demostrativos: bool
    # Decisión táctica de Nivel 2 (campos añadidos; no alteran los anteriores)
    accion_tactica: Literal["PERMITIR", "ADVERTIR", "BLOQUEAR_ENLACES"] = "PERMITIR"
    categoria_fraude: Literal["CONVERSACION_GENUINA", "PHISHING_BANCARIO",
                              "SUPLANTACION_IDENTIDAD", "PREMIO_FALSO", "OTRO_FRAUDE"] = "CONVERSACION_GENUINA"
    confianza_calibrada: float | None = None
    motor_decision: str = "fast_path"
    aviso: str = DISCLAIMER
