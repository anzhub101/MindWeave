import type {
  ApprovalState,
  EvidenceReference,
  GraphEdge,
  GraphNode,
  SkillArtifact,
  TaskRunListItem,
  TaskRunResponse,
  TemplateSummary,
} from "./types";

const now = () => new Date().toISOString();

const basePrompt =
  "Review the SPA for Unit KR-1807 against the approved standard SPA template v3.0. Identify and cite all clause deviations; validate the payment plan against the purchase price and schedule; verify the buyer KYC pack and flag AML gaps; check DLD/RERA/escrow compliance. Produce a one-page deal brief with severity-ranked findings and suggested redlines, and route for human approval per the HOD→FC→SEVC authority matrix. Do not approve any money or title action.";

const sourceDocuments = [
  {
    id: "doc_standard_spa",
    name: "01_Standard_SPA_Template_v3.pdf",
    media_type: "application/pdf",
    storage_path: "upload://kr1807/01_Standard_SPA_Template_v3.pdf",
    text_path: "upload://kr1807/01_Standard_SPA_Template_v3.txt",
    sha256: "sample-standard-spa-v3",
    extracted_text:
      "MAG / KETURAH Approved SPA Template v3.0. Clause 5: All Buyer payments shall be deposited into the project escrow account maintained in accordance with Dubai Law No. (8) of 2007. Clause 13: Governed by laws of the Emirate of Dubai and UAE Courts. Clause 9: Structural defects 10 years from completion. Clause 7: Delay penalty 1%/month capped at 10%.",
    metadata: { source: "Standard SPA Template", version: "v3.0", role: "reference_standard" },
  },
  {
    id: "doc_deal_spa",
    name: "02_Deal_SPA_Unit_KR-1807.pdf",
    media_type: "application/pdf",
    storage_path: "upload://kr1807/02_Deal_SPA_Unit_KR-1807.pdf",
    text_path: "upload://kr1807/02_Deal_SPA_Unit_KR-1807.txt",
    sha256: "sample-deal-spa-kr1807",
    extracted_text:
      "SPA for Unit KR-1807, Keturah Reserve. Buyer: Mr. John A. Smith. Total price AED 6,500,000. Clause 5: Payments to Developer's nominated operating account. Clause 13: Courts of the Republic of Seychelles. Clause 9: Structural defects 5 years. Clause 7: Delay penalty 2%/month uncapped. Clause 4: No DLD/Oqood clause present.",
    metadata: { source: "Deal SPA", unit: "KR-1807", project: "Keturah Reserve", price_aed: 6500000 },
  },
  {
    id: "doc_payment_plan",
    name: "03_Payment_Plan_KR-1807.pdf",
    media_type: "application/pdf",
    storage_path: "upload://kr1807/03_Payment_Plan_KR-1807.pdf",
    text_path: "upload://kr1807/03_Payment_Plan_KR-1807.txt",
    sha256: "sample-payment-plan-kr1807",
    extracted_text:
      "Payment Plan KR-1807. Total price AED 6,500,000. Down payment 20% / AED 1,250,000 on signing. Milestone payments 70% across 6 stages. Handover 8% / AED 520,000. Stated total: 98% / AED 6,470,000. Milestone 7 due Q1 2028 (after anticipated completion Q4 2027).",
    metadata: { source: "Payment Plan", unit: "KR-1807", stated_total_pct: 98, stated_total_aed: 6470000 },
  },
  {
    id: "doc_kyc",
    name: "04_Buyer_KYC_Pack_KR-1807.pdf",
    media_type: "application/pdf",
    storage_path: "upload://kr1807/04_Buyer_KYC_Pack_KR-1807.pdf",
    text_path: "upload://kr1807/04_Buyer_KYC_Pack_KR-1807.txt",
    sha256: "sample-kyc-kr1807",
    extracted_text:
      "KYC Pack KR-1807. Passport: John Andrew Smithe, British, expiry 01 Aug 2026. Bank reference: J. A. Smithe, 14 Eaton Place London (differs from SPA address: Villa 9 Emirates Hills Dubai). Source/proof of funds: NOT PROVIDED. Signed reservation form: NOT ON FILE. Sanctions/PEP screening: NOT YET RUN.",
    metadata: { source: "Buyer KYC Pack", unit: "KR-1807", spa_buyer_name: "Mr. John A. Smith", passport_name: "John Andrew Smithe" },
  },
];

const documentById = new Map(sourceDocuments.map((document) => [document.id, document]));

function evidence(
  documentId: string,
  excerpt: string,
  options: Partial<EvidenceReference> = {},
): EvidenceReference {
  const document = documentById.get(documentId);
  return {
    id: `${documentId}_${String(options.chunk_id ?? "chunk_0")}`,
    document_id: documentId,
    document_name: document?.name ?? documentId,
    chunk_id: String(options.chunk_id ?? `${documentId}_chunk_0`),
    page: options.page ?? null,
    char_start: options.char_start ?? 0,
    char_end: options.char_end ?? excerpt.length,
    retrieval_score: options.retrieval_score ?? 0.94,
    support_level: options.support_level ?? "direct",
    citation_mode: options.citation_mode ?? "direct",
    source_type: options.source_type ?? "retrieved",
    text_excerpt: excerpt,
    metadata: options.metadata ?? {},
  };
}

function previousWork(sourceNodeId: string, sourceTitle: string, excerpt: string): EvidenceReference {
  return {
    id: `work_from_${sourceNodeId}`,
    document_id: `node:${sourceNodeId}`,
    document_name: `Work from previous node: ${sourceTitle}`,
    chunk_id: `previous_node_${sourceNodeId}`,
    page: null,
    char_start: null,
    char_end: null,
    retrieval_score: null,
    support_level: "derived",
    citation_mode: "previous_node",
    source_type: "previous_node",
    text_excerpt: excerpt,
    metadata: { source_node_id: sourceNodeId, source_node_title: sourceTitle },
  };
}

function approvalState(requiredApprovals = 0, approvedCount = 0): ApprovalState {
  const pendingApprovals = Math.max(requiredApprovals - approvedCount, 0);
  return {
    required_approvals: requiredApprovals,
    approved_count: approvedCount,
    pending_approvals: pendingApprovals,
    requires_human_review: pendingApprovals > 0,
    status: requiredApprovals === 0 ? "not_required" : pendingApprovals > 0 ? "pending" : "approved",
  };
}

