import base64
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("CLIENT_TOKEN", "test-client-token")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("WAHA_API_KEY", "test-waha-key")
os.environ.setdefault("WAHA_BASE_URL", "http://waha.local")

from backend.prompt.media import audio_processing, image_analysis


def test_transcribe_audio_data_url_uses_openai_upload(monkeypatch):
    captured = {}

    def fake_transcribe(file_path: Path, media_kind: str, *, api_key: str) -> str:
        captured["media_kind"] = media_kind
        captured["bytes"] = file_path.read_bytes()
        captured["suffix"] = file_path.suffix
        captured["api_key"] = api_key
        return "[Áudio recebido/transcrição]\nolá"

    monkeypatch.setattr(audio_processing, "_openai_transcribe_file", fake_transcribe)

    payload = base64.b64encode(b"mp3-bytes").decode("utf-8")
    result = audio_processing.transcribe_audio(
        f"data:audio/mpeg;base64,{payload}",
        api_key="company-openai-key",
    )

    assert result == "[Áudio recebido/transcrição]\nolá"
    assert captured == {
        "media_kind": "audio",
        "bytes": b"mp3-bytes",
        "suffix": ".mp3",
        "api_key": "company-openai-key",
    }


def test_transcribe_video_resolves_local_waha_proxy(monkeypatch, tmp_path):
    monkeypatch.setenv("WAHA_MEDIA_DIR", str(tmp_path / "waha"))

    video_path = tmp_path / "waha" / "company_3" / "video.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"mp4-bytes")
    captured = {}

    def fake_transcribe(file_path: Path, media_kind: str, *, api_key: str) -> str:
        captured["media_kind"] = media_kind
        captured["path"] = file_path
        captured["bytes"] = file_path.read_bytes()
        captured["api_key"] = api_key
        return "[Vídeo recebido/transcrição]\nolá do vídeo"

    monkeypatch.setattr(audio_processing, "_openai_transcribe_file", fake_transcribe)

    result = audio_processing.transcribe_video(
        "/api/waha/media/company_3/video.mp4",
        api_key="company-openai-key",
    )

    assert result == "[Vídeo recebido/transcrição]\nolá do vídeo"
    assert captured["media_kind"] == "video"
    assert captured["path"] == video_path.resolve()
    assert captured["bytes"] == b"mp4-bytes"
    assert captured["api_key"] == "company-openai-key"


def test_transcribe_audio_aliases_local_waha_oga_without_ffmpeg(monkeypatch, tmp_path):
    monkeypatch.setenv("WAHA_MEDIA_DIR", str(tmp_path / "waha"))

    audio_path = tmp_path / "waha" / "company_3" / "audio.oga"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"ogg-opus-bytes")
    captured = {}

    def fake_transcribe(file_path: Path, media_kind: str, *, api_key: str) -> str:
        captured["media_kind"] = media_kind
        captured["suffix"] = file_path.suffix
        captured["bytes"] = file_path.read_bytes()
        captured["api_key"] = api_key
        return "[Áudio recebido/transcrição]\nolá do áudio"

    monkeypatch.setattr(audio_processing, "_openai_transcribe_file", fake_transcribe)

    result = audio_processing.transcribe_audio(
        "/api/waha/media/company_3/audio.oga",
        api_key="company-openai-key",
    )

    assert result == "[Áudio recebido/transcrição]\nolá do áudio"
    assert captured == {
        "media_kind": "audio",
        "suffix": ".ogg",
        "bytes": b"ogg-opus-bytes",
        "api_key": "company-openai-key",
    }


def test_configure_audio_segment_uses_configured_ffmpeg(monkeypatch, tmp_path):
    ffmpeg_path = tmp_path / "ffmpeg"
    ffprobe_path = tmp_path / "ffprobe"
    ffmpeg_path.write_text("#!/bin/sh\n", encoding="utf-8")
    ffprobe_path.write_text("#!/bin/sh\n", encoding="utf-8")
    ffmpeg_path.chmod(0o755)
    ffprobe_path.chmod(0o755)
    monkeypatch.setenv("FFMPEG_BINARY", str(ffmpeg_path))
    monkeypatch.setenv("FFPROBE_BINARY", str(ffprobe_path))

    class FakeAudioSegment:
        converter = ""
        ffmpeg = ""
        ffprobe = ""

    audio_processing._configure_audio_segment_binaries(FakeAudioSegment)

    assert FakeAudioSegment.converter == str(ffmpeg_path)
    assert FakeAudioSegment.ffmpeg == str(ffmpeg_path)
    assert FakeAudioSegment.ffprobe == str(ffprobe_path)
    assert str(tmp_path) in os.environ["PATH"].split(os.pathsep)


def test_analyze_image_with_openai_sends_local_waha_media_as_data_url(monkeypatch, tmp_path):
    monkeypatch.setenv("WAHA_MEDIA_DIR", str(tmp_path / "waha"))

    image_path = tmp_path / "waha" / "company_3" / "foto.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"png-bytes")
    captured = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_text="A imagem mostra um comprovante.")

    class FakeOpenAI:
        def __init__(self, *, api_key):
            assert api_key == "company-openai-key"
            self.responses = FakeResponses()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    result = image_analysis.analyze_image_with_openai(
        "/api/waha/media/company_3/foto.png",
        api_key="company-openai-key",
        conversation_context="Cliente perguntou sobre pagamento.",
        caption="comprovante",
    )

    assert result == "[Imagem recebida]\nA imagem mostra um comprovante."
    assert captured["model"] == "gpt-4o-mini"
    content = captured["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/png;base64,")
    encoded = content[1]["image_url"].split(",", 1)[1]
    assert base64.b64decode(encoded) == b"png-bytes"
