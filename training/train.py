"""Ejecutar desde la raíz: python -m training.train."""

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import joblib
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, confusion_matrix, f1_score, make_scorer,
    precision_score, recall_score,
)
from sklearn.model_selection import GridSearchCV, StratifiedKFold, train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline

from app.text_features import preprocesar_para_modelo

ROOT = Path(__file__).resolve().parents[1]
DEMO_DATA = ROOT / "data" / "mensajes_demo.csv"
LABELS = ["legitimo", "fraudulento"]
SEED = 42


# Palabras funcionales neutras en español que no deben sesgar la detección
SPANISH_STOPWORDS = [
    "de", "la", "que", "el", "en", "y", "a", "los", "del", "se", "las", "por", "un", "para",
    "con", "no", "una", "su", "al", "lo", "como", "mas", "pero", "sus", "le", "ya", "o",
    "este", "ha", "si", "porque", "esta", "son", "entre", "cuando", "muy", "sin",
    "sobre", "ser", "tiene", "tambien", "me", "hasta", "hay", "donde", "quien", "desde",
    "todo", "nos", "durante", "todos", "uno", "les", "ni", "contra", "otros", "ese", "eso",
    "ante", "ellos", "e", "esto", "mi", "antes", "algunos", "unos", "yo", "otro",
    "otras", "otra", "tanto", "esa", "estos", "mucho", "quienes", "nada", "muchos",
    "cual", "sea", "poco", "ella", "estar", "haber", "estas", "estaba", "estamos", "algunas",
    "algo", "nosotros", "mis", "tu", "te", "ti", "tus", "ellas", "nosotras", "vosotros", "vosotras"
]


CATEGORIES = ("CONVERSACION_GENUINA", "PHISHING_BANCARIO", "SUPLANTACION_IDENTIDAD", "PREMIO_FALSO", "OTRO_FRAUDE")


def load_dataset(path: Path):
    """Conservar el texto; normalizar espacios y mayúsculas para detectar duplicados."""
    texts, labels, _, report = load_dataset_with_categories(path)
    return texts, labels, report


def load_dataset_with_categories(path: Path):
    """Como load_dataset, pero también devuelve la columna opcional ``categoria``.

    Si falta la columna o una celda, la categoría queda en None (el entrenamiento de
    Laya la infiere con reglas)."""
    texts, labels, categories, seen = [], [], [], {}
    removed_empty = removed_duplicates = 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"texto", "etiqueta"}.issubset(reader.fieldnames or []):
            raise ValueError("El CSV debe incluir las columnas texto y etiqueta.")
        for line, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"CSV mal formado en la fila {line}: revisa las comillas y separadores.")
            text = (row.get("texto") or "").strip()
            label = (row.get("etiqueta") or "").strip()
            if label and label not in LABELS:
                raise ValueError(f"Etiqueta inválida en la fila {line}: {label!r}.")
            if not text or not label:
                removed_empty += 1
                continue
            key = " ".join(text.split()).casefold()
            if key in seen:
                if seen[key] != label:
                    raise ValueError(f"Texto con etiquetas contradictorias en la fila {line}.")
                removed_duplicates += 1
                continue
            seen[key] = label
            texts.append(text)
            labels.append(label)
            category = (row.get("categoria") or "").strip().upper() or None
            if category is not None and category not in CATEGORIES:
                raise ValueError(f"Categoría inválida en la fila {line}: {category!r}.")
            if category is not None and (category == "CONVERSACION_GENUINA") != (label == "legitimo"):
                raise ValueError(f"Categoría incoherente con la etiqueta en la fila {line}.")
            categories.append(category)
    counts = Counter(labels)
    if set(counts) != set(LABELS):
        raise ValueError("Se necesitan ejemplos de ambas clases: legitimo y fraudulento.")
    if min(counts.values()) < 5:
        raise ValueError("Datos insuficientes: se requieren al menos 5 textos distintos por clase para separar y validar.")
    return texts, labels, categories, {
        "registros_utilizados": len(texts), "vacios_eliminados": removed_empty,
        "duplicados_eliminados": removed_duplicates, "clases": dict(counts),
    }