function node(config: {
  id: string;
  title: string;
  subtitle: string;
  operation_type: string;
  instruction: string;
  thought_summary: string;
  reasoning_trace: string;
  output: Record<string, unknown>;
  evidence_refs?: EvidenceReference[];
  depends_on?: string[];
  next_nodes?: string[];
  priority?: number;
  status?: GraphNode["status"];
  verification_status?: GraphNode["verification_status"];
  verification_checks?: string[];
  required_approvals?: number;
  approved_count?: number;
  executor_type?: string;
  executor_profile?: string | null;
  skill_artifact_id?: string;
  latency_ms?: number | null;
  demo_copilot_paragraph?: string;
  demo_skill_result?: Record<string, unknown>;
  row?: number;
  column?: number;
}): GraphNode {
  const requiredApprovals = config.required_approvals ?? 0;
  const approvedCount = config.approved_count ?? requiredApprovals;
  const approvals = approvalState(requiredApprovals, approvedCount);
  return {
    id: config.id,
    title: config.title,
    subtitle: config.subtitle,
    operation_type: config.operation_type,
    instruction: config.instruction,
    success_criteria: ["Conclusion is evidence-linked", "Verification status is visible"],
    evaluation_ids: ["output_present", "evidence_grounded"],
    priority: config.priority ?? 50,
    status: config.status ?? "completed",
    verification_status:
      config.verification_status ?? (approvals.pending_approvals > 0 ? "pending" : "passed"),
    verification_checks:
      config.verification_checks ??
      (approvals.pending_approvals > 0
        ? ["Awaiting reviewer approval before final verification is recorded."]
        : ["Evidence references resolved.", "Output schema matched.", "Downstream dependency update recorded."]),
    depends_on: config.depends_on ?? [],
    guarded_by: [],
    next_nodes: config.next_nodes ?? [],
    evidence_refs: config.evidence_refs ?? [],
    finding_records: [],
    inputs: {},
    output: config.output,
    reasoning_trace: config.reasoning_trace,
    executor_type: config.executor_type ?? "llm_operator",
    executor_profile: config.executor_profile ?? "general",
    max_child_agents: 0,
    max_recursion_depth: 0,
    child_token_budget: 0,
    delegated_summary_required: false,
    thought_summary: config.thought_summary,
    evaluation_score: approvals.pending_approvals > 0 ? 0.82 : 0.96,
    approval_state: approvals,
    evidence_scope: {},
    model_metadata: {
      provider: "k2think",
      model_id: "MBZUAI-IFM/K2-Think-v2",
      model_version: "K2-Think-v2 replay",
    },
    delegated_children: [],
    patch_history: config.skill_artifact_id ? ["skill_deployed"] : [],
    required_approvals: requiredApprovals,
    metadata: {
      layout: { column: config.column ?? 0, row: config.row ?? 0 },
      skill_artifact_id: config.skill_artifact_id,
      demo_explanation: config.thought_summary,
      demo_copilot_paragraph: config.demo_copilot_paragraph,
      demo_skill_result: config.demo_skill_result,
      requires_human_review: requiredApprovals > 0,
    },
    created_at: now(),
    started_at: now(),
    completed_at: config.status === "pending" || config.status === "blocked" ? null : now(),
    latency_ms: config.latency_ms ?? 450,
  };
}

// Evidence anchors
const standardEscrowEvidence = evidence(
  "doc_standard_spa",
  "Clause 5: All Buyer payments shall be deposited into the project escrow account maintained in accordance with Dubai Law No. (8) of 2007. The Developer shall not draw funds except as permitted by the escrow agent against verified construction progress. This clause is mandatory and may not be amended.",
  { chunk_id: "standard_cl5_escrow", retrieval_score: 0.993 },
);

const standardJurisdictionEvidence = evidence(
  "doc_standard_spa",
  "Clause 13: This Agreement is governed by the laws of the Emirate of Dubai and the UAE, and the Dubai Courts (or DIFC Courts where expressly agreed in writing) have jurisdiction. Foreign jurisdiction is not permitted without SEVC + Legal approval.",
  { chunk_id: "standard_cl13_jurisdiction", retrieval_score: 0.988 },
);

const dealEscrowEvidence = evidence(
  "doc_deal_spa",
  "Clause 5: All Buyer payments shall be deposited into the Developer's nominated operating account as advised in writing. Note: does not reference the project escrow account or Law No. 8 of 2007.",
  { chunk_id: "deal_cl5_escrow", retrieval_score: 0.991 },
);

const dealJurisdictionEvidence = evidence(
  "doc_deal_spa",
  "Clause 13: This Agreement is governed by the laws of, and subject to the exclusive jurisdiction of, the Courts of the Republic of Seychelles.",
  { chunk_id: "deal_cl13_jurisdiction", retrieval_score: 0.987 },
);

const paymentPlanEvidence = evidence(
  "doc_payment_plan",
  "Stated total: 98% / AED 6,470,000. Down payment (on signing): 20% / AED 1,250,000. Milestone 7 due Q1 2028. Anticipated completion: Q4 2027.",
  { chunk_id: "payment_plan_summary", retrieval_score: 0.982 },
);

const kycNameEvidence = evidence(
  "doc_kyc",
  "SPA buyer name: Mr. John A. Smith. Passport holder: John Andrew Smithe. Bank reference account holder: J. A. Smithe.",
  { chunk_id: "kyc_name_comparison", retrieval_score: 0.976 },
);

const kycFundsEvidence = evidence(
  "doc_kyc",
  "Source / proof of funds: NOT PROVIDED. Signed reservation form: NOT ON FILE. Sanctions / PEP screening: NOT YET RUN.",
  { chunk_id: "kyc_aml_gaps", retrieval_score: 0.984 },
);

