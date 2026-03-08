# **Sprint 1 — Deterministic Execution Hardening**

Goal: Ensure reproducible runs and complete execution metadata.

## **Tasks**

### **Deterministic Execution Metadata**

Implement full run metadata capture.

* Add DB fields:  
  * determinism\_mode  
  * control\_level  
  * model\_id  
  * model\_version  
  * provider\_fingerprint  
  * prompt\_hash  
  * grs\_hash  
  * execution\_env\_hash

### **Prompt Hashing**

Add SHA-256 hashing for:

prompt\_hash \= sha256(all\_node\_prompts)

**GRS Hashing**

Serialize and hash the reasoning state.

grs\_hash \= sha256(serialized\_graph\_reasoning\_state)  
​​**Environment Hash**

Capture runtime environment:

* Python version  
* dependency versions  
* runtime config

### **LLM Gateway Controls**

Enforce deterministic parameters:

temperature \= 0  
top\_p \= 1  
seed \= fixed if supported

**Store Prompt \+ Parameters**

Persist:

* prompt text  
* parameters  
* model name  
* model version

## **Acceptance Criteria**

* Two identical tasks produce identical GRS hash ≥80%  
* All deterministic metadata stored  
* Audit package includes metadata

---

# **Sprint 2 — Graph Replay and Diff Engine**

Goal: Enable reasoning replay and run comparison.

## **Tasks**

### **Snapshot Enhancement**

Ensure snapshots include:

* node inputs  
* node outputs  
* evidence references  
* prompts  
* model metadata

### **Replay Endpoint**

POST /tasks/{id}/replay  
Steps:

1. Load snapshot  
2. Rebuild GraphReasoningState  
3. Re-execute nodes  
4. Compare results

### **Graph Diff Engine**

Create a structured diff algorithm.

Detect:

* added nodes  
* removed nodes  
* changed inputs  
* changed outputs  
* changed prompts  
* changed evidence

### **UI Integration**

Add:

* “Compare with previous run”  
* Node-level diff highlighting

## **Acceptance Criteria**

* Any run can be replayed  
* Diff engine identifies changed nodes  
* UI shows meaningful comparison

---

# **Sprint 3 — Evidence Traceability System**

Goal: Provide complete evidence lineage from report to document.

## **Tasks**

### **EvidenceSpan Model**

Create object:

EvidenceSpan  
  document\_id  
  chunk\_id  
  page  
  offset\_start  
  offset\_end  
  retrieval\_score  
  citation\_type

Below is a structured sprint plan for completing the remaining Phase 1 governance features and implementing Phase 2 adaptive reasoning capabilities for MindNerve/MindWeave.

It assumes 1–2 week sprints with a small engineering team (1–3 backend engineers \+ optional frontend support).

The plan is designed so that each sprint produces a demonstrable capability rather than just infrastructure work.

---

# **MindNerve Implementation Sprint Plan**

## **Sprint Planning Principles**

The roadmap follows this logic:

1. Finish Phase 1 governance \+ audit completeness  
2. Add replayability and diffing  
3. Add safe reasoning visibility  
4. Enable controlled reasoning modification  
5. Introduce agent expansion  
6. Introduce approval workflows

This order ensures that adaptive reasoning never breaks auditability or determinism.

---

# **Sprint 1 — Deterministic Execution Hardening**

Goal: Ensure reproducible runs and complete execution metadata.

## **Tasks**

### **Deterministic Execution Metadata**

Implement full run metadata capture.

* Add DB fields:  
  * determinism\_mode  
  * control\_level  
  * model\_id  
  * model\_version  
  * provider\_fingerprint  
  * prompt\_hash  
  * grs\_hash  
  * execution\_env\_hash

### **Prompt Hashing**

Add SHA-256 hashing for:

prompt\_hash \= sha256(all\_node\_prompts)

### **GRS Hashing**

Serialize and hash the reasoning state.

