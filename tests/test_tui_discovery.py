import httpx

from tui import discovery


def _patch_transport(monkeypatch, handler):
    """Route discovery's AsyncClient through a MockTransport handler."""
    orig = httpx.AsyncClient

    def factory(**kwargs):
        return orig(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


_TAGS = {
    "models": [
        {
            "name": "qwen2.5:3b-instruct",
            "size": 1929379200,
            "modified_at": "2026-01-01T00:00:00Z",
            "details": {"parameter_size": "3.2B", "quantization_level": "Q4_K_M", "family": "qwen2"},
        },
        {"name": "llama3.2"},  # sparse entry: no size/details
    ]
}


async def test_ollama_models_lists_names(monkeypatch):
    def handler(request):
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "qwen2.5:3b"}, {"name": "llama3.2"}]})

    _patch_transport(monkeypatch, handler)
    assert await discovery.ollama_models("http://localhost:11434") == ["qwen2.5:3b", "llama3.2"]


async def test_ollama_models_empty_when_down(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("connection refused")

    _patch_transport(monkeypatch, handler)
    assert await discovery.ollama_models() == []


async def test_ollama_models_info_parses_size_and_params(monkeypatch):
    def handler(request):
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json=_TAGS)

    _patch_transport(monkeypatch, handler)
    models = await discovery.ollama_models_info()
    assert [m.name for m in models] == ["qwen2.5:3b-instruct", "llama3.2"]
    qwen = models[0]
    assert qwen.size == 1929379200
    assert qwen.parameter_size == "3.2B"
    assert qwen.quantization == "Q4_K_M"
    assert qwen.family == "qwen2"
    assert qwen.human_size == "1.8 GB"
    # Sparse entry falls back to empty/zero, not a crash.
    assert models[1].parameter_size == "" and models[1].human_size == "?"


