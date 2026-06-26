"""Option providers and current-value seeding for the Config tab.

Providers share the signature ``(host=..., **_)`` so the app can resolve them
uniformly; sync providers simply ignore ``host``. The TUI imports only httpx and
the typed Config — never the daemon's native deps.
"""

from __future__ import annotations

import glob
import html as _html
import json as _json
import logging
import os
import re
import time
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field

import httpx

from assistant.core.config import Config
from assistant.wake import registry

log = logging.getLogger(__name__)

DEFAULT_HOST = "http://localhost:11434"
WAKE_MODEL_DIR = "models/wake"

# Public model registry. Scraped (no official search API); isolated here so a markup
# change degrades to empty results rather than crashing the TUI.
OLLAMA_REGISTRY = "https://ollama.com"
# Browser-ish UA — ollama.com serves the search HTML we parse below.
_REGISTRY_UA = "Mozilla/5.0 (compatible; personal-assistant-tui)"

CACHE_PATH = ".cache/ollama_registry.json"
CACHE_TTL_SECONDS = 72 * 3600

_OLLAMA_ERRORS = (httpx.HTTPError, _json.JSONDecodeError, KeyError, ValueError)


def _human_size(n: int) -> str:
    """Bytes -> a compact human string (e.g. 1992 -> '1.9 KB', 0 -> '?')."""
    if not n:
        return "?"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


@dataclass(frozen=True)
class OllamaModel:
    """Tags-level metadata for one pulled model (cheap: all models in one call)."""

    name: str
    size: int  # bytes on disk
    parameter_size: str  # e.g. "3.2B"
    quantization: str  # e.g. "Q4_K_M"
    family: str  # e.g. "qwen2"
    modified_at: str

    @property
    def human_size(self) -> str:
        return _human_size(self.size)


@dataclass(frozen=True)
class OllamaModelDetail:
    """Show-level metadata for one model (one POST /api/show per model)."""

    name: str
    parameter_count: int  # exact, e.g. 3085938688
    context_length: int  # e.g. 32768
    quantization: str
    family: str
    capabilities: list[str] = field(default_factory=list)


async def ollama_models_info(host: str = DEFAULT_HOST, **_: object) -> list[OllamaModel]:
    """Pulled models with size/params/quant via GET {host}/api/tags. [] if unreachable."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{host.rstrip('/')}/api/tags")
            resp.raise_for_status()
            models = resp.json().get("models", [])
    except _OLLAMA_ERRORS as exc:
        log.warning("Ollama model discovery failed (%s); is `ollama serve` up?", exc)
        return []
    out: list[OllamaModel] = []
    for m in models:
        details = m.get("details") or {}
        out.append(
            OllamaModel(
                name=m["name"],
                size=m.get("size", 0),
                parameter_size=details.get("parameter_size", ""),
                quantization=details.get("quantization_level", ""),
                family=details.get("family", ""),
                modified_at=m.get("modified_at", ""),
            )
        )
    return out


async def ollama_model_detail(host: str, name: str) -> OllamaModelDetail | None:
    """Deep metadata for one pulled model via POST {host}/api/show. None if unavailable."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{host.rstrip('/')}/api/show", json={"model": name})
            resp.raise_for_status()
            data = resp.json()
    except _OLLAMA_ERRORS as exc:
        log.warning("Ollama show for %r failed (%s)", name, exc)
        return None
    info = data.get("model_info") or {}
    details = data.get("details") or {}
    # model_info keys are architecture-prefixed (e.g. "qwen2.context_length"); scan by suffix.
    context_length = next(
        (v for k, v in info.items() if k.endswith(".context_length")), 0
    )
    return OllamaModelDetail(
        name=name,
        parameter_count=info.get("general.parameter_count", 0),
        context_length=context_length,
        quantization=details.get("quantization_level", ""),
        family=details.get("family", ""),
        capabilities=list(data.get("capabilities") or []),
    )


