import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(trained_artifact):
    with TestClient(create_app(trained_artifact[0])) as test_client:
        yield test_client


def test_analyze(client):
    response = client.post("/analizar", json={"texto": "URGENTE: envía tu contraseña y haz una transferencia ahora mismo."})
    assert response.status_code == 200
    data = response.json()
    assert data["datos_demostrativos"] is True
    assert data["categoria"] == "Fraudulento según el modelo"
    assert data["etiqueta_modelo"] == "fraudulento"
    assert isinstance(data["incertidumbre"], bool)
    assert data["senales"]
    assert data["explicacion"] and data["recomendaciones"]
    assert "puede cometer errores" in data["aviso"]
    assert "puntuacion" not in data
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("payload", [{}, {"texto": ""}, {"texto": " \n\t"}, {"texto": "a" * 5001},
                                         {"texto": None}, {"texto": 42}, {"texto": []},
                                         {"texto": "hola", "otro": "valor"}])
def test_invalid_inputs(client, payload):
    response = client.post("/analizar", json=payload)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


def test_max_length_accepted(client):
    assert client.post("/analizar", json={"texto": "a" * 5000}).status_code == 200


def test_validation_does_not_echo_input(client, caplog):
    private = "DATOS_PERSONALES_NO_REPETIR"
    response = client.post("/analizar", json={"texto": private, "extra": private})
    assert response.status_code == 422
    assert private not in response.text
    assert private not in caplog.text
    malformed = client.post("/analizar", content='{"texto":"' + private,
                            headers={"Content-Type": "application/json"})
    assert malformed.status_code == 422
    assert private not in malformed.text


def test_message_not_echoed_or_logged(client, caplog):
    text = '<script>alert("PRIVADO_123")</script>'
    response = client.post("/analizar", json={"texto": text})
    assert response.status_code == 200
    assert text not in response.text
    assert "PRIVADO_123" not in caplog.text


def test_missing_model(tmp_path):
    with TestClient(create_app(tmp_path / "missing.joblib")) as client:
        assert client.get("/estado").json()["modelo_disponible"] is False
        response = client.post("/analizar", json={"texto": "hola"})
        assert response.status_code == 503
        assert "training.train" in response.json()["detail"]


def test_static_page(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "Mensaje Seguro" in page.text
    assert "Content-Security-Policy" in page.headers
    assert client.get("/static/styles.css").status_code == 200
    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert "innerHTML" not in script.text
    assert client.get("/estado").json()["datos_demostrativos"] is True


def test_rules_do_not_override_category(trained_artifact):
    # Umbrales explícitos para aislar la categoría del modelo respecto de las reglas.
    with TestClient(create_app(trained_artifact[0], low=.998, high=.999)) as client:
        response = client.post("/analizar", json={"texto": "Hola, aquí tienes los horarios https://biblioteca.example.org"})
        assert response.status_code == 200
        assert response.json()["categoria"] == "Legítimo según el modelo"
        assert "enlace" in {s["codigo"] for s in response.json()["senales"]}


@pytest.mark.parametrize("text,label", [
    ("Hola, nos vemos mañana para comer.", "legitimo"),
    ("Tu cita en el centro de salud es el martes a las diez.", "legitimo"),
    ("URGENTE: envía tu contraseña y haz una transferencia ahora mismo.", "fraudulento"),
    ("Has ganado un premio. Paga una tasa para cobrarlo.", "fraudulento"),
])
def test_binary_examples(client, text, label):
    # Pruebas de regresión funcional, no una estimación de eficacia real.
    data = client.post("/analizar", json={"texto": text}).json()
    assert data["etiqueta_modelo"] == label
    assert data["categoria"] != "Sospechoso"
    assert data["nivel"] == ("bajo" if label == "legitimo" else "alto")


def test_uncertainty_is_separate_from_class(trained_artifact):
    with TestClient(create_app(trained_artifact[0], low=.001, high=.999)) as client:
        data = client.post("/analizar", json={"texto": "Nos vemos mañana para comer."}).json()
        assert data["categoria"] == "Legítimo según el modelo"
        assert data["incertidumbre"] is True
        assert "Resultado incierto" in data["aviso_incertidumbre"]


def test_no_uncertainty_notice_outside_band(trained_artifact):
    with TestClient(create_app(trained_artifact[0], low=.998, high=.999)) as client:
        data = client.post("/analizar", json={"texto": "Nos vemos mañana para comer."}).json()
        assert data["incertidumbre"] is False
        assert data["aviso_incertidumbre"] is None
