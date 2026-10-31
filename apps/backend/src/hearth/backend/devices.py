"""Device registry stored as a YAML mapping of device id to token hash."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from pathlib import Path

import yaml

from .config import DEFAULT_DEVICES_PATH


class DeviceError(Exception):
    """Raised when the device registry cannot be read or changed."""


def token_hash(token: str) -> str:
    """Return the SHA-256 hex digest stored for a token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class DeviceStore:
    """Read and update the device registry.

    Only token hashes are stored. The plain token is returned once by
    :meth:`add` and never persisted.
    """

    def __init__(self, path: Path = DEFAULT_DEVICES_PATH) -> None:
        self._path = path

    def _load(self) -> dict[str, str]:
        if not self._path.is_file():
            return {}
        try:
            data = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise DeviceError(f"cannot read device registry {self._path}: {exc}") from exc
        if not isinstance(data, dict):
            raise DeviceError(f"device registry {self._path} must be a mapping")
        return {str(device_id): str(digest) for device_id, digest in data.items()}

    def _save(self, devices: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(yaml.safe_dump(devices, sort_keys=True), encoding="utf-8")

    def add(self, device_id: str) -> str:
        """Register a device and return its new plain token."""
        devices = self._load()
        if device_id in devices:
            raise DeviceError(f"device {device_id!r} already exists")
        token = secrets.token_urlsafe(32)
        devices[device_id] = token_hash(token)
        try:
            self._save(devices)
        except OSError as exc:
            raise DeviceError(f"cannot write device registry {self._path}: {exc}") from exc
        return token

    def remove(self, device_id: str) -> None:
        """Remove a registered device."""
        devices = self._load()
        if device_id not in devices:
            raise DeviceError(f"device {device_id!r} does not exist")
        del devices[device_id]
        try:
            self._save(devices)
        except OSError as exc:
            raise DeviceError(f"cannot write device registry {self._path}: {exc}") from exc

    def verify(self, device_id: str, token: str) -> bool:
        """Return whether ``token`` matches the stored hash for ``device_id``."""
        stored = self._load().get(device_id)
        if stored is None:
            return False
        return hmac.compare_digest(stored, token_hash(token))
