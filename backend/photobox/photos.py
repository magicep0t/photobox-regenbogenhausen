"""Photo storage on disk: naming, listing and safe lookup."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

NAME_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}\.jpg$")


@dataclass(frozen=True)
class Photo:
    name: str
    taken_at: datetime

    def to_dict(self) -> dict:
        return {"name": self.name, "url": f"/photos/{self.name}", "taken_at": self.taken_at.isoformat()}


class PhotoStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def new_path(self) -> Path:
        name = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}.jpg"
        return self.directory / name

    def get(self, name: str) -> Path | None:
        """Return the path for ``name`` if it is a valid, existing photo; never escapes the directory."""
        if not NAME_RE.match(name):
            return None
        path = self.directory / name
        return path if path.is_file() else None

    @staticmethod
    def photo(path: Path) -> Photo:
        return Photo(path.name, datetime.strptime(path.name[:15], "%Y%m%d-%H%M%S"))

    def list(self, limit: int | None = None) -> list[Photo]:
        files = sorted((p for p in self.directory.glob("*.jpg") if NAME_RE.match(p.name)), reverse=True)
        if limit is not None:
            files = files[:limit]
        return [self.photo(p) for p in files]
