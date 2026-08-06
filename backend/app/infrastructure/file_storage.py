from pathlib import Path


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