const spaNodes: GraphNode[] = [
  node({
    id: "intake_scope",
    title: "Document Intake & Scope",
    subtitle: "Identify deal SPA, payment plan, KYC, and standard template",
    operation_type: "generate",
    instruction: "Identify and list all documents in the uploaded evidence set and confirm the reference standard.",
    thought_summary: "Maps all four uploaded documents to their roles before any analysis begins.",
    reasoning_trace:
      "Identified four documents in the evidence set: (1) Standard SPA Template v3.0 — the approved reference standard; (2) Deal SPA Unit KR-1807 — the instrument under review; (3) Payment Plan KR-1807 — the financial schedule; (4) Buyer KYC Pack KR-1807 — the identity and AML file. Property reference: Unit KR-1807, Keturah Reserve. Buyer: Mr. John A. Smith. Total purchase price: AED 6,500,000. Anticipated completion: Q4 2027. Reference standard confirmed as 01_Standard_SPA_Template_v3.",
    output: {
      unit: "KR-1807",
      project: "Keturah Reserve",
      buyer: "Mr. John A. Smith",
      purchase_price_aed: 6500000,
      reference_standard: "01_Standard_SPA_Template_v3",
      documents_identified: [
        "01_Standard_SPA_Template_v3.pdf (reference standard)",
        "02_Deal_SPA_Unit_KR-1807.pdf (deal instrument)",
        "03_Payment_Plan_KR-1807.pdf (payment schedule)",
        "04_Buyer_KYC_Pack_KR-1807.pdf (KYC/AML file)",
      ],
    },
    evidence_refs: [standardEscrowEvidence, dealEscrowEvidence, paymentPlanEvidence, kycFundsEvidence],
    next_nodes: ["term_extraction"],
    priority: 10,
    row: 0,
    column: 1,
  }),
  node({
    id: "term_extraction",
    title: "SPA Term Extraction",
    subtitle: "Extract parties, price, payment schedule, key clause terms",
    operation_type: "analyze",
    instruction: "Extract all structured key terms from the deal SPA and payment plan to feed downstream verification nodes.",
    thought_summary:
      "Extracts parties, price, schedule percentages, jurisdiction, DLP, and delay-penalty terms — feeding all four downstream verify nodes.",
    reasoning_trace:
      "Extracted key terms: Seller = MAG Property Development LLC; Buyer = Mr. John A. Smith; Unit KR-1807, Keturah Reserve, Plot 442, 2,140 sq ft; Price = AED 6,500,000. Payment schedule: Down 20% (AED 1,250,000), 6 construction milestones (10% each), Handover 8% (AED 520,000), stated total 98%. Completion: Q4 2027. Key deviating clauses: Clause 4 (DLD/Oqood — absent), Clause 5 (payments to operating account, not escrow), Clause 7 (penalty 2%/month uncapped), Clause 9 (structural DLP 5 years), Clause 13 (Seychelles jurisdiction). Full term set passed to four parallel verification nodes.",
    output: {
      parties: { seller: "MAG Property Development LLC", buyer: "Mr. John A. Smith" },
      unit: "KR-1807, Keturah Reserve, Plot 442, 2,140 sq ft",
      purchase_price_aed: 6500000,
      payment_schedule_summary: "Down 20%, 6×10% milestones, Handover 8% — stated total 98%",
      completion_date: "Q4 2027",
      clauses_flagged_for_review: [
        "Clause 4 (DLD/Oqood absent)",
        "Clause 5 (payment account — no escrow reference)",
        "Clause 7 (delay penalty 2%/month uncapped)",
        "Clause 9 (structural DLP 5 years)",
        "Clause 13 (Seychelles jurisdiction)",
      ],
    },
    evidence_refs: [dealEscrowEvidence, paymentPlanEvidence],
    depends_on: ["intake_scope"],
    next_nodes: ["clause_deviation_check", "payment_plan_validation", "kyc_aml_check", "compliance_check"],
    priority: 20,
    row: 1,
    column: 1,
    demo_copilot_paragraph:
      "Term extraction is the shared planning node before the four parallel verification branches. Its job is to produce a structured, citable record of everything in the deal SPA and payment plan so downstream nodes can compare against the standard rather than re-parsing raw documents. The five clause flags it identified (Clauses 4, 5, 7, 9, 13) are exactly the ones the clause-deviation checker will examine in detail. This node also anchors the payment schedule numbers (AED 1,250,000 down payment at '20%', total 98%) that the payment-plan validator will recompute.",
  }),
  node({
    id: "clause_deviation_check",
    title: "Clause Deviation Checker",
    subtitle: "Compare deal SPA vs approved standard template clause-by-clause",
    operation_type: "verify",
    instruction: "Compare the deal SPA against the standard template and flag every clause deviation with citation and authority routing.",
    thought_summary:
      "Compared all 14 clauses; found 6 deviations — two Critical (escrow, jurisdiction), three High (structural DLP, uncapped delay penalty, missing Oqood), one Medium (handover % short).",
    reasoning_trace:
      "Performed clause-by-clause comparison against Standard SPA Template v3.0. D1 (Critical): Clause 5 routes payments to Developer's operating account — the mandatory escrow reference to Dubai Law No. 8 of 2007 is absent; routes to SEVC + Legal. D2 (Critical): Clause 13 jurisdiction is Courts of the Republic of Seychelles; standard requires Dubai Courts; routes to SEVC + Legal. D3 (High): Clause 9 structural DLP is 5 years; mandatory 10 years under UAE law; routes to SEVC + Legal. D4 (High): Clause 7 delay penalty is 2%/month uncapped; standard is 1%/month capped at 10%; routes to SEVC + FC. D5 (High): Clause 4 — no DLD/Oqood interim-registration clause present at all; routes to SEVC + Legal. D6 (Medium): Clause 3 handover payment is 8% vs standard 10%; routes to FC. Clauses 1, 2, 6, 8, 10, 11, 12, 14 are compliant.",
    output: {
      clauses_reviewed: 14,
      deviations_found: 6,
      findings: [
        { id: "D1", severity: "Critical", clause: "Cl. 5", issue: "Payments to Developer's operating account — no escrow / no Law No. 8 of 2007", routes_to: "SEVC + Legal" },
        { id: "D2", severity: "Critical", clause: "Cl. 13", issue: "Jurisdiction = Courts of Seychelles (standard: Dubai Courts)", routes_to: "SEVC + Legal" },
        { id: "D3", severity: "High", clause: "Cl. 9", issue: "Structural DLP 5 years (mandatory 10 years under UAE law)", routes_to: "SEVC + Legal" },
        { id: "D4", severity: "High", clause: "Cl. 7", issue: "Delay penalty 2%/month uncapped (standard: 1%/month capped at 10%)", routes_to: "SEVC + FC" },
        { id: "D5", severity: "High", clause: "Cl. 4", issue: "DLD/Oqood interim-registration clause entirely absent", routes_to: "SEVC + Legal" },
        { id: "D6", severity: "Medium", clause: "Cl. 3", issue: "Handover payment 8% (standard 10%)", routes_to: "FC" },
      ],
    },
    evidence_refs: [standardEscrowEvidence, dealEscrowEvidence, standardJurisdictionEvidence, dealJurisdictionEvidence],
    depends_on: ["term_extraction"],
    next_nodes: ["risk_aggregation"],
    priority: 30,
    row: 2,
    column: 0,
    demo_copilot_paragraph:
      "This node retrieved the standard SPA template from the knowledge base and compared it against the deal SPA clause-by-clause. The two Critical findings — escrow non-compliance (D1) and Seychelles jurisdiction (D2) — are both SEVC-level issues because the authority matrix routes anything touching escrow, governing law, or statutory clauses to SEVC + Legal. These are not drafting preferences; D1 means buyer funds would flow to the developer's own operating account instead of a RERA-regulated escrow account, and D2 means dispute resolution happens offshore under non-UAE law. Every finding is cited to the exact clause in both the deal and the standard — click any finding in the inspector to see the source text.",
  }),
  node({
    id: "payment_plan_validation",
    title: "Payment Plan Validator",
    subtitle: "Recompute schedule totals and verify down-payment AED",
    operation_type: "verify",
    instruction: "Recompute schedule percentages, cross-check down-payment AED, and verify milestone sequencing.",
    thought_summary:
      "Recomputed schedule: sums to 98% — AED 130,000 unallocated. Down payment AED 1,250,000 = 19.23%, not 20%. Milestone 7 due Q1 2028, after completion Q4 2027.",
    reasoning_trace:
      "Recomputed schedule against AED 6,500,000: Down 20% = AED 1,300,000 expected but AED 1,250,000 stated (AED 50,000 short, 19.23%). Six milestones × 10% = 60%. Handover 8%. Sum = 20 + 60 + 8 = 88% from stated amounts? Re-check: 20+10+10+10+10+10+10+8 = 88% — wait, stated total = 98%. Checking: Down 20% + 6×10% (milestones 2-7) + Handover 8% = 20+60+8 = 88%; but stated total is 98%. Milestones: rows 2-7 are 10%×6 = 60%, plus down 20% plus handover 8% = 88%. Discrepancy: stated 98% vs computed 88%? Actually re-reading: milestones are Foundation (10%), Structure (10%), MEP (10%), Façade (10%), Fit-out (10%), Pre-handover (10%) = 60%, plus Down 20% + Handover 8% = 88%. But document states 98%. The anomaly is: schedule sums to 98% per stated figures, but 20+70+8=98 from clause 3. Payment plan rows sum to 88% not 98 — a 2% gap left unallocated across the milestones. P1 (High): Schedule sums to 98% — 2% / AED 130,000 unallocated. P2 (High): Down payment AED 1,250,000 = 19.23% of AED 6,500,000, not 20% as stated — AED 50,000 short. P3 (Medium): Milestone 7 due Q1 2028, after anticipated completion Q4 2027 — post-completion installment is a sequencing error.",
    output: {
      purchase_price_aed: 6500000,
      stated_total_pct: 98,
      computed_total_pct: 98,
      down_payment_stated_pct: 20,
      down_payment_stated_aed: 1250000,
      down_payment_computed_pct: 19.23,
      down_payment_expected_aed: 1300000,
      shortfall_aed: 50000,
      errors: [
        "P1 (High): Schedule sums to 98% — 2% / AED 130,000 unallocated; must total 100%",
        "P2 (High): Down payment AED 1,250,000 = 19.23%, not 20% — AED 50,000 short of AED 1,300,000",
        "P3 (Medium): Milestone 7 due Q1 2028 — after anticipated completion Q4 2027 (sequencing error)",
      ],
    },
    evidence_refs: [paymentPlanEvidence],
    depends_on: ["term_extraction"],
    next_nodes: ["risk_aggregation"],
    priority: 31,
    row: 2,
    column: 1,
    demo_copilot_paragraph:
      "The payment plan validator used arithmetic rather than LLM judgment for the core checks — which is why the calculator tool is listed in evidence. P1 and P2 interact: if the down payment were corrected to AED 1,300,000 (the true 20% of AED 6.5M), that alone closes AED 50,000 of the AED 130,000 gap. The remaining gap requires either a new milestone or a larger handover amount. P3 is a sequencing issue: the pre-handover milestone falls after the anticipated completion date, which creates a contractual ambiguity about whether the developer can draw that payment after handover. All three are FC-level findings; they are financial/payment terms that sit below the SEVC threshold unless they affect price, in which case SEVC sign-off is needed.",
  }),
  node({
    id: "kyc_aml_check",
    title: "KYC / AML Verification",
    subtitle: "Name mismatch, source-of-funds gaps, screening status",
    operation_type: "verify",
    instruction: "Verify buyer identity, source-of-funds, screening, and address consistency across KYC documents.",
    thought_summary:
      "Found 6 KYC/AML flags: source-of-funds missing (Critical), name mismatch, screening not run (both High), address inconsistency, missing reservation form (Medium), near-expiry passport (Low).",
    reasoning_trace:
      "K1 (Critical): Source / proof of funds not provided — this is a mandatory AML requirement for a AED 6.5M transaction; routes to Compliance. K2 (High): Buyer name mismatch — SPA states 'Mr. John A. Smith' vs passport 'John Andrew Smithe' vs bank letter 'J. A. Smithe'; three documents, three name variants; routes to Compliance. K3 (High): Sanctions / PEP screening not yet run — cannot execute a transaction without a clean screen on a property of this value; routes to Compliance. K4 (Medium): Bank reference letter address is 14 Eaton Place, London, UK; SPA notice address is Villa 9, Emirates Hills, Dubai — inconsistency raises residence questions; routes to Compliance. K5 (Medium): Signed reservation form not on file — standard requirement before SPA execution; routes to Sales ops. K6 (Low): Passport expiry 01 Aug 2026 — within 12 months, near-term renewal needed before handover Q4 2027; routes to Sales ops.",
    output: {
      kyc_flags: [
        { id: "K1", severity: "Critical", issue: "Source / proof of funds not provided (AML requirement)", routes_to: "Compliance" },
        { id: "K2", severity: "High", issue: "Name mismatch — SPA 'John A. Smith' vs passport 'John Andrew Smithe' vs bank 'J. A. Smithe'", routes_to: "Compliance" },
        { id: "K3", severity: "High", issue: "Sanctions / PEP screening not run", routes_to: "Compliance" },
        { id: "K4", severity: "Medium", issue: "Bank reference address (London) ≠ SPA notice address (Dubai)", routes_to: "Compliance" },
        { id: "K5", severity: "Medium", issue: "Signed reservation form missing", routes_to: "Sales ops" },
        { id: "K6", severity: "Low", issue: "Passport expires 01 Aug 2026 — near-term; expires before handover Q4 2027", routes_to: "Sales ops" },
      ],
    },
    evidence_refs: [kycNameEvidence, kycFundsEvidence],
    depends_on: ["term_extraction"],
    next_nodes: ["risk_aggregation"],
    priority: 32,
    row: 2,
    column: 2,
    demo_copilot_paragraph:
      "The KYC node cross-checked buyer identity across three documents and found three different name variants — the SPA, the passport, and the bank reference do not agree. For a AED 6.5M property transaction the absence of source-of-funds documentation (K1) is the single most serious KYC finding: the transaction cannot proceed through a RERA-regulated escrow account without it. The name mismatch (K2) is also blocking because DLD registration requires exact name matching between the SPA and the passport. K3 (no PEP/sanctions screen) is procedurally required before any SPA execution. Combined, K1–K3 are sufficient to HOLD the transaction on KYC grounds alone, independent of the legal clause deviations.",
  }),
  node({
    id: "compliance_check",
    title: "DLD / RERA / Escrow Compliance",
    subtitle: "Statutory requirement checklist for Dubai real estate",
    operation_type: "verify",
    instruction: "Check DLD registration, Oqood, escrow law reference, and statutory DLP against Dubai real-estate law.",
    thought_summary:
      "Four statutory requirements checked: DLD/Oqood absent (Fail), escrow law reference absent (Fail), RERA delay remedy reference present (Pass), 10-year structural DLP not met (Fail).",
    reasoning_trace:
      "Dubai real-estate statutory compliance: (1) DLD Registration / Oqood: Standard Clause 4 requires the Developer to register with the Dubai Land Department and issue the Oqood interim registration. Deal Clause 4 is entirely absent — FAIL. (2) Escrow compliance under Dubai Law No. 8 of 2007: Standard Clause 5 requires all payments into the project escrow account per Law 8/2007. Deal Clause 5 routes to the Developer's operating account with no law reference — FAIL. (3) RERA regulations: Clause 8 references Dubai Law No. (13) of 2008 for buyer default — PASS (compliant). (4) Structural DLP: UAE Civil Transactions Law requires 10-year structural warranty. Deal Clause 9 specifies 5 years — FAIL. All three failures route to SEVC + Legal as they touch statutory clauses.",
    output: {
      compliance_results: [
        { requirement: "DLD Registration & Oqood (Clause 4)", status: "FAIL", detail: "Clause entirely absent from deal SPA", routes_to: "SEVC + Legal" },
        { requirement: "Escrow — Dubai Law No. 8/2007 (Clause 5)", status: "FAIL", detail: "Payments routed to Developer's operating account; escrow law reference absent", routes_to: "SEVC + Legal" },
        { requirement: "RERA buyer default reference (Clause 8)", status: "PASS", detail: "Dubai Law No. 13/2008 referenced correctly", routes_to: null },
        { requirement: "10-year structural DLP — UAE law (Clause 9)", status: "FAIL", detail: "5-year DLP stated; 10 years mandatory under UAE Civil Transactions Law", routes_to: "SEVC + Legal" },
      ],
    },
    evidence_refs: [standardEscrowEvidence, dealEscrowEvidence],
    depends_on: ["term_extraction"],
    next_nodes: ["risk_aggregation"],
    priority: 33,
    row: 2,
    column: 3,
    demo_copilot_paragraph:
      "The compliance node checks statutory requirements that are not optional — they are mandated by Dubai and UAE law. The escrow failure (Dubai Law No. 8 of 2007) is the most consequential: if buyer payments flow to the developer's operating account rather than a RERA-regulated escrow account, the buyer has no legal protection against the developer drawing funds without verified construction progress. The DLD/Oqood failure means the transaction cannot be formally registered on title, which exposes the buyer to the risk that the unit is sold to another buyer. The 5-year structural DLP failure is a statutory warranty reduction that cannot be contractually waived under UAE Civil Transactions Law. All three are SEVC + Legal escalations.",
  }),
  node({
    id: "risk_aggregation",
    title: "Risk Aggregation",
    subtitle: "Severity-ranked findings and authority routing",
    operation_type: "aggregate",
    instruction: "Consolidate all findings and apply the HOD→FC→SEVC authority matrix to determine required approval tier.",
    thought_summary:
      "Consolidated 15 findings: 3 Critical (escrow D1, jurisdiction D2, source-of-funds K1), 7 High, 3 Medium, 2 Low. Highest authority: SEVC + Legal + Compliance. Recommendation: HOLD.",
    reasoning_trace:
      "Aggregated 15 findings across four verification nodes. Critical tier (3): D1 escrow non-compliance (SEVC + Legal), D2 Seychelles jurisdiction (SEVC + Legal), K1 source-of-funds missing (Compliance). High tier (7): D3 structural DLP 5yr (SEVC + Legal), D4 uncapped delay penalty (SEVC + FC), D5 Oqood absent (SEVC + Legal), P1 schedule 98% (FC), P2 down payment short (FC), K2 name mismatch (Compliance), K3 screening not run (Compliance). Medium tier (3): D6 handover %, P3 milestone sequencing, K4 address inconsistency. Low tier (2): K5 reservation form, K6 passport expiry. Authority routing: because findings touch escrow (D1), governing law (D2), statutory warranties (D3, D5), and price/payment totals (P1, P2), the matrix routes to SEVC + Legal + Compliance — above HOD and FC authority. Overall recommendation: HOLD — do not execute.",
    output: {
      total_findings: 15,
      critical_count: 3,
      high_count: 7,
      medium_count: 3,
      low_count: 2,
      required_authority: "SEVC + Legal + Compliance",
      recommendation: "HOLD — do not execute",
      sevc_routing_reasons: [
        "D1 (escrow) — mandatory clause, may not be amended",
        "D2 (jurisdiction) — foreign jurisdiction requires SEVC + Legal approval",
        "D3 (structural DLP) — statutory warranty under UAE law",
        "D5 (Oqood absent) — statutory registration requirement",
      ],
    },
    evidence_refs: [
      previousWork("clause_deviation_check", "Clause Deviation Checker", "6 deviations: 2 Critical, 3 High, 1 Medium."),
      previousWork("payment_plan_validation", "Payment Plan Validator", "3 errors: 98% total, down payment short, sequencing error."),
      previousWork("kyc_aml_check", "KYC / AML Verification", "6 flags: 1 Critical, 2 High, 2 Medium, 1 Low."),
      previousWork("compliance_check", "DLD / RERA / Escrow Compliance", "3 failures: Oqood absent, escrow law absent, DLP 5 years."),
    ],
    depends_on: ["clause_deviation_check", "payment_plan_validation", "kyc_aml_check", "compliance_check"],
    next_nodes: ["human_review"],
    priority: 50,
    row: 3,
    column: 1,
    demo_copilot_paragraph:
      "Risk aggregation is the first convergence node after the four parallel verification branches. It does not run any new analysis — its job is to apply the authority matrix to the full finding set and produce a single routing decision. The key pattern is that the matrix escalates based on the nature of the deviations, not just their count. One escrow finding (D1) is sufficient to escalate to SEVC because the authority matrix explicitly routes anything touching escrow, governing law, or statutory clauses to SEVC + Legal. The result is HOLD: 3 Critical findings, 7 High findings, escrow non-compliance, offshore jurisdiction, and AML gaps collectively mean no money or title action should proceed without SEVC sign-off and Compliance clearance.",
  }),
  node({
    id: "human_review",
    title: "Authority Gate (HOD / FC / SEVC)",
    subtitle: "Human approval required before deal brief can be issued",
    operation_type: "verify",
    instruction: "Review aggregated risk findings and approve before deal brief synthesis can proceed.",
    thought_summary:
      "Execution paused — awaiting reviewer approval. Findings touch escrow, governing law, and statutory warranties; SEVC + Legal + Compliance sign-off required.",
    reasoning_trace:
      "The authority gate has paused execution. The risk aggregation node determined that findings D1 (escrow), D2 (jurisdiction), D3 (structural DLP), and D5 (Oqood) all touch SEVC-level categories per the authority matrix: price, jurisdiction, escrow, and statutory clauses. Additionally, K1 (source-of-funds) is a Compliance block. No deal brief can be issued and no money or title action can proceed without a human reviewer approving this gate. Required approvals: 1. Current approved count: 0.",
    output: {
      approval_status: "PENDING",
      required_authority: "SEVC + Legal + Compliance",
      sevc_trigger_reasons: [
        "Escrow clause deviation (D1) — statutory, may not be amended",
        "Foreign jurisdiction (D2) — Seychelles courts",
        "Statutory warranty reduced (D3) — structural DLP 5yr",
        "DLD/Oqood absent (D5) — statutory registration",
      ],
      instruction_to_reviewer: "Review the risk aggregation findings and approve to proceed with deal brief synthesis, or reject to halt the transaction.",
    },
    evidence_refs: [
      previousWork("risk_aggregation", "Risk Aggregation", "15 findings: 3 Critical, 7 High. Recommendation: HOLD."),
    ],
    depends_on: ["risk_aggregation"],
    next_nodes: ["deal_brief_synthesis"],
    required_approvals: 1,
    approved_count: 0,
    status: "blocked",
    verification_status: "pending",
    verification_checks: ["Awaiting SEVC + Legal + Compliance approval before deal brief synthesis proceeds."],
    executor_type: "human_operator",
    executor_profile: "sevc_reviewer",
    latency_ms: null,
    priority: 60,
    row: 4,
    column: 1,
    demo_copilot_paragraph:
      "This is the governance gate. The system has paused here because the authority matrix requires SEVC + Legal + Compliance sign-off before any further action. In the demo, clicking 'Approve' as the reviewer allows the deal brief synthesis node to proceed. Clicking 'Reject' halts the transaction and records the decision in the audit package. The crucial point for the audience is that this pause is not a limitation — it is the control. Nothing irreversible (no money movement, no title action, no deal brief issued) can happen without a human being deliberately signing off. The full finding set, citations, and authority routing recommendation are visible to the reviewer before they decide.",
  }),
  node({
    id: "deal_brief_synthesis",
    title: "Deal Brief Synthesis",
    subtitle: "Schema-validated deal brief with findings, redlines, and recommendation",
    operation_type: "synthesize",
    instruction: "Produce the schema-validated deal brief with severity-ranked findings, payment validation, KYC flags, and suggested redlines.",
    thought_summary:
      "Terminal node pending human approval gate. Will produce deal brief matching deal_brief_schema_v1 once the authority gate is cleared.",
    reasoning_trace:
      "Synthesis pending human approval of the authority gate node. Once approved, this node will produce the final deal brief: unit reference KR-1807, buyer Mr. John A. Smith, price AED 6.5M, recommendation HOLD — do not execute. The brief will include: 15 severity-ranked findings with source-clause citations; payment schedule errors (98% total, AED 50,000 down-payment shortfall); 6 KYC/AML flags; and suggested redlines to restore the escrow clause, Dubai Courts jurisdiction, 10-year structural DLP, capped delay penalty, Oqood clause, and correct payment schedule.",
    output: {
      status: "Pending authority gate approval",
    },
    evidence_refs: [
      previousWork("human_review", "Authority Gate", "Awaiting human approval before synthesis proceeds."),
    ],
    depends_on: ["human_review"],
    next_nodes: [],
    status: "pending",
    verification_status: "pending",
    verification_checks: ["Waiting for authority gate approval before deal brief synthesis."],
    latency_ms: null,
    priority: 70,
    row: 5,
    column: 1,
  }),
];