grs\_hash \= sha256(serialized\_graph\_reasoning\_state)

### **Environment Hash**

Capture runtime environment:

* Python version  
* dependency versions  
* runtime config

### **LLM Gateway Controls**

Enforce deterministic parameters:

temperature \= 0  
top\_p \= 1  
seed \= fixed if supported

### **Store Prompt \+ Parameters**

Persist:

* prompt text  
* parameters  
* model name  
* model version

## **Acceptance Criteria**

* Two identical tasks produce identical GRS hash ≥80%  
* All deterministic metadata stored  
* Audit package includes metadata

---

# **Sprint 2 — Graph Replay and Diff Engine**

Goal: Enable reasoning replay and run comparison.

## **Tasks**

### **Snapshot Enhancement**

Ensure snapshots include:

* node inputs  
* node outputs  
* evidence references  
* prompts  
* model metadata

### **Replay Endpoint**

POST /tasks/{id}/replay

Steps:

1. Load snapshot  
2. Rebuild GraphReasoningState  
3. Re-execute nodes  
4. Compare results

### **Graph Diff Engine**

Create a structured diff algorithm.

Detect:

* added nodes  
* removed nodes  
* changed inputs  
* changed outputs  
* changed prompts  
* changed evidence

### **Diff API**

GET /tasks/{id1}/compare/{id2}

Return:

{  
  "changed\_nodes": \[\],  
  "added\_nodes": \[\],  
  "removed\_nodes": \[\]  
}

### **UI Integration**

Add:

* “Compare with previous run”  
* Node-level diff highlighting

## **Acceptance Criteria**

* Any run can be replayed  
* Diff engine identifies changed nodes  
* UI shows meaningful comparison

---

# **Sprint 3 — Evidence Traceability System**

Goal: Provide complete evidence lineage from report to document.

## **Tasks**

### **EvidenceSpan Model**

Create object:

EvidenceSpan  
  document\_id  
  chunk\_id  
  page  
  offset\_start  
  offset\_end  
  retrieval\_score  
  citation\_type

### **Modify Node Execution**

Require nodes to emit:

{  
  claim,  
  evidence\_spans\[\]  
}

### **Prompt Update**

Change prompts to request citations.

Example:

Provide supporting evidence references using document\_id and chunk\_id.

### **Document Processor Enhancement**

Capture:

* page numbers  
* character offsets  
* chunk metadata

### **Claim Classification**

Add claim types:

grounded  
inferred  
calculated  
human\_entered

### **Verification Rule**

Enforce:

grounded claim \-\> must include evidence

## **Acceptance Criteria**

* Every claim traceable to document  
* Evidence stored in audit package  
* Evidence lineage reconstructable

---

# **Sprint 4 — Three-Graph Architecture**

Goal: Explicitly separate reasoning artifacts.

## **Tasks**

### **Graph Types**

Implement:

1. Execution Graph

nodes \= executable steps  
edges \= dependencies

2. Thought Graph

nodes \= reasoning artifacts  
edges \= reasoning flow

3. Evidence Graph

nodes \= claims \+ evidence  
edges \= "supported\_by"

### **Controller Updates**

When node runs:

execution\_graph.add(node)  
thought\_graph.add(thought)  
evidence\_graph.add(claim → evidence)

### **Evidence Graph API**

GET /tasks/{id}/evidence-graph

### **Query Features**

Examples:

find\_claims\_by\_document(document\_id)  
trace\_claim\_to\_source(claim\_id)

## **Acceptance Criteria**

* All three graphs stored  
* Evidence lineage reconstructable via API

---

# **Sprint 5 — Reasoning Visibility Tiers**

Goal: Provide safe reasoning transparency.

## **Tasks**

### **Tier Definition**

LEVEL\_1\_SUMMARY  
LEVEL\_2\_STRUCTURED  
LEVEL\_3\_EXPANDED

### **Tenant Configuration**

Add:

tenant.default\_visibility\_tier

### **Program Configuration**

