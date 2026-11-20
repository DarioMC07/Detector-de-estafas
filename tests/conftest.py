import pytest

from training.train import DEMO_DATA, train


@pytest.fixture(autouse=True)
def isolated_device_registry(tmp_path, monkeypatch):
    """Las pruebas no leen ni escriben el registro real de dispositivos del chat."""
    monkeypatch.setenv("CHAT_DEVICES_PATH", str(tmp_path / "dispositivos_chat.json"))


@pytest.fixture(scope="session")
def trained_artifact(tmp_path_factory):
    output = tmp_path_factory.mktemp("modelo")
    report = train(DEMO_DATA, output)
    return output / "modelo.joblib", report