const spaEdges: GraphEdge[] = [
  { source: "intake_scope", target: "term_extraction", kind: "execution" },
  { source: "term_extraction", target: "clause_deviation_check", kind: "verification_branch" },
  { source: "term_extraction", target: "payment_plan_validation", kind: "verification_branch" },
  { source: "term_extraction", target: "kyc_aml_check", kind: "verification_branch" },
  { source: "term_extraction", target: "compliance_check", kind: "verification_branch" },
  { source: "clause_deviation_check", target: "risk_aggregation", kind: "finding_input" },
  { source: "payment_plan_validation", target: "risk_aggregation", kind: "finding_input" },
  { source: "kyc_aml_check", target: "risk_aggregation", kind: "finding_input" },
  { source: "compliance_check", target: "risk_aggregation", kind: "finding_input" },
  { source: "risk_aggregation", target: "human_review", kind: "approval_route" },
  { source: "human_review", target: "deal_brief_synthesis", kind: "release_gate" },
];

export const mockTask: TaskRunResponse = {
  task_id: "kr1807-spa-review-demo",
  prompt: basePrompt,
  template_id: "spa_contract_to_cash_v1",
  program_id: "spa_contract_to_cash_v1",
  program_version: "1.0.0",
  domain: "legal_contracts",
  deterministic: true,
  determinism_mode: "best_effort_deterministic",
  control_level: "regulated",
  default_visibility_tier: "structured_reasoning_trace",
  model_id: "MBZUAI-IFM/K2-Think-v2",
  model_version: "K2-Think-v2 replay",
  provider_fingerprint: "k2think-replay-fingerprint",
  execution_endpoint: "https://api.k2think.ai/v1/chat/completions",
  prompt_hash: "kr1807-spa-prompt-hash",
  grs_hash: "kr1807-spa-grs-hash",
  execution_env_hash: "kr1807-env-hash",
  reproducibility_hash: "kr1807-repro-hash",
  status: "paused",
  created_at: now(),
  completed_at: null,
  source_documents: sourceDocuments,
  nodes: spaNodes,
  edges: spaEdges,
  execution_sequence: spaNodes.filter((n) => n.status === "completed").map((n) => n.id),
  evidence_graph_nodes: {
    claim_escrow_noncompliant: {
      id: "claim_escrow_noncompliant",
      kind: "claim",
      label: "Payments routed to Developer's operating account — escrow law absent",
      metadata: { severity: "critical", routes_to: "SEVC + Legal" },
    },
    claim_seychelles_jurisdiction: {
      id: "claim_seychelles_jurisdiction",
      kind: "claim",
      label: "Jurisdiction changed to Courts of Seychelles",
      metadata: { severity: "critical", routes_to: "SEVC + Legal" },
    },
    evidence_deal_cl5: {
      id: "evidence_deal_cl5",
      kind: "evidence",
      label: "Deal SPA Clause 5",
      metadata: { document_id: "doc_deal_spa", clause: "5" },
    },
    evidence_standard_cl5: {
      id: "evidence_standard_cl5",
      kind: "evidence",
      label: "Standard SPA Template Clause 5",
      metadata: { document_id: "doc_standard_spa", clause: "5" },
    },
  },
  evidence_graph_edges: [
    {
      source: "evidence_deal_cl5",
      target: "claim_escrow_noncompliant",
      relation: "supports",
      metadata: { support_level: "direct" },
    },
    {
      source: "evidence_standard_cl5",
      target: "claim_escrow_noncompliant",
      relation: "contradicts",
      metadata: { support_level: "direct" },
    },
  ],
  prompt_traces: [
    {
      trace_id: "trace_program_kr1807",
      phase: "program_synthesis",
      node_id: null,
      prompt: basePrompt,
      system_prompt: "You synthesize auditable reasoning programs for regulated contract review workflows.",
      context: { domain: "legal_contracts", template: "spa_contract_to_cash_v1" },
      params: { temperature: 0, seed: 7 },
      request_payload: { model: "MBZUAI-IFM/K2-Think-v2", temperature: 0, seed: 7 },
      response_payload: { program_id: "spa_contract_to_cash_v1", nodes: spaNodes.length },
      provider: "k2think",
      model_id: "MBZUAI-IFM/K2-Think-v2",
      model_version: "K2-Think-v2 replay",
      provider_fingerprint: "k2think-replay-fingerprint",
      endpoint: "https://api.k2think.ai/v1/chat/completions",
      prompt_hash: "kr1807-program-prompt-hash",
      response_hash: "kr1807-program-response-hash",
      created_at: now(),
    },
  ],
  planner_trace: {
    trace_id: "planner_kr1807",
    summary:
      "Created a contract-review reasoning graph: shared intake and term extraction, four parallel verification branches (clause deviation, payment validation, KYC/AML, compliance), risk aggregation with authority routing, human approval gate, and deal brief synthesis.",
    graph_shape_reason:
      "The four verification branches run in parallel after term extraction because they are independent checks on different aspects of the same document set. They converge at risk aggregation, which applies the authority matrix before routing to the human gate.",
    evidence_sources_available: sourceDocuments.map((document) => ({
      source_id: document.id,
      source_type: "document",
      label: document.name,
      detail: document.extracted_text,
    })),
    web_fallback_used: false,
    web_search_queries: [],
    candidate_graph_operations: [
      {
        operation: "parallel_verification_branches",
        disposition: "selected",
        rationale: "Four verification domains (clause, payment, KYC, compliance) are independent — parallel execution reduces latency.",
      },
      {
        operation: "authority_matrix_gate",
        disposition: "selected",
        rationale: "SEVC-level findings require a mandatory human gate before any deal brief is produced.",
      },
      {
        operation: "schema_validated_synthesis",
        disposition: "selected",
        rationale: "deal_brief_schema_v1 ensures the deal brief is machine-readable and exportable.",
      },
    ],
    node_decisions: spaNodes.map((n) => ({
      node_id: n.id,
      action: "created",
      reason: n.thought_summary ?? "Created as a reasoning checkpoint.",
    })),
    confidence: 0.96,
    unresolved_gaps: [],
    created_at: now(),
  },
  graph_patch_history: [],
  graph_version_history: [
    {
      version_id: "graph_version_kr1807_spa_review",
      program_version: "1.0.0",
      blueprint_hash: "kr1807-spa-blueprint-hash",
      created_by: "controller",
      reason: "Instantiated SPA contract-to-cash review graph for Unit KR-1807.",
      patch_id: null,
      parent_program_version: null,
      created_at: now(),
    },
  ],
  patch_diff_history: [],
  trace_access_history: [
    {
      task_id: "kr1807-spa-review-demo",
      viewer_id: "dashboard-user",
      viewer_role: "reviewer",
      requested_tier: "structured_reasoning_trace",
      effective_tier: "structured_reasoning_trace",
      entry_count: spaNodes.length,
      accessed_at: now(),
    },
  ],
  program_blueprint: {
    program_id: "spa_contract_to_cash_v1",
    version: "1.0.0",
    domain: "legal_contracts",
    policy: "priority_based",
    convergence_rule: "no_pending_nodes",
    nodes: spaNodes.map((n) => ({
      id: n.id,
      type: n.operation_type,
      next: n.next_nodes,
      required_approvals: n.required_approvals ?? 0,
      executor_type: n.executor_type,
    })),
  },
  output_schema_definition: {
    title: "deal_brief_schema_v1",
    type: "object",
    required: ["recommendation", "findings", "payment_validation", "kyc_flags", "suggested_redlines"],
  },
  final_output: {
    unit: "KR-1807",
    project: "Keturah Reserve",
    purchase_price_aed: 6500000,
    recommendation: "HOLD — do not execute",
    open_approval_gates: ["human_review"],
  },
  final_summary: {
    headline: "Unit KR-1807 · AED 6.5M · HOLD — do not execute",
    verdict: "SEVC + Legal + Compliance approval required",
    key_points: [
      "3 Critical findings: escrow non-compliance (no Law 8/2007 reference), Seychelles jurisdiction, and missing source-of-funds.",
      "Payment schedule sums to 98% — AED 130,000 unallocated; down payment AED 1,250,000 is AED 50,000 short of true 20%.",
      "Every finding is cited to the exact source clause in the deal SPA and the approved standard template.",
      "Execution paused at the HOD→FC→SEVC authority gate — nothing proceeds without a human signature.",
    ],
    metrics: [
      { label: "Findings", value: "15" },
      { label: "Critical", value: "3" },
      { label: "Price (AED)", value: "6,500,000" },
      { label: "Gate", value: "SEVC" },
    ],
  },
  graph_build_ms: 184,
  scheduler_metrics_ms: [38, 41, 39],
  pending_review_node_id: "human_review",
  review_history: [],
  schema_validation_logs: [],
  audit_package: {
    event_log: [
      {
        timestamp: now(),
        event: "reasoning_graph_loaded",
        message:
          "Loaded SPA contract-to-cash review graph for Unit KR-1807, Keturah Reserve. Four parallel verification branches converge at risk aggregation. Execution paused at SEVC authority gate with 3 Critical and 7 High findings.",
      },
    ],
  },
};

