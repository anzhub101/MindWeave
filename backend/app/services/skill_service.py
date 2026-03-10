from __future__ import annotations

import json
import subprocess
from tempfile import TemporaryDirectory
from typing import Any

from app.models.artifacts import RegistryArtifact
from app.services.artifact_registry_service import ArtifactRegistryService
from app.services.json_utils import extract_json_object
from app.services.llm_gateway import LLMGateway, LLMRequest


class SkillService:
    def __init__(self, registry: ArtifactRegistryService, llm_gateway: LLMGateway) -> None:
        self.registry = registry
        self.llm_gateway = llm_gateway

    def list_skills(self) -> list[RegistryArtifact]:
        return self.registry.list("skill")

    def get_skill(self, skill_id: str, version: str | None = None) -> RegistryArtifact:
        return self.registry.get("skill", skill_id, version=version)

    def save_skill(
        self,
        skill_id: str,
        version: str,
        name: str,
        description: str,
        language: str,
        skill_type: str,
        entrypoint_filename: str,
        code: str,
        test_input: str = "",
        source: str = "user",
    ) -> RegistryArtifact:
        return self.registry.upsert(
            RegistryArtifact(
                kind="skill",
                artifact_id=skill_id,
                version=version,
                name=name,
                description=description,
                payload={
                    "skill_id": skill_id,
                    "name": name,
                    "description": description,
                    "language": language,
                    "skill_type": skill_type,
                    "entrypoint_filename": entrypoint_filename,
                    "code": code,
                    "test_input": test_input,
                    "suggested_node_executor": "tool_operator",
                },
                source=source,
                status="active",
            )
        )

    def generate_skill(
        self,
        prompt: str,
        language: str = "python",
        skill_type: str = "script",
        existing_code: str = "",
    ) -> dict[str, Any]:
        response = self.llm_gateway.generate(
            LLMRequest(
                task="skill_generation",
                prompt=(
                    "Generate a reusable skill for MindWeave. "
                    "Return strict JSON with keys: name, description, language, skill_type, "
                    "entrypoint_filename, code, test_input, notes."
                ),
                context={
                    "user_prompt": prompt,
                    "language": language,
                    "skill_type": skill_type,
                    "existing_code": existing_code,
                },
                determinism_mode="non_deterministic",
                temperature=0.4,
                top_p=0.95,
                agentic=True,
                max_tokens=2200,
            )
        )
        try:
            payload = extract_json_object(response.content)
        except Exception:
            payload = self._fallback_skill(prompt=prompt, language=language, skill_type=skill_type, existing_code=existing_code)
        return self._normalize_skill_payload(payload, prompt, language, skill_type, existing_code)

    def test_skill(
        self,
        language: str,
        entrypoint_filename: str,
        code: str,
        test_input: str = "",
        args: list[str] | None = None,
    ) -> dict[str, Any]:
        args = args or []
        try:
            stdout, stderr, exit_code, command = self._execute_code(
                language=language,
                entrypoint_filename=entrypoint_filename,
                code=code,
                stdin_payload=test_input,
                args=args,
            )
            return {
                "passed": exit_code == 0,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "command": command,
            }
        except FileNotFoundError as exc:
            return {
                "passed": False,
                "stdout": "",
                "stderr": str(exc),
                "exit_code": -1,
                "command": [],
            }
        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "stdout": "",
                "stderr": "Skill test timed out.",
                "exit_code": -1,
                "command": [],
            }

    def run_skill_artifact(
        self,
        skill_id: str,
        input_payload: dict[str, Any],
        version: str | None = None,
    ) -> dict[str, Any]:
        artifact = self.get_skill(skill_id, version=version)
        payload = artifact.payload
        language = str(payload.get("language") or "python")
        entrypoint_filename = str(payload.get("entrypoint_filename") or self._default_entrypoint(language))
        code = str(payload.get("code") or "")
        result = self.test_skill(
            language=language,
            entrypoint_filename=entrypoint_filename,
            code=code,
            test_input=json.dumps(input_payload),
        )
        parsed_output: Any = result["stdout"]
        if isinstance(parsed_output, str):
            stripped = parsed_output.strip()
            if stripped:
                try:
                    parsed_output = json.loads(stripped)
                except Exception:
                    parsed_output = stripped
        return {
            "skill_id": artifact.artifact_id,
            "version": artifact.version,
            "language": language,
            "result": parsed_output,
            "stderr": result["stderr"],
            "exit_code": result["exit_code"],
            "passed": result["passed"],
        }

    def _normalize_skill_payload(
        self,
        payload: dict[str, Any],
        prompt: str,
        language: str,
        skill_type: str,
        existing_code: str,
    ) -> dict[str, Any]:
        normalized_language = str(payload.get("language") or language or "python").strip().lower()
        normalized_skill_type = str(payload.get("skill_type") or skill_type or "script").strip().lower()
        default_name = prompt.strip().splitlines()[0][:64] or "Generated Skill"
        name = str(payload.get("name") or default_name).strip() or "Generated Skill"
        entrypoint_filename = str(payload.get("entrypoint_filename") or self._default_entrypoint(normalized_language)).strip()
        code = str(payload.get("code") or "").rstrip()
        if not code:
            code = existing_code.rstrip() or self._fallback_skill(prompt, normalized_language, normalized_skill_type, existing_code)["code"]
        description = str(payload.get("description") or f"{normalized_skill_type.title()} generated from prompt.").strip()
        notes = payload.get("notes") if isinstance(payload.get("notes"), list) else []
        test_input = str(payload.get("test_input") or "").strip()
        return {
            "name": name,
            "description": description,
            "language": normalized_language,
            "skill_type": normalized_skill_type,
            "entrypoint_filename": entrypoint_filename,
            "code": code,
            "test_input": test_input,
            "notes": [str(note) for note in notes if str(note).strip()],
            "suggested_node_executor": "tool_operator",
        }

    def _fallback_skill(
        self,
        prompt: str,
        language: str,
        skill_type: str,
        existing_code: str,
    ) -> dict[str, Any]:
        normalized_language = language.strip().lower() or "python"
        if existing_code.strip():
            code = existing_code
        elif normalized_language in {"javascript", "js", "typescript", "ts"}:
            code = (
                "const fs = require('fs');\n"
                "const raw = fs.readFileSync(0, 'utf8').trim();\n"
                "const payload = raw ? JSON.parse(raw) : {};\n"
                "const response = {\n"
                f"  summary: {json.dumps(prompt[:120])},\n"
                "  received: payload,\n"
                "  status: 'ok'\n"
                "};\n"
                "console.log(JSON.stringify(response));\n"
            )
        else:
            code = (
                "import json\n"
                "import sys\n\n"
                "raw = sys.stdin.read().strip()\n"
                "payload = json.loads(raw) if raw else {}\n"
                "response = {\n"
                f"    'summary': {prompt[:120]!r},\n"
                "    'received': payload,\n"
                "    'status': 'ok',\n"
                "}\n"
                "print(json.dumps(response))\n"
            )
        return {
            "name": "Generated Skill",
            "description": f"{skill_type.title()} scaffold generated from prompt.",
            "language": normalized_language,
            "skill_type": skill_type,
            "entrypoint_filename": self._default_entrypoint(normalized_language),
            "code": code,
            "test_input": json.dumps({"message": "hello from test"}),
            "notes": ["This draft follows the stdin-json to stdout-json convention for node deployment."],
        }

    def _execute_code(
        self,
        language: str,
        entrypoint_filename: str,
        code: str,
        stdin_payload: str,
        args: list[str],
    ) -> tuple[str, str, int, list[str]]:
        normalized_language = language.strip().lower()
        with TemporaryDirectory(prefix="mindweave-skill-") as tmpdir:
            entrypoint_path = f"{tmpdir}/{entrypoint_filename}"
            with open(entrypoint_path, "w", encoding="utf-8") as handle:
                handle.write(code)
            command = self._command_for_language(normalized_language, entrypoint_path, args)
            completed = subprocess.run(
                command,
                input=stdin_payload,
                text=True,
                capture_output=True,
                timeout=15,
                cwd=tmpdir,
            )
            return completed.stdout, completed.stderr, completed.returncode, command

    @staticmethod
    def _command_for_language(language: str, entrypoint_path: str, args: list[str]) -> list[str]:
        if language in {"javascript", "js", "typescript", "ts"}:
            return ["node", entrypoint_path, *args]
        return ["python3", entrypoint_path, *args]

    @staticmethod
    def _default_entrypoint(language: str) -> str:
        if language in {"javascript", "js", "typescript", "ts"}:
            return "main.js"
        return "main.py"
