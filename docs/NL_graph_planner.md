# **Natural Language to Graph Patch Planner**

Implementation Guide for MindNerve Adaptive Reasoning

This document defines the steps required to implement natural-language change planning in MindNerve.

The goal is to allow a user or reviewer to request reasoning changes in plain language, such as:

* “Re-run the revenue analysis with more conservative assumptions”  
* “Expand the fraud branch”  
* “Add an internal controls review node”  
* “Exclude vendor payments under 10,000”  
* “Change the evidence scope to only audited statements”

and have the system translate those requests into:

1. a structured change intent  
2. a proposed graph patch  
3. a validated patch plan  
4. an optional approval/apply flow

This completes the missing usability layer on top of the existing structured graph patch engine.

---

# **1\. Objectives**

The NL-to-patch planner must:

* accept natural language change requests  
* convert them into structured change intents  
* compile intents into patch proposals  
* validate proposals against graph safety rules  
* present the patch for review before application  
* log all planning activity in the audit trail

This planner must not mutate the live graph directly.

All changes must flow through:

Natural Language Request  
    ↓  
Intent Parser  
    ↓  
Change Intent  
    ↓  
Patch Planner  
    ↓  
Patch Proposal  
    ↓  
Patch Validator  
    ↓  
Graph Patch Engine  
---

# **2\. Architectural Principle**

The planner must follow this rule:

No direct graph mutation from natural language.

Natural language is only used to generate a proposal, never to mutate the graph immediately.

This preserves:

* graph safety  
* auditability  
* reviewer control  
* deterministic change application

---

# **3\. Supported User Request Categories**

The planner should initially support a small set of request types.

These become intent classes.

Supported categories:

expand\_node  
rerun\_subtree  
add\_node  
remove\_node  
change\_policy  
change\_budget  
change\_evidence\_scope  
change\_executor  
rewire\_dependency

Example mapping:

| User Request | Intent Type |
| ----- | ----- |
| “Expand the fraud branch” | expand\_node |
| “Re-run only revenue analysis” | rerun\_subtree |
| “Add an internal controls check” | add\_node |
| “Exclude vendor payments under 10k” | change\_evidence\_scope |
| “Use a forensic agent on this node” | change\_executor |

---

# **4\. Define the Change Intent Model**

Create a ChangeIntent model.

Suggested fields:

intent\_id  
task\_id  
requested\_by  
requested\_at  
intent\_type  
target\_node\_id  
target\_scope  
payload  
reason  
confidence  
source\_text  
status

Field descriptions:

* intent\_id — unique identifier  
* task\_id — target reasoning task  
* requested\_by — user or reviewer ID  
* intent\_type — one of the supported intent classes  
* target\_node\_id — node being changed  
* target\_scope — subtree, graph-wide, or node-local  
* payload — structured parsed parameters  
* reason — normalized explanation  
* confidence — parser confidence score  
* source\_text — original NL request  
* status — proposed, approved, rejected, applied

---

# **5\. Implement Intent Parsing**

Create an IntentParserService.

Responsibilities:

1. receive a natural language request  
2. inspect the current graph context  
3. identify:  
   * target node  
   * intent type  
   * action parameters  
4. output a structured ChangeIntent

Example input:

"Re-run the revenue analysis with more conservative assumptions"

Example parsed intent:

{  
  "intent\_type": "rerun\_subtree",  
  "target\_node\_id": "revenue\_analysis",  
  "payload": {  
    "assumption\_profile": "conservative"  
  },  
  "reason": "User requested subtree re-execution with stricter assumptions.",  
  "confidence": 0.88  
}  
---

# **6\. Add Target Node Resolution**

The parser must resolve user references to graph nodes.

Examples:

* “fraud branch” → fraud\_analysis  
* “revenue section” → revenue\_analysis  
* “final opinion” → audit\_opinion

Implement a NodeReferenceResolver.

Responsibilities:

* map NL phrases to graph node IDs  
* use aliases, title matching, and semantic similarity  
* return ambiguity if multiple matches exist

Example ambiguity handling:

{  
  "status": "ambiguous",  
  "candidates": \["revenue\_analysis", "revenue\_validation"\]  
}  
---

# **7\. Build the Patch Planner**

Create a PatchPlannerService.

Responsibilities:

* take a ChangeIntent  
* translate it into one or more structured patch operations

Example:

intent: expand\_node(fraud\_analysis, expand\_subgraph)

becomes:

\[  
  {"type": "add\_node", "target": "fraud\_analysis", "payload": {...}},  
  {"type": "rewire\_dependency", "target": "fraud\_analysis", "payload": {...}},  
  {"type": "rerun\_subtree", "target": "fraud\_analysis", "payload": {...}}  
\]

