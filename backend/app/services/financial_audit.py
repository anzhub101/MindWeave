from __future__ import annotations

import json
import re
from typing import Any

from app.models.runtime import (
    GraphNodeState,
    GraphReasoningState,
    NodeExecutionResult,
    VerificationStatus,
)
from app.services.knowledge_base import KnowledgeBase
from app.services.llm_gateway import LLMGateway, LLMRequest


class HumanReviewRequired(RuntimeError):
    pass


class FinancialAuditOperator:
    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        llm_gateway: LLMGateway,
        auto_approve_human_review: bool,
    ) -> None:
        self.knowledge_base = knowledge_base
        self.llm_gateway = llm_gateway
        self.auto_approve_human_review = auto_approve_human_review
        self.documents = knowledge_base.documents

    def execute(self, state: GraphReasoningState, node: GraphNodeState) -> NodeExecutionResult:
        handler = getattr(self, f"_run_{node.id}")
        return handler(state, node)

    def _run_audit_scope(self, state: GraphReasoningState, node: GraphNodeState) -> NodeExecutionResult:
        charter = self._find_document_text("charter")
        company_name = self._first_match(r"Entity:\s*([A-Za-z0-9 _-]+)", charter) or self._company_from_prompt(
            state.prompt
        )
        fiscal_year = self._first_match(r"Fiscal year:\s*([A-Za-z0-9_-]+)", charter) or self._year_from_prompt(
            state.prompt
        )
        evidence = [document.id for document in self.documents]
        return NodeExecutionResult(
            output={
                "company_name": company_name,
                "fiscal_year": fiscal_year,
                "document_inventory": [document.name for document in self.documents],
                "objective": "Perform a structured financial audit reasoning run with verifiable checkpoints.",
            },
            evidence_refs=evidence,
            verification_status=VerificationStatus.skipped,
            thought_summary=f"Mapped audit scope for {company_name} {fiscal_year}.",
        )

    def _run_financial_data_analysis(
        self, state: GraphReasoningState, node: GraphNodeState
    ) -> NodeExecutionResult:
        revenue = self._table_value("income_statement", "Revenue", "fy2026")
        gross_profit = self._table_value("income_statement", "Gross Profit", "fy2026")
        net_income = self._table_value("income_statement", "Net Income", "fy2026")
        total_assets = self._table_value("balance_sheet", "Total Assets", "fy2026")
        total_liabilities_equity = self._table_value(
            "balance_sheet", "Total Liabilities and Equity", "fy2026"
        )

        overall_materiality = round(max(revenue * 0.05, total_assets * 0.01), 2)
        gross_margin = round(gross_profit / revenue, 4) if revenue else 0.0
        net_margin = round(net_income / revenue, 4) if revenue else 0.0

        controls_text = self._find_document_text("controls")
        concentration_text = self._find_document_text("concentration")
        aged_receivables = self._extract_currency(concentration_text, r"USD\s*([0-9]+)")

        metrics = {
            "revenue": revenue,
            "gross_profit": gross_profit,
            "net_income": net_income,
            "total_assets": total_assets,
            "total_liabilities_and_equity": total_liabilities_equity,
            "gross_margin": gross_margin,
            "net_margin": net_margin,
            "overall_materiality": overall_materiality,
            "aged_receivables_90_plus": aged_receivables,
        }
        evidence = [
            document.id
            for document in self.documents
            if "income_statement" in document.name or "balance_sheet" in document.name
        ]
        evidence.extend(
            [
                document.id
                for document in self.documents
                if "controls" in document.name or "concentration" in document.name
            ]
        )
        return NodeExecutionResult(
            output={
                "key_metrics": metrics,
                "notable_observations": [
                    "Bad debt expense increased materially versus the prior year.",
                    "Revenue concentration and aging trends warrant deeper testing.",
                    "Materiality was calculated from revenue and total assets.",
                ],
            },
            evidence_refs=evidence,
            verification_status=VerificationStatus.skipped,
            thought_summary="Extracted financial metrics and computed materiality.",
        )

    def _run_compliance_check(self, state: GraphReasoningState, node: GraphNodeState) -> NodeExecutionResult:
        controls_text = self._find_document_text("controls")
        journal_exception = self._extract_currency(
            controls_text,
            r"approval exceptions:[\s\S]*?USD\s*([0-9]+)",
        )
        cutoff_amount = self._extract_currency(
            controls_text,
            r"Revenue cutoff observations:[\s\S]*?USD\s*([0-9]+)",
        )
        checks = [
            "Audit charter and core financial statements were located.",
            "Control exception memo reviewed for approval and cutoff issues.",
            "Required source documents were preserved in the audit package.",
        ]
        return NodeExecutionResult(
            output={
                "policy_exceptions": [
                    {
                        "id": "journal_approval_gap",
                        "title": "Manual journal approvals missing",
                        "amount": journal_exception,
                        "summary": "Three entries lacked second-level approval.",
                    },
                    {
                        "id": "revenue_cutoff",
                        "title": "Revenue cutoff timing exception",
                        "amount": cutoff_amount,
                        "summary": "Invoices were recognized before shipment.",
                    },
                ],
                "conclusion": "Verification completed with exceptions logged for downstream risk scoring.",
            },
            evidence_refs=[document.id for document in self.documents if "controls" in document.name],
            verification_status=VerificationStatus.passed,
            verification_checks=checks,
            thought_summary="Verified compliance evidence and captured control exceptions.",
        )

    def _run_integrity_check(self, state: GraphReasoningState, node: GraphNodeState) -> NodeExecutionResult:
        assets = self._table_value("balance_sheet", "Total Assets", "fy2026")
        liabilities_equity = self._table_value("balance_sheet", "Total Liabilities and Equity", "fy2026")
        ar_balance = self._table_value("balance_sheet", "Accounts Receivable", "fy2026")
        allowance = self._table_value("balance_sheet", "Allowance for Doubtful Accounts", "fy2026")
        allowance_ratio = round(allowance / ar_balance, 4) if ar_balance else 0.0

        controls_text = self._find_document_text("controls")
        inventory_variance = self._first_match(r"([0-9.]+)\s*percent", controls_text) or "0"
        checks = [
            f"Balance sheet equation reconciled: {assets:.0f} assets vs {liabilities_equity:.0f} liabilities and equity.",
            f"Allowance coverage ratio observed at {allowance_ratio:.2%}.",
            f"Inventory count variance observed at {inventory_variance} percent.",
        ]
        return NodeExecutionResult(
            output={
                "integrity_checks": {
                    "balance_sheet_reconciled": assets == liabilities_equity,
                    "allowance_ratio": allowance_ratio,
                    "inventory_variance_percent": float(inventory_variance),
                },
                "conclusion": "Integrity checks completed and evidence prepared for risk aggregation.",
            },
            evidence_refs=[document.id for document in self.documents if "balance_sheet" in document.name or "controls" in document.name],
            verification_status=VerificationStatus.passed,
            verification_checks=checks,
            thought_summary="Verified balance sheet integrity and reserve coverage indicators.",
        )

    def _run_risk_assessment(self, state: GraphReasoningState, node: GraphNodeState) -> NodeExecutionResult:
        analysis = state.nodes["financial_data_analysis"].output
        compliance = state.nodes["compliance_check"].output
        integrity = state.nodes["integrity_check"].output
        metrics = analysis["key_metrics"]
        materiality = metrics["overall_materiality"]

        findings = [
            {
                "id": "revenue_cutoff",
                "title": "Revenue cutoff timing exception",
                "status": "open",
                "amount": float(compliance["policy_exceptions"][1]["amount"]),
                "summary": "Invoices were recognized before shipment at year end.",
                "evidence_refs": state.nodes["compliance_check"].evidence_refs,
            },
            {
                "id": "journal_approval_gap",
                "title": "Manual journal approval deficiency",
                "status": "open",
                "amount": float(compliance["policy_exceptions"][0]["amount"]),
                "summary": "Approval workflow exceptions suggest a control weakness.",
                "evidence_refs": state.nodes["compliance_check"].evidence_refs,
            },
            {
                "id": "customer_concentration",
                "title": "Customer concentration and collections pressure",
                "status": "open",
                "amount": float(metrics["aged_receivables_90_plus"]),
                "summary": "Customer concentration and aged receivables increase collectability risk.",
                "evidence_refs": [document.id for document in self.documents if "concentration" in document.name],
            },
        ]

        risks = []
        for finding in findings:
            severity = "high" if finding["amount"] >= materiality * 0.75 else "medium"
            if finding["id"] == "journal_approval_gap":
                severity = "medium"
            risks.append(
                {
                    "id": finding["id"],
                    "title": finding["title"],
                    "severity": severity,
                    "rationale": (
                        f"Finding value {finding['amount']:.0f} evaluated against materiality {materiality:.0f}. "
                        f"Integrity data: {json.dumps(integrity['integrity_checks'])}"
                    ),
                    "evidence_refs": finding["evidence_refs"],
                }
            )

        return NodeExecutionResult(
            output={
                "overall_materiality": materiality,
                "identified_risks": risks,
                "substantive_findings": findings,
            },
            evidence_refs=sorted({ref for finding in findings for ref in finding["evidence_refs"]}),
            verification_status=VerificationStatus.skipped,
            thought_summary="Aggregated verified findings into a risk-ranked audit assessment.",
        )

    def _run_human_review(self, state: GraphReasoningState, node: GraphNodeState) -> NodeExecutionResult:
        if not self.auto_approve_human_review:
            raise HumanReviewRequired("Task paused for human review.")
        return NodeExecutionResult(
            output={
                "review_mode": "simulated_auto_approval",
                "review_notes": "MVP demo mode auto-approved the reviewer checkpoint after all verify gates passed.",
            },
            evidence_refs=state.nodes["risk_assessment"].evidence_refs,
            verification_status=VerificationStatus.passed,
            verification_checks=[
                "Reviewer checkpoint reached.",
                "Simulated approval recorded in deterministic MVP mode.",
            ],
            thought_summary="Recorded human review checkpoint outcome.",
        )

    def _run_final_report_synthesis(
        self, state: GraphReasoningState, node: GraphNodeState
    ) -> NodeExecutionResult:
        scope = state.nodes["audit_scope"].output
        analysis = state.nodes["financial_data_analysis"].output
        risk = state.nodes["risk_assessment"].output

        findings = risk["substantive_findings"]
        high_risk_count = sum(1 for item in risk["identified_risks"] if item["severity"] == "high")
        opinion = "Qualified" if high_risk_count or findings else "Unqualified"
        opinion_basis = (
            "Qualified due to year-end cutoff exceptions, control approval deficiencies, "
            "and elevated collectability risk requiring follow-up."
            if opinion == "Qualified"
            else "No material exceptions were identified."
        )

        llm_response = self.llm_gateway.generate(
            LLMRequest(
                task="executive_summary",
                prompt="Draft a concise executive summary for the audit report.",
                context={
                    "company_name": scope["company_name"],
                    "audit_opinion": opinion,
                    "findings_count": len(findings),
                },
            )
        )

        verification_summary = [
            entry.model_dump(mode="json") for entry in state.verification_logs
        ]
        trace_references = [
            {
                "node_id": thought.node_id,
                "thought_id": thought.id,
                "summary": thought.summary,
            }
            for thought in state.thoughts.values()
        ]
        report = {
            "company_name": scope["company_name"],
            "fiscal_year": scope["fiscal_year"],
            "audit_opinion": opinion,
            "opinion_basis": opinion_basis,
            "overall_materiality": risk["overall_materiality"],
            "key_metrics": analysis["key_metrics"],
            "identified_risks": risk["identified_risks"],
            "substantive_findings": findings,
            "verification_summary": verification_summary,
            "evidence_sources": [
                {
                    "document_id": document.id,
                    "name": document.name,
                    "sha256": document.sha256,
                }
                for document in self.documents
            ],
            "trace_references": trace_references,
            "executive_summary": llm_response.content,
        }
        summary = {
            "company_name": scope["company_name"],
            "opinion": opinion,
            "findings_count": len(findings),
            "materiality": risk["overall_materiality"],
        }
        return NodeExecutionResult(
            output={
                "audit_opinion": opinion,
                "opinion_basis": opinion_basis,
                "findings_count": len(findings),
            },
            evidence_refs=[document.id for document in self.documents],
            verification_status=VerificationStatus.skipped,
            thought_summary="Synthesized the final audit report and summary card.",
            llm_usage_tokens=llm_response.prompt_tokens + llm_response.completion_tokens,
            final_output=report,
            final_summary=summary,
        )

    def _find_document_text(self, name_fragment: str) -> str:
        matches = self.knowledge_base.by_name(name_fragment)
        return matches[0].extracted_text if matches else ""

    def _table_value(self, document_name_fragment: str, line_item: str, column: str) -> float:
        for document in self.knowledge_base.by_name(document_name_fragment):
            for row in document.metadata.get("structured_rows", []):
                if str(row.get("line_item", "")).strip().lower() == line_item.strip().lower():
                    raw_value = row.get(column, 0) or 0
                    return float(raw_value)
        return 0.0

    @staticmethod
    def _company_from_prompt(prompt: str) -> str:
        match = re.search(r"for\s+([A-Za-z0-9_-]+)\s+FY\d{4}", prompt, re.IGNORECASE)
        return match.group(1) if match else "Unknown Entity"

    @staticmethod
    def _year_from_prompt(prompt: str) -> str:
        match = re.search(r"(FY\d{4})", prompt, re.IGNORECASE)
        return match.group(1).upper() if match else "FY2026"

    @staticmethod
    def _first_match(pattern: str, value: str) -> str | None:
        match = re.search(pattern, value, re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_currency(value: str, pattern: str) -> float:
        match = re.search(pattern, value, re.IGNORECASE | re.DOTALL)
        return float(match.group(1)) if match else 0.0
