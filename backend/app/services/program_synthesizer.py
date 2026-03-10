from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.models.artifacts import AgentSpec, NodeSpec, ReasoningProgram, SynthesizedProgramBundle
from app.models.runtime import (
    DocumentRecord,
    ControlLevel,
    PlannerCandidateOperation,
    PlannerEvidenceSource,
    PlannerNodeDecision,
    PlannerTrace,
    PromptTrace,
)
from app.services.json_utils import extract_json_object
from app.services.llm_gateway import LLMGateway, LLMRequest, MockProvider
from app.services.requirements_reference import RequirementsReference
from app.services.runtime_metadata import trace_from_request_response
from app.services.schema_service import SchemaService
from app.services.web_search_service import WebSearchResult, WebSearchService


class TaskSynthesisProfile(BaseModel):
    task_type: str
    problem_decomposition: list[str] = Field(default_factory=list)
    available_evidence_mode: str = "none"
    evidence_source_count: int = 0
    risk_profile: str = "standard"
    control_level: str = ControlLevel.operational.value
    required_output_sections: list[str] = Field(default_factory=list)
    requires_branching: bool = False
    requires_verification: bool = True
    requires_tools: bool = False
    requires_delegation: bool = False
    recommended_policy: str = "priority_based"
    branch_focuses: list[str] = Field(default_factory=list)
    suggested_budget: dict[str, int] = Field(default_factory=dict)
    summary: str = ""