def train(data_path: Path, output_dir: Path, demo: bool = False, train_level2: bool = True):
    texts, labels, categories, cleaning = load_dataset_with_categories(data_path)
    x_train, x_test, y_train, y_test, c_train, c_test = train_test_split(
        texts, labels, categories, test_size=0.25, stratify=labels, random_state=SEED,
    )
    folds = min(5, min(Counter(y_train).values()))
    if folds < 2 or set(y_test) != set(LABELS):
        raise ValueError("Datos insuficientes para validación estratificada y prueba con ambas clases.")
    scoring = {
        "exactitud": "accuracy",
        "precision": make_scorer(precision_score, pos_label="fraudulento", zero_division=0),
        "recall": make_scorer(recall_score, pos_label="fraudulento", zero_division=0),
        "f1": make_scorer(f1_score, pos_label="fraudulento", zero_division=0),
    }
    candidates = {
        "regresion_logistica": LogisticRegression(max_iter=1000, random_state=SEED),
        "naive_bayes": MultinomialNB(),
    }
    grids = {
        "regresion_logistica": {"classifier__C": [1.0, 0.1, 10.0]},
        "naive_bayes": {"classifier__alpha": [1.0, 0.5, 0.1]},
    }
    tuning = {}
    pipelines, comparison = {}, {}
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=SEED)
    for name, classifier in candidates.items():
        # El preprocesador (guardado dentro del pipeline) sustituye enlaces por tokens de
        # riesgo, quita tildes y colapsa alargamientos; el patrón conserva palabras y signos.
        pipeline = Pipeline([
            ("tfidf", TfidfVectorizer(
                preprocessor=preprocesar_para_modelo, ngram_range=(1, 2),
                token_pattern=r"(?u)\b\w+\b|[^\w\s]", sublinear_tf=True,
            )),
            ("classifier", classifier),
        ])
        search = GridSearchCV(pipeline, grids[name], cv=cv, scoring=scoring,
                              refit="f1", error_score="raise")
        search.fit(x_train, y_train)
        scores = search.cv_results_
        best = search.best_index_
        comparison[name] = {
            metric: {"media": float(scores[f"mean_test_{metric}"][best]),
                     "desviacion": float(scores[f"std_test_{metric}"][best])}
            for metric in scoring
        }
        tuning[name] = {
            "parametros_seleccionados": search.best_params_,
            "configuraciones": [
                {"parametros": params, "f1_medio": float(scores["mean_test_f1"][i])}
                for i, params in enumerate(scores["params"])
            ],
        }
        pipelines[name] = search.best_estimator_
    selected = max(comparison, key=lambda name: comparison[name]["f1"]["media"])
    model = pipelines[selected]
    prediction = model.predict(x_test)
    evaluation = {
        "exactitud": float(accuracy_score(y_test, prediction)),
        "precision": float(precision_score(y_test, prediction, pos_label="fraudulento", zero_division=0)),
        "recall": float(recall_score(y_test, prediction, pos_label="fraudulento", zero_division=0)),
        "f1": float(f1_score(y_test, prediction, pos_label="fraudulento", zero_division=0)),
        "matriz_confusion": confusion_matrix(y_test, prediction, labels=LABELS).tolist(),
        "orden_clases": LABELS,
        "filas": "etiqueta real", "columnas": "predicción",
    }
    # Detectar también una copia idéntica del CSV demostrativo en otra ruta.
    fingerprint = hashlib.sha256(data_path.read_bytes()).hexdigest()
    is_demo = demo or (DEMO_DATA.exists() and fingerprint == hashlib.sha256(DEMO_DATA.read_bytes()).hexdigest())
    metadata = {
        "formato": 1, "modelo": selected, "datos_demostrativos": is_demo,
        "fecha_utc": datetime.now(timezone.utc).isoformat(),
        "sklearn_version": sklearn.__version__, "dataset_sha256": fingerprint,
        "semilla": SEED, "limpieza": cleaning,
        "entrenamiento": len(x_train), "prueba": len(x_test),
        "clases_entrenamiento": dict(Counter(y_train)), "clases_prueba": dict(Counter(y_test)),
        "particiones_validacion": folds, "criterio_seleccion": "F1 de fraudulento en validación",
        "clase_positiva": "fraudulento", "validacion": comparison, "evaluacion_prueba": evaluation,
        "ajuste_hiperparametros": tuning,
        "advertencia": "Los datos ficticios no permiten validar la eficacia real del sistema." if is_demo else
        "Las métricas dependen de la representatividad del dataset; no garantizan eficacia en otros mensajes.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    if train_level2:
        # Nivel 2 (Laya): mismo split; usa puntuaciones del Nivel 1 fuera de muestra.
        from training.train_laya import train_laya
        metadata["nivel2"] = train_laya(
            x_train, y_train, c_train, x_test, y_test, c_test,
            l1_template=model, l1_final=model, folds=folds, output_dir=output_dir,
        )
    joblib.dump({"pipeline": model, "metadata": metadata}, output_dir / "modelo.joblib")
    (output_dir / "metricas.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEMO_DATA)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts")
    parser.add_argument("--demo", action="store_true", help="Identificar otros datos ficticios como demostrativos")
    args = parser.parse_args()
    try:
        report = train(args.data, args.output, args.demo)
    except (ValueError, OSError, csv.Error) as exc:
        parser.exit(1, f"No se pudo entrenar: {exc}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("Modelo guardado. Inicia o reinicia la API para cargarlo.")


if __name__ == "__main__":
    main()
