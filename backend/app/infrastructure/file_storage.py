import hashlib
import os
from pathlib import Path
from typing import Any
from uuid import uuid4


class FileSizeLimitExceeded(ValueError):
    pass


class FileStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, storage_key: str) -> Path:
        if Path(storage_key).is_absolute():
            raise ValueError("invalid storage key")
        path = (self.root / storage_key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("invalid storage key")
        return path

    def exists(self, storage_key: str) -> bool:
        return self.resolve(storage_key).is_file()

    async def save_stream(
        self,
        stream: Any,
        storage_key: str,
        max_bytes: int,
        *,
        chunk_size: int = 64 * 1024,
    ) -> tuple[int, str]:
        destination = self.resolve(storage_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        digest = hashlib.sha256()
        size = 0
        try:
            with temporary.open("xb") as handle:
                while True:
                    chunk = await stream.read(chunk_size)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise FileSizeLimitExceeded("file exceeds configured limit")
                    handle.write(chunk)
                    digest.update(chunk)
            if size == 0:
                raise ValueError("empty file")
            os.replace(temporary, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return size, digest.hexdigest()