The planner should output a PatchProposal.

Suggested fields:

proposal\_id  
intent\_id  
patches\[\]  
summary  
risk\_level  
requires\_approval  
planner\_confidence  
---

# **8\. Add Patch Proposal Explanation**

Every patch proposal should include a human-readable explanation.

Example:

"This proposal will expand the fraud\_analysis node into a subgraph,  
rerun the affected subtree, and leave unrelated branches unchanged."

This explanation is shown to the user or reviewer before applying the patch.

---

# **9\. Validate the Patch Proposal**

Before a patch is shown as ready, validate it with the existing graph patch validator.

Validation must check:

* no cycles created  
* verify gates preserved  
* no disconnected synthesis path  
* budget limits respected  
* target node exists  
* expansion contract allowed  
* executor change allowed by policy  
* approval required if high-risk

If validation fails, return:

{  
  "status": "invalid",  
  "errors": \[  
    "Patch would create a cycle in the graph"  
  \]  
}  
---

# **10\. Add Clarification Flow for Low Confidence**

If parser confidence is low or node resolution is ambiguous:

* do not generate a final patch  
* return clarification request

Example:

{  
  "status": "needs\_clarification",  
  "question": "Did you mean revenue\_analysis or revenue\_validation?"  
}

This is essential for safe operation.

---

# **11\. Add Planner API**

Create API endpoint:

POST /api/tasks/{task\_id}/plan-change

Request body:

{  
  "request\_text": "Expand the fraud branch and assign a forensic agent"  
}

Response body:

{  
  "intent": {...},  
  "proposal": {...},  
  "validation": {...},  
  "status": "proposed"  
}

Optional apply endpoint:

POST /api/tasks/{task\_id}/apply-planned-change

This should only accept an already-validated proposal ID.

---

# **12\. Add UI Flow**

Add change request controls to the task view.

Recommended flow:

1. user selects node or task  
2. enters natural language change request  
3. system returns:  
   * interpreted intent  
   * patch summary  
   * affected nodes  
   * rerun scope  
4. user or reviewer approves  
5. patch is applied

UI should display:

* original request text  
* interpreted target node  
* patch operations  
* explanation  
* validation warnings  
* approval requirement

---

# **13\. Audit and Logging Requirements**

Every planner interaction must be logged.

Store:

source\_text  
parsed\_intent  
planner\_confidence  
target\_node\_resolution  
patch\_proposal  
validation\_result  
approval\_decision  
applied\_patch\_id

This must be included in the audit package.

---

# **14\. Security and Safety Controls**

The NL-to-patch planner must never:

* apply changes automatically without validation  
* bypass approval gates  
* bypass verify nodes  
* change hidden policy defaults without explicit request  
* mutate strict-audit tasks without policy-compliant approval

Add control-level restrictions:

* exploratory — planner can suggest and apply low-risk changes  
* regulated — planner can suggest, reviewer must approve  
* strict\_audit — planner can suggest, but patches require stricter approval and trace logging

---

# **15\. Suggested Internal Modules**

Create a package:

backend/app/change\_planning/

Recommended files:

intent\_models.py  
intent\_parser.py  
node\_resolver.py  
patch\_planner.py  
proposal\_explainer.py  
validation\_bridge.py  
---

# **16\. Acceptance Criteria**

The NL-to-patch planner is complete when:

* common reviewer requests can be converted into valid patch proposals  
* ambiguous requests trigger clarification rather than unsafe patching  
* every patch proposal includes a human-readable explanation  
* no patch is applied without validation  
* all planning steps are auditable

Examples of accepted requests:

* “Expand the fraud branch”  
* “Re-run only the revenue analysis”  
* “Use a forensic agent on this node”  
* “Add a controls review node”  
* “Restrict evidence to audited financial statements”

---

# **17\. Recommended Implementation Order**

## **Step 1**

Implement ChangeIntent model

## **Step 2**

Implement node reference resolver

## **Step 3**

Implement intent parser for 3–4 basic request types:

* expand\_node  
* rerun\_subtree  
* add\_node  
* change\_executor

## **Step 4**

Implement patch planner

## **Step 5**

Integrate existing patch validator

## **Step 6**

Add planner API

## **Step 7**

Add patch proposal UI

## **Step 8**

Add clarification flow

## **Step 9**

Add full audit logging

---

# **18\. Final Outcome**

After completing this guide, MindNerve will support:

* natural language graph change requests  
* safe translation into structured patches  
* reviewer-friendly change previews  
* auditable graph adaptation

This closes the final missing usability gap in the graph patching architecture and completes the adaptive reasoning control loop.

