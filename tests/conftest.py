import os
import shutil
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
import app.database as app_db
from app.database import Base, get_db
from app.main import app


@pytest.fixture(scope="session")
def test_temp_dir():
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def setup_test_db(test_temp_dir):
    # Set up dedicated sqlite file in temp dir
    test_db_path = test_temp_dir / "test_parttrackr.db"
    test_db_url = f"sqlite:///{test_db_path}"

    settings.STORAGE_DIR = test_temp_dir / "storage"
    settings.init_storage()

    # Create new engine & SessionLocal for app.database
    engine = create_engine(test_db_url, connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Patch app.database
    app_db.engine = engine
    app_db.SessionLocal = TestingSession
    Base.metadata.create_all(bind=engine)

    yield

    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    if test_db_path.exists():
        try:
            test_db_path.unlink()
        except Exception:
            pass


@pytest.fixture
def client():
    def override_get_db():
        db = app_db.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
