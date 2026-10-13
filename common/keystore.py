"""Loading and saving of long-term ML-KEM keys (JSON files)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from common.pqc_channel import ALGORITHM, DK_LEN, EK_LEN, ChannelError, b64d, b64e

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class KeyRecord:
    role: str  # "cloud" or "gateway"
    identity: str  # e.g. "cloud", "gateway-1"
    ek: bytes
    dk: bytes | None = None


def keys_dir() -> Path:
    return Path(os.getenv("PQC_KEYS_DIR", REPO_ROOT / "keys"))


def trusted_gateways_dir() -> Path:
    return Path(os.getenv("TRUSTED_GATEWAYS_DIR", keys_dir() / "trusted_gateways"))


def save_key(path: Path, record: KeyRecord, include_private: bool) -> None:
    data = {
        "algorithm": ALGORITHM,
        "role": record.role,
        "id": record.identity,
        "ek": b64e(record.ek),
    }
    if include_private:
        if record.dk is None:
            raise ValueError("No private key to save.")
        data["dk"] = b64e(record.dk)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    if include_private:
        try:
            path.chmod(0o600)  # best effort; limited effect on Windows
        except OSError:
            pass


def load_key(path: Path, require_private: bool = False) -> KeyRecord:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data["algorithm"] != ALGORITHM:
            raise ValueError(f"unsupported algorithm {data['algorithm']!r}")
        ek = b64d(data["ek"])
        dk = b64d(data["dk"]) if "dk" in data else None
        if len(ek) != EK_LEN or (dk is not None and len(dk) != DK_LEN):
            raise ValueError("key has an unexpected length")
        if require_private and dk is None:
            raise ValueError("file does not contain a private key")
        return KeyRecord(role=data["role"], identity=data["id"], ek=ek, dk=dk)
    except (OSError, KeyError, ValueError, ChannelError) as error:
        raise RuntimeError(f"Cannot load key file {path}: {error}") from error


def load_trusted_gateways(directory: Path) -> dict[str, bytes]:
    """Return {gateway_id: encapsulation_key} for every *.json file in directory."""
    trusted: dict[str, bytes] = {}
    if not Path(directory).is_dir():
        return trusted
    for file in sorted(Path(directory).glob("*.json")):
        record = load_key(file)
        if record.role != "gateway":
            raise RuntimeError(f"{file} is not a gateway key.")
        trusted[record.identity] = record.ek
    return trusted