async def ollama_health(host: str = DEFAULT_HOST, **_: object) -> bool:
    """True if an Ollama server answers at {host} (GET /api/version)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{host.rstrip('/')}/api/version")
            resp.raise_for_status()
            return True
    except _OLLAMA_ERRORS as exc:
        # Polled every few seconds by the TUI; debug-level so a down server
        # doesn't spam the log on every poll.
        log.debug("Ollama not reachable at %s (%s)", host, exc)
        return False


async def ollama_models(host: str = DEFAULT_HOST, **_: object) -> list[str]:
    """Pulled model names via GET {host}/api/tags. [] if unreachable."""
    return [m.name for m in await ollama_models_info(host)]


async def ollama_model_options(host: str = DEFAULT_HOST, **_: object) -> list[tuple[str, str]]:
    """(label, value) pairs for the model picker: label shows size/params, value is the name."""
    options: list[tuple[str, str]] = []
    for m in await ollama_models_info(host):
        size = m.human_size if m.size else ""
        meta = " · ".join(p for p in (size, m.parameter_size, m.quantization) if p)
        label = f"{m.name}  —  {meta}" if meta else m.name
        options.append((label, m.name))
    return options


async def delete_model(host: str, name: str) -> bool:
    """Remove a pulled model via DELETE {host}/api/delete. True on success."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request("DELETE", f"{host.rstrip('/')}/api/delete",
                                        json={"model": name})
            resp.raise_for_status()
            return True
    except _OLLAMA_ERRORS as exc:
        log.warning("Ollama delete of %r failed (%s)", name, exc)
        return False


# ---- registry (ollama.com) browsing + pulling --------------------------------


@dataclass(frozen=True)
class RegistryModel:
    """A model listed on ollama.com (not necessarily pulled locally)."""

    name: str  # slug, e.g. "qwen2.5" — the library URL + pull prefix
    description: str
    sizes: list[str] = field(default_factory=list)  # e.g. ["0.5b", "3b", "7b"]
    capabilities: list[str] = field(default_factory=list)  # e.g. ["tools", "vision"]
    pulls: str = ""  # popularity, e.g. "14.2M"


@dataclass(frozen=True)
class RegistryTag:
    """One pullable tag of a registry model."""

    ref: str  # exact POST /api/pull model, e.g. "qwen2.5:3b"
    size: str  # disk size label, e.g. "1.9GB"


@dataclass(frozen=True)
class PullProgress:
    """One streamed progress line from POST /api/pull."""

    status: str
    completed: int = 0
    total: int = 0

    @property
    def percent(self) -> float:
        return 100.0 * self.completed / self.total if self.total else 0.0


def _cache_get(key: str) -> object | None:
    """Cached value for key if present and < CACHE_TTL_SECONDS old, else None."""
    try:
        with open(CACHE_PATH) as fh:
            entry = _json.load(fh).get(key)
        if entry and time.time() - entry["ts"] < CACHE_TTL_SECONDS:
            return entry["data"]
    except (OSError, _json.JSONDecodeError, KeyError, TypeError):
        pass  # missing/corrupt cache is a miss, never an error
    return None


def _cache_put(key: str, data: object) -> None:
    """Store data under key with a fresh timestamp (best-effort)."""
    try:
        os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
        cache: dict = {}
        try:
            with open(CACHE_PATH) as fh:
                cache = _json.load(fh)
        except (OSError, _json.JSONDecodeError):
            cache = {}
        cache[key] = {"ts": time.time(), "data": data}
        with open(CACHE_PATH, "w") as fh:
            _json.dump(cache, fh)
    except OSError as exc:
        log.debug("Could not write registry cache (%s)", exc)


async def _registry_get(path: str) -> str:
    """GET text from ollama.com (raises on error; callers fail soft)."""
    async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": _REGISTRY_UA}) as client:
        resp = await client.get(f"{OLLAMA_REGISTRY}{path}")
        resp.raise_for_status()
        return resp.text


def _parse_search(html_text: str) -> list[RegistryModel]:
    """Parse ollama.com/search HTML into RegistryModels via the x-test-* markers."""
    out: list[RegistryModel] = []
    # Each result chunk runs from its title marker to the next one.
    for chunk in html_text.split("x-test-search-response-title>")[1:]:
        name = chunk.split("<", 1)[0].strip()
        if not name:
            continue
        desc = re.search(r"max-w-lg[^>]*>([^<]+)<", chunk)
        pulls = re.search(r"x-test-pull-count>([^<]+)<", chunk)
        out.append(
            RegistryModel(
                name=name,
                description=_html.unescape(desc.group(1).strip()) if desc else "",
                sizes=[s.strip() for s in re.findall(r"x-test-size[^>]*>([^<]+)<", chunk)],
                capabilities=[c.strip() for c in re.findall(r"x-test-capability[^>]*>([^<]+)<", chunk)],
                pulls=pulls.group(1).strip() if pulls else "",
            )
        )
    return out


