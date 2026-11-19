import contextlib
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.clock import FakeClock, reset_clock, set_clock
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.base import Base
from app.db.constants import SYSTEM_PERMISSIONS, SYSTEM_ROLES, get_permission_id, get_system_role_id
from app.db.session import get_db
from app.main import app
from app.models.permission import Permission
from app.models.role import Role, RolePermission

# Test database engine
TEST_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


# Enable foreign keys for SQLite
@event.listens_for(test_engine, "connect")
def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=test_engine,
)


@pytest.fixture(scope="session", autouse=True)
def setup_test_schema() -> Generator[None, None, None]:
    """Creates schema, immutability triggers, and seeds system data once for session."""
    Base.metadata.create_all(bind=test_engine)

    # Install SQLite immutability trigger for audit_logs
    with test_engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS trg_audit_logs_no_update
            BEFORE UPDATE ON audit_logs
            BEGIN
                SELECT RAISE(ABORT, 'audit_logs entries are immutable');
            END;
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS trg_audit_logs_no_delete
            BEFORE DELETE ON audit_logs
            BEGIN
                SELECT RAISE(ABORT, 'audit_logs entries are immutable');
            END;
            """
        )

    # Seed system permissions and roles in ordered steps
    with TestingSessionLocal() as session:
        # Step 1: Permissions
        for code, desc in SYSTEM_PERMISSIONS.items():
            session.add(
                Permission(
                    id=get_permission_id(code),
                    code=code,
                    description=desc,
                )
            )
        session.commit()

        # Step 2: Roles
        for role_name, role_info in SYSTEM_ROLES.items():
            session.add(
                Role(
                    id=get_system_role_id(role_name),
                    organization_id=None,
                    name=role_name,
                    description=str(role_info["description"]),
                    is_system=True,
                )
            )
        session.commit()

        # Step 3: Role-Permissions mapping
        for role_name, role_info in SYSTEM_ROLES.items():
            perms = role_info["permissions"]
            if isinstance(perms, list):
                for code in perms:
                    session.add(
                        RolePermission(
                            role_id=get_system_role_id(role_name),
                            permission_id=get_permission_id(str(code)),
                        )
                    )
        session.commit()

    yield

    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provides a transactional database session rolled back after each test."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(
        bind=connection,
        join_transaction_mode="create_savepoint",
    )

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture(autouse=True)
def setup_test_environment() -> Generator[None, None, None]:
    import app.services.audit_service

    app.services.audit_service.get_audit_session = lambda: TestingSessionLocal()
    settings.ENVIRONMENT = "test"
    reset_clock()
    with contextlib.suppress(Exception):
        limiter.reset()
    yield
    reset_clock()


@pytest.fixture
def fake_clock() -> FakeClock:
    clock = FakeClock()
    set_clock(clock)
    return clock


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