async def test_ollama_models_info_empty_when_down(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("connection refused")

    _patch_transport(monkeypatch, handler)
    assert await discovery.ollama_models_info() == []


async def test_ollama_model_options_labels_and_values(monkeypatch):
    def handler(request):
        return httpx.Response(200, json=_TAGS)

    _patch_transport(monkeypatch, handler)
    options = await discovery.ollama_model_options()
    label, value = options[0]
    assert value == "qwen2.5:3b-instruct"  # value stays the bare name (becomes the env override)
    assert "1.8 GB" in label and "3.2B" in label and "Q4_K_M" in label
    assert options[1] == ("llama3.2", "llama3.2")  # no metadata -> bare name label


async def test_ollama_model_detail_parses_show(monkeypatch):
    def handler(request):
        assert request.url.path == "/api/show"
        assert request.method == "POST"
        return httpx.Response(
            200,
            json={
                "details": {"quantization_level": "Q4_K_M", "family": "qwen2"},
                "model_info": {
                    "general.parameter_count": 3085938688,
                    "qwen2.context_length": 32768,
                },
                "capabilities": ["completion", "tools"],
            },
        )

    _patch_transport(monkeypatch, handler)
    detail = await discovery.ollama_model_detail("http://localhost:11434", "qwen2.5:3b-instruct")
    assert detail.parameter_count == 3085938688
    assert detail.context_length == 32768  # found via the ".context_length" suffix scan
    assert detail.quantization == "Q4_K_M"
    assert detail.capabilities == ["completion", "tools"]


async def test_ollama_model_detail_none_when_missing(monkeypatch):
    def handler(request):
        return httpx.Response(404, json={"error": "model not found"})

    _patch_transport(monkeypatch, handler)
    assert await discovery.ollama_model_detail("http://localhost:11434", "nope") is None


async def test_ollama_health_true_when_version_ok(monkeypatch):
    def handler(request):
        assert request.url.path == "/api/version"
        return httpx.Response(200, json={"version": "0.1.0"})

    _patch_transport(monkeypatch, handler)
    assert await discovery.ollama_health("http://localhost:11434") is True


async def test_ollama_health_false_when_down(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("connection refused")

    _patch_transport(monkeypatch, handler)
    assert await discovery.ollama_health() is False


def test_wake_models_globs_onnx(tmp_path):
    (tmp_path / "b.onnx").touch()
    (tmp_path / "a.onnx").touch()
    (tmp_path / "notes.txt").touch()
    found = discovery.wake_models(str(tmp_path))
    assert [p.rsplit("/", 1)[-1] for p in found] == ["a.onnx", "b.onnx"]  # sorted, .onnx only


def test_wake_model_choices_pairs_phrase_and_path(tmp_path):
    (tmp_path / "penguin.onnx").touch()
    (tmp_path / "hey_there.onnx").touch()
    choices = discovery.wake_model_choices(str(tmp_path))
    # (phrase, path) pairs, sorted by path; phrase derived from the filename stem.
    assert choices == [
        ("hey there", str(tmp_path / "hey_there.onnx")),
        ("penguin", str(tmp_path / "penguin.onnx")),
    ]


def test_clean_smoke_models_deletes_files_and_prunes_manifest(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    (tmp_path / "penguin.onnx").touch()
    (tmp_path / "penguin_smoke.onnx").touch()
    manifest = tmp_path / "models.json"
    manifest.write_text(
        json.dumps(
            {
                "penguin": {"phrase": "penguin", "model_path": "models/wake/penguin.onnx"},
                "penguin_smoke": {
                    "phrase": "penguin smoke",
                    "model_path": "models/wake/penguin_smoke.onnx",
                },
            }
        )
    )
    monkeypatch.setattr(discovery.registry, "MANIFEST", Path(manifest))

    removed = discovery.clean_smoke_models(str(tmp_path))

    assert removed == [str(tmp_path / "penguin_smoke.onnx")]
    assert (tmp_path / "penguin.onnx").exists()
    assert not (tmp_path / "penguin_smoke.onnx").exists()
    assert json.loads(manifest.read_text()) == {
        "penguin": {"phrase": "penguin", "model_path": "models/wake/penguin.onnx"}
    }


def test_clean_smoke_models_noop_when_none(tmp_path, monkeypatch):
    from pathlib import Path

    (tmp_path / "penguin.onnx").touch()
    monkeypatch.setattr(discovery.registry, "MANIFEST", Path(tmp_path / "models.json"))
    assert discovery.clean_smoke_models(str(tmp_path)) == []
    assert (tmp_path / "penguin.onnx").exists()


def test_log_levels_static():
    assert discovery.log_levels() == ["DEBUG", "INFO", "WARNING", "ERROR"]


def test_current_value_walks_dotted_key():
    cfg = discovery.current_config()
    assert discovery.current_value(cfg, ("llm", "host")) == cfg.llm.host


# ---- registry browsing + pull + delete ---------------------------------------

SEARCH_HTML = (
    "<div x-test-search-response-title>qwen2.5</div>"
    '<p class="max-w-lg break-words text-neutral-800 text-md">Alibaba&#39;s Qwen2.5 models.</p>'
    '<span x-test-capability class="x">tools</span>'
    '<span x-test-size class="x">0.5b</span><span x-test-size class="x">3b</span>'
    "<span x-test-pull-count>12.3M</span>"
    "<div x-test-search-response-title>nomic-embed</div>"
    '<p class="max-w-lg break-words text-neutral-800 text-md">An embedding model.</p>'
    '<span x-test-size class="x">137m</span><span x-test-pull-count>9M</span>'
)

TAGS_HTML = (
    '<a href="/library/qwen2.5:latest">latest</a><span>4.7GB</span>'
    '<a href="/library/qwen2.5:3b">3b</a><span>1.9GB</span>'
    '<a href="/library/qwen2.5:3b">3b</a>'  # duplicate link — should dedup
)


async def test_search_registry_parses_and_unescapes(monkeypatch, tmp_path):
    monkeypatch.setattr(discovery, "CACHE_PATH", str(tmp_path / "c.json"))

    def handler(request):
        assert request.url.path == "/search"
        assert request.url.params["q"] == "qwen"
        return httpx.Response(200, text=SEARCH_HTML)

    _patch_transport(monkeypatch, handler)
    models = await discovery.search_registry("qwen")
    assert [m.name for m in models] == ["qwen2.5", "nomic-embed"]
    assert models[0].description == "Alibaba's Qwen2.5 models."  # html.unescape applied
    assert models[0].sizes == ["0.5b", "3b"]
    assert models[0].capabilities == ["tools"]
    assert models[0].pulls == "12.3M"


async def test_search_registry_empty_when_offline(monkeypatch, tmp_path):
    monkeypatch.setattr(discovery, "CACHE_PATH", str(tmp_path / "c.json"))

    def handler(request):
        raise httpx.ConnectError("offline")

    _patch_transport(monkeypatch, handler)
    assert await discovery.search_registry("qwen") == []


async def test_registry_tags_pairs_size_and_dedups(monkeypatch, tmp_path):
    monkeypatch.setattr(discovery, "CACHE_PATH", str(tmp_path / "c.json"))

    def handler(request):
        assert request.url.path == "/library/qwen2.5/tags"
        return httpx.Response(200, text=TAGS_HTML)

    _patch_transport(monkeypatch, handler)
    tags = await discovery.registry_tags("qwen2.5")
    assert [(t.ref, t.size) for t in tags] == [
        ("qwen2.5:latest", "4.7GB"),
        ("qwen2.5:3b", "1.9GB"),
    ]


async def test_pull_model_streams_progress(monkeypatch):
    body = (
        b'{"status":"pulling manifest"}\n'
        b'{"status":"downloading","completed":50,"total":100}\n'
        b'{"status":"success"}\n'
    )

    def handler(request):
        assert request.url.path == "/api/pull"
        return httpx.Response(200, content=body)

    _patch_transport(monkeypatch, handler)
    seen = [p async for p in discovery.pull_model("http://localhost:11434", "qwen2.5:3b")]
    assert [p.status for p in seen] == ["pulling manifest", "downloading", "success"]
    assert seen[1].percent == 50.0
    assert seen[0].percent == 0.0  # total 0 -> no div-by-zero


async def test_delete_model(monkeypatch):
    def handler(request):
        assert request.method == "DELETE"
        assert request.url.path == "/api/delete"
        return httpx.Response(200)

    _patch_transport(monkeypatch, handler)
    assert await discovery.delete_model("http://localhost:11434", "qwen2.5:3b") is True


async def test_delete_model_false_on_error(monkeypatch):
    def handler(request):
        return httpx.Response(404)

    _patch_transport(monkeypatch, handler)
    assert await discovery.delete_model("http://localhost:11434", "nope") is False


# ---- 72h disk cache ----------------------------------------------------------


async def test_cache_hit_avoids_second_http(monkeypatch, tmp_path):
    monkeypatch.setattr(discovery, "CACHE_PATH", str(tmp_path / "c.json"))
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, text=SEARCH_HTML)

    _patch_transport(monkeypatch, handler)
    first = await discovery.search_registry("qwen")
    second = await discovery.search_registry("qwen")  # served from cache
    assert len(calls) == 1
    assert [m.name for m in first] == [m.name for m in second]


async def test_cache_expires_after_ttl(monkeypatch, tmp_path):
    monkeypatch.setattr(discovery, "CACHE_PATH", str(tmp_path / "c.json"))
    clock = {"now": 1000.0}
    monkeypatch.setattr(discovery.time, "time", lambda: clock["now"])
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, text=SEARCH_HTML)

    _patch_transport(monkeypatch, handler)
    await discovery.search_registry("qwen")
    clock["now"] += discovery.CACHE_TTL_SECONDS + 1  # age past the TTL
    await discovery.search_registry("qwen")
    assert len(calls) == 2  # stale entry re-fetched


async def test_refresh_bypasses_fresh_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(discovery, "CACHE_PATH", str(tmp_path / "c.json"))
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, text=SEARCH_HTML)

    _patch_transport(monkeypatch, handler)
    await discovery.search_registry("qwen")
    await discovery.search_registry("qwen", refresh=True)  # force re-scrape
    assert len(calls) == 2


