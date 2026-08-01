import threading

from fastapi import HTTPException

from backend import auth
from backend.models import (
    Client,
    Company,
    CustomerManagedCompany,
    RefundAccessSuspension,
    User,
    UserSession,
)


class _FakeQuery:
    def __init__(self, *, first=None, scalar=None):
        self._first = first
        self._scalar = scalar

    def filter(self, *_args, **_kwargs):
        return self

    def filter_by(self, **_kwargs):
        return self

    def first(self):
        return self._first

    def scalar(self):
        return self._scalar


class _RaceDB:
    def __init__(
        self,
        *,
        user,
        master,
        entity_lock,
        client_namespace_probe=True,
    ):
        self.user = user
        self.master = master
        self.entity_lock = entity_lock
        self.client_namespace_probe = client_namespace_probe
        self.entity_lock_held = False
        self.client_queries = 0
        self.pending_sessions = []
        self.sessions = []
        self.close_calls = 0
        self.info = {}

    def query(self, model):
        if model is Client:
            self.client_queries += 1
            # Login probes the master namespace first with the staff email.
            return _FakeQuery(
                first=(
                    None
                    if self.client_namespace_probe
                    and self.client_queries == 1
                    else self.master
                )
            )
        if model is User:
            return _FakeQuery(first=self.user)
        if model is RefundAccessSuspension.id:
            return _FakeQuery(first=None)
        if model is Client.email:
            return _FakeQuery(scalar=self.master.email)
        if model is Company.operational_status:
            return _FakeQuery(scalar="active")
        if model is CustomerManagedCompany:
            return _FakeQuery(first=None)
        raise AssertionError(f"Consulta inesperada: {model}")

    def expire_all(self):
        return None

    def add(self, value):
        assert isinstance(value, UserSession)
        self.pending_sessions.append(value)

    def commit(self):
        self.sessions.extend(self.pending_sessions)
        self.pending_sessions.clear()
        self._release_entity_lock()

    def rollback(self):
        self.pending_sessions.clear()
        self._release_entity_lock()

    def close(self):
        self.close_calls += 1

    def _release_entity_lock(self):
        if self.entity_lock_held:
            self.entity_lock_held = False
            self.entity_lock.release()


def _account_pair():
    master = Client(
        id=7,
        email="owner@example.com",
        password="hash",
        company_id=3,
        ownership_company_id=3,
        is_active=True,
        auth_token_version=0,
    )
    user = User(
        id=11,
        client_id=7,
        company_id=3,
        email="staff@example.com",
        password="hash",
        name="Staff",
        is_active=True,
        auth_token_version=0,
    )
    return master, user


def _install_entity_fence(monkeypatch, entity_lock, lock_waiting):
    def acquire_entity_fence(db, **_kwargs):
        lock_waiting.set()
        entity_lock.acquire()
        db.entity_lock_held = True

    monkeypatch.setattr(
        auth,
        "try_lock_refund_entities_for_access",
        acquire_entity_fence,
    )
    monkeypatch.setattr(auth, "verify_password", lambda *_args: True)


def test_refund_winning_entity_fence_prevents_login_session_and_token(monkeypatch):
    master, user = _account_pair()
    entity_lock = threading.Lock()
    entity_lock.acquire()
    lock_waiting = threading.Event()
    db = _RaceDB(user=user, master=master, entity_lock=entity_lock)
    _install_entity_fence(monkeypatch, entity_lock, lock_waiting)
    monkeypatch.setattr(
        auth,
        "create_tokens_for_user",
        lambda account: {
            "access_token": f"token-v{account.auth_token_version}",
            "refresh_token": "refresh",
            "token_type": "bearer",
        },
    )
    outcome = {}

    def login():
        try:
            outcome["result"] = auth.authenticate_login_and_issue_tokens(
                db,
                email=user.email,
                password="secret",
            )
        except Exception as exc:  # pragma: no branch - asserted below
            outcome["error"] = exc

    login_thread = threading.Thread(target=login)
    login_thread.start()
    assert lock_waiting.wait(timeout=1)

    # Refund owns the entity fence, sweeps the account, then releases it.
    master.is_active = False
    master.auth_token_version = 1
    user.is_active = False
    user.auth_token_version = 1
    db.sessions.clear()
    entity_lock.release()

    login_thread.join(timeout=1)
    assert not login_thread.is_alive()
    assert isinstance(outcome.get("error"), HTTPException)
    assert "result" not in outcome
    assert db.sessions == []


