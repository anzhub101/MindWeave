from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.config import get_settings
from app.models.runtime import (
    ClaimClassification,
    EvidenceReference,
    EvidenceSupportLevel,
    ExecutorType,
    FindingRecord,
    GraphDelta,
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
        agent_spec = node.agent_spec
        effective_instruction = (
            agent_spec.instruction.strip()
            if agent_spec is not None and isinstance(agent_spec.instruction, str) and agent_spec.instruction.strip()
            else node.instruction
        )
        evidence_scope = node.evidence_scope or node.metadata.get("evidence_scope", {})
        evidence_chunks = self.knowledge_base.retrieve(
            f"{state.prompt}\n{node.title}\n{node.subtitle}\n{effective_instruction}",
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
        skill_artifact_id = str(node.metadata.get("skill_artifact_id") or "").strip()
        agent_tools = (
            [tool.model_dump(mode="json") for tool in agent_spec.tools]
            if agent_spec is not None
            else []
        )
        tool_spec = (
            {
                "name": "skill",
                "args": {
                    "skill_artifact_id": skill_artifact_id,
                    "input_payload": {
                        "task_prompt": state.prompt,
                        "node_id": node.id,
                        "node_title": node.title,
                        "node_instruction": effective_instruction,
                        "inputs": node.inputs,
                        "evidence_refs": [reference.model_dump(mode="json") for reference in list(available_evidence.values())[:4]],
                    },
                },
            }
            if skill_artifact_id
            else node.metadata.get("tool") if isinstance(node.metadata.get("tool"), dict) else agent_tools[0] if agent_tools else None
        )
        tool_result = None
        web_fallback_used = False

        if isinstance(tool_spec, dict):
            tool_result = self.tool_runtime.execute(tool_spec, state, node, self.knowledge_base)
            tool_calls.append(tool_result)
            if node.metadata.get("tool_only") or node.executor_type == ExecutorType.tool_operator:
                evidence_refs = list(available_evidence.values())[:3]
                tool_name = str(tool_result.get("tool", node.subtitle))
                return NodeExecutionResult(
                    output={"tool_result": tool_result},
                    evidence_refs=evidence_refs,
                    verification_status=VerificationStatus.skipped,
                    thought_summary=tool_name,
                    reasoning_trace=f"Executed the {tool_name} tool path to anchor evidence and prepare structured inputs for this node.",
                    llm_usage_tokens=0,
                    model_metadata={
                        "provider": "tool_runtime",
                        "executor_type": node.executor_type.value,
                        "executor_profile": node.executor_profile,
                        "agent_spec": agent_spec.model_dump(mode="json") if agent_spec is not None else None,
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

        if self._should_use_web_fallback(evidence_chunks):
            web_result = self.tool_runtime.execute(
                {
                    "name": "web_search",
                    "args": {
                        "query": f"{state.prompt} {node.title} {node.subtitle}".strip(),
                        "top_k": 4,
                    },
                },
                state,
                node,
                self.knowledge_base,
            )
            tool_calls.append(web_result)
            web_refs = self._web_results_to_evidence_refs(web_result.get("results", []))
            if web_refs:
                web_fallback_used = True
                available_evidence.update({reference.id: reference for reference in web_refs})
                evidence_context.extend(self._web_context(reference) for reference in web_refs)
                available_evidence_ids = list(available_evidence.keys())

        prompt = (
            "Execute the current reasoning node and return JSON only.\n"
            "Use only provided evidence identifiers.\n"
            "Ground every substantive claim in the supplied evidence.\n"
            "If a finding is inferred or unsupported, label it explicitly.\n"
            "When dependency outputs contain thought summaries, reasoning traces, or finding records, use them as prior branch context.\n"
            "For aggregate or merge nodes, reconcile substantive dependency findings instead of returning null placeholders when upstream branches contain content.\n"
            'Include a "reasoning" field containing the model rationale used to produce the node output.\n'
            'If the node needs to mutate the downstream runtime graph, include a "graph_delta" object with a summary and patch operations.\n'
        )
        system_prompt = (
            "You are the MindWeave runtime executor. "
            "Produce structured node outputs for a reasoning graph. "
            "Never bypass verification gates or fabricate evidence references."
        )
        if agent_spec is not None and agent_spec.persona.strip():
            system_prompt = f"{system_prompt} Operate as {agent_spec.persona.strip()}."
        context = {
            "user_prompt": state.prompt,
            "domain": state.domain,
            "program_id": state.program_id,
            "node_id": node.id,
            "node_title": node.title,
            "node_subtitle": node.subtitle,
            "operation_type": node.operation_type,
            "node_instruction": effective_instruction,
            "success_criteria": node.success_criteria,
            "executor_type": node.executor_type.value,
            "executor_profile": node.executor_profile,
            "agent_spec": agent_spec.model_dump(mode="json") if agent_spec is not None else None,
            "expansion_contracts": node.expansion_contracts,
            "max_child_agents": node.max_child_agents,
            "max_recursion_depth": node.max_recursion_depth,
            "child_token_budget": node.child_token_budget,
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
            "web_fallback_used": web_fallback_used,
            "tool_result": tool_result,
            "evidence_scope": evidence_scope,
            "control_level": state.control_level.value,
            "determinism_mode": state.determinism_mode.value,
            "is_final_node": is_final_node,
            "delegation_policy": state.delegation_policy.model_dump(mode="json"),
        }
        max_tokens = 3200 if is_final_node else 2000
        if agent_spec is not None and agent_spec.model is not None and isinstance(agent_spec.model.max_tokens, int) and agent_spec.model.max_tokens > 0:
            max_tokens = agent_spec.model.max_tokens
        delegated_token_budget = int(node.metadata.get("delegated_token_budget", 0) or 0)
        if delegated_token_budget > 0:
            max_tokens = min(max_tokens, max(256, delegated_token_budget))
        requested_model_id = (
            agent_spec.model.model_id
            if agent_spec is not None and agent_spec.model is not None and agent_spec.model.model_id
            else state.model_id or None
        )
        requested_model_version = (
            agent_spec.model.model_version
            if agent_spec is not None and agent_spec.model is not None and agent_spec.model.model_version
            else state.model_version or None
        )
        requested_temperature = (
            0.0
            if state.deterministic
            else agent_spec.model.temperature
            if agent_spec is not None and agent_spec.model is not None and agent_spec.model.temperature is not None
            else self.settings.k2_temperature
        )
        response = self.llm_gateway.generate(
            LLMRequest(
                task="node_execution",
                prompt=prompt,
                system_prompt=system_prompt,
                context=context,
                temperature=requested_temperature,
                top_p=1.0 if state.determinism_mode.value != "non_deterministic" else self.settings.k2_top_p,
                seed=(state.program_blueprint or {}).get("deterministic_defaults", {}).get("seed")
                if state.program_blueprint
                else None,
                determinism_mode=state.determinism_mode.value,
                model_id=requested_model_id,
                model_version=requested_model_version,
                agentic=True,
                max_tokens=max_tokens,
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
        reasoning_trace = payload.pop("reasoning", payload.pop("reasoning_trace", None))
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
        if is_final_node and isinstance(final_output, dict):
            final_output = self._ensure_required_final_output_fields(final_output, state.output_schema_definition)

        final_summary = payload.get("final_summary")
        if is_final_node and final_summary is None:
            final_summary = self._build_fallback_summary(state, node, final_output or output)

        graph_delta = self._parse_graph_delta(payload.get("graph_delta"), node)
        spawned_nodes = self._parse_spawned_nodes(state, payload.get("spawned_nodes"), node)

        return NodeExecutionResult(
            output=output if isinstance(output, dict) else {"value": output},
            evidence_refs=evidence_refs,
            verification_status=verification_status,
            verification_checks=verification_checks if isinstance(verification_checks, list) else [],
            thought_summary=str(payload.get("summary", node.subtitle)),
            reasoning_trace=str(reasoning_trace).strip() if isinstance(reasoning_trace, str) and reasoning_trace.strip() else None,
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
                "executor_profile": node.executor_profile,
                "agent_spec": agent_spec.model_dump(mode="json") if agent_spec is not None else None,
                "prompt_hash": prompt_trace.prompt_hash,
                "web_fallback_used": web_fallback_used,
            },
            finding_records=finding_records,
            final_output=final_output if isinstance(final_output, dict) else None,
            final_summary=final_summary if isinstance(final_summary, dict) else None,
            graph_delta=graph_delta,
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
        total_child_token_budget = (
            parent.child_token_budget
            or int(parent.metadata.get("child_token_budget", 0) or 0)
            or state.delegation_policy.default_child_token_budget
        )
        per_child_token_budget = max(
            256,
            int(total_child_token_budget / max(parent.max_child_agents, 1)),
        )
        for index, item in enumerate(payload):
            if not isinstance(item, dict):
                continue
            if parent.max_child_agents and len(spawned) >= parent.max_child_agents:
                break
            child_depth = current_depth + 1
            if parent.max_recursion_depth and child_depth > parent.max_recursion_depth:
                break

            node_id = str(item.get("id") or f"{parent.id}_child_{index + 1}")
            next_nodes = item.get("next_nodes") or item.get("next") or list(parent.next_nodes)
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
                    executor_profile=item.get("executor_profile"),
                    agent_spec=item.get("agent_spec") if isinstance(item.get("agent_spec"), dict) else None,
                    max_child_agents=int(item.get("max_child_agents", 0)),
                    max_recursion_depth=int(item.get("max_recursion_depth", 0)),
                    child_token_budget=0,
                    expansion_contracts=[str(value) for value in item.get("expansion_contracts", [])],
                    delegated_summary_required=state.delegation_policy.require_child_summary,
                    required_approvals=int(item.get("required_approvals", 0)),
                    depends_on=[parent.id],
                    guarded_by=[str(value) for value in item.get("guarded_by", [])],
                    next_nodes=[str(value) for value in next_nodes if str(value).strip()],
                    metadata={
                        **(item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}),
                        "delegation_depth": child_depth,
                        "delegated_from": parent.id,
                        "parent_summary_required": state.delegation_policy.require_child_summary,
                        "delegated_token_budget": per_child_token_budget,
                    },
                    spawned_from=parent.id,
                )
            )
        return spawned

    @staticmethod
    def _parse_graph_delta(payload: Any, parent: GraphNodeState) -> GraphDelta | None:
        if payload is None:
            return None
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump(mode="json")
        if isinstance(payload, list):
            payload = {"operations": payload}
        if not isinstance(payload, dict):
            return None

        operations = payload.get("operations", payload.get("patches"))
        if not isinstance(operations, list):
            return None

        normalized_operations: list[dict[str, Any]] = []
        for item in operations:
            if not isinstance(item, dict):
                continue
            patch_type = str(item.get("patch_type") or "").strip()
            if not patch_type:
                continue
            normalized_operations.append(
                {
                    "patch_type": patch_type,
                    "target_node_id": str(item.get("target_node_id")).strip() if item.get("target_node_id") else None,
                    "change_reason": str(item.get("change_reason") or f"Runtime graph delta requested by {parent.id}.").strip(),
                    "payload": item.get("payload", {}) if isinstance(item.get("payload"), dict) else {},
                    "auto_rerun": bool(item.get("auto_rerun", False)),
                }
            )

        if not normalized_operations:
            return None

        return GraphDelta.model_validate(
            {
                "delta_id": payload.get("delta_id"),
                "source_node_id": str(payload.get("source_node_id") or parent.id),
                "summary": str(payload.get("summary") or f"Runtime graph delta proposed by {parent.id}.").strip(),
                "operations": normalized_operations,
            }
        )

    @staticmethod
    def _extract_structured_output(payload: dict[str, Any], raw_content: str) -> dict[str, Any]:
        reserved = {
            "summary",
            "reasoning",
            "reasoning_trace",
            "evidence_ids",
            "verification_status",
            "verification_checks",
            "final_output",
            "final_summary",
            "finding_records",
            "graph_delta",
            "spawned_nodes",
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
    def _web_context(reference: EvidenceReference) -> dict[str, Any]:
        return {
            "document_id": reference.document_id,
            "document_name": reference.document_name,
            "chunk_id": reference.chunk_id,
            "page": reference.page,
            "char_start": reference.char_start,
            "char_end": reference.char_end,
            "retrieval_score": reference.retrieval_score,
            "text": reference.text_excerpt,
            "url": reference.metadata.get("url"),
            "source_type": reference.source_type,
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
    def _web_results_to_evidence_refs(values: Any) -> list[EvidenceReference]:
        if not isinstance(values, list):
            return []
        references: list[EvidenceReference] = []
        for index, item in enumerate(values):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or url or f"Web result {index + 1}")
            snippet = str(item.get("snippet") or item.get("description") or "").strip()
            if not url and not snippet:
                continue
            references.append(
                EvidenceReference(
                    id=str(item.get("result_id") or item.get("id") or url or f"web_result_{index}"),
                    document_id=url or f"web_result_{index}",
                    document_name=title,
                    chunk_id=str(item.get("result_id") or item.get("id") or f"web_result_{index}"),
                    retrieval_score=item.get("score") if isinstance(item.get("score"), (int, float)) else None,
                    support_level=EvidenceSupportLevel.direct,
                    citation_mode="web_search",
                    source_type="web_search",
                    text_excerpt=snippet[:280],
                    metadata={"url": url, "provider": item.get("provider", "web_search")},
                )
            )
        return references

    def _should_use_web_fallback(self, evidence_chunks: list[KnowledgeChunk]) -> bool:
        if not self.settings.web_search_enabled:
            return False
        if not self.documents:
            return True
        return not evidence_chunks

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
                claim_classification = self._normalize_claim_classification(
                    item.get("claim_classification"),
                    support_level=support_level,
                    node=node,
                    text=str(item.get("text") or item.get("summary") or ""),
                )
                records.append(
                    FindingRecord(
                        id=str(item.get("id") or f"{node.id}_finding_{index + 1}"),
                        text=str(item.get("text") or item.get("summary") or ""),
                        support_level=support_level,
                        claim_classification=claim_classification,
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
                        claim_classification=self._normalize_claim_classification(
                            None,
                            support_level=EvidenceSupportLevel.direct if evidence_refs else EvidenceSupportLevel.inferred,
                            node=node,
                            text=finding.strip(),
                        ),
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
                claim_classification=GenericReasoningOperator._normalize_claim_classification(
                    None,
                    support_level=support_level,
                    node=node,
                    text=text,
                ),
                evidence_refs=evidence_refs,
            )
        ]

    @staticmethod
    def _normalize_claim_classification(
        raw_value: Any,
        support_level: Any,
        node: GraphNodeState,
        text: str,
    ) -> ClaimClassification:
        if raw_value in {classification.value for classification in ClaimClassification}:
            return ClaimClassification(raw_value)

        normalized_support = getattr(support_level, "value", str(support_level or ""))
        if normalized_support == EvidenceSupportLevel.user_provided.value:
            return ClaimClassification.human_entered
        if normalized_support in {
            EvidenceSupportLevel.inferred.value,
            EvidenceSupportLevel.unsupported.value,
        }:
            return ClaimClassification.inferred
        if node.operation_type in {"aggregate", "analyze"} and any(character.isdigit() for character in text):
            return ClaimClassification.calculated
        return ClaimClassification.grounded

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
                claim_classification=self._normalize_claim_classification(
                    None,
                    support_level=EvidenceSupportLevel.direct if evidence_refs else EvidenceSupportLevel.inferred,
                    node=node,
                    text=finding,
                ),
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
    def _ensure_required_final_output_fields(
        final_output: dict[str, Any],
        schema_definition: dict[str, Any] | None,
    ) -> dict[str, Any]:
        schema = schema_definition if isinstance(schema_definition, dict) else {}
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required_fields = schema.get("required") if isinstance(schema.get("required"), list) else []
        normalized = dict(final_output)
        for field_name in required_fields:
            if field_name in normalized:
                continue
            field_schema = properties.get(field_name) if isinstance(properties, dict) else {}
            field_type = field_schema.get("type") if isinstance(field_schema, dict) else None
            if field_type == "array":
                normalized[field_name] = []
            elif field_type == "object":
                normalized[field_name] = {}
            else:
                normalized[field_name] = ""
        return normalized

    @staticmethod
    def _delegation_allowed(state: GraphReasoningState, parent: GraphNodeState) -> bool:
        if not state.delegation_policy.enabled:
            return False
        if state.control_level not in state.delegation_policy.allowed_control_levels:
            return False
        if parent.executor_type != ExecutorType.agent_operator:
            return False
        if parent.max_child_agents <= 0:
            return False
        child_budget = parent.child_token_budget or state.delegation_policy.default_child_token_budget
        if child_budget <= 0:
            return False
        if state.budget_usage.nodes_created >= state.budget_spec.max_nodes:
            return False
        policy = (state.program_blueprint or {}).get("policy", "priority_based")
        if policy not in state.delegation_policy.allowed_program_policies:
            return False
        if parent.metadata.get("delegation_requested") is True:
            return True
        complexity_score = float(parent.metadata.get("complexity_score", 0))
        threshold = float(parent.metadata.get("delegation_threshold", state.delegation_policy.complexity_threshold))
        return complexity_score >= threshold
