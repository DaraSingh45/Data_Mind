import os
import sys
import tempfile
from pathlib import Path

# Isolated data folder for the whole test session (must be set before app imports).
_tmp = tempfile.mkdtemp(prefix="datamind-test-")
os.environ.setdefault("DATAMIND_DATA_DIR", _tmp)
os.environ.setdefault("DATAMIND_ENV_FILE", os.path.join(_tmp, ".env"))  # never touch the real .env
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.samples.generate import ensure_samples  # noqa: E402

ensure_samples()


@pytest.fixture(scope="session")
def churn():
    from app.core.config import SAMPLES_DIR
    from app.engine.ingest import read_any
    from app.engine.profiler import profile_dataframe

    df, _ = read_any(SAMPLES_DIR / "customer_churn.csv")
    return df, profile_dataframe(df)
