from __future__ import annotations

from pathlib import Path


class RequirementsReference:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")

