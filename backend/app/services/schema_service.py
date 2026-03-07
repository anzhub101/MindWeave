from __future__ import annotations

from typing import Any

from jsonschema import ValidationError, validate

from app.models.artifacts import RegistryArtifact, SynthesizedProgramBundle
from app.models.runtime import GraphNodeState, GraphReasoningState, NodeExecutionResult, SchemaValidationLogEntry


class SchemaService:
    def __init__(self, registry=None) -> None:
        self.registry = registry

    def attach_generated_node_schemas(self, bundle: SynthesizedProgramBundle) -> SynthesizedProgramBundle:
        schema_definitions = dict(bundle.node_schema_definitions)
        schema_bindings: dict[str, dict[str, str]] = {}

        for node in bundle.program.nodes:
            input_schema_id = node.input_schema_id or f"{bundle.program.program_id}_{node.id}_input_v1"
            output_schema_id = node.output_schema_id or f"{bundle.program.program_id}_{node.id}_output_v1"
            node.input_schema_id = input_schema_id
            node.output_schema_id = output_schema_id
            schema_definitions[input_schema_id] = self._build_input_schema(node)
            schema_definitions[output_schema_id] = self._build_output_schema(node, bundle.output_schema_definition)
            schema_bindings[node.id] = {
                "input_schema_id": input_schema_id,
                "output_schema_id": output_schema_id,
            }

        bundle.node_schema_definitions = schema_definitions
        bundle.program.metadata.setdefault("node_schema_registry", schema_bindings)
        bundle.program.metadata.setdefault("node_schema_definitions", schema_definitions)
        return bundle

    def register_bundle_schemas(self, bundle: SynthesizedProgramBundle) -> list[RegistryArtifact]:
        if self.registry is None:
            return []

        artifacts: list[RegistryArtifact] = []
        output_schema_id = bundle.program.output_schema
        artifacts.append(
            self.registry.upsert(
                RegistryArtifact(
                    kind="schema",
                    artifact_id=output_schema_id,
                    version=bundle.program.version,
                    name=output_schema_id,
                    description=f"Program output schema for {bundle.program.program_id}.",
                    payload=bundle.output_schema_definition,
                    source="generated",
                )
            )
        )
        for schema_id, schema_definition in bundle.node_schema_definitions.items():
            phase = "input" if schema_id.endswith("_input_v1") else "output"
            artifacts.append(
                self.registry.upsert(
                    RegistryArtifact(
                        kind="schema",
                        artifact_id=schema_id,
                        version=bundle.program.version,
                        name=schema_id,
                        description=f"Node {phase} schema for {bundle.program.program_id}.",
                        payload=schema_definition,
                        source="generated",
                    )
                )
            )
        return artifacts

    def validate_node_inputs(
        self,
        state: GraphReasoningState,
        node: GraphNodeState,
    ) -> SchemaValidationLogEntry | None:
        if not node.input_schema_id:
            return None
        return self._validate_payload(node.id, node.input_schema_id, "input", node.inputs)

    def validate_node_output(
        self,
        state: GraphReasoningState,
        node: GraphNodeState,
        result: NodeExecutionResult,
    ) -> SchemaValidationLogEntry | None:
        schema_id = node.output_schema_id or (state.output_schema_definition and state.program_id)
        if not schema_id:
            return None
        payload = result.final_output if node.operation_type == "synthesize" and result.final_output else result.output
        return self._validate_payload(node.id, schema_id, "output", payload)

    def _validate_payload(
        self,
        node_id: str,
        schema_id: str,
        phase: str,
        payload: dict[str, Any],
    ) -> SchemaValidationLogEntry:
        schema = self._load_schema(schema_id)
        try:
            validate(instance=payload, schema=schema)
            return SchemaValidationLogEntry(
                node_id=node_id,
                schema_id=schema_id,
                phase=phase,
                passed=True,
                message=f"{phase.title()} payload satisfied schema {schema_id}.",
            )
        except ValidationError as exc:
            return SchemaValidationLogEntry(
                node_id=node_id,
                schema_id=schema_id,
                phase=phase,
                passed=False,
                message=str(exc.message),
                details={"path": [str(item) for item in exc.path]},
            )

    def _load_schema(self, schema_id: str) -> dict[str, Any]:
        if self.registry is None:
            return {"type": "object"}
        artifact = self.registry.get("schema", schema_id)
        return artifact.payload

    @staticmethod
    def _build_input_schema(node: GraphNodeState | Any) -> dict[str, Any]:
        properties = {dependency_id: {"type": "object"} for dependency_id in getattr(node, "depends_on", [])}
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": f"{getattr(node, 'id', 'node')}_input_schema",
            "type": "object",
            "properties": properties,
            "required": list(properties.keys()),
            "additionalProperties": False,
        }

    @staticmethod
    def _build_output_schema(node: GraphNodeState | Any, final_output_schema: dict[str, Any]) -> dict[str, Any]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": f"{getattr(node, 'id', 'node')}_output_schema",
            "type": "object",
            "minProperties": 1,
            "additionalProperties": True,
        }