Add:

reasoning\_program.visibility\_tier

### **Task Override**

Allow:

task.visibility\_tier

### **API Filtering**

Level 1:

* node names  
* status  
* final result

Level 2:

* node inputs/outputs  
* verification  
* evidence links

Level 3:

* alternative branches  
* rejected nodes  
* raw reasoning

### **UI Integration**

Add:

* tier selector  
* tier indicators

## **Acceptance Criteria**

* Reasoning detail controlled by tier  
* Higher-tier data never exposed to lower-tier users

---

# **Sprint 6 — Run Classification & Governance**

Goal: Enforce operational risk levels.

## **Tasks**

### **Control Levels**

Add:

exploratory  
operational  
regulated  
strict\_audit

### **Policy Mapping**

Example:

strict\_audit:  
  determinism\_mode \= strict  
  approval\_required \= true  
  visibility\_tier \>= structured

### **Runtime Enforcement**

Before execution:

validate\_control\_constraints()

### **UI Indicators**

Show:

* control-level badge  
* warnings

## **Acceptance Criteria**

* Control-level policies enforced  
* Invalid tasks blocked

---

# **Sprint 7 — Graph Patching Engine (Phase 2 Start)**

Goal: Allow safe modification of reasoning graphs.

## **Tasks**

### **GraphPatch Model**

Fields:

patch\_id  
task\_id  
patch\_type  
target\_node  
payload  
reason  
approval\_status

### **Patch Types**

Support:

add\_node  
remove\_node  
replace\_node  
rewire\_dependency  
rerun\_subtree  
expand\_node

### **Patch Validation**

Reject patches that:

* create cycles  
* bypass verification  
* break graph connectivity

### **Patch Application**

Steps:

1. validate patch  
2. generate new graph version  
3. mark impacted nodes stale  
4. rerun subtree

### **Patch API**

POST /tasks/{id}/patch  
GET /tasks/{id}/patches

## **Acceptance Criteria**

* Users can modify reasoning  
* Only affected subtree reruns  
* Patch history logged

---

# **Sprint 8 — Node-Level Agent Delegation**

Goal: Allow deeper reasoning expansion.

## **Tasks**

### **Executor Types**

Add:

llm\_operator  
tool\_operator  
agent\_operator  
human\_operator

### **Agent Registry**

Store:

agent\_id  
capabilities  
supported\_node\_types

### **Delegation Policy**

max\_child\_agents  
max\_depth  
budget\_limit

### **Delegated Execution**

Agent must return:

summary  
findings  
evidence  
confidence

### **Delegation Audit**

Log:

* parent node  
* child agent  
* tools used

## **Acceptance Criteria**

* Nodes can delegate reasoning  
* Delegation bounded by policy  
* Activity fully auditable

---

# **Sprint 9 — Expansion Contracts**

Goal: Make node expansion predictable.

## **Tasks**

### **Expansion Modes**

expand\_summary  
expand\_evidence  
expand\_alternatives  
expand\_counterarguments  
expand\_calculations  
expand\_subgraph

### **Expansion Registry**

Define per node type.

### **Expansion API**

POST /tasks/{id}/nodes/{node\_id}/expand

### **Logging**

Log:

* expansion reason  
* resulting nodes

## **Acceptance Criteria**

* Node expansion deterministic  
* Unsupported expansions rejected

---

# **Sprint 10 — Approval Workflow Engine**

Goal: Enable enterprise governance.

## **Tasks**

### **Approval Policy**

approval\_required  
approval\_type  
approver\_roles  
deadline

### **Approval States**

pending  
approved  
rejected  
escalated

### **Controller Integration**

Block execution until approval.

### **Approval API**

POST /approvals/{id}/approve  
POST /approvals/{id}/reject

### **Notifications**

Notify:

* reviewer  
* backup reviewer

## **Acceptance Criteria**

* Approval gates enforced  
* Dual approval supported  
* Records immutable

---