def test_stt_model_options_are_static_and_nonempty():
    options = discovery.stt_model_options()
    assert "distil-medium.en" in options
    assert all(isinstance(o, str) for o in options)


# ---- OpenCode Zen discovery + provider-aware routing ------------------------


def test_llm_provider_options_static():
    assert discovery.llm_provider_options() == ["ollama", "opencode-zen"]


def test_llm_fallback_options_static_includes_none():
    opts = discovery.llm_fallback_options()
    assert opts[0] == ""  # "" = no fallback, listed first
    assert "ollama" in opts and "opencode-zen" in opts


async def test_zen_health_true_when_models_ok(monkeypatch):
    def handler(request):
        assert request.url.path == "/zen/v1/models"
        assert request.headers["Authorization"] == "Bearer k"
        return httpx.Response(200, json={"data": [{"id": "deepseek-v4-flash-free"}]})

    _patch_transport(monkeypatch, handler)
    assert await discovery.zen_health("https://opencode.ai/zen/v1", "k") is True


async def test_zen_health_false_when_down(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("connection refused")

    _patch_transport(monkeypatch, handler)
    assert await discovery.zen_health("https://opencode.ai/zen/v1", "k") is False


async def test_zen_health_false_on_401(monkeypatch):
    def handler(request):
        return httpx.Response(401, text="unauthorized")

    _patch_transport(monkeypatch, handler)
    assert await discovery.zen_health("https://opencode.ai/zen/v1", "k") is False


async def test_zen_health_false_when_no_base_url():
    assert await discovery.zen_health("", "k") is False


async def test_zen_model_options_lists_ids(monkeypatch):
    def handler(request):
        return httpx.Response(
            200, json={"data": [{"id": "deepseek-v4-flash-free"}, {"id": "gpt-oss"}]}
        )

    _patch_transport(monkeypatch, handler)
    opts = await discovery.zen_model_options("https://opencode.ai/zen/v1", "k")
    assert opts == [
        ("deepseek-v4-flash-free  —  free", "deepseek-v4-flash-free"),
        ("gpt-oss", "gpt-oss"),
    ]


async def test_zen_model_options_pins_free_to_top(monkeypatch):
    def handler(request):
        # "zzz-free" is alphabetically last but must still sort above paid models.
        return httpx.Response(
            200,
            json={"data": [{"id": "gpt-oss"}, {"id": "zzz-free"}, {"id": "claude-opus"}]},
        )

    _patch_transport(monkeypatch, handler)
    opts = await discovery.zen_model_options("https://opencode.ai/zen/v1", "k")
    assert opts == [
        ("zzz-free  —  free", "zzz-free"),
        ("claude-opus", "claude-opus"),
        ("gpt-oss", "gpt-oss"),
    ]


async def test_zen_model_options_no_auth_header_when_key_blank(monkeypatch):
    # Regression: a blank key built "Authorization: Bearer " (trailing space), which
    # httpx rejects as an illegal header value — the request never sent, list empty.
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"data": [{"id": "deepseek-v4-flash-free"}]})

    _patch_transport(monkeypatch, handler)
    opts = await discovery.zen_model_options("https://opencode.ai/zen/v1", "")
    assert seen["auth"] is None  # header omitted entirely
    assert opts == [("deepseek-v4-flash-free  —  free", "deepseek-v4-flash-free")]


