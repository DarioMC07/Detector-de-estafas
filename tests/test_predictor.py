import joblib
import numpy as np
import pytest

from app.predictor import ModelUnavailable, Predictor
from app.signals import detect_signals


def test_load_and_predict(trained_artifact):
    path, _ = trained_artifact
    predictor = Predictor(path)
    assert predictor.available
    prediction = predictor.classify("Nos vemos mañana para comer.")
    assert prediction.etiqueta == "legitimo"
    assert isinstance(prediction.incertidumbre, bool)


@pytest.mark.parametrize("kind", ["missing", "corrupt", "incompatible"])
def test_unavailable_artifacts(tmp_path, kind):
    path = tmp_path / "bad.joblib"
    if kind == "corrupt":
        path.write_bytes(b"not a model")
    elif kind == "incompatible":
        joblib.dump({"pipeline": None, "metadata": {}}, path)
    predictor = Predictor(path)
    assert not predictor.available
    with pytest.raises(ModelUnavailable):
        predictor.classify("hola")


@pytest.mark.parametrize("low,high", [(0, .7), (.7, .3), (.3, 1), (float("nan"), .7)])
def test_invalid_thresholds(tmp_path, low, high):
    with pytest.raises(ValueError, match="umbrales"):
        Predictor(tmp_path / "absent.joblib", low, high)


@pytest.mark.parametrize("score,label,uncertain", [(.349, "legitimo", False), (.35, "legitimo", True),
                                                 (.699, "fraudulento", True), (.7, "fraudulento", False)])
def test_threshold_boundaries_and_class_order(tmp_path, score, label, uncertain):
    class StubPipeline:
        # Orden invertido para verificar que no se presupone una columna concreta.
        classes_ = ["fraudulento", "legitimo"]

        def predict_proba(self, texts):
            return np.array([[score, 1 - score]])

    predictor = Predictor(tmp_path / "missing.joblib")
    predictor.pipeline = StubPipeline()
    result = predictor.classify("texto")
    assert result.etiqueta == label
    assert result.incertidumbre is uncertain


def test_uncertainty_does_not_replace_binary_class(tmp_path):
    class StubPipeline:
        classes_ = ["legitimo", "fraudulento"]

        def predict_proba(self, texts):
            return np.array([[.55, .45]])

    predictor = Predictor(tmp_path / "missing.joblib")
    predictor.pipeline = StubPipeline()
    result = predictor.classify("texto")
    assert result.etiqueta == "legitimo"
    assert result.incertidumbre is True


def test_complementary_signals():
    signals = detect_signals("¡URGENTE! Has ganado un premio. Haz una transferencia ahora mismo, envía tu contraseña en https://ejemplo.example.com")
    assert {s.codigo for s in signals} == {"urgencia", "premio", "dinero", "credenciales", "enlace"}
    link = detect_signals("Consulta https://biblioteca.example.org")
    assert [s.codigo for s in link] == ["enlace"]
    assert "por sí solo no demuestra fraude" in link[0].descripcion


def test_negation_not_claimed_as_credential_request():
    signals = detect_signals("Nunca compartas tu contraseña")
    assert signals[0].titulo == "Mención de claves o códigos de acceso"
    assert "o hablando de ellos" in signals[0].descripcion