def test_refund_after_login_fence_sweeps_session_and_revokes_issued_token(
    monkeypatch,
):
    master, user = _account_pair()
    entity_lock = threading.Lock()
    lock_waiting = threading.Event()
    token_created = threading.Event()
    allow_login_commit = threading.Event()
    refund_waiting = threading.Event()
    db = _RaceDB(user=user, master=master, entity_lock=entity_lock)
    _install_entity_fence(monkeypatch, entity_lock, lock_waiting)

    def create_tokens(account):
        token_created.set()
        assert allow_login_commit.wait(timeout=1)
        return {
            "access_token": f"token-v{account.auth_token_version}",
            "refresh_token": "refresh",
            "token_type": "bearer",
        }

    monkeypatch.setattr(auth, "create_tokens_for_user", create_tokens)
    outcome = {}

    def login():
        try:
            outcome["result"] = auth.authenticate_login_and_issue_tokens(
                db,
                email=user.email,
                password="secret",
            )
        except Exception as exc:  # pragma: no cover - diagnostic path
            outcome["error"] = exc

    def refund():
        refund_waiting.set()
        with entity_lock:
            master.is_active = False
            master.auth_token_version = 1
            user.is_active = False
            user.auth_token_version = 1
            db.sessions.clear()

    login_thread = threading.Thread(target=login)
    login_thread.start()
    assert token_created.wait(timeout=1)

    refund_thread = threading.Thread(target=refund)
    refund_thread.start()
    assert refund_waiting.wait(timeout=1)
    allow_login_commit.set()

    login_thread.join(timeout=1)
    refund_thread.join(timeout=1)
    assert not login_thread.is_alive()
    assert not refund_thread.is_alive()
    assert "error" not in outcome
    assert outcome["result"].tokens["access_token"] == "token-v0"
    assert user.auth_token_version == 1
    assert db.sessions == []


def test_refund_winning_entity_fence_rejects_concurrent_refresh(monkeypatch):
    master, user = _account_pair()
    entity_lock = threading.Lock()
    entity_lock.acquire()
    lock_waiting = threading.Event()
    db = _RaceDB(
        user=user,
        master=master,
        entity_lock=entity_lock,
        client_namespace_probe=False,
    )
    _install_entity_fence(monkeypatch, entity_lock, lock_waiting)
    monkeypatch.setattr(
        auth,
        "decode_token",
        lambda _token, verify_access=False: {
            "sub": user.email,
            "user_id": str(user.id),
            "user_type": "user",
            "tv": 0,
        },
    )
    monkeypatch.setattr(
        auth,
        "create_tokens_for_user",
        lambda _account: (_ for _ in ()).throw(
            AssertionError("Refresh não deve emitir token após o sweep")
        ),
    )
    outcome = {}

    def refresh():
        try:
            outcome["result"] = auth._refresh_access_token_with_db(
                "refresh-token",
                db,
            )
        except Exception as exc:  # pragma: no branch - asserted below
            outcome["error"] = exc

    refresh_thread = threading.Thread(target=refresh)
    refresh_thread.start()
    assert lock_waiting.wait(timeout=1)

    master.is_active = False
    master.auth_token_version = 1
    user.is_active = False
    user.auth_token_version = 1
    entity_lock.release()

    refresh_thread.join(timeout=1)
    assert not refresh_thread.is_alive()
    assert isinstance(outcome.get("error"), HTTPException)
    assert "result" not in outcome
    assert db.sessions == []


def test_login_entity_lock_busy_emits_neither_token_nor_session(monkeypatch):
    master, user = _account_pair()
    db = _RaceDB(
        user=user,
        master=master,
        entity_lock=threading.Lock(),
    )
    monkeypatch.setattr(auth, "verify_password", lambda *_args: True)
    monkeypatch.setattr(auth, "is_account_refund_blocked", lambda *_args: False)
    monkeypatch.setattr(
        auth,
        "try_lock_refund_entities_for_access",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            auth.CompanyOperationalLockBusyError(3)
        ),
    )
    monkeypatch.setattr(
        auth,
        "create_tokens_for_user",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("contenção não pode emitir token")
        ),
    )

    try:
        auth.authenticate_login_and_issue_tokens(
            db,
            email=user.email,
            password="correct-password",
        )
    except auth.CompanyOperationalLockBusyError as exc:
        assert exc.company_id == 3
    else:  # pragma: no cover - assertion guard
        raise AssertionError("contenção deveria falhar imediatamente")

    assert db.pending_sessions == []
    assert db.sessions == []


def test_refresh_busy_owns_and_closes_its_session_without_issuing_token(
    monkeypatch,
):
    master, user = _account_pair()
    db = _RaceDB(
        user=user,
        master=master,
        entity_lock=threading.Lock(),
        client_namespace_probe=False,
    )
    monkeypatch.setattr(auth, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        auth,
        "decode_token",
        lambda _token, verify_access=False: {
            "sub": user.email,
            "user_id": str(user.id),
            "user_type": "user",
            "tv": 0,
        },
    )
    monkeypatch.setattr(
        auth,
        "try_lock_refund_entities_for_access",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            auth.CompanyOperationalLockBusyError(3)
        ),
    )
    monkeypatch.setattr(
        auth,
        "create_tokens_for_user",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("contenção não pode emitir token")
        ),
    )

    try:
        auth.refresh_access_token("refresh-token")
    except auth.CompanyOperationalLockBusyError as exc:
        assert exc.company_id == 3
    else:  # pragma: no cover - assertion guard
        raise AssertionError("contenção deveria falhar imediatamente")

    assert db.sessions == []
    assert db.close_calls == 1
