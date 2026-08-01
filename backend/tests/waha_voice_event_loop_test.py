import asyncio
import os
import time
from types import SimpleNamespace


os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")

from backend.integrations import waha_utils
from backend.routes import waha_routes


class _AudioUpload:
    filename = "voice.ogg"
    content_type = "audio/ogg"

    async def read(self):
        return b"OggS" + (b"x" * 128)


class _FakeResult:
    def fetchone(self):
        return SimpleNamespace(id=3)


class _FakeDB:
    def execute(self, *_args, **_kwargs):
        return _FakeResult()


def test_direct_voice_send_does_not_block_event_loop(monkeypatch):
    def slow_send(**kwargs):
        assert kwargs["company_id"] == 3
        time.sleep(0.15)
        return {"id": "voice-message"}

    monkeypatch.setattr(waha_utils, "send_audio_to_waha", slow_send)

    async def scenario():
        send_task = asyncio.create_task(
            waha_routes.send_voice_direct(
                phone="5500000000007",
                audio=_AudioUpload(),
                convert=True,
                session="default",
                db=_FakeDB(),
                current_user=SimpleNamespace(company_id=3),
            )
        )
        heartbeat_ticks = 0
        while not send_task.done():
            await asyncio.sleep(0.01)
            heartbeat_ticks += 1
        return await send_task, heartbeat_ticks

    response, heartbeat_ticks = asyncio.run(scenario())

    assert heartbeat_ticks >= 5
    assert response["status"] == "success"
    assert response["waha_response"] == {"id": "voice-message"}
