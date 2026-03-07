from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.models.artifacts import PolicyDefinition, ReasoningProgram, TemplateDefinition


class DesignRegistry:
    def __init__(self, artifact_root: Path) -> None:
        self.artifact_root = artifact_root

    def _load_json(self, *parts: str) -> dict:
        path = self.artifact_root.joinpath(*parts)
        return json.loads(path.read_text(encoding="utf-8"))

    def get_program(self, program_id: str) -> ReasoningProgram:
        return ReasoningProgram.model_validate(self._load_json("programs", f"{program_id}.json"))

    def get_policy(self, policy_id: str) -> PolicyDefinition:
        return PolicyDefinition.model_validate(self._load_json("policies", f"{policy_id}.json"))

    def get_template(self, template_id: str) -> TemplateDefinition:
        return TemplateDefinition.model_validate(self._load_json("templates", f"{template_id}.json"))

    def list_templates(self) -> list[TemplateDefinition]:
        templates_dir = self.artifact_root / "templates"
        return [
            TemplateDefinition.model_validate(json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(templates_dir.glob("*.json"))
        ]

    def get_schema(self, schema_id: str) -> dict:
        return self._load_json("schemas", f"{schema_id}.json")


@lru_cache(maxsize=1)
def get_registry() -> DesignRegistry:
    return DesignRegistry(get_settings().artifact_root)
