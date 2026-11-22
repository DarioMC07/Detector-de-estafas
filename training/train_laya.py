"""Entrena Laya (Nivel 2): árbitro de decisión con probabilidades calibradas.

Se llama desde ``training.train`` con el mismo split entrenamiento/prueba que el Nivel 1.

Diseño (stacking honesto):
1. Puntuación del Nivel 1 FUERA DE MUESTRA para cada mensaje de entrenamiento
   (cross_val_predict). Si se usara la puntuación del modelo ya ajustado, Laya
   aprendería a confiar ciegamente en un Nivel 1 sobreajustado.
2. Vector estructurado por mensaje (``app.text_features.caracteristicas_laya``):
   puntuación del Nivel 1 + señales léxicas + análisis de enlaces + estilo.
3. Cabeza de riesgo: clasificador calibrado (CalibratedClassifierCV, sigmoide) que
   devuelve P(fraude). Se elige entre regresión logística y gradient boosting por
   puntuación de Brier en validación cruzada.
4. Cabeza de categoría: clasificador de texto entrenado solo con fraudes
   (PHISHING_BANCARIO, SUPLANTACION_IDENTIDAD, PREMIO_FALSO, OTRO_FRAUDE).
5. Evaluación final de la cascada completa en el conjunto de prueba reservado.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import joblib
import numpy as np
from sklearn.base import clone
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier, VotingClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, brier_score_loss, confusion_matrix, f1_score,
                             log_loss, precision_score, recall_score)
from sklearn.model_selection import StratifiedKFold, cross_val_predict, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.signals import detect_signals
from app.text_features import CARACTERISTICAS, caracteristicas_laya, preprocesar_para_modelo

SEED = 42
FORMATO_LAYA = 1
# Política de decisión sobre la probabilidad calibrada (ver app/decision_engine.py).
UMBRAL_ADVERTENCIA = 0.40
UMBRAL_FRAUDE = 0.65
CATEGORIAS_FRAUDE = ("PHISHING_BANCARIO", "SUPLANTACION_IDENTIDAD", "PREMIO_FALSO", "OTRO_FRAUDE")


def inferir_categoria(texto: str, etiqueta: str) -> str:
    """Categoría por reglas cuando el CSV no la trae."""
    from app.decision_engine import categoria_heuristica

    if etiqueta == "legitimo":
        return "CONVERSACION_GENUINA"
    return categoria_heuristica(texto, {s.codigo for s in detect_signals(texto)})


def _matriz(textos, puntuaciones) -> np.ndarray:
    return np.array([
        caracteristicas_laya(t, s, frozenset(sig.codigo for sig in detect_signals(t)))
        for t, s in zip(textos, puntuaciones)
    ])


def _ece(y_true: np.ndarray, prob: np.ndarray, bins: int = 5) -> float:
    """Error de calibración esperado (diferencia media entre confianza y acierto)."""
    bordes = np.linspace(0, 1, bins + 1)
    total, error = len(prob), 0.0
    for lo, hi in zip(bordes[:-1], bordes[1:]):
        mask = (prob >= lo) & (prob < hi if hi < 1 else prob <= hi)
        if mask.any():
            error += mask.sum() / total * abs(prob[mask].mean() - y_true[mask].mean())
    return float(error)


def _metricas_binarias(y_true: np.ndarray, pred: np.ndarray) -> dict:
    tn, fp, fn, tp = confusion_matrix(y_true, pred, labels=[0, 1]).ravel()
    return {
        "exactitud": float(accuracy_score(y_true, pred)),
        "precision": float(precision_score(y_true, pred, zero_division=0)),
        "recall": float(recall_score(y_true, pred, zero_division=0)),
        "f1": float(f1_score(y_true, pred, zero_division=0)),
        "falsos_positivos": int(fp), "falsos_negativos": int(fn),
        "tasa_falsos_positivos": float(fp / (fp + tn)) if (fp + tn) else 0.0,
    }


def train_laya(x_train, y_train, c_train, x_test, y_test, c_test, *, l1_template, l1_final,
               folds: int, output_dir: Path) -> dict:
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=SEED)
    y_tr = np.array([1 if y == "fraudulento" else 0 for y in y_train])
    y_te = np.array([1 if y == "fraudulento" else 0 for y in y_test])

    # 1) Puntuaciones del Nivel 1 fuera de muestra (stacking sin fuga de información).
    clases = sorted(set(y_train))
    idx = clases.index("fraudulento")
    oof = cross_val_predict(clone(l1_template), x_train, y_train, cv=cv, method="predict_proba")[:, idx]
    X_tr = _matriz(x_train, oof)

    # 2) Cabeza de riesgo calibrada: comparar candidatos por Brier en validación cruzada.
    candidatos = {
        "regresion_logistica": Pipeline([
            ("escala", StandardScaler()),
            ("clf", LogisticRegression(C=0.5, max_iter=2000, random_state=SEED)),
        ]),
        "gradient_boosting": HistGradientBoostingClassifier(
            max_depth=3, learning_rate=0.08, max_iter=150, min_samples_leaf=4,
            l2_regularization=1.0, random_state=SEED),
    }
    # ensemble=False: un solo modelo ajustado con todos los datos + calibrador obtenido con
    # predicciones de validación cruzada. Igual de calibrado y ~5 veces más rápido en
    # inferencia que guardar una copia por partición (clave para el presupuesto de 50 ms).
    calibrados = {n: CalibratedClassifierCV(b, method="sigmoid", cv=folds, ensemble=False)
                  for n, b in candidatos.items()}
    # Ensamble: promedio de las probabilidades calibradas de ambos (más estable con pocos datos).
    calibrados["ensamble"] = VotingClassifier(
        [(n, clone(m)) for n, m in calibrados.items()], voting="soft")
    comparacion = {}
    for nombre, modelo in calibrados.items():
        scores = cross_val_score(modelo, X_tr, y_tr, cv=cv, scoring="neg_brier_score")
        comparacion[nombre] = {"brier_medio": float(-scores.mean()), "desviacion": float(scores.std())}
    mejor = min(comparacion, key=lambda n: comparacion[n]["brier_medio"])
    # Con datasets pequeños las diferencias de Brier son ruido: se prefiere el ensamble
    # salvo que otro candidato sea al menos un 15 % mejor.
    elegido = "ensamble" if comparacion["ensamble"]["brier_medio"] <= 1.15 * comparacion[mejor]["brier_medio"] else mejor
    riesgo = clone(calibrados[elegido]).fit(X_tr, y_tr)

    # 3) Cabeza de categoría (solo fraudes).
    cats_tr = [c or inferir_categoria(t, y) for t, y, c in zip(x_train, y_train, c_train)]
    fraude_txt = [t for t, y in zip(x_train, y_train) if y == "fraudulento"]
    fraude_cat = [c for c, y in zip(cats_tr, y_train) if y == "fraudulento"]
    categoria = None
    if len(set(fraude_cat)) >= 2:
        categoria = Pipeline([
            ("tfidf", TfidfVectorizer(preprocessor=preprocesar_para_modelo, ngram_range=(1, 2),
                                      token_pattern=r"(?u)\b\w+\b", sublinear_tf=True)),
            ("clf", LogisticRegression(C=5.0, max_iter=2000, class_weight="balanced", random_state=SEED)),
        ]).fit(fraude_txt, fraude_cat)

    # 4) Evaluación de la cascada en prueba con el Nivel 1 final.
    p_l1 = l1_final.predict_proba(x_test)[:, list(l1_final.classes_).index("fraudulento")]
    X_te = _matriz(x_test, p_l1)
    p = riesgo.predict_proba(X_te)[:, 1]
    evaluacion = {
        "brier": float(brier_score_loss(y_te, p)),
        "log_loss": float(log_loss(y_te, np.clip(p, 1e-6, 1 - 1e-6), labels=[0, 1])),
        "ece": _ece(y_te, p),
        "laya": _metricas_binarias(y_te, (p >= UMBRAL_FRAUDE).astype(int)),
        "nivel1_solo": _metricas_binarias(y_te, (p_l1 >= 0.5).astype(int)),
        "zona_advertencia": int(((p >= UMBRAL_ADVERTENCIA) & (p < UMBRAL_FRAUDE)).sum()),
    }
    if categoria is not None:
        cats_te = [c or inferir_categoria(t, y) for t, y, c in zip(x_test, y_test, c_test)]
        pares = [(t, c) for t, y, c in zip(x_test, y_test, cats_te) if y == "fraudulento"]
        if pares:
            pred = categoria.predict([t for t, _ in pares])
            evaluacion["categoria_exactitud"] = float(accuracy_score([c for _, c in pares], pred))

    artefacto = {
        "formato": FORMATO_LAYA,
        "tipo": "laya-local",
        "caracteristicas": list(CARACTERISTICAS),
        "riesgo": riesgo,
        "categoria": categoria,
        "umbrales": {"advertencia": UMBRAL_ADVERTENCIA, "fraude": UMBRAL_FRAUDE},
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(artefacto, output_dir / "laya.joblib")
    return {
        "modelo_riesgo": elegido,
        "calibracion": "sigmoide (CalibratedClassifierCV, ensemble=False)",
        "comparacion_validacion": comparacion,
        "caracteristicas": len(CARACTERISTICAS),
        "categorias_entrenamiento": dict(Counter(fraude_cat)),
        "umbrales": artefacto["umbrales"],
        "evaluacion_prueba": evaluacion,
    }
