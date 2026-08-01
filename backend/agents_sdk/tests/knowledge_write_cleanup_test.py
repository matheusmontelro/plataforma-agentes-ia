import asyncio
import io
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/agentive_test")

from backend.routes import agent_workforces as routes


class _FakeDB:
    def __init__(self, *, fail_commit=False):
        self.fail_commit = fail_commit
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1
        if self.fail_commit:
            raise RuntimeError("database commit failed")

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, _value):
        return None


class _FakeFiles:
    def __init__(self):
        self.deleted = []

    def create(self, **_kwargs):
        return SimpleNamespace(id="file-new")

    def delete(self, file_id):
        self.deleted.append(file_id)


class _FakeVectorFiles:
    def __init__(self, status):
        self.status = status
        self.deleted = []

    def create_and_poll(self, **_kwargs):
        return SimpleNamespace(id="file-new", status=self.status)

    def delete(self, file_id, *, vector_store_id):
        self.deleted.append((file_id, vector_store_id))


class _FakeVectorStores:
    def __init__(self, status):
        self.files = _FakeVectorFiles(status)
        self.deleted = []

    def create(self, **_kwargs):
        return SimpleNamespace(id="vs-new")

    def retrieve(self, vector_store_id):
        return SimpleNamespace(
            id=vector_store_id,
            metadata={
                "company_id": "7",
                "workforce_id": "25",
            },
        )

    def delete(self, vector_store_id):
        self.deleted.append(vector_store_id)


class _FakeOpenAI:
    def __init__(self, status):
        self.files = _FakeFiles()
        self.vector_stores = _FakeVectorStores(status)


def _workforce(*, vector_store_id=None):
    file_search = {"files": [], "links": []}
    if vector_store_id:
        file_search["vector_store_id"] = vector_store_id
    return SimpleNamespace(
        id=25,
        company_id=7,
        name="Atendimento",
        version=1,
        settings={
            "agent_context": {
                "knowledge": {
                    "file_search": file_search,
                }
            }
        },
    )


def _upload():
    return UploadFile(
        filename="base.txt",
        file=io.BytesIO(b"conteudo da base"),
        headers=Headers({"content-type": "text/plain"}),
    )


def _patch_route(monkeypatch, *, workforce, client):
    monkeypatch.setattr(
        routes,
        "_get_workforce_or_404",
        lambda _db, _company_id, _workforce_id: workforce,
    )
    monkeypatch.setattr(
        routes,
        "_ensure_openai_client",
        lambda _db, _company_id: client,
    )
    monkeypatch.setattr(
        routes,
        "_mark_company_knowledge_scope",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(routes, "flag_modified", lambda *_args: None)


def test_failed_indexing_removes_new_vector_store_and_file(monkeypatch):
    db = _FakeDB()
    workforce = _workforce()
    client = _FakeOpenAI(status="failed")
    _patch_route(monkeypatch, workforce=workforce, client=client)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            routes.upload_workforce_knowledge_file(
                25,
                _upload(),
                db=db,
                current_user=SimpleNamespace(company_id=7),
            )
        )

    assert exc_info.value.status_code == 502
    assert db.rollbacks == 1
    assert client.vector_stores.deleted == ["vs-new"]
    assert client.files.deleted == ["file-new"]


def test_commit_failure_detaches_file_from_existing_store(monkeypatch):
    db = _FakeDB(fail_commit=True)
    workforce = _workforce(vector_store_id="vs-existing")
    client = _FakeOpenAI(status="completed")
    _patch_route(monkeypatch, workforce=workforce, client=client)

    with pytest.raises(RuntimeError, match="database commit failed"):
        asyncio.run(
            routes.upload_workforce_knowledge_file(
                25,
                _upload(),
                db=db,
                current_user=SimpleNamespace(company_id=7),
            )
        )

    assert db.rollbacks == 1
    assert client.vector_stores.deleted == []
    assert client.vector_stores.files.deleted == [
        ("file-new", "vs-existing")
    ]
    assert client.files.deleted == ["file-new"]


def test_delete_workforce_removes_remote_knowledge_before_local_row(
    monkeypatch,
):
    workforce = _workforce(vector_store_id="vs-existing")
    file_search = workforce.settings["agent_context"]["knowledge"][
        "file_search"
    ]
    file_search["files"] = [
        {
            "file_id": "file-company",
            "vector_store_file_id": "file-company",
        }
    ]
    client = _FakeOpenAI(status="completed")

    class _Query:
        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            return workforce

    class _DeleteDB(_FakeDB):
        def __init__(self):
            super().__init__()
            self.deleted = []

        def query(self, _model):
            return _Query()

        def delete(self, value):
            self.deleted.append(value)

    db = _DeleteDB()
    monkeypatch.setattr(
        routes,
        "_ensure_openai_client",
        lambda _db, _company_id: client,
    )

    result = routes.delete_agent_workforce(
        25,
        db=db,
        current_user=SimpleNamespace(company_id=7),
    )

    assert result is None
    assert client.vector_stores.files.deleted == [
        ("file-company", "vs-existing")
    ]
    assert client.files.deleted == ["file-company"]
    assert client.vector_stores.deleted == ["vs-existing"]
    assert db.deleted == [workforce]
    assert db.commits == 1