async def test_zen_model_options_empty_when_down(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("connection refused")

    _patch_transport(monkeypatch, handler)
    assert await discovery.zen_model_options("https://opencode.ai/zen/v1", "k") == []


async def test_zen_model_options_empty_when_no_base_url():
    assert await discovery.zen_model_options("", "k") == []


async def test_zen_model_options_skips_entries_without_id(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"data": [{"id": "ok"}, {"no": "id"}, "x"]})

    _patch_transport(monkeypatch, handler)
    assert await discovery.zen_model_options("https://x/v1", "k") == [("ok", "ok")]


async def test_llm_model_options_routes_to_zen(monkeypatch):
    async def fake_zen(base_url="", api_key="", **_):
        assert base_url == "https://zen/v1"
        assert api_key == "k"
        return [("m1", "m1")]

    async def fake_ollama(host="", **_):
        raise AssertionError("should not call ollama for zen primary")

    monkeypatch.setattr(discovery, "zen_model_options", fake_zen)
    monkeypatch.setattr(discovery, "ollama_model_options", fake_ollama)
    opts = await discovery.llm_model_options(
        provider="opencode-zen", base_url="https://zen/v1", api_key="k",
    )
    assert opts == [("m1", "m1")]


async def test_llm_model_options_routes_to_ollama(monkeypatch):
    async def fake_ollama(host="", **_):
        assert host == "http://localhost:11434"
        return [("q:3b", "q:3b")]

    async def fake_zen(**_):
        raise AssertionError("should not call zen for ollama primary")

    monkeypatch.setattr(discovery, "ollama_model_options", fake_ollama)
    monkeypatch.setattr(discovery, "zen_model_options", fake_zen)
    opts = await discovery.llm_model_options(
        provider="ollama", host="http://localhost:11434",
    )
    assert opts == [("q:3b", "q:3b")]


async def test_llm_fallback_model_options_routes_by_fallback_provider(monkeypatch):
    async def fake_zen(base_url="", api_key="", **_):
        return [("zen-m", "zen-m")]

    async def fake_ollama(host="", **_):
        return [("ollama-m", "ollama-m")]

    monkeypatch.setattr(discovery, "zen_model_options", fake_zen)
    monkeypatch.setattr(discovery, "ollama_model_options", fake_ollama)
    # The fallback model picker keys off `fallback`, NOT `provider`.
    assert await discovery.llm_fallback_model_options(
        provider="opencode-zen", fallback="ollama", host="http://h",
    ) == [("ollama-m", "ollama-m")]
    assert await discovery.llm_fallback_model_options(
        provider="ollama", fallback="opencode-zen", base_url="https://zen/v1", api_key="k",
    ) == [("zen-m", "zen-m")]
    # No fallback configured -> still lists local models so one can be chosen.
    assert await discovery.llm_fallback_model_options(fallback="", host="http://h") == [
        ("ollama-m", "ollama-m")
    ]