def _parse_tags(html_text: str, name: str) -> list[RegistryTag]:
    """Parse a library/<name>/tags page: each tag ref paired with its disk size."""
    link = re.compile(rf"/library/{re.escape(name)}:([A-Za-z0-9._-]+)")
    sizes = [(m.start(), m.group(1)) for m in re.finditer(r"([0-9.]+\s?[GM]B)", html_text)]
    tags: list[RegistryTag] = []
    seen: set[str] = set()
    for m in link.finditer(html_text):
        tag = m.group(1)
        if tag in seen:
            continue
        seen.add(tag)
        size = next((s for pos, s in sizes if pos >= m.start()), "")
        tags.append(RegistryTag(ref=f"{name}:{tag}", size=size))
    return tags


async def search_registry(query: str, *, refresh: bool = False) -> list[RegistryModel]:
    """Search ollama.com for models. Cached 72h; refresh=True forces a re-scrape."""
    key = f"search:{query}"
    if not refresh and (cached := _cache_get(key)) is not None:
        return [RegistryModel(**m) for m in cached]
    try:
        html_text = await _registry_get(f"/search?q={query}")
    except _OLLAMA_ERRORS as exc:
        log.warning("Ollama registry search failed (%s); offline?", exc)
        return []
    models = _parse_search(html_text)
    _cache_put(key, [asdict(m) for m in models])
    return models


async def registry_tags(name: str, *, refresh: bool = False) -> list[RegistryTag]:
    """List pullable tags (with disk sizes) for a registry model. Cached 72h."""
    key = f"tags:{name}"
    if not refresh and (cached := _cache_get(key)) is not None:
        return [RegistryTag(**t) for t in cached]
    try:
        html_text = await _registry_get(f"/library/{name}/tags")
    except _OLLAMA_ERRORS as exc:
        log.warning("Ollama registry tags for %r failed (%s)", name, exc)
        return []
    tags = _parse_tags(html_text, name)
    _cache_put(key, [asdict(t) for t in tags])
    return tags


async def pull_model(host: str, ref: str) -> AsyncIterator[PullProgress]:
    """Stream POST {host}/api/pull progress for a model ref. Never cached."""
    payload = {"model": ref, "stream": True}
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", f"{host.rstrip('/')}/api/pull", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                data = _json.loads(line)
                yield PullProgress(
                    status=data.get("status", ""),
                    completed=data.get("completed", 0),
                    total=data.get("total", 0),
                )


def wake_models(root: str = WAKE_MODEL_DIR, **_: object) -> list[str]:
    """Glob trained wake-word models, e.g. models/wake/*.onnx."""
    return sorted(glob.glob(os.path.join(root, "*.onnx")))


def wake_model_choices(root: str = WAKE_MODEL_DIR, **_: object) -> list[tuple[str, str]]:
    """(phrase, path) for each trained wake model — the phrase labels the checkbox,
    the path is the stored value (wake.model_paths)."""
    return [(registry.phrase_for(path), path) for path in wake_models(root)]


def log_levels(**_: object) -> list[str]:
    return ["DEBUG", "INFO", "WARNING", "ERROR"]


def current_config() -> Config:
    """Effective config (yaml + ASSISTANT_* env) used to seed the form."""
    return Config()


def config_from_dict(data: dict) -> Config:
    """Build a Config from a raw mapping (e.g. default-config.yaml).

    Passed sections win over env/yaml (init args have top precedence); any section
    missing from the dict falls back to the usual sources."""
    return Config(**data)


def current_value(config: Config, key: tuple[str, ...]) -> str:
    """Walk a dotted key on a Config instance, as a string for the widgets."""
    obj: object = config
    for part in key:
        obj = getattr(obj, part)
    return "" if obj is None else str(obj)
