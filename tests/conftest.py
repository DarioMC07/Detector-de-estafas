import pytest

from training.train import DEMO_DATA, train


@pytest.fixture(scope="session")
def trained_artifact(tmp_path_factory):
    output = tmp_path_factory.mktemp("modelo")
    report = train(DEMO_DATA, output)
    return output / "modelo.joblib", report
