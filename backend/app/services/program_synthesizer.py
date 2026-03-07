from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.models.artifacts import NodeSpec, ReasoningProgram, SynthesizedProgramBundle
from app.services.json_utils import extract_json_object
from app.services.llm_gateway import LLMGateway, LLMRequest, MockProvider
from app.services.requirements_reference import RequirementsReference
from app.services.schema_service import SchemaService


class ProgramSynthesisService:
    def __init__(self, llm_gateway: LLMGateway) -> None:
        self.llm_gateway = llm_gateway
        self.settings = get_settings()
        self.reference = RequirementsReference(self.settings.requirements_markdown_path)
        self.generated_root = self.settings.generated_artifact_root
        self.schema_service = SchemaService()

    def synthesize(self, user_prompt: str, deterministic: bool = False) -> SynthesizedProgramBundle:
        requirements_text = self.reference.read()
        system_prompt = (
            "You are MindWeave's design-plane synthesizer. "
            "Create a domain-agnostic reasoning program for the given task using the supplied "
            "requirements reference. Output JSON only."
        )
        prompt = (
            "Synthesize a complete reasoning program bundle for the user's task.\n"
            "The bundle must include:\n"
            "1. template_id\n"
            "2. template_name\n"
            "3. domain\n"
            "4. mapping_explanation\n"
            "5. program\n"
            "6. output_schema_definition\n\n"
            "Constraints:\n"
            "- The system must remain domain-agnostic. Only specialize to the user's domain because the prompt requires it.\n"
            "- Use only node operation types: generate, analyze, aggregate, verify, synthesize.\n"
            "- Include at least one verify node before the final synthesis node.\n"
            "- Provide node instructions and success_criteria for each node.\n"
            "- Provide layout metadata with row and column for the UI.\n"
            "- The output_schema_definition must be valid JSON Schema.\n"
            "- Program IDs and node IDs must use snake_case.\n"
            "- Budget values should be realistic for an MVP.\n"
            "- The final schema should be suitable for structured output and audit export.\n"
            "- Return strict JSON, no commentary.\n"
        )
        if deterministic:
            bundle = self._normalize_bundle(self._fallback_payload(user_prompt, requirements_text), user_prompt)
            bundle = self.schema_service.attach_generated_node_schemas(bundle)
            self._persist_bundle(bundle)
            return bundle

        response = self.llm_gateway.generate(
            LLMRequest(
                task="program_synthesis",
                prompt=prompt,
                system_prompt=system_prompt,
                context={
                    "user_prompt": user_prompt,
                    "requirements_reference_markdown": requirements_text,
                },
                temperature=self.settings.k2_temperature,
                seed=self.settings.deterministic_seed,
                agentic=True,
                max_tokens=3500,
            )
        )

        try:
            payload = self._load_payload(response.content)
            bundle = self._normalize_bundle(payload, user_prompt)
        except Exception:
            fallback_payload = self._fallback_payload(user_prompt, requirements_text)
            bundle = self._normalize_bundle(fallback_payload, user_prompt)
        bundle = self.schema_service.attach_generated_node_schemas(bundle)
        self._persist_bundle(bundle)
        return bundle

    def _load_payload(self, content: str) -> dict[str, Any]:
        try:
            return extract_json_object(content)
        except Exception:
            repair = self.llm_gateway.generate(
                LLMRequest(
                    task="json_repair",
                    prompt=(
                        "Convert the provided content into a single strict JSON object only. "
                        "Use double-quoted keys, no markdown fences, no comments, and no trailing commas."
                    ),
                    context={"raw_text": content},
                    temperature=self.settings.k2_temperature,
                    seed=self.settings.deterministic_seed,
                    agentic=False,
                    max_tokens=3500,
                )
            )
            return extract_json_object(repair.content)

    @staticmethod
    def _fallback_payload(user_prompt: str, requirements_text: str) -> dict[str, Any]:
        fallback = MockProvider().generate(
            LLMRequest(
                task="program_synthesis",
                prompt="Fallback synthesis for invalid upstream JSON.",
                context={
                    "user_prompt": user_prompt,
                    "requirements_reference_markdown": requirements_text,
                },
                temperature=0.0,
                agentic=False,
            )
        )
        return extract_json_object(fallback.content)

    def _normalize_bundle(self, payload: dict[str, Any], user_prompt: str) -> SynthesizedProgramBundle:
        payload = self._coerce_bundle_payload(payload, user_prompt)

        if not payload.get("template_id"):
            payload["template_id"] = f"{self._slug(user_prompt)}_template"
        if not payload.get("template_name"):
            payload["template_name"] = "Generated Reasoning Template"
        if not payload.get("domain"):
            payload["domain"] = self._infer_domain(user_prompt)
        if not payload.get("mapping_explanation"):
            payload["mapping_explanation"] = "Synthesized from requirements reference and prompt."

        program_payload = payload["program"]
        program_payload.setdefault("program_id", f"{self._slug(user_prompt)}_v1")
        program_payload.setdefault("version", "1.0.0")
        program_payload.setdefault("template_id", payload["template_id"])
        program_payload.setdefault("domain", payload["domain"])
        program_payload.setdefault("goal", user_prompt)
        program_payload.setdefault("policy", "priority_based")
        program_payload.setdefault(
            "budget",
            {"max_nodes": 12, "max_tokens": 18000, "max_runtime_seconds": 240},
        )
        program_payload["budget"] = self._normalize_budget(program_payload["budget"], program_payload.get("nodes", []))
        program_payload.setdefault("convergence_rule", "no_pending_nodes")
        schema_title = payload["output_schema_definition"].get(
            "title",
            f"{program_payload['program_id']}_output_schema_v1",
        )
        payload["output_schema_definition"].setdefault(
            "$schema",
            "https://json-schema.org/draft/2020-12/schema",
        )
        payload["output_schema_definition"]["title"] = schema_title
        program_payload["output_schema"] = schema_title
        program_payload.setdefault(
            "deterministic_defaults",
            {"temperature": 0, "seed": self.settings.deterministic_seed},
        )
        program_payload.setdefault("metadata", {})
        program_payload["nodes"] = self._repair_graph_connectivity(
            self._normalize_nodes(program_payload.get("nodes", []))
        )

        program = ReasoningProgram.model_validate(program_payload)
        self._ensure_layout_metadata(program)
        self._ensure_verify_gate(program)
        return SynthesizedProgramBundle(
            template_id=payload["template_id"],
            template_name=payload["template_name"],
            domain=payload["domain"],
            program=program,
            output_schema_definition=payload["output_schema_definition"],
            mapping_explanation=payload["mapping_explanation"],
            source_requirements_path=str(self.settings.requirements_markdown_path),
        )

    def _coerce_bundle_payload(self, payload: dict[str, Any], user_prompt: str) -> dict[str, Any]:
        if isinstance(payload.get("program"), dict) and isinstance(payload.get("output_schema_definition"), dict):
            return payload

        wrapped_payload = self._unwrap_payload_container(payload)
        if wrapped_payload is not None and wrapped_payload is not payload:
            payload = wrapped_payload
            if isinstance(payload.get("program"), dict) and isinstance(payload.get("output_schema_definition"), dict):
                return payload

        program_payload = payload.get("program")
        if not isinstance(program_payload, dict):
            for key in ("reasoning_program", "program_definition", "graph_of_operations"):
                candidate = payload.get(key)
                if isinstance(candidate, dict):
                    program_payload = candidate
                    break
        if not isinstance(program_payload, dict) and self._looks_like_program(payload):
            program_payload = payload

        schema_payload = payload.get("output_schema_definition")
        if not isinstance(schema_payload, dict):
            for key in ("output_schema", "schema", "schema_definition", "result_schema"):
                candidate = payload.get(key)
                if isinstance(candidate, dict):
                    schema_payload = candidate
                    break

        if not isinstance(program_payload, dict):
            raise ValueError("Synthesized bundle is missing required keys.")

        program_id = str(program_payload.get("program_id") or self._slug(user_prompt) or "generated_reasoning_v1")
        if not isinstance(schema_payload, dict):
            schema_payload = self._default_output_schema_definition(program_id)

        return {
            "template_id": payload.get("template_id"),
            "template_name": payload.get("template_name"),
            "domain": payload.get("domain"),
            "mapping_explanation": payload.get("mapping_explanation"),
            "program": program_payload,
            "output_schema_definition": schema_payload,
        }

    @staticmethod
    def _unwrap_payload_container(payload: dict[str, Any]) -> dict[str, Any] | None:
        for key in ("bundle", "result", "response", "data"):
            candidate = payload.get(key)
            if isinstance(candidate, dict):
                return candidate
        return None

    @staticmethod
    def _looks_like_program(payload: dict[str, Any]) -> bool:
        return isinstance(payload.get("nodes"), list) and ("policy" in payload or "budget" in payload)

    @staticmethod
    def _default_output_schema_definition(program_id: str) -> dict[str, Any]:
        schema_title = f"{program_id}_output_schema_v1"
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": schema_title,
            "type": "object",
            "required": ["objective", "conclusion", "findings", "evidence_sources", "next_steps"],
            "properties": {
                "objective": {"type": "string"},
                "conclusion": {"type": "string"},
                "findings": {"type": "array", "items": {"type": "string"}},
                "evidence_sources": {"type": "array", "items": {"type": "string"}},
                "next_steps": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": True,
        }

    def _ensure_verify_gate(self, program: ReasoningProgram) -> None:
        verify_nodes = [node.id for node in program.nodes if node.operation_type == "verify"]
        synthesis_nodes = [node for node in program.nodes if node.operation_type == "synthesize"]
        if not synthesis_nodes:
            terminal_nodes = [node for node in program.nodes if not node.next_nodes]
            predecessor_ids = [node.id for node in terminal_nodes] or [program.nodes[-1].id]
            injected_synthesis_id = "final_synthesis"
            synthesis_node = NodeSpec(
                id=injected_synthesis_id,
                title="Final Synthesis",
                subtitle="Produce structured output",
                operation_type="synthesize",
                instruction="Produce the final structured answer and summary for the task.",
                success_criteria=[
                    "Final structured output returned",
                    "Summary prepared for UI review",
                ],
                priority=max(node.priority for node in program.nodes) + 10,
                depends_on=predecessor_ids,
                guarded_by=[],
                next=[],
                metadata={"layout": {"column": 1, "row": len(program.nodes)}},
            )
            for node in program.nodes:
                if node.id in predecessor_ids and injected_synthesis_id not in node.next_nodes:
                    node.next_nodes.append(injected_synthesis_id)
            program.nodes.append(synthesis_node)
            synthesis_nodes = [synthesis_node]

        final_node = synthesis_nodes[-1]
        if not verify_nodes:
            injected_verify_id = "verification_gate"
            predecessor_ids = final_node.depends_on.copy()
            verify_node = NodeSpec(
                id=injected_verify_id,
                title="Verification Gate",
                subtitle="Check evidence sufficiency",
                operation_type="verify",
                instruction="Verify that predecessor outputs are grounded, consistent, and sufficient for final synthesis.",
                success_criteria=[
                    "Verification status returned",
                    "Checks explicitly listed",
                ],
                priority=max(node.priority for node in program.nodes) - 1,
                depends_on=predecessor_ids,
                guarded_by=[],
                next=[final_node.id],
                metadata={"layout": {"column": 2, "row": max(0, len(program.nodes) - 2)}},
            )
            program.nodes.append(verify_node)
            final_node.depends_on = sorted({*final_node.depends_on, injected_verify_id})
            final_node.guarded_by = sorted({*final_node.guarded_by, injected_verify_id})
            for node in program.nodes:
                if node.id in predecessor_ids and final_node.id in node.next_nodes:
                    node.next_nodes = [target for target in node.next_nodes if target != final_node.id]
                    if injected_verify_id not in node.next_nodes:
                        node.next_nodes.append(injected_verify_id)
            return

        if not final_node.guarded_by:
            final_node.guarded_by = [verify_nodes[-1]]
        if verify_nodes[-1] not in final_node.depends_on:
            final_node.depends_on.append(verify_nodes[-1])

    def _normalize_nodes(self, nodes_payload: Any) -> list[dict[str, Any]]:
        if not isinstance(nodes_payload, list):
            return []

        normalized: list[dict[str, Any]] = []
        for index, raw_node in enumerate(nodes_payload):
            if not isinstance(raw_node, dict):
                continue

            raw_title = self._first_string(raw_node, "title", "name", "label", "step")
            node_id = self._slug(raw_node.get("id") or raw_title or f"node_{index + 1}")
            instruction = self._first_string(raw_node, "instruction", "description", "details", "prompt")
            title = raw_title or node_id.replace("_", " ").title()
            subtitle = self._first_string(raw_node, "subtitle", "summary", "purpose")
            operation_type = self._first_string(raw_node, "operation_type", "type", "operation")
            metadata = raw_node.get("metadata") if isinstance(raw_node.get("metadata"), dict) else {}

            row = raw_node.get("row")
            column = raw_node.get("column")
            layout = metadata.get("layout") if isinstance(metadata.get("layout"), dict) else {}
            if isinstance(row, int) and "row" not in layout:
                layout["row"] = row
            if isinstance(column, int) and "column" not in layout:
                layout["column"] = column
            if layout:
                metadata["layout"] = layout

            normalized.append(
                {
                    "id": node_id,
                    "title": title,
                    "subtitle": subtitle or instruction or title,
                    "operation_type": (operation_type or self._infer_operation_type(title, instruction, index, len(nodes_payload))).lower(),
                    "instruction": instruction or f"Execute {title.lower()} for the current reasoning task.",
                    "success_criteria": self._normalize_success_criteria(raw_node.get("success_criteria")),
                    "evaluation_ids": self._normalize_evaluation_ids(raw_node.get("evaluation_ids"), operation_type, title, instruction, index, len(nodes_payload)),
                    "input_schema_id": str(raw_node.get("input_schema_id")) if raw_node.get("input_schema_id") else None,
                    "output_schema_id": str(raw_node.get("output_schema_id")) if raw_node.get("output_schema_id") else None,
                    "priority": self._normalize_priority(raw_node.get("priority"), index),
                    "depends_on": self._normalize_string_list(raw_node.get("depends_on") or raw_node.get("dependencies")),
                    "next": self._normalize_string_list(raw_node.get("next") or raw_node.get("next_nodes")),
                    "guarded_by": self._normalize_string_list(raw_node.get("guarded_by")),
                    "metadata": {
                        **metadata,
                        "estimated_cost": metadata.get("estimated_cost", (index + 1) * 10),
                    },
                }
            )

        return normalized

    @staticmethod
    def _normalize_budget(value: Any, nodes_payload: Any) -> dict[str, int]:
        node_count = len(nodes_payload) if isinstance(nodes_payload, list) else 0
        budget = value if isinstance(value, dict) else {}
        max_nodes = budget.get("max_nodes")
        max_tokens = budget.get("max_tokens")
        max_runtime_seconds = budget.get("max_runtime_seconds")
        return {
            "max_nodes": max(int(max_nodes) if isinstance(max_nodes, int) else 0, node_count + 2, 12),
            "max_tokens": max(int(max_tokens) if isinstance(max_tokens, int) else 0, node_count * 10000, 50000),
            "max_runtime_seconds": max(
                int(max_runtime_seconds) if isinstance(max_runtime_seconds, int) else 0,
                300,
            ),
        }

    def _repair_graph_connectivity(self, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(nodes) < 2:
            return nodes

        inbound_targets = {
            target
            for node in nodes
            for target in [*node.get("depends_on", []), *node.get("guarded_by", [])]
            if isinstance(target, str)
        }

        for index in range(1, len(nodes)):
            previous = nodes[index - 1]
            current = nodes[index]
            previous_id = previous["id"]
            current_id = current["id"]

            if not current["depends_on"] and current_id not in inbound_targets:
                current["depends_on"].append(previous_id)
                inbound_targets.add(current_id)

            if current["operation_type"] == "synthesize" and previous_id not in current["depends_on"]:
                current["depends_on"].append(previous_id)

            for dependency_id in current["depends_on"]:
                source = next((node for node in nodes if node["id"] == dependency_id), None)
                if source is not None and current_id not in source["next"]:
                    source["next"].append(current_id)

        return nodes

    @staticmethod
    def _first_string(payload: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _normalize_priority(value: Any, index: int) -> int:
        if isinstance(value, int):
            return value
        return (index + 1) * 10

    def _normalize_success_criteria(self, value: Any) -> list[str]:
        if isinstance(value, list):
            normalized = [str(item).strip() for item in value if str(item).strip()]
            return normalized or ["Node completed successfully."]
        if isinstance(value, dict):
            normalized = [str(item).strip() for item in value.values() if str(item).strip()]
            return normalized or ["Node completed successfully."]
        if isinstance(value, str) and value.strip():
            parts = [part.strip() for part in re.split(r"[;\n]+", value) if part.strip()]
            return parts or [value.strip()]
        return ["Node completed successfully."]

    def _normalize_evaluation_ids(
        self,
        value: Any,
        operation_type: str,
        title: str,
        instruction: str,
        index: int,
        total_nodes: int,
    ) -> list[str]:
        if isinstance(value, list):
            normalized = [str(item).strip() for item in value if str(item).strip()]
            if normalized:
                return normalized
        resolved_operation = (operation_type or self._infer_operation_type(title, instruction, index, total_nodes)).lower()
        if resolved_operation == "verify":
            return ["verification_gate"]
        evaluation_ids = ["output_present"]
        if resolved_operation == "synthesize":
            evaluation_ids.append("final_output_schema")
        return evaluation_ids

    def _normalize_string_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [self._slug(str(item)) for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [self._slug(part) for part in re.split(r"[,\n]+", value) if part.strip()]
        return []

    @staticmethod
    def _infer_operation_type(title: str, instruction: str, index: int, total_nodes: int) -> str:
        lowered = f"{title} {instruction}".lower()
        if "verify" in lowered or "check" in lowered or "validate" in lowered:
            return "verify"
        if index == total_nodes - 1 or "synth" in lowered or "final" in lowered or "report" in lowered:
            return "synthesize"
        if "aggregate" in lowered or "combine" in lowered:
            return "aggregate"
        if "generate" in lowered or "draft" in lowered or "scope" in lowered:
            return "generate"
        return "analyze"

    @staticmethod
    def _ensure_layout_metadata(program: ReasoningProgram) -> None:
        for index, node in enumerate(program.nodes):
            layout = node.metadata.get("layout", {})
            layout.setdefault("row", index)
            layout.setdefault("column", 1 if index == 0 else min(index % 3, 2))
            node.metadata["layout"] = layout

    def _persist_bundle(self, bundle: SynthesizedProgramBundle) -> None:
        programs_dir = self.generated_root / "programs"
        schemas_dir = self.generated_root / "schemas"
        metadata_dir = self.generated_root / "bundles"
        for directory in (programs_dir, schemas_dir, metadata_dir):
            directory.mkdir(parents=True, exist_ok=True)

        program_path = programs_dir / f"{bundle.program.program_id}.json"
        schema_path = schemas_dir / f"{bundle.program.output_schema}.json"
        bundle_path = metadata_dir / f"{bundle.program.program_id}.json"

        program_path.write_text(
            json.dumps(bundle.program.model_dump(mode="json", by_alias=True), indent=2),
            encoding="utf-8",
        )
        schema_path.write_text(json.dumps(bundle.output_schema_definition, indent=2), encoding="utf-8")
        for schema_id, schema_definition in bundle.node_schema_definitions.items():
            (schemas_dir / f"{schema_id}.json").write_text(json.dumps(schema_definition, indent=2), encoding="utf-8")
        bundle_path.write_text(json.dumps(bundle.model_dump(mode="json"), indent=2), encoding="utf-8")

    @staticmethod
    def _slug(value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
        return cleaned[:40] or "generated_reasoning"

    @staticmethod
    def _infer_domain(value: str) -> str:
        lowered = value.lower()
        if "audit" in lowered:
            return "financial audit"
        if "legal" in lowered:
            return "legal research"
        if "compliance" in lowered:
            return "regulatory compliance"
        if "health" in lowered or "diagnostic" in lowered:
            return "healthcare diagnostics"
        return "general reasoning"
