"""Content-addressed local payload storage, separate from relational metadata."""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import uuid

from task_advisor.core import canonical


class LocalObjectStore:
    version = "local-objects-1.0"

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, digest, media_type="application/json"):
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("invalid object digest")
        return self.root / digest[:2] / (digest + (".json" if media_type == "application/json" else ".bin"))

    def put(self, value):
        payload = canonical(value).encode("utf-8")
        return self.put_bytes(payload, media_type="application/json")

    def put_bytes(self, payload, *, media_type="application/octet-stream"):
        if not isinstance(payload, bytes) or media_type not in {"application/json", "application/octet-stream", "image/png", "application/x-depth-f32"}:
            raise ValueError("unsupported binary payload encoding")
        digest = sha256(payload).hexdigest()
        path = self._path(digest, media_type)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != payload:
                raise ValueError("existing content-addressed object is corrupt")
        else:
            temporary = path.parent / ("write-" + uuid.uuid4().hex)
            try:
                with temporary.open("xb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                # Hard-link publication is atomic and cannot overwrite another
                # writer's object. A crashed transaction may leave an orphaned
                # complete object; it cannot expose a partially written object.
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    if path.read_bytes() != payload:
                        raise ValueError("concurrent object publication conflict")
            finally:
                temporary.unlink(missing_ok=True)
        return {"storage_schema": self.version, "sha256": digest,
                "bytes": len(payload), "media_type": media_type}

    def get(self, reference):
        if reference.get("media_type") != "application/json":
            raise ValueError("unsupported JSON payload encoding")
        return json.loads(self.get_bytes(reference))

    def get_bytes(self, reference):
        if set(reference) != {"storage_schema", "sha256", "bytes", "media_type"}:
            raise ValueError("invalid object reference")
        if reference["storage_schema"] != self.version or reference["media_type"] not in {"application/json", "application/octet-stream", "image/png", "application/x-depth-f32"}:
            raise ValueError("unsupported payload encoding")
        try:
            payload = self._path(reference["sha256"], reference["media_type"]).read_bytes()
        except FileNotFoundError as exc:
            raise ValueError("referenced payload is missing") from exc
        if len(payload) != reference["bytes"] or sha256(payload).hexdigest() != reference["sha256"]:
            raise ValueError("payload integrity check failed")
        return payload
