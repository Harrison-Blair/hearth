"""Unit tests for the Piper voice catalog + downloader in tui.discovery.

httpx is routed through a MockTransport so nothing hits the network; the voice
dir is redirected to a tmp path so nothing touches models/piper/.
"""

import httpx

from tui import discovery


def _patch_transport(monkeypatch, handler):
    orig = httpx.AsyncClient

    def factory(**kwargs):
        return orig(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def _no_cache(monkeypatch):
    monkeypatch.setattr(discovery, "_cache_get", lambda key: None)
    monkeypatch.setattr(discovery, "_cache_put", lambda key, data: None)


CATALOG = {
    "en_US-amy-low": {
        "language": {"code": "en_US"}, "quality": "low", "num_speakers": 1,
        "files": {
            "en/en_US/amy/low/en_US-amy-low.onnx": {"size_bytes": 100},
            "en/en_US/amy/low/en_US-amy-low.onnx.json": {"size_bytes": 10},
        },
    },
    "de_DE-thorsten-low": {  # non-English: must be filtered out
        "language": {"code": "de_DE"}, "quality": "low", "num_speakers": 1,
        "files": {
            "de/de_DE/thorsten/low/de_DE-thorsten-low.onnx": {"size_bytes": 100},
            "de/de_DE/thorsten/low/de_DE-thorsten-low.onnx.json": {"size_bytes": 10},
        },
    },
}


async def test_catalog_filters_english_and_marks_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(discovery, "PIPER_VOICE_DIR", str(tmp_path))
    (tmp_path / "en_US-amy-low.onnx").write_bytes(b"already here")
    _no_cache(monkeypatch)

    # HuggingFace's resolve/ URL 307-redirects to a CDN; the client must follow it.
    def handler(request):
        if request.url.host == "huggingface.co":
            return httpx.Response(307, headers={"location": "https://cdn.example/voices.json"})
        return httpx.Response(200, json=CATALOG)

    _patch_transport(monkeypatch, handler)

    voices = await discovery.piper_voice_catalog()

    assert [v.key for v in voices] == ["en_US-amy-low"]  # German dropped
    assert voices[0].installed  # matched the on-disk .onnx
    assert voices[0].size_bytes == 110  # onnx + json


async def test_catalog_empty_on_http_error(monkeypatch):
    _no_cache(monkeypatch)

    def handler(request):
        raise httpx.ConnectError("boom")

    _patch_transport(monkeypatch, handler)
    assert await discovery.piper_voice_catalog() == []


async def test_download_writes_both_files_and_reports_progress(monkeypatch, tmp_path):
    monkeypatch.setattr(discovery, "PIPER_VOICE_DIR", str(tmp_path))

    def handler(request):
        if request.url.path.endswith(".onnx"):
            return httpx.Response(200, content=b"ONNXDATA")
        return httpx.Response(200, content=b"{}")

    _patch_transport(monkeypatch, handler)
    voice = discovery.RegistryVoice(
        key="en_US-amy-low", quality="low", num_speakers=1, size_bytes=10,
        onnx_path="en/en_US/amy/low/en_US-amy-low.onnx",
        config_path="en/en_US/amy/low/en_US-amy-low.onnx.json",
    )

    progress = [p async for p in discovery.download_voice(voice)]

    assert (tmp_path / "en_US-amy-low.onnx").read_bytes() == b"ONNXDATA"
    assert (tmp_path / "en_US-amy-low.onnx.json").read_bytes() == b"{}"
    assert progress[-1].status.startswith("installed")
    assert progress[-1].completed == progress[-1].total
    # a partial .part temp is renamed away, never left behind
    assert not list(tmp_path.glob("*.part"))
