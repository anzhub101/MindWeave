from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.config import get_settings
from app.models.runtime import (
    EvidenceReference,
    EvidenceSupportLevel,
    ExecutorType,
    FindingRecord,
    GraphNodeState,
    GraphReasoningState,
    NodeExecutionResult,
    VerificationStatus,
)
from app.services.json_utils import extract_json_object
from app.services.knowledge_base import KnowledgeBase, KnowledgeChunk
from app.services.llm_gateway import LLMGateway, LLMRequest
from app.services.runtime_metadata import trace_from_request_response
from app.services.tool_runtime import ToolRuntime


class GenericReasoningOperator:
    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        llm_gateway: LLMGateway,
        tool_runtime: ToolRuntime | None = None,
    ) -> None:
        self.settings = get_settings()
        self.knowledge_base = knowledge_base
        self.llm_gateway = llm_gateway
        self.tool_runtime = tool_runtime or ToolRuntime()
        self.documents = knowledge_base.documents

    def execute(self, state: GraphReasoningState, node: GraphNodeState) -> NodeExecutionResult:
        evidence_scope = node.evidence_scope or node.metadata.get("evidence_scope", {})
        evidence_chunks = self.knowledge_base.retrieve(
            f"{state.prompt}\n{node.title}\n{node.subtitle}\n{node.instruction}",
            top_k=4,
            evidence_scope=evidence_scope,
        )
        available_evidence = {
            chunk.id: self._chunk_to_evidence_reference(chunk)
            for chunk in evidence_chunks
        }
        evidence_context = [self._chunk_context(chunk) for chunk in evidence_chunks]
        available_evidence_ids = list(available_evidence.keys())
        is_final_node = node.operation_type == "synthesize" or not node.next_nodes
        node_schema_definitions = (
            (state.program_blueprint or {}).get("metadata", {}).get("node_schema_definitions", {})
            if isinstance((state.program_blueprint or {}).get("metadata", {}), dict)
            else {}
        )
        tool_calls: list[dict[str, Any]] = []
        tool_spec = node.metadata.get("tool")
        tool_result = None

        if isinstance(tool_spec, dict):
            tool_result = self.tool_runtime.execute(tool_spec, state, node, self.knowledge_base)
            tool_calls.append(tool_result)
            if node.metadata.get("tool_only") or node.executor_type == ExecutorType.tool_operator:
                evidence_refs = list(available_evidence.values())[:3]
                return NodeExecutionResult(
                    output={"tool_result": tool_result},
                    evidence_refs=evidence_refs,
                    verification_status=VerificationStatus.skipped,
                    thought_summary=str(tool_result.get("tool", node.subtitle)),
                    llm_usage_tokens=0,
                    model_metadata={
                        "provider": "tool_runtime",
                        "executor_type": node.executor_type.value,
                    },
                    finding_records=self._default_finding_records(node, evidence_refs),
                    final_output=self._build_fallback_final_output(state, node, {"tool_result": tool_result}, evidence_refs)
                    if is_final_node
                    else None,
                    final_summary=self._build_fallback_summary(state, node, {"tool_result": tool_result})
                    if is_final_node
                    else None,
                    tool_calls=tool_calls,
                )

        prompt = (
            "Execute the current reasoning node and return JSON only.\n"
            "Use only provided evidence identifiers.\n"
            "Ground every substantive claim in the supplied evidence.\n"
            "If a finding is inferred or unsupported, label it explicitly.\n"
        )
        system_prompt = (
            "You are the MindWeave runtime executor. "
            "Produce structured node outputs for a reasoning graph. "
            "Never bypass verification gates or fabricate evidence references."
        )
        context = {
            "user_prompt": state.prompt,
            "domain": state.domain,
            "program_id": state.program_id,
            "node_count": len(state.nodes),
            "node_id": node.id,
            "node_title": node.title,
            "node_subtitle": node.subtitle,
            "operation_type": node.operation_type,
            "node_instruction": node.instruction,
            "success_criteria": node.success_criteria,
            "executor_type": node.executor_type.value,
            "expansion_contracts": node.expansion_contracts,
            "max_child_agents": node.max_child_agents,
            "max_recursion_depth": node.max_recursion_depth,
            "input_schema_definition": node_schema_definitions.get(node.input_schema_id or "", {}),
            "output_schema_definition": (
                state.output_schema_definition
                if is_final_node
                else node_schema_definitions.get(node.output_schema_id or "", {})
            ),
            "dependency_outputs": node.inputs,
            "available_evidence_ids": available_evidence_ids,
            "available_document_ids": sorted({reference.document_id for reference in available_evidence.values()}),
            "retrieved_evidence": evidence_context,
            "tool_result": tool_result,
            "evidence_scope": evidence_scope,
            "control_level": state.control_level.value,
            "determinism_mode": state.determinism_mode.value,
            "is_final_node": is_final_node,
        }
        response = self.llm_gateway.generate(
            LLMRequest(
                task="node_execution",
                prompt=prompt,
                system_prompt=system_prompt,
                context=context,
                temperature=0.0 if state.deterministic else self.settings.k2_temperature,
                top_p=1.0 if state.determinism_mode.value != "non_deterministic" else self.settings.k2_top_p,
                seed=(state.program_blueprint or {}).get("deterministic_defaults", {}).get("seed")
                if state.program_blueprint
                else None,
                determinism_mode=state.determinism_mode.value,
                model_id=state.model_id or None,
                model_version=state.model_version or None,
                agentic=True,
                max_tokens=3200 if is_final_node else 2000,
            )
        )

        prompt_trace = trace_from_request_response(
            trace_id=f"{state.task_id}:{node.id}:{uuid4().hex[:8]}",
            phase="node_execution",
            node_id=node.id,
            prompt=prompt,
            system_prompt=system_prompt,
            context=context,
            params=response.request_params,
            provider=response.provider,
            model_id=response.model,
            model_version=response.model_version or response.model,
            provider_fingerprint=response.provider_fingerprint,
            endpoint=response.endpoint,
            request_payload=response.request_payload,
            response_payload=response.raw,
        )

        payload = self._load_payload(response.content)
        evidence_refs = self._normalize_evidence_refs(payload.get("evidence_ids", []), available_evidence)
        verification_status = self._normalize_verification_status(payload.get("verification_status"))
        if node.operation_type == "verify" and verification_status == VerificationStatus.skipped:
            verification_status = VerificationStatus.passed
        verification_checks = payload.get("verification_checks", [])
        output = payload.get("output")
        if not isinstance(output, dict) or not output:
            output = self._extract_structured_output(payload, response.content)

        finding_records = self._normalize_finding_records(
            payload.get("finding_records"),
            output,
            evidence_refs,
            node,
        )

        final_output = payload.get("final_output")
        if is_final_node and (not isinstance(final_output, dict) or not final_output):
            final_output = output
        if is_final_node and (not isinstance(final_output, dict) or not final_output):
            final_output = self._build_fallback_final_output(state, node, output if isinstance(output, dict) else {}, evidence_refs)
        if is_final_node and isinstance(final_output, dict) and "finding_records" not in final_output:
            final_output["finding_records"] = [record.model_dump(mode="json") for record in finding_records]

        final_summary = payload.get("final_summary")
        if is_final_node and final_summary is None:
            final_summary = self._build_fallback_summary(state, node, final_output or output)

        spawned_nodes = self._parse_spawned_nodes(state, payload.get("spawned_nodes"), node)

        return NodeExecutionResult(
            output=output if isinstance(output, dict) else {"value": output},
            evidence_refs=evidence_refs,
            verification_status=verification_status,
            verification_checks=verification_checks if isinstance(verification_checks, list) else [],
            thought_summary=str(payload.get("summary", node.subtitle)),
            llm_usage_tokens=response.prompt_tokens + response.completion_tokens,
            prompt_trace=prompt_trace,
            model_metadata={
                "provider": response.provider,
                "model_id": response.model,
                "model_version": response.model_version or response.model,
                "provider_fingerprint": response.provider_fingerprint,
                "endpoint": response.endpoint,
                "request_params": response.request_params,
                "executor_type": node.executor_type.value,
            },
            finding_records=finding_records,
            final_output=final_output if isinstance(final_output, dict) else None,
            final_summary=final_summary if isinstance(final_summary, dict) else None,
            spawned_nodes=spawned_nodes,
            tool_calls=tool_calls,
        )

    def _load_payload(self, content: str) -> dict[str, Any]:
        try:
            return extract_json_object(content)
        except Exception:
            try:
                repair = self.llm_gateway.generate(
                    LLMRequest(
                        task="json_repair",
                        prompt=(
                            "Convert the provided content into a single strict JSON object only. "
                            "Use double-quoted keys, no markdown fences, no comments, and no trailing commas."
                        ),
                        context={"raw_text": content},
                        temperature=self.settings.k2_temperature,
                        determinism_mode="best_effort_deterministic",
                        agentic=False,
                        max_tokens=2400,
                    )
                )
                return extract_json_object(repair.content)
            except Exception:
                return {"raw_response": content.strip()}

    def _parse_spawned_nodes(
        self,
        state: GraphReasoningState,
        payload: Any,
        parent: GraphNodeState,
    ) -> list[GraphNodeState]:
        if not isinstance(payload, list) or not self._delegation_allowed(state, parent):
            return []

        spawned: list[GraphNodeState] = []
        current_depth = int(parent.metadata.get("delegation_depth", 0))
        for index, item in enumerate(payload):
            if not isinstance(item, dict):
                continue
            if parent.max_child_agents and len(spawned) >= parent.max_child_agents:
                break
            child_depth = current_depth + 1
            if parent.max_recursion_depth and child_depth > parent.max_recursion_depth:
                break

            node_id = str(item.get("id") or f"{parent.id}_child_{index + 1}")
            next_nodes = item.get("next_nodes") or item.get("next") or []
            spawned.append(
                GraphNodeState(
                    id=node_id,
                    title=str(item.get("title") or node_id.replace("_", " ").title()),
                    subtitle=str(item.get("subtitle") or "Spawned reasoning step"),
                    operation_type=str(item.get("operation_type") or "analyze"),
                    instruction=str(item.get("instruction") or "Analyze spawned branch and summarize back into the parent node."),
                    success_criteria=[str(value) for value in item.get("success_criteria", [])],
                    evaluation_ids=[str(value) for value in item.get("evaluation_ids", [])],
                    priority=int(item.get("priority", parent.priority + 5)),
                    executor_type=item.get("executor_type") or ExecutorType.llm_operator,
                    max_child_agents=int(item.get("max_child_agents", 0)),
                    max_recursion_depth=int(item.get("max_recursion_depth", 0)),
                    expansion_contracts=[str(value) for value in item.get("expansion_contracts", [])],
                    required_approvals=int(item.get("required_approvals", 0)),
                    depends_on=[parent.id],
                    guarded_by=[str(value) for value in item.get("guarded_by", [])],
                    next_nodes=[str(value) for value in next_nodes if str(value).strip()],
                    metadata={
                        **(item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}),
                        "delegation_depth": child_depth,
                        "delegated_from": parent.id,
                        "parent_summary_required": True,
                    },
                    spawned_from=parent.id,
                )
            )
        return spawned

    @staticmethod
    def _extract_structured_output(payload: dict[str, Any], raw_content: str) -> dict[str, Any]:
        reserved = {
            "summary",
            "evidence_ids",
            "verification_status",
            "verification_checks",
            "final_output",
            "final_summary",
            "finding_records",
        }
        structured = {
            key: value
            for key, value in payload.items()
            if key not in reserved and value not in (None, "", [], {})
        }
        if structured:
            return structured
        if raw_content.strip():
            return {"raw_response": raw_content.strip()}
        return {}

    @staticmethod
    def _chunk_context(chunk: KnowledgeChunk) -> dict[str, Any]:
        return {
            "document_id": chunk.document_id,
            "document_name": chunk.document_name,
            "chunk_id": chunk.id,
            "page": chunk.page,
            "char_start": chunk.char_start,
            "char_end": chunk.char_end,
            "retrieval_score": chunk.retrieval_score,
            "text": chunk.text,
        }

    @staticmethod
    def _chunk_to_evidence_reference(chunk: KnowledgeChunk) -> EvidenceReference:
        return EvidenceReference(
            id=chunk.id,
            document_id=chunk.document_id,
            document_name=chunk.document_name,
            chunk_id=chunk.id,
            page=chunk.page,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            retrieval_score=chunk.retrieval_score,
            support_level=EvidenceSupportLevel.direct,
            citation_mode="direct",
            source_type=chunk.source_type,
            text_excerpt=chunk.text[:280],
        )

    @staticmethod
    def _normalize_evidence_refs(values: Any, available_map: dict[str, EvidenceReference]) -> list[EvidenceReference]:
        if not isinstance(values, list):
            return list(available_map.values())[:3]

        normalized: list[EvidenceReference] = []
        for value in values:
            if isinstance(value, str) and value in available_map:
                normalized.append(available_map[value])
            elif isinstance(value, dict):
                evidence_id = str(value.get("chunk_id") or value.get("id") or "")
                support_level = value.get("support_level") or "direct"
                if evidence_id and evidence_id in available_map:
                    reference = available_map[evidence_id].model_copy(
                        update={
                            "support_level": support_level,
                            "citation_mode": value.get("citation_mode", "direct"),
                        }
                    )
                    normalized.append(reference)
        return normalized or list(available_map.values())[:3]

    def _normalize_finding_records(
        self,
        raw_records: Any,
        output: dict[str, Any],
        evidence_refs: list[EvidenceReference],
        node: GraphNodeState,
    ) -> list[FindingRecord]:
        records: list[FindingRecord] = []
        if isinstance(raw_records, list):
            for index, item in enumerate(raw_records):
                if not isinstance(item, dict):
                    continue
                linked_refs = [EvidenceReference.model_validate(reference) for reference in item.get("evidence_refs", [])]
                support_level = item.get("support_level") or (
                    EvidenceSupportLevel.direct.value if linked_refs else EvidenceSupportLevel.inferred.value
                )
                records.append(
                    FindingRecord(
                        id=str(item.get("id") or f"{node.id}_finding_{index + 1}"),
                        text=str(item.get("text") or item.get("summary") or ""),
                        support_level=support_level,
                        evidence_refs=linked_refs,
                    )
                )
        if records:
            return records

        findings = output.get("findings", [])
        if isinstance(findings, list) and findings:
            for index, finding in enumerate(findings):
                if not isinstance(finding, str) or not finding.strip():
                    continue
                records.append(
                    FindingRecord(
                        id=f"{node.id}_finding_{index + 1}",
                        text=finding.strip(),
                        support_level=EvidenceSupportLevel.direct if evidence_refs else EvidenceSupportLevel.inferred,
                        evidence_refs=evidence_refs,
                    )
                )
        if records:
            return records

        return self._default_finding_records(node, evidence_refs)

    @staticmethod
    def _default_finding_records(
        node: GraphNodeState,
        evidence_refs: list[EvidenceReference],
    ) -> list[FindingRecord]:
        support_level = EvidenceSupportLevel.direct if evidence_refs else EvidenceSupportLevel.unsupported
        text = node.subtitle if node.subtitle.strip() else node.title
        return [
            FindingRecord(
                id=f"{node.id}_finding_1",
                text=text,
                support_level=support_level,
                evidence_refs=evidence_refs,
            )
        ]

    @staticmethod
    def _normalize_verification_status(value: Any) -> VerificationStatus:
        if value == "passed":
            return VerificationStatus.passed
        if value == "failed":
            return VerificationStatus.failed
        return VerificationStatus.skipped

    @staticmethod
    def _build_fallback_summary(
        state: GraphReasoningState,
        node: GraphNodeState,
        final_output: dict[str, Any],
    ) -> dict[str, Any]:
        top_keys = list(final_output.keys())[:3]
        return {
            "headline": node.title,
            "verdict": state.domain.title(),
            "key_points": [f"Structured output produced with keys: {', '.join(top_keys)}."],
            "metrics": [
                {"label": "Program", "value": state.program_id},
                {"label": "Documents", "value": str(len(state.source_documents))},
            ],
        }

    def _build_fallback_final_output(
        self,
        state: GraphReasoningState,
        node: GraphNodeState,
        output: dict[str, Any],
        evidence_refs: list[EvidenceReference],
    ) -> dict[str, Any]:
        supporting_findings = [
            thought.summary
            for thought in state.thoughts.values()
            if thought.node_id != node.id and thought.summary
        ]
        findings = supporting_findings[-3:] or [node.subtitle]
        conclusion = "Structured reasoning completed. Review the supporting node outputs for full traceability."
        if output:
            conclusion = f"{conclusion} Captured fields: {', '.join(list(output.keys())[:4])}."
        finding_records = [
            FindingRecord(
                id=f"{node.id}_finding_{index + 1}",
                text=finding,
                support_level=EvidenceSupportLevel.direct if evidence_refs else EvidenceSupportLevel.inferred,
                evidence_refs=evidence_refs,
            )
            for index, finding in enumerate(findings)
        ]
        return {
            "objective": state.prompt,
            "conclusion": conclusion,
            "findings": findings,
            "finding_records": [record.model_dump(mode="json") for record in finding_records],
            "evidence_sources": [reference.document_id for reference in evidence_refs] or [document.id for document in state.source_documents[:5]],
            "next_steps": [
                "Review the verification node and linked evidence.",
                "Confirm the final conclusion before external distribution.",
            ],
        }

    @staticmethod
    def _delegation_allowed(state: GraphReasoningState, parent: GraphNodeState) -> bool:
        if parent.executor_type != ExecutorType.agent_operator:
            return False
        if parent.max_child_agents <= 0:
            return False
        if state.budget_usage.nodes_created >= state.budget_spec.max_nodes:
            return False
        if parent.metadata.get("delegation_requested") is True:
            return True
        complexity_score = float(parent.metadata.get("complexity_score", 0))
        threshold = float(parent.metadata.get("delegation_threshold", 8))
        policy = (state.program_blueprint or {}).get("policy", "priority_based")
        return complexity_score >= threshold and policy in {"priority_based", "breadth_first", "cost_aware"}