class ProgramSynthesisService:
    def __init__(self, llm_gateway: LLMGateway) -> None:
        self.llm_gateway = llm_gateway
        self.settings = get_settings()
        self.reference = RequirementsReference(self.settings.requirements_markdown_path)
        self.generated_root = self.settings.generated_artifact_root
        self.schema_service = SchemaService()
        self.last_prompt_trace: PromptTrace | None = None
        self.last_provider_metadata: dict[str, Any] = {}
        self.last_planner_trace: PlannerTrace | None = None

    def synthesize(
        self,
        user_prompt: str,
        documents: list[DocumentRecord] | None = None,
        deterministic: bool = False,
        determinism_mode: str | None = None,
        control_level: str = ControlLevel.operational.value,
    ) -> SynthesizedProgramBundle:
        requirements_text = self.reference.read()
        self.last_planner_trace = None
        determinism_mode = determinism_mode or ("best_effort_deterministic" if deterministic else "non_deterministic")
        planner_sources = self._planner_sources_from_documents(documents or [])
        web_fallback_results: list[WebSearchResult] = []
        web_fallback_used = False
        attempted_web_queries: list[str] = []
        if not planner_sources and self.settings.web_search_enabled:
            attempted_web_queries = [user_prompt]
            web_fallback_results = WebSearchService().search(user_prompt, top_k=min(self.settings.web_search_top_k, 4))
            planner_sources = self._planner_sources_from_web_results(web_fallback_results)
            web_fallback_used = bool(web_fallback_results)
        task_profile = self._build_task_profile(
            user_prompt=user_prompt,
            documents=documents or [],
            planner_sources=planner_sources,
            web_fallback_used=web_fallback_used,
            control_level=control_level,
        )
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
            "7. planner_trace\n\n"
            "Constraints:\n"
            "- The system must remain domain-agnostic. Only specialize to the user's domain because the prompt requires it.\n"
            "- Use only node operation types: generate, analyze, aggregate, verify, synthesize.\n"
            "- Include at least one verify node before the final synthesis node.\n"
            "- Make graph shape depend on task type, problem decomposition, evidence availability, control level, required output structure, and whether the task needs branching, tools, or delegation.\n"
            "- The model must decide node formation and per-node execution assignment. For each node, explicitly choose executor_type, optional executor_profile, and required_approvals based on the task and control level.\n"
            "- When a node benefits from a bespoke persona, tool subset, or model override, include agent_spec with instruction, context, tools, and model fields.\n"
            "- Use executor_type values only from: llm_operator, tool_operator, agent_operator, human_operator.\n"
            "- Assign human_operator or required_approvals only when a human checkpoint is justified by the control level or task risk.\n"
            "- Assign agent_operator only when deeper delegated exploration is justified, and include max_child_agents, max_recursion_depth, child_token_budget, and delegated_summary_required when you do.\n"
            "- If a node needs web search or tool use, choose tool_operator and encode the tool in node.metadata.tool.\n"
            "- Provide node instructions and success_criteria for each node.\n"
            "- Provide layout metadata with row and column for the UI.\n"
            "- The output_schema_definition must be valid JSON Schema.\n"
            "- Program IDs and node IDs must use snake_case.\n"
            "- Budget values should be realistic for an MVP.\n"
            "- The final schema should be suitable for structured output and audit export.\n"
            "- planner_trace must be a structured planning summary, not hidden chain-of-thought.\n"
            "- planner_trace must explain graph shape, candidate operations considered, node add/merge/branch decisions, available evidence sources, confidence, unresolved gaps, and whether web fallback was used.\n"
            "- Return strict JSON, no commentary.\n"
        )
        if deterministic and determinism_mode == "strict_deterministic":
            bundle = self._normalize_bundle(
                self._fallback_payload(user_prompt, requirements_text, task_profile),
                user_prompt,
                task_profile,
                prefer_model_graph=False,
            )
            self.last_planner_trace = self._normalize_planner_trace(
                bundle.program.metadata.get("planner_trace"),
                bundle,
                user_prompt,
                task_profile,
                planner_sources,
                web_fallback_used,
                web_fallback_results,
                attempted_web_queries,
            )
            bundle.program.metadata["planner_trace"] = self.last_planner_trace.model_dump(mode="json")
            bundle = self.schema_service.attach_generated_node_schemas(bundle)
            provider_metadata = self.llm_gateway.describe_provider(determinism_mode)
            self.last_provider_metadata = provider_metadata
            self.last_prompt_trace = trace_from_request_response(
                trace_id=f"synthesis:{uuid4().hex[:8]}",
                phase="program_synthesis",
                node_id=None,
                prompt=prompt,
                system_prompt=system_prompt,
                context={
                    "user_prompt": user_prompt,
                    "requirements_reference_markdown": requirements_text,
                    "task_synthesis_profile": task_profile.model_dump(mode="json"),
                    "available_evidence_sources": [source.model_dump(mode="json") for source in planner_sources],
                    "web_fallback_used": web_fallback_used,
                    "web_search_results": [result.model_dump(mode="json") for result in web_fallback_results],
                },
                params={
                    "temperature": 0.0,
                    "top_p": 1.0,
                    "seed": self.settings.deterministic_seed,
                    "determinism_mode": determinism_mode,
                },
                provider=provider_metadata["provider"],
                model_id=provider_metadata["model_id"],
                model_version=provider_metadata["model_version"],
                provider_fingerprint=provider_metadata["provider_fingerprint"],
                endpoint=provider_metadata.get("endpoint"),
                request_payload={
                    "model": provider_metadata["model_id"],
                    "prompt": prompt,
                    "system_prompt": system_prompt,
                    "context": {
                        "user_prompt": user_prompt,
                        "requirements_reference_markdown": requirements_text,
                        "task_synthesis_profile": task_profile.model_dump(mode="json"),
                        "available_evidence_sources": [source.model_dump(mode="json") for source in planner_sources],
                        "web_fallback_used": web_fallback_used,
                        "web_search_results": [result.model_dump(mode="json") for result in web_fallback_results],
                    },
                    "temperature": 0.0,
                    "top_p": 1.0,
                    "seed": self.settings.deterministic_seed,
                    "determinism_mode": determinism_mode,
                },
                response_payload={"bundle_source": "strict_local_fallback"},
            )
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
                    "task_synthesis_profile": task_profile.model_dump(mode="json"),
                    "available_evidence_sources": [source.model_dump(mode="json") for source in planner_sources],
                    "web_fallback_used": web_fallback_used,
                    "web_search_results": [result.model_dump(mode="json") for result in web_fallback_results],
                },
                temperature=self.settings.k2_temperature,
                top_p=self.settings.k2_top_p,
                seed=self.settings.deterministic_seed,
                determinism_mode=determinism_mode,
                agentic=True,
                max_tokens=3500,
            )
        )
        self.last_provider_metadata = {
            "provider": response.provider,
            "model_id": response.model,
            "model_version": response.model_version or response.model,
            "provider_fingerprint": response.provider_fingerprint,
            "endpoint": response.endpoint,
        }
        self.last_prompt_trace = trace_from_request_response(
            trace_id=f"synthesis:{uuid4().hex[:8]}",
            phase="program_synthesis",
            node_id=None,
            prompt=prompt,
            system_prompt=system_prompt,
            context={
                "user_prompt": user_prompt,
                "requirements_reference_markdown": requirements_text,
                "task_synthesis_profile": task_profile.model_dump(mode="json"),
                "available_evidence_sources": [source.model_dump(mode="json") for source in planner_sources],
                "web_fallback_used": web_fallback_used,
                "web_search_results": [result.model_dump(mode="json") for result in web_fallback_results],
            },
            params=response.request_params,
            provider=response.provider,
            model_id=response.model,
            model_version=response.model_version or response.model,
            provider_fingerprint=response.provider_fingerprint,
            endpoint=response.endpoint,
            request_payload=response.request_payload,
            response_payload=response.raw,
        )

        try:
            payload = self._load_payload(response.content)
            bundle = self._normalize_bundle(
                payload,
                user_prompt,
                task_profile,
                prefer_model_graph=self.last_provider_metadata.get("provider") == "k2",
            )
        except Exception:
            fallback_payload = self._fallback_payload(user_prompt, requirements_text, task_profile)
            bundle = self._normalize_bundle(fallback_payload, user_prompt, task_profile, prefer_model_graph=False)
            payload = fallback_payload
        self.last_planner_trace = self._normalize_planner_trace(
            payload.get("planner_trace"),
            bundle,
            user_prompt,
            task_profile,
            planner_sources,
            web_fallback_used,
            web_fallback_results,
            attempted_web_queries,
        )
        bundle.program.metadata["planner_trace"] = self.last_planner_trace.model_dump(mode="json")
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
                    top_p=self.settings.k2_top_p,
                    seed=self.settings.deterministic_seed,
                    determinism_mode="best_effort_deterministic",
                    agentic=False,
                    max_tokens=3500,
                )
            )
            return extract_json_object(repair.content)

    def _fallback_payload(
        self,
        user_prompt: str,
        requirements_text: str,
        task_profile: TaskSynthesisProfile,
    ) -> dict[str, Any]:
        fallback = MockProvider().generate(
            LLMRequest(
                task="program_synthesis",
                prompt="Fallback synthesis for invalid upstream JSON.",
                context={
                    "user_prompt": user_prompt,
                    "requirements_reference_markdown": requirements_text,
                    "task_synthesis_profile": task_profile.model_dump(mode="json"),
                },
                temperature=0.0,
                agentic=False,
            )
        )
        payload = extract_json_object(fallback.content)
        if self._should_use_profile_graph(payload.get("program", payload), task_profile):
            return self._build_profile_fallback_payload(user_prompt, task_profile)
        return payload

    def _normalize_bundle(
        self,
        payload: dict[str, Any],
        user_prompt: str,
        task_profile: TaskSynthesisProfile | None = None,
        prefer_model_graph: bool = False,
    ) -> SynthesizedProgramBundle:
        task_profile = task_profile or self._build_task_profile(
            user_prompt=user_prompt,
            documents=[],
            planner_sources=[],
            web_fallback_used=False,
            control_level=ControlLevel.operational.value,
        )
        payload = self._coerce_bundle_payload(payload, user_prompt)

        if not payload.get("template_id"):
            payload["template_id"] = f"{self._slug(task_profile.task_type)}_{self._slug(user_prompt)}_template"
        if not payload.get("template_name"):
            payload["template_name"] = f"{task_profile.task_type.replace('_', ' ').title()} Reasoning Template"
        if not payload.get("domain"):
            payload["domain"] = self._infer_domain(user_prompt)
        if not payload.get("mapping_explanation"):
            payload["mapping_explanation"] = (
                "Synthesized from requirements reference, prompt, and a task profile covering "
                "problem decomposition, evidence availability, control level, output structure, "
                "and branching/tool/delegation needs."
            )

        program_payload = payload["program"]
        program_payload.setdefault("program_id", f"{self._slug(user_prompt)}_v1")
        program_payload.setdefault("version", "1.0.0")
        program_payload.setdefault("template_id", payload["template_id"])
        program_payload.setdefault("domain", payload["domain"])
        program_payload.setdefault("goal", user_prompt)
        program_payload.setdefault("policy", task_profile.recommended_policy)
        program_payload.setdefault(
            "budget",
            task_profile.suggested_budget or {"max_nodes": 12, "max_tokens": 18000, "max_runtime_seconds": 240},
        )
        if self._should_use_profile_graph(program_payload, task_profile, prefer_model_graph=prefer_model_graph):
            program_payload["nodes"] = self._build_profile_nodes(task_profile, user_prompt)
        program_payload["budget"] = self._normalize_budget(
            program_payload["budget"],
            program_payload.get("nodes", []),
            task_profile.suggested_budget,
        )
        program_payload.setdefault(
            "convergence_rule",
            "verification_passed_and_output_ready" if task_profile.requires_verification else "no_pending_nodes",
        )
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
        payload["output_schema_definition"] = self._specialize_output_schema_definition(
            payload["output_schema_definition"],
            task_profile,
        )
        program_payload.setdefault(
            "deterministic_defaults",
            {"temperature": 0, "seed": self.settings.deterministic_seed},
        )
        program_payload.setdefault("metadata", {})
        program_payload["metadata"]["task_profile"] = task_profile.model_dump(mode="json")
        program_payload["nodes"] = self._repair_graph_connectivity(
            self._normalize_nodes(program_payload.get("nodes", []))
        )

        program = ReasoningProgram.model_validate(program_payload)
        self._specialize_program_for_profile(program, task_profile, prefer_model_graph=prefer_model_graph)
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

    def _default_output_schema_definition(
        self,
        program_id: str,
        task_profile: TaskSynthesisProfile | None = None,
    ) -> dict[str, Any]:
        required_sections = (
            task_profile.required_output_sections
            if task_profile is not None and task_profile.required_output_sections
            else ["objective", "conclusion", "findings", "evidence_sources", "next_steps"]
        )
        schema_title = f"{program_id}_output_schema_v1"
        properties = {
            section: self._schema_property_for_output_section(section)
            for section in required_sections
        }
        properties.setdefault("finding_records", {"type": "array", "items": {"type": "object"}})
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": schema_title,
            "type": "object",
            "required": required_sections,
            "properties": properties,
            "additionalProperties": True,
        }

    @staticmethod
    def _schema_property_for_output_section(section: str) -> dict[str, Any]:
        array_of_strings = {
            "findings",
            "evidence_sources",
            "next_steps",
            "alternatives",
            "control_issues",
            "violations",
            "obligations",
            "recommendations",
            "criteria",
        }
        array_of_objects = {"finding_records", "calculations", "options"}
        if section in array_of_strings:
            return {"type": "array", "items": {"type": "string"}}
        if section in array_of_objects:
            return {"type": "array", "items": {"type": "object"}}
        return {"type": "string"}

    def _build_task_profile(
        self,
        user_prompt: str,
        documents: list[DocumentRecord],
        planner_sources: list[PlannerEvidenceSource],
        web_fallback_used: bool,
        control_level: str,
    ) -> TaskSynthesisProfile:
        lowered = user_prompt.lower()
        task_type = self._infer_task_type(lowered)
        decomposition = self._infer_problem_decomposition(lowered)
        available_evidence_mode = "none"
        if web_fallback_used:
            available_evidence_mode = "web_search"
        elif any(str(document.metadata.get("ingest_source")) == "upload" for document in documents):
            available_evidence_mode = "uploaded_documents"
        elif any(str(document.metadata.get("ingest_source")) == "sample" for document in documents):
            available_evidence_mode = "sample_pack"

        structured_docs = any(document.media_type.endswith(("csv", "sheet", "spreadsheetml.sheet")) for document in documents)
        requires_tools = structured_docs or any(
            keyword in lowered
            for keyword in ("calculate", "quantify", "reconcile", "trend", "latest", "recent", "search", "lookup", "compare")
        )
        branch_focuses = self._branch_focuses_for_task(task_type, lowered, decomposition)
        requires_branching = len(branch_focuses) > 1
        risk_profile = "standard"
        if control_level in {ControlLevel.regulated.value, ControlLevel.strict_audit.value} or any(
            keyword in lowered for keyword in ("audit", "fraud", "material weakness", "regulatory", "compliance")
        ):
            risk_profile = "elevated"
        if control_level == ControlLevel.strict_audit.value or any(
            keyword in lowered for keyword in ("fraud", "material weakness", "regulatory non-compliance")
        ):
            risk_profile = "critical"

        explicit_expansion = any(keyword in lowered for keyword in ("expand", "deep", "detailed", "comprehensive", "branch"))
        requires_delegation = (
            control_level in {ControlLevel.exploratory.value, ControlLevel.operational.value}
            and (explicit_expansion or (requires_branching and len(branch_focuses) >= 3))
        )
        if control_level == ControlLevel.strict_audit.value:
            requires_delegation = False

        recommended_policy = "priority_based"
        if requires_branching and risk_profile == "standard":
            recommended_policy = "breadth_first"
        if available_evidence_mode == "web_search" and risk_profile == "standard":
            recommended_policy = "cost_aware"

        required_output_sections = self._required_output_sections_for_task(task_type, lowered)
        summary = (
            f"{task_type.replace('_', ' ').title()} task with {available_evidence_mode.replace('_', ' ')} evidence, "
            f"{risk_profile} governance, and {'branching' if requires_branching else 'linear'} reasoning."
        )

        return TaskSynthesisProfile(
            task_type=task_type,
            problem_decomposition=decomposition,
            available_evidence_mode=available_evidence_mode,
            evidence_source_count=len(planner_sources),
            risk_profile=risk_profile,
            control_level=control_level,
            required_output_sections=required_output_sections,
            requires_branching=requires_branching,
            requires_verification=True,
            requires_tools=requires_tools or available_evidence_mode == "web_search",
            requires_delegation=requires_delegation,
            recommended_policy=recommended_policy,
            branch_focuses=branch_focuses,
            suggested_budget=self._suggested_budget(requires_branching, requires_tools, requires_delegation, risk_profile),
            summary=summary,
        )

    @staticmethod
    def _infer_task_type(lowered_prompt: str) -> str:
        if any(keyword in lowered_prompt for keyword in ("audit", "fraud", "material weakness", "revenue recognition")):
            return "audit"
        if any(keyword in lowered_prompt for keyword in ("compliance", "regulatory", "policy", "obligation")):
            return "compliance"
        if any(keyword in lowered_prompt for keyword in ("compare", "versus", "vs", "choose", "select", "recommend between")):
            return "comparison"
        if any(keyword in lowered_prompt for keyword in ("calculate", "forecast", "model", "variance", "reconcile", "quantify")):
            return "calculation"
        if any(keyword in lowered_prompt for keyword in ("research", "investigate", "why", "how", "latest", "recent")):
            return "research"
        if any(keyword in lowered_prompt for keyword in ("extract", "summarize", "list", "catalog")):
            return "extraction"
        return "analysis"

    @staticmethod
    def _infer_problem_decomposition(lowered_prompt: str) -> list[str]:
        decomposition: list[str] = []
        if any(keyword in lowered_prompt for keyword in ("risk", "fraud", "control")):
            decomposition.append("risk_and_controls")
        if any(keyword in lowered_prompt for keyword in ("evidence", "source", "document", "citation")):
            decomposition.append("evidence_grounding")
        if any(keyword in lowered_prompt for keyword in ("calculate", "quantify", "metric", "variance", "trend")):
            decomposition.append("quantitative_checks")
        if any(keyword in lowered_prompt for keyword in ("compare", "alternative", "option", "versus", "scenario")):
            decomposition.append("alternative_paths")
        if any(keyword in lowered_prompt for keyword in ("regulatory", "compliance", "policy", "obligation")):
            decomposition.append("requirement_mapping")
        if not decomposition:
            decomposition.append("core_analysis")
        return decomposition

    @staticmethod
    def _required_output_sections_for_task(task_type: str, lowered_prompt: str) -> list[str]:
        sections_by_type = {
            "audit": ["objective", "conclusion", "findings", "control_issues", "evidence_sources", "next_steps"],
            "compliance": ["objective", "conclusion", "obligations", "violations", "evidence_sources", "next_steps"],
            "comparison": ["objective", "recommendation", "criteria", "options", "findings", "next_steps"],
            "calculation": ["objective", "conclusion", "assumptions", "calculations", "findings", "evidence_sources"],
            "research": ["question", "answer", "findings", "alternatives", "evidence_sources", "next_steps"],
            "extraction": ["objective", "findings", "evidence_sources", "next_steps"],
            "analysis": ["objective", "conclusion", "findings", "evidence_sources", "next_steps"],
        }
        sections = list(sections_by_type.get(task_type, sections_by_type["analysis"]))
        if "confidence" in lowered_prompt and "confidence" not in sections:
            sections.append("confidence")
        return sections

    @staticmethod
    def _branch_focuses_for_task(task_type: str, lowered_prompt: str, decomposition: list[str]) -> list[str]:
        if task_type == "audit":
            focuses = ["control review", "exception analysis", "evidence corroboration"]
            if "fraud" in lowered_prompt:
                focuses[1] = "fraud indicator review"
            return focuses
        if task_type == "compliance":
            return ["requirement mapping", "gap assessment", "remediation review"]
        if task_type == "comparison":
            return ["option analysis", "criteria scoring", "tradeoff review"]
        if task_type == "calculation":
            return ["assumption review", "calculation checks"]
        if task_type == "research":
            return ["source scan", "alternative hypotheses", "gap analysis"]
        if "alternative_paths" in decomposition:
            return ["primary path", "alternative path"]
        return ["core analysis"]

    @staticmethod
    def _suggested_budget(
        requires_branching: bool,
        requires_tools: bool,
        requires_delegation: bool,
        risk_profile: str,
    ) -> dict[str, int]:
        max_nodes = 12
        if requires_branching:
            max_nodes += 4
        if requires_tools:
            max_nodes += 1
        if requires_delegation:
            max_nodes += 2
        max_tokens = 18000 + (7000 if requires_branching else 0) + (4000 if requires_delegation else 0)
        max_runtime_seconds = 240 + (120 if risk_profile in {"elevated", "critical"} else 0)
        return {
            "max_nodes": max_nodes,
            "max_tokens": max_tokens,
            "max_runtime_seconds": max_runtime_seconds,
        }

    @staticmethod
    def _build_agent_spec_payload(
        persona: str = "",
        instruction: str = "",
        *,
        context: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        model: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        payload = {
            "persona": persona.strip(),
            "instruction": instruction.strip(),
            "context": context or {},
            "tools": [tool for tool in (tools or []) if isinstance(tool, dict) and str(tool.get("name") or "").strip()],
            "model": model if isinstance(model, dict) and model else None,
        }
        if not payload["persona"] and not payload["instruction"] and not payload["context"] and not payload["tools"] and not payload["model"]:
            return None
        return payload

    def _normalize_agent_spec_payload(
        self,
        raw_node: dict[str, Any],
        *,
        title: str,
        instruction: str,
        executor_type: str,
        executor_profile: str | None,
        metadata: dict[str, Any],
    ) -> dict[str, Any] | None:
        raw_agent_spec = raw_node.get("agent_spec")
        if hasattr(raw_agent_spec, "model_dump"):
            raw_agent_spec = raw_agent_spec.model_dump(mode="json")
        if isinstance(raw_agent_spec, dict):
            normalized = dict(raw_agent_spec)
        else:
            tool_spec = metadata.get("tool") if isinstance(metadata.get("tool"), dict) else None
            persona = executor_profile or title
            context = {
                "executor_type": executor_type,
                "executor_profile": executor_profile,
            }
            normalized = self._build_agent_spec_payload(
                persona=persona,
                instruction=instruction,
                context={key: value for key, value in context.items() if value},
                tools=[tool_spec] if tool_spec is not None else [],
            ) or {}

        if isinstance(normalized.get("tool"), dict) and not normalized.get("tools"):
            normalized["tools"] = [normalized.pop("tool")]
        if "context" not in normalized or not isinstance(normalized.get("context"), dict):
            normalized["context"] = {}
        if "tools" not in normalized or not isinstance(normalized.get("tools"), list):
            normalized["tools"] = []

        if not normalized:
            return None
        return AgentSpec.model_validate(normalized).model_dump(mode="json")

    def _should_use_profile_graph(
        self,
        program_payload: Any,
        task_profile: TaskSynthesisProfile,
        prefer_model_graph: bool = False,
    ) -> bool:
        if not isinstance(program_payload, dict):
            return True
        raw_nodes = program_payload.get("nodes")
        if not isinstance(raw_nodes, list) or not raw_nodes:
            return True

        node_count = 0
        generic_hits = 0
        has_branch = False
        has_tool = False
        has_agent = False
        generic_markers = {
            "scope_definition",
            "evidence_mapping",
            "analysis",
            "core_analysis",
            "verification_gate",
            "synthesis",
            "final_synthesis",
        }

        for raw_node in raw_nodes:
            if not isinstance(raw_node, dict):
                continue
            node_count += 1
            node_id = str(raw_node.get("id") or "").lower()
            title = str(raw_node.get("title") or "").lower().replace(" ", "_")
            if node_id in generic_markers or title in generic_markers:
                generic_hits += 1
            if str(raw_node.get("executor_type") or "").lower() == "tool_operator":
                has_tool = True
            if str(raw_node.get("executor_type") or "").lower() == "agent_operator":
                has_agent = True
            next_nodes = raw_node.get("next") or raw_node.get("next_nodes") or []
            depends_on = raw_node.get("depends_on") or raw_node.get("dependencies") or []
            if isinstance(next_nodes, list) and len(next_nodes) > 1:
                has_branch = True
            if isinstance(depends_on, list) and len(depends_on) > 1:
                has_branch = True

        if node_count == 0:
            return True
        if prefer_model_graph:
            return False
        if generic_hits == node_count and node_count <= 5:
            return True
        if task_profile.requires_branching and not has_branch:
            return True
        if task_profile.requires_tools and not has_tool:
            return True
        if task_profile.requires_delegation and not has_agent:
            return True
        return False

    def _build_profile_fallback_payload(self, user_prompt: str, task_profile: TaskSynthesisProfile) -> dict[str, Any]:
        program_id = f"{self._slug(user_prompt)}_v1"
        template_id = f"{self._slug(task_profile.task_type)}_{self._slug(user_prompt)}_template"
        return {
            "template_id": template_id,
            "template_name": f"{task_profile.task_type.replace('_', ' ').title()} Reasoning Template",
            "domain": self._infer_domain(user_prompt),
            "mapping_explanation": (
                "Fallback profile graph generated from task type, evidence mode, control level, "
                "required output sections, and branching/tool/delegation heuristics."
            ),
            "program": {
                "program_id": program_id,
                "version": "1.0.0",
                "template_id": template_id,
                "domain": self._infer_domain(user_prompt),
                "goal": user_prompt,
                "policy": task_profile.recommended_policy,
                "budget": task_profile.suggested_budget,
                "convergence_rule": "verification_passed_and_output_ready",
                "output_schema": f"{program_id}_output_schema_v1",
                "deterministic_defaults": {
                    "temperature": 0,
                    "seed": self.settings.deterministic_seed,
                },
                "metadata": {"task_profile": task_profile.model_dump(mode="json")},
                "nodes": self._build_profile_nodes(task_profile, user_prompt),
            },
            "output_schema_definition": self._default_output_schema_definition(program_id, task_profile),
            "planner_trace": {
                "summary": task_profile.summary,
                "graph_shape_reason": (
                    "The graph was shaped from the detected task type, available evidence mode, "
                    "risk/control level, required output sections, and whether branching, tools, "
                    "or delegation were needed."
                ),
                "candidate_graph_operations": [],
                "node_decisions": [],
                "confidence": 0.74,
                "unresolved_gaps": [],
            },
        }

    def _build_profile_nodes(self, task_profile: TaskSynthesisProfile, user_prompt: str) -> list[dict[str, Any]]:
        scope_node = {
            "id": "task_scope",
            "title": "Task Scope",
            "subtitle": f"{task_profile.task_type.replace('_', ' ').title()} objective and constraints",
            "operation_type": "generate",
            "instruction": "Restate the objective, constraints, and expected deliverable before deeper analysis.",
            "success_criteria": ["Objective restated", "Constraints identified", "Deliverable clarified"],
            "priority": 10,
            "depends_on": [],
            "next": ["evidence_anchoring"],
            "guarded_by": [],
            "metadata": {"layout": {"column": 1, "row": 0}},
        }

        evidence_metadata: dict[str, Any] = {
            "layout": {"column": 1, "row": 1},
            "evidence_mode": task_profile.available_evidence_mode,
        }
        if task_profile.available_evidence_mode == "web_search":
            evidence_metadata["tool"] = {"name": "web_search", "args": {"query": user_prompt, "top_k": 4}}
        elif task_profile.requires_tools:
            evidence_metadata["tool"] = {"name": "evidence_search", "args": {"query": user_prompt, "top_k": 4}}

        evidence_node = {
            "id": "evidence_anchoring",
            "title": "Evidence Anchoring",
            "subtitle": f"Prepare {task_profile.available_evidence_mode.replace('_', ' ')} evidence for analysis",
            "operation_type": "analyze",
            "instruction": "Map the most relevant evidence, note gaps, and establish what sources will anchor downstream claims.",
            "success_criteria": ["Evidence mapped", "Gaps noted", "Evidence scope prepared"],
            "priority": 20,
            "executor_type": "tool_operator" if task_profile.requires_tools else "llm_operator",
            "agent_spec": self._build_agent_spec_payload(
                persona="Evidence Curator",
                instruction="Curate the smallest viable evidence set that grounds downstream reasoning.",
                context={"evidence_mode": task_profile.available_evidence_mode},
                tools=[evidence_metadata["tool"]] if isinstance(evidence_metadata.get("tool"), dict) else [],
            ),
            "depends_on": ["task_scope"],
            "next": [],
            "guarded_by": [],
            "metadata": evidence_metadata,
        }

        analysis_nodes: list[dict[str, Any]] = []
        branch_focuses = task_profile.branch_focuses if task_profile.requires_branching else ["core analysis"]
        for index, focus in enumerate(branch_focuses[:3]):
            node_id = self._slug(focus)
            is_agent_branch = task_profile.requires_delegation and index == 0
            analysis_nodes.append(
                {
                    "id": node_id,
                    "title": focus.title(),
                    "subtitle": f"{task_profile.task_type.replace('_', ' ').title()} branch",
                    "operation_type": "analyze",
                    "instruction": f"Analyze the task through the lens of {focus}, grounded in the anchored evidence.",
                    "success_criteria": [f"{focus.title()} findings produced", "Evidence-linked claims returned"],
                    "priority": 30 + (index * 10),
                    "executor_type": "agent_operator" if is_agent_branch else "llm_operator",
                    "executor_profile": "general" if is_agent_branch else None,
                    "agent_spec": self._build_agent_spec_payload(
                        persona=f"{focus.title()} Specialist" if is_agent_branch else focus.title(),
                        instruction=f"Analyze the task through {focus} and return only grounded findings.",
                        context={"branch_focus": focus, "task_type": task_profile.task_type},
                    ),
                    "max_child_agents": 2 if is_agent_branch else 0,
                    "max_recursion_depth": 1 if is_agent_branch else 0,
                    "child_token_budget": 4000 if is_agent_branch else 0,
                    "delegated_summary_required": is_agent_branch,
                    "expansion_contracts": (
                        ["expand_evidence", "expand_alternatives", "expand_subgraph"]
                        if is_agent_branch
                        else []
                    ),
                    "depends_on": ["evidence_anchoring"],
                    "next": [],
                    "guarded_by": [],
                    "metadata": {"layout": {"column": index, "row": 2}},
                }
            )

        merge_node_id = analysis_nodes[0]["id"] if len(analysis_nodes) == 1 else "branch_merge"
        merge_nodes: list[dict[str, Any]] = []
        if len(analysis_nodes) > 1:
            merge_nodes.append(
                {
                    "id": "branch_merge",
                    "title": "Branch Merge",
                    "subtitle": "Reconcile branch findings",
                    "operation_type": "aggregate",
                    "instruction": "Combine branch findings into a coherent view, preserving conflicts and unresolved gaps.",
                    "success_criteria": ["Branch outputs reconciled", "Conflicts preserved explicitly"],
                    "priority": 70,
                    "depends_on": [node["id"] for node in analysis_nodes],
                    "next": [],
                    "guarded_by": [],
                    "metadata": {"layout": {"column": 1, "row": 3}},
                }
            )

        verify_approvals = 1 if task_profile.control_level in {ControlLevel.regulated.value, ControlLevel.strict_audit.value} else 0
        verify_row = 4 if merge_nodes else 3
        verify_node = {
            "id": "verification_gate",
            "title": "Verification Gate",
            "subtitle": "Check grounding and control fit",
            "operation_type": "verify",
            "instruction": "Verify evidence grounding, contradiction handling, and fitness for the requested control level.",
            "success_criteria": ["Verification status returned", "Checks explicitly listed", "Open gaps preserved"],
            "priority": 80,
            "required_approvals": verify_approvals,
            "depends_on": [merge_node_id],
            "next": ["final_synthesis"],
            "guarded_by": [],
            "metadata": {"layout": {"column": 2 if merge_nodes else 1, "row": verify_row}},
        }

        final_required_approvals = 0
        if task_profile.control_level == ControlLevel.strict_audit.value:
            final_required_approvals = 2
        elif task_profile.control_level == ControlLevel.regulated.value:
            final_required_approvals = 1
        final_row = verify_row + 1
        final_title_by_type = {
            "audit": "Audit Conclusion",
            "compliance": "Compliance Conclusion",
            "comparison": "Decision Synthesis",
            "calculation": "Calculation Synthesis",
            "research": "Research Synthesis",
            "extraction": "Structured Extraction",
            "analysis": "Final Synthesis",
        }
        final_node = {
            "id": "final_synthesis",
            "title": final_title_by_type.get(task_profile.task_type, "Final Synthesis"),
            "subtitle": "Produce required structured output",
            "operation_type": "synthesize",
            "instruction": (
                "Produce the final structured output with these sections: "
                + ", ".join(task_profile.required_output_sections)
                + ". Explicitly preserve uncertainties and unsupported items."
            ),
            "success_criteria": ["Output matches schema", "Final answer references evidence", "Gaps remain visible"],
            "priority": 90,
            "required_approvals": final_required_approvals,
            "depends_on": [merge_node_id, "verification_gate"],
            "next": [],
            "guarded_by": ["verification_gate"],
            "metadata": {"layout": {"column": 1, "row": final_row}},
        }

        evidence_node["next"] = [node["id"] for node in analysis_nodes]
        for node in analysis_nodes:
            node["next"] = [merge_node_id] if merge_node_id != node["id"] else ["verification_gate"]

        nodes = [scope_node, evidence_node, *analysis_nodes, *merge_nodes, verify_node, final_node]
        return nodes

    def _specialize_output_schema_definition(
        self,
        schema_definition: dict[str, Any],
        task_profile: TaskSynthesisProfile,
    ) -> dict[str, Any]:
        schema = dict(schema_definition)
        schema["type"] = "object"
        properties = dict(schema.get("properties") or {})
        required = list(schema.get("required") or [])
        for section in task_profile.required_output_sections:
            properties.setdefault(section, self._schema_property_for_output_section(section))
            if section not in required:
                required.append(section)
        properties.setdefault("finding_records", {"type": "array", "items": {"type": "object"}})
        schema["properties"] = properties
        schema["required"] = required
        schema.setdefault("additionalProperties", True)
        return schema

    def _specialize_program_for_profile(
        self,
        program: ReasoningProgram,
        task_profile: TaskSynthesisProfile,
        prefer_model_graph: bool = False,
    ) -> None:
        program.policy = task_profile.recommended_policy if program.policy == "priority_based" else program.policy
        program.metadata["task_profile"] = task_profile.model_dump(mode="json")
        final_sections = ", ".join(task_profile.required_output_sections)

        has_tool = any(node.executor_type == "tool_operator" for node in program.nodes)
        has_agent = any(node.executor_type == "agent_operator" for node in program.nodes)

        for node in program.nodes:
            if node.operation_type == "synthesize":
                node.instruction = (
                    f"{node.instruction.rstrip()} Return sections for: {final_sections}."
                    if final_sections
                    else node.instruction
                )
                if task_profile.control_level == ControlLevel.strict_audit.value:
                    node.required_approvals = max(node.required_approvals, 2)
                elif task_profile.control_level == ControlLevel.regulated.value:
                    node.required_approvals = max(node.required_approvals, 1)
            if node.operation_type == "verify" and task_profile.control_level in {
                ControlLevel.regulated.value,
                ControlLevel.strict_audit.value,
            }:
                node.required_approvals = max(node.required_approvals, 1)

        if not prefer_model_graph and task_profile.requires_tools and not has_tool:
            for node in program.nodes:
                if node.operation_type in {"generate", "analyze"} and node.id not in {"final_synthesis", "verification_gate"}:
                    node.executor_type = "tool_operator"
                    node.metadata.setdefault("tool", {"name": "evidence_search", "args": {"query": program.goal, "top_k": 4}})
                    if node.agent_spec is None:
                        node.agent_spec = AgentSpec.model_validate(
                            self._build_agent_spec_payload(
                                persona=node.executor_profile or node.title,
                                instruction=node.instruction,
                                context={"executor_type": "tool_operator"},
                                tools=[node.metadata["tool"]],
                            )
                        )
                    break

        if not prefer_model_graph and task_profile.requires_delegation and not has_agent:
            for node in program.nodes:
                if node.operation_type == "analyze":
                    node.executor_type = "agent_operator"
                    node.max_child_agents = max(node.max_child_agents, 2)
                    node.max_recursion_depth = max(node.max_recursion_depth, 1)
                    node.expansion_contracts = list(
                        dict.fromkeys([*node.expansion_contracts, "expand_evidence", "expand_alternatives", "expand_subgraph"])
                    )
                    if node.agent_spec is None:
                        node.agent_spec = AgentSpec.model_validate(
                            self._build_agent_spec_payload(
                                persona=node.executor_profile or f"{node.title} Specialist",
                                instruction=node.instruction,
                                context={"executor_type": "agent_operator", "delegation_enabled": True},
                            )
                        )
                    break

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
            executor_type = self._first_string(raw_node, "executor_type") or "llm_operator"
            executor_profile = self._first_string(raw_node, "executor_profile")

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
                    "executor_type": executor_type,
                    "executor_profile": executor_profile,
                    "agent_spec": self._normalize_agent_spec_payload(
                        raw_node,
                        title=title,
                        instruction=instruction or f"Execute {title.lower()} for the current reasoning task.",
                        executor_type=executor_type,
                        executor_profile=executor_profile,
                        metadata=metadata,
                    ),
                    "max_child_agents": int(raw_node.get("max_child_agents", 0) or 0),
                    "max_recursion_depth": int(raw_node.get("max_recursion_depth", 0) or 0),
                    "child_token_budget": int(raw_node.get("child_token_budget", 0) or 0),
                    "delegated_summary_required": bool(raw_node.get("delegated_summary_required", False)),
                    "expansion_contracts": self._normalize_string_list(raw_node.get("expansion_contracts")),
                    "required_approvals": int(raw_node.get("required_approvals", 0) or 0),
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
    def _normalize_budget(
        value: Any,
        nodes_payload: Any,
        suggested_budget: dict[str, int] | None = None,
    ) -> dict[str, int]:
        node_count = len(nodes_payload) if isinstance(nodes_payload, list) else 0
        budget = value if isinstance(value, dict) else {}
        suggested_budget = suggested_budget or {}
        max_nodes = budget.get("max_nodes")
        max_tokens = budget.get("max_tokens")
        max_runtime_seconds = budget.get("max_runtime_seconds")
        return {
            "max_nodes": max(
                int(max_nodes) if isinstance(max_nodes, int) else 0,
                node_count + 2,
                int(suggested_budget.get("max_nodes", 12) or 12),
                12,
            ),
            "max_tokens": max(
                int(max_tokens) if isinstance(max_tokens, int) else 0,
                node_count * 10000,
                int(suggested_budget.get("max_tokens", 50000) or 50000),
                50000,
            ),
            "max_runtime_seconds": max(
                int(max_runtime_seconds) if isinstance(max_runtime_seconds, int) else 0,
                int(suggested_budget.get("max_runtime_seconds", 300) or 300),
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

    def _normalize_planner_trace(
        self,
        payload: Any,
        bundle: SynthesizedProgramBundle,
        user_prompt: str,
        task_profile: TaskSynthesisProfile,
        planner_sources: list[PlannerEvidenceSource],
        web_fallback_used: bool,
        web_fallback_results: list[WebSearchResult],
        attempted_web_queries: list[str],
    ) -> PlannerTrace:
        graph_shape_reason = ""
        summary = ""
        confidence: float | None = None
        unresolved_gaps: list[str] = []
        candidate_graph_operations: list[PlannerCandidateOperation] = []
        node_decisions: list[PlannerNodeDecision] = []
        web_search_queries = list(attempted_web_queries) or ([user_prompt] if web_fallback_used else [])

        if isinstance(payload, dict):
            graph_shape_reason = str(payload.get("graph_shape_reason") or "").strip()
            summary = str(payload.get("summary") or "").strip()
            raw_confidence = payload.get("confidence")
            if isinstance(raw_confidence, (int, float)):
                confidence = float(raw_confidence)
            unresolved_gaps = [str(item).strip() for item in payload.get("unresolved_gaps", []) if str(item).strip()]
            web_search_queries = [str(item).strip() for item in payload.get("web_search_queries", []) if str(item).strip()] or web_search_queries
            if isinstance(payload.get("candidate_graph_operations"), list):
                candidate_graph_operations = [
                    PlannerCandidateOperation.model_validate(item)
                    for item in payload["candidate_graph_operations"]
                    if isinstance(item, dict)
                ]
            if isinstance(payload.get("node_decisions"), list):
                node_decisions = [
                    PlannerNodeDecision.model_validate(item)
                    for item in payload["node_decisions"]
                    if isinstance(item, dict)
                ]

        if not graph_shape_reason:
            verify_nodes = [node for node in bundle.program.nodes if node.operation_type == "verify"]
            branch_count = sum(1 for node in bundle.program.nodes if len(node.next_nodes) > 1)
            graph_shape_reason = (
                f"Chose a {task_profile.task_type.replace('_', ' ')} reasoning graph with "
                f"{task_profile.available_evidence_mode.replace('_', ' ')} evidence anchoring"
                f"{' plus a verification branch' if verify_nodes else ''}"
                f"{' and branching analysis lanes' if branch_count else ''}."
            )
        if not summary:
            summary = task_profile.summary or "Structured graph planning completed with an auditable graph-shape summary."
        if confidence is None:
            confidence = 0.86 if planner_sources else 0.62
        if not unresolved_gaps and not planner_sources:
            unresolved_gaps.append("No uploaded evidence was available at planning time.")
        if web_fallback_used and not unresolved_gaps:
            unresolved_gaps.append("Web evidence was used as a fallback and should be reviewed before distribution.")
        if attempted_web_queries and not web_fallback_used and not planner_sources:
            unresolved_gaps.append("Attempted Brave web referrals, but no usable online sources were returned.")
        if not candidate_graph_operations:
            candidate_graph_operations = self._derive_candidate_operations(bundle.program, task_profile)
        if not node_decisions:
            node_decisions = self._derive_node_decisions(bundle.program, task_profile)

        evidence_sources = planner_sources or [PlannerEvidenceSource(
            source_id="requirements_reference",
            source_type="requirements_reference",
            label="Requirements Reference",
            detail="No uploaded or web evidence was available during graph planning.",
        )]
        if web_fallback_used and not any(source.source_type == "web_search" for source in evidence_sources):
            for result in web_fallback_results[:3]:
                evidence_sources.append(
                    PlannerEvidenceSource(
                        source_id=result.result_id,
                        source_type="web_search",
                        label=result.title,
                        detail=result.snippet,
                        url=result.url,
                    )
                )

        return PlannerTrace(
            summary=summary,
            graph_shape_reason=graph_shape_reason,
            evidence_sources_available=evidence_sources,
            web_fallback_used=web_fallback_used,
            web_search_queries=web_search_queries,
            candidate_graph_operations=candidate_graph_operations,
            node_decisions=node_decisions,
            confidence=confidence,
            unresolved_gaps=unresolved_gaps,
        )

    @staticmethod
    def _planner_sources_from_documents(documents: list[DocumentRecord]) -> list[PlannerEvidenceSource]:
        sources: list[PlannerEvidenceSource] = []
        usable_documents = [document for document in documents if document.extracted_text.strip()]
        for document in usable_documents[:6]:
            source_type = str(document.metadata.get("ingest_source") or "document")
            sources.append(
                PlannerEvidenceSource(
                    source_id=document.id,
                    source_type=source_type,
                    label=document.name,
                    detail=f"{document.media_type} · {len(document.extracted_text)} chars extracted",
                )
            )
        return sources

    @staticmethod
    def _planner_sources_from_web_results(results: list[WebSearchResult]) -> list[PlannerEvidenceSource]:
        return [
            PlannerEvidenceSource(
                source_id=result.result_id,
                source_type="web_search",
                label=result.title,
                detail=result.snippet,
                url=result.url,
            )
            for result in results[:4]
        ]

    @staticmethod
    def _derive_candidate_operations(
        program: ReasoningProgram,
        task_profile: TaskSynthesisProfile | None = None,
    ) -> list[PlannerCandidateOperation]:
        has_verify = any(node.operation_type == "verify" for node in program.nodes)
        has_branch = any(len(node.next_nodes) > 1 for node in program.nodes)
        has_tool = any(node.executor_type == "tool_operator" for node in program.nodes)
        has_agent = any(node.executor_type == "agent_operator" for node in program.nodes)
        operations = [
            PlannerCandidateOperation(
                operation="linear_scope_mapping",
                disposition="selected",
                rationale="A linear scope and evidence setup keeps early context deterministic and inspectable.",
            ),
            PlannerCandidateOperation(
                operation="direct_final_synthesis",
                disposition="rejected" if has_verify else "selected",
                rationale="Direct synthesis was not used when a dedicated verification gate was required.",
            ),
        ]
        if has_verify:
            operations.append(
                PlannerCandidateOperation(
                    operation="branch_for_verification",
                    disposition="selected",
                    rationale="Verification was split into its own path so synthesis could be explicitly guarded.",
                )
            )
        if has_branch:
            operations.append(
                PlannerCandidateOperation(
                    operation="parallel_analysis_branches",
                    disposition="selected",
                    rationale="Parallel branches were added where separate analytical checks improved coverage.",
                )
            )
        if task_profile is not None and task_profile.requires_tools:
            operations.append(
                PlannerCandidateOperation(
                    operation="tool_grounded_evidence_collection",
                    disposition="selected" if has_tool else "considered",
                    rationale="Tools were considered because the task requires search, retrieval, or quantitative support.",
                )
            )
        if task_profile is not None and task_profile.requires_delegation:
            operations.append(
                PlannerCandidateOperation(
                    operation="delegated_subanalysis",
                    disposition="selected" if has_agent else "considered",
                    rationale="Delegation was considered for complex branches that benefit from deeper controlled expansion.",
                )
            )
        return operations

    @staticmethod
    def _derive_node_decisions(
        program: ReasoningProgram,
        task_profile: TaskSynthesisProfile | None = None,
    ) -> list[PlannerNodeDecision]:
        decisions: list[PlannerNodeDecision] = []
        for node in program.nodes:
            action = "added"
            if len(node.next_nodes) > 1:
                action = "branched"
            elif len(node.depends_on) > 1:
                action = "merged"
            reason = (
                "Inserted to cover a distinct reasoning responsibility."
                if action == "added"
                else "Separated into a branch to isolate this analytical check."
                if action == "branched"
                else "Merged upstream dependencies to synthesize or reconcile prior outputs."
            )
            if task_profile is not None and node.operation_type == "verify":
                reason = f"Added to satisfy {task_profile.risk_profile} verification requirements for the requested control level."
            if task_profile is not None and node.executor_type == "tool_operator":
                reason = "Added or specialized to anchor the graph in search/retrieval or quantitative tooling."
            if task_profile is not None and node.executor_type == "agent_operator":
                reason = "Delegated branch created because the task profile called for controlled deeper decomposition."
            decisions.append(PlannerNodeDecision(node_id=node.id, action=action, reason=reason))
        return decisions

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