export const mockHistory: TaskRunListItem[] = [
  {
    task_id: "kr1807-spa-review-demo",
    prompt: basePrompt,
    status: "paused",
    template_id: "spa_contract_to_cash_v1",
    program_id: "spa_contract_to_cash_v1",
    domain: "legal_contracts",
    determinism_mode: "best_effort_deterministic",
    control_level: "regulated",
    created_at: now(),
    completed_at: null,
    final_summary: mockTask.final_summary,
  },
];

export const mockTemplates: TemplateSummary[] = [
  {
    template_id: "generated_from_requirements",
    name: "Generated From Requirements",
    description: "Synthesizes a reasoning program from the requirements reference and the user prompt.",
  },
  {
    template_id: "spa_contract_to_cash_v1",
    name: "SPA Contract-to-Cash Review",
    description: "Reviews a Sale & Purchase Agreement against the approved standard template — clause deviation, payment validation, KYC/AML, DLD/RERA compliance, and HOD→FC→SEVC approval gate.",
  },
  {
    template_id: "financial_audit_v1",
    name: "Financial Audit",
    description: "Split-and-converge audit reasoning workflow with evidence links, tool skills, and partner approval gate.",
  },
];

export const mockSkills: SkillArtifact[] = [
  {
    skill_id: "payment_plan_validator",
    version: "0.1.0",
    name: "Payment Plan Validator",
    description: "Recomputes payment schedule percentages and AED amounts against the total purchase price; flags arithmetic errors, shortfalls, and sequencing issues.",
    language: "python",
    skill_type: "checker",
    updated_at: now(),
    status: "active",
    entrypoint_filename: "main.py",
    code: [
      "import json",
      "import sys",
      "",
      "raw = sys.stdin.read() or '{}'",
      "payload = json.loads(raw)",
      "price = float(payload.get('purchase_price_aed', 0))",
      "milestones = payload.get('milestones', [])",
      "errors = []",
      "",
      "total_pct = sum(float(m.get('pct', 0)) for m in milestones)",
      "if abs(total_pct - 100.0) > 0.01:",
      "    errors.append(f'Schedule totals {total_pct:.2f}% — {100 - total_pct:.2f}% / AED {(100 - total_pct) * price / 100:,.0f} unallocated')",
      "",
      "for m in milestones:",
      "    stated_aed = float(m.get('amount_aed', 0))",
      "    stated_pct = float(m.get('pct', 0))",
      "    computed_aed = round(stated_pct * price / 100, 0)",
      "    if abs(stated_aed - computed_aed) > 1:",
      "        errors.append(f'{m[\"label\"]}: stated AED {stated_aed:,.0f} ≠ computed AED {computed_aed:,.0f} ({stated_pct}% of {price:,.0f})')",
      "",
      "print(json.dumps({'total_pct': total_pct, 'errors': errors, 'price': price}))",
    ].join("\n"),
    test_input: JSON.stringify(
      {
        purchase_price_aed: 6500000,
        milestones: [
          { label: "Down payment", pct: 20, amount_aed: 1250000 },
          { label: "Foundation", pct: 10, amount_aed: 650000 },
          { label: "Structure", pct: 10, amount_aed: 650000 },
          { label: "Handover", pct: 8, amount_aed: 520000 },
        ],
      },
      null,
      2,
    ),
    notes: ["Deployed to the Payment Plan Validator node.", "Flags 98% total and AED 50,000 down-payment shortfall on the KR-1807 demo pack."],
    suggested_node_executor: "tool_operator",
  },
];
