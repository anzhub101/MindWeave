from __future__ import annotations

import re
from typing import Any

from app.models.runtime import EvidenceSupportLevel, GraphNodeState, GraphReasoningState
from app.services.llm_gateway import LLMGateway, LLMRequest
from app.services.skill_service import SkillService
from app.services.web_search_service import WebSearchService


class NodeChatService:
    def __init__(
        self,
        llm_gateway: LLMGateway,
        skill_service: SkillService,
    ) -> None:
        self.llm_gateway = llm_gateway
        self.skill_service = skill_service
        self.web_search = WebSearchService()

    def chat(
        self,
        state: GraphReasoningState,
        node: GraphNodeState,
        message: str,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        history = history or []
        tool_results: list[dict[str, Any]] = []
        lowered = message.lower()

        if self._should_search_web(node, state, lowered):
            results = self.web_search.search(f"{state.prompt} {node.title} {message}", top_k=4)
            if results:
                tool_results.append(
                    {
                        "tool": "web_search",
                        "results": [result.model_dump(mode="json") for result in results],
                    }
                )

        skill_artifact_id = str(node.metadata.get("skill_artifact_id") or "").strip()
        if skill_artifact_id and any(keyword in lowered for keyword in ("run skill", "test skill", "execute skill")):
            tool_results.append(
                {
                    "tool": "skill",
                    "result": self.skill_service.run_skill_artifact(
                        skill_artifact_id,
                        {
                            "task_prompt": state.prompt,
                            "node_id": node.id,
                            "node_title": node.title,
                            "message": message,
                            "inputs": node.inputs,
                        },
                    ),
                }
            )

        conversation_history = "\n".join(
            f"- {entry.get('role', 'user')}: {entry.get('content', '').strip()}"
            for entry in history[-8:]
            if str(entry.get("content", "")).strip()
        )
        evidence_text = "\n".join(
            f"- {ref.document_name}: {ref.text_excerpt[:200]}{self._format_evidence_metadata(ref)}"
            for ref in node.evidence_refs[:5]
        )
        tool_text = self._format_tool_results(tool_results)
        user_prompt = (
            f"The user asks: '{message}'\n\n"
            f"Recent conversation:\n{conversation_history or 'No prior conversation.'}\n\n"
            f"Here is the current node information:\n"
            f"Title: {node.title}\n"
            f"Subtitle: {node.subtitle}\n"
            f"Instruction: {node.instruction}\n"
            f"Dependency Inputs: {node.inputs}\n"
            f"Output: {node.output}\n"
            f"Thought Summary: {node.thought_summary}\n"
            f"Reasoning Trace: {node.reasoning_trace}\n"
            f"Evidence:\n{evidence_text or 'No evidence linked.'}\n\n"
            f"External source referrals:\n{tool_text or 'No external referrals were loaded.'}\n\n"
            "Answer the user's question directly and helpfully. "
            "If external source referrals are present, use them and cite the most relevant titles or URLs. "
            "If this node had little or no uploaded evidence, explain that you supplemented the answer with Brave web referrals."
        )

        response = self.llm_gateway.generate(
            LLMRequest(
                task="node_chat",
                prompt=user_prompt,
                system_prompt=(
                    "You are MindWeave's node copilot. "
                    "Use the node state, linked evidence, and any fetched web referrals to answer the user's question. "
                    "Do not claim a source was uploaded if it came from web search. "
                    "Return only the user-facing answer. Do not expose chain-of-thought, XML thinking tags, or analyst scratchpad."
                ),
                context={
                    "task_prompt": state.prompt,
                    "user_message": message,
                    "node_id": node.id,
                    "node_title": node.title,
                    "node_instruction": node.instruction,
                    "node_inputs": node.inputs,
                    "node_output": node.output,
                    "node_reasoning_trace": node.reasoning_trace,
                    "node_evidence_refs": [reference.model_dump(mode="json") for reference in node.evidence_refs[:5]],
                    "tool_results": tool_results,
                    "source_document_count": len(state.source_documents),
                },
                determinism_mode="non_deterministic",
                temperature=0.3,
                top_p=1.0,
                agentic=True,
                max_tokens=1800,
            )
        )

        return {
            "reply": self._sanitize_reply(response.content),
            "tool_results": tool_results,
            "model_metadata": {
                "provider": response.provider,
                "model_id": response.model,
                "model_version": response.model_version or response.model,
                "provider_fingerprint": response.provider_fingerprint,
                "endpoint": response.endpoint,
            },
            "suggested_actions": self._suggested_actions(node, message, skill_artifact_id, bool(tool_results)),
        }

    @staticmethod
    def _should_search_web(node: GraphNodeState, state: GraphReasoningState, lowered_message: str) -> bool:
        search_keywords = ("search", "web", "internet", "latest", "recent", "look up", "find sources")
        if any(keyword in lowered_message for keyword in search_keywords):
            return True
        if not node.evidence_refs:
            return True
        weak_support_levels = {
            EvidenceSupportLevel.unsupported.value,
            EvidenceSupportLevel.user_provided.value,
        }
        return all(
            getattr(reference.support_level, "value", str(reference.support_level)) in weak_support_levels
            for reference in node.evidence_refs
        )

    @staticmethod
    def _sanitize_reply(reply: Any) -> str:
        text = str(reply or "").strip()
        if not text:
            return ""
        text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()
        text = text.replace("<think>", "").replace("</think>", "").strip()
        paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
        if paragraphs and paragraphs[0].lower().startswith(("the user asks:", "we need to", "we should", "thus ")):
            text = paragraphs[-1]
        return text.strip()

    @staticmethod
    def _format_evidence_metadata(reference: Any) -> str:
        segments: list[str] = []
        page = getattr(reference, "page", None)
        if isinstance(page, int):
            segments.append(f"page {page}")
        metadata = getattr(reference, "metadata", {}) if hasattr(reference, "metadata") else {}
        if isinstance(metadata, dict) and str(metadata.get("url") or "").strip():
            segments.append(str(metadata["url"]).strip())
        return f" ({' · '.join(segments)})" if segments else ""

    @staticmethod
    def _format_tool_results(tool_results: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for tool_result in tool_results:
            tool_name = str(tool_result.get("tool") or tool_result.get("name") or "tool")
            if tool_name == "web_search":
                results = tool_result.get("results", [])
                if not isinstance(results, list) or not results:
                    lines.append("- Brave search returned no usable results.")
                    continue
                for item in results[:4]:
                    if not isinstance(item, dict):
                        continue
                    title = str(item.get("title") or item.get("url") or "Web result").strip()
                    url = str(item.get("url") or "").strip()
                    snippet = str(item.get("snippet") or item.get("description") or "").strip()
                    lines.append(f"- {title}")
                    if url:
                        lines.append(f"  URL: {url}")
                    if snippet:
                        lines.append(f"  Snippet: {snippet[:280]}")
                continue
            lines.append(f"- {tool_name}: {tool_result}")
        return "\n".join(lines)

    @staticmethod
    def _suggested_actions(
        node: GraphNodeState,
        message: str,
        skill_artifact_id: str,
        used_tools: bool,
    ) -> list[str]:
        actions: list[str] = []
        lowered = message.lower()
        if any(keyword in lowered for keyword in ("change", "rewrite", "update executor", "agent")):
            actions.append("Apply executor changes from the Execution Mode section after reviewing this reply.")
        if any(keyword in lowered for keyword in ("expand", "rerun", "branch", "scope")):
            actions.append("Compile a structured graph patch if you want the chat suggestion to change the graph.")
        if used_tools:
            actions.append("Tool output was included in this reply.")
        if skill_artifact_id:
            actions.append(f"Skill {skill_artifact_id} is available for this node.")
        if not actions:
            actions.append(f"Continue the node conversation for {node.title}.")
        return actions
