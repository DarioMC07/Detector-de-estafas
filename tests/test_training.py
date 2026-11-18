import csv

import joblib
import pytest
from sklearn.model_selection import train_test_split

from training.train import DEMO_DATA, SEED, load_dataset


def write_csv(path, rows, headers=("texto", "etiqueta")):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def test_demo_data():
    texts, labels, report = load_dataset(DEMO_DATA)
    assert len(texts) == len(labels) >= 80
    assert report["clases"]["legitimo"] >= 40 and report["clases"]["fraudulento"] >= 40


@pytest.mark.parametrize("headers,rows,expected", [
    (("mensaje", "clase"), [], "columnas"),
    (("texto", "etiqueta"), [("hola", "seguro")], "Etiqueta inválida"),
    (("texto", "etiqueta"), [("hola", "legitimo"), (" HOLA  ", "fraudulento")], "contradictorias"),
    (("texto", "etiqueta"), [("hola", "legitimo")], "ambas clases"),
    (("texto", "etiqueta"), [("hola", "legitimo"), ("paga", "fraudulento")], "insuficientes"),
])
def test_invalid_data(tmp_path, headers, rows, expected):
    path = write_csv(tmp_path / "invalid.csv", rows, headers)
    with pytest.raises(ValueError, match=expected):
        load_dataset(path)


def test_empty_and_duplicate_rows_removed(tmp_path):
    rows = [(f"mensaje normal {i}", "legitimo") for i in range(5)]
    rows += [(f"mensaje engañoso {i}", "fraudulento") for i in range(5)]
    rows += [("", "legitimo"), ("  ", ""), ("MENSAJE   NORMAL 0", "legitimo")]
    texts, _, report = load_dataset(write_csv(tmp_path / "data.csv", rows))
    assert len(texts) == 10
    assert report["vacios_eliminados"] == 2
    assert report["duplicados_eliminados"] == 1


def test_report_and_holdout_isolation(trained_artifact):
    artifact_path, report = trained_artifact
    assert report["datos_demostrativos"] is True
    assert report["entrenamiento"] + report["prueba"] == report["limpieza"]["registros_utilizados"]
    assert report["prueba"] > 0
    assert set(report["validacion"]) == {"regresion_logistica", "naive_bayes"}
    for name, tuning in report["ajuste_hiperparametros"].items():
        assert len(tuning["configuraciones"]) == 3
        best_f1 = max(item["f1_medio"] for item in tuning["configuraciones"])
        assert report["validacion"][name]["f1"]["media"] == best_f1
    evaluation = report["evaluacion_prueba"]
    assert sum(map(sum, evaluation["matriz_confusion"])) == report["prueba"]
    assert evaluation["orden_clases"] == ["legitimo", "fraudulento"]
    for metric in ("exactitud", "precision", "recall", "f1"):
        assert 0 <= evaluation[metric] <= 1
    assert (artifact_path.parent / "metricas.json").exists()
    pipeline = joblib.load(artifact_path)["pipeline"]
    texts, labels, _ = load_dataset(DEMO_DATA)
    train_texts, test_texts, _, _ = train_test_split(texts, labels, test_size=.25, stratify=labels, random_state=SEED)
    analyzer = pipeline.named_steps["tfidf"].build_analyzer()
    train_tokens = {token for text in train_texts for token in analyzer(text)}
    test_only = {token for text in test_texts for token in analyzer(text)} - train_tokens
    assert test_only  # Hay vocabulario exclusivo de prueba para comprobar la separación.
    assert test_only.isdisjoint(pipeline.named_steps["tfidf"].vocabulary_)
    assert not set(train_texts).intersection(test_texts)
