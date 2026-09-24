# Problem statement proposal

## 1. Problem definition

| TEAM NAME | TEAM CODE | VERSION / DATE |
|---|---|---|
| Mission Importable | W3KKD4FL | Final v5 / 25 September 2026 |

Registered team members: Li Chenxuan, Lu Junyi, Lai Wendi, Sun Zekun.

### Business problem

An employee preparing a monitor quotation must turn a customer's incomplete enquiry into a product choice and a price that a reviewer can check. A request such as "eight USB-C monitors under SGD 2,500" leaves important questions unanswered: whether USB-C must carry video and charge a laptop, the minimum charging wattage, and the preferred screen size and resolution.

The employee checks specifications, compares products, calculates quantities and discounts, and prepares a quotation. These steps can involve specification PDFs, price sheets and separate approval messages. Similar model names can conceal different capabilities. When the customer changes the quantity, the employee must recalculate the price and keep the earlier draft available for comparison.

### Users and operational impact

The primary user is a quotation employee in a small sales team. A reviewer checks the proposed product, commercial terms and final document. Missing requirements can cause unsuitable product choices, repeated clarification and quotation rework. Incorrect calculations or overwritten drafts can make a previous price difficult to explain. These are workflow risks to test during the pilot; no participating SME's loss or productivity baseline has been measured.

### Desired outcome and business value

The employee should prepare a quotation with fewer repeated checks and corrections. A reviewable draft must contain confirmed requirements, a suitable product with manufacturer evidence, a reproducible price and preserved revision history. The reviewer confirms the exact saved version used for PDF export.

The pilot will compare preparation time and reviewer corrections against the manual process. Any later labour-value estimate will use measured minutes saved per quote, monthly quotation volume and staff cost per minute. No financial saving is assumed in this proposal.

The pilot covers 50 Dell and Lenovo/ThinkVision monitor models and synthetic SGD prices. Inventory, delivery dates, tax and customer-specific contracts are outside the prototype's data. Staff must resolve those matters through the normal commercial process before making a customer commitment.

<!-- pagebreak -->

## 2. Problem statement selection

| TEAM NAME | TEAM CODE |
|---|---|
| Mission Importable | W3KKD4FL |

| # | Problem statement | 1st | 2nd | 3rd |
|---|---|---|---|---|
| 1 | Quotation Preparation | X | | |
| 2 | Supplier Comparison | | | |
| 3 | Managing WhatsApp Sales Enquiries | | | |
| 4 | Product Selection | | | |
| 5 | Inventory Monitoring | | | |
| 6 | Purchase Order Preparation | | | |
| 7 | Production Planning | | | |
| 8 | Technician Scheduling | | | |
| 9 | Service Report Preparation | | | |
| 10 | Client Document Collection | | | |
| 11 | Expense Classification | | | |
| 12 | Initial Client Consultation | | | |
| 13 | Design Inspiration | | | |
| 14 | Construction Progress Monitoring | | | |
| 15 | Site Inspection Documentation | | | |
| 16 | Delivery Planning | | | |
| 17 | Delivery Status Enquiries | | | |
| 18 | Demand Forecasting | | | |
| 19 | Kitchen Inventory Planning | | | |
| 20 | Appointment Management | | | |
| 21 | Patient Follow-up | | | |
| 22 | Training Proposal Preparation | | | |
| 23 | Resume Screening | | | |
| 24 | Candidate Matching | | | |
| 25 | Marketing Campaign Planning | | | |
| 26 | Property Recommendation | | | |
| 27 | Vehicle Fault Diagnosis | | | |
| 28 | Print Cost Estimation | | | |
| 29 | Farm Production Planning | | | |
| 30 | Business Performance Monitoring | | | |

### Product names for selected choices

| 1ST CHOICE PRODUCT NAME / PROJECT TITLE | 2ND CHOICE PRODUCT NAME / PROJECT TITLE | 3RD CHOICE PRODUCT NAME / PROJECT TITLE |
|---|---|---|
| Quotation Desk | Not selected | Not selected |

Quotation Preparation is the selected problem statement. Only the first choice is nominated.

<!-- pagebreak -->

## 3. Scope and proposed approach

The prototype already supports enquiry-to-PDF handling. The proposed two-week pilot tests it with one quotation employee and one reviewer. The eight-person-day estimate, alternating test order and acceptance targets below are proposed pilot arrangements, subject to staff availability.

| Milestone | Scope / deliverables | Assumptions | Estimated effort |
|---|---|---|---|
| 1st week scope | Confirm the manual workflow; prepare five de-identified pilot cases; freeze catalogue and prices; independently check at least 24 fields across 12 Lenovo models; rerun the 50-model Gateway evaluation. | An employee, reviewer and maintainer are available. Cases can be de-identified, and Gateway access is available. | 3 person-days |
| 2nd week scope | Run five matched pilot cases with alternating method order; record time, corrections and failures; verify confirmed PDFs. Separately complete the existing TIME-001 to TIME-005 timing protocol. | Both methods use the same data and rules. The frozen data remains suitable for all five cases. | 4 person-days |
| Final scope | Demonstrate enquiry-to-PDF handling and exception cases; deliver the comparison report and a reviewer decision on whether to extend the trial. | Failed cases are documented. Customer-facing deployment remains a separate decision. | 1 person-day |

### Proposed solution overview

Customer enquiries use varied wording and omit details needed for product selection. The Agent turns that wording into focused questions and structured catalogue searches. It retrieves candidate products with manufacturer evidence; the employee resolves the questions and selects a product. A deterministic tool calculates the price in integer cents and enforces the 5% demonstration discount limit.

The workbench preserves each saved draft and shows changes between versions. A reviewer can first confirm only the latest valid saved draft; older unconfirmed drafts are rejected. Previously confirmed snapshots remain exportable. Product-card selection initially creates a one-unit draft; the employee checks and restores the requested quantity before saving.

### Demonstration and exceptions

For eight Dell P2425HE units at a synthetic SGD 289 each, the draft total is SGD 2,312 at zero discount. Changing the quantity to ten produces SGD 2,890, exceeding a SGD 2,500 budget by SGD 390. The saved comparison records the SGD 578 increase and preserves the original draft.

A request for USB-C video and 90 W laptop charging must not accept Dell U2724D's data-only USB-C connection. The system may show a sourced alternative, but the employee selects it. A 6% discount request is blocked; a next-day delivery request remains unresolved because the catalogue has no delivery data.

### Evidence supporting the pilot

The data validation report records 50 models, 50 synthetic prices and 400 field-level evidence records from 44 official documents. The 15-step browser acceptance run covers clarification, quantity revision, version comparison and agreement between displayed, stored and PDF amounts.

Gateway evaluation on the earlier 12-model catalogue scored 10/20 on the first pass and 20/20 after fixes. Week 1 must complete the final 50-model Gateway evaluation and independent Lenovo evidence spot check before staff testing. Employee preparation time and rework remain unmeasured. Five matched cases can inform a larger trial; they cannot establish a lasting productivity gain.

<!-- pagebreak -->

## 4. Delivery, measurement and controls

### Data, tools and operating constraints

| Data or document | Source | Owner in pilot | Access status | Privacy or quality concern |
|---|---|---|---|---|
| Product facts and evidence | Dell and Lenovo official documents | Catalogue maintainer | 50 models; 400 evidence records | Verify model variants and source pages; independent Lenovo spot check pending. |
| Prices and discount rules | Synthetic SGD price table and demo policy | Pilot maintainer | Available; freeze for trial | No manufacturer pricing; maximum discount 5%; tax and stock unknown. |
| Enquiries and evaluation cases | Five new staff cases; existing TIME-001 to TIME-005 | Employee and reviewer | New cases to be de-identified | Keep pilot and fixed-case results separate; exclude evaluation answers from Agent context. |
| Saved drafts and confirmations | Workbench records in SQLite | Reviewer | Prototype available | Preserve versions; use de-identified data during the pilot. |

### AI models and tools

| Model / tool | Role in the proposal | Operating constraint |
|---|---|---|
| Organizer LLM Gateway | Interpret enquiries, ask questions and select tool calls | Use the configured model; log actual model and fallback status. Validate tool inputs. |
| search_products / get_product | Filter the catalogue; return product facts and evidence | Unknown fields cannot satisfy requirements; preserve exact model identity. |
| calculate_quote | Calculate totals and apply discount rules | Integer-cent arithmetic and a fixed rounding rule; reject discounts above 5%. |
| FastAPI, SQLite and PDF exporter | Run the workflow; store snapshots and confirmations; create PDFs | Export the confirmed snapshot; later conversation must not change its figures. |

### Integrations and manual fallback

The browser calls FastAPI, which connects the Agent to catalogue and pricing tools and stores drafts in SQLite. The existing deployment uses Nginx, systemd and AWS Lightsail. If Gateway access fails, the workbench identifies its deterministic offline path. Record those runs separately from real-model results. Staff can also check source documents and calculate a draft manually for reviewer approval.

### Agent / workflow roles

| Role | Responsibility | Input | Output | Escalate when |
|---|---|---|---|---|
| Quotation Agent | Clarify needs and call tools | Enquiry and user answers | Questions, sourced candidates and draft calculation | Requirements conflict, facts are missing or requested terms exceed policy. |
| Employee and reviewer | Select product, check quantity and confirm the latest valid saved draft | Evidence and saved drafts | Confirmed snapshot and PDF | Commercial terms are unresolved or evidence/calculations disagree. |

### Success measures

Pilot timing covers enquiry reading to a reviewable draft. The existing TIME-001 to TIME-005 protocol measures Driver call-to-result time for the Agent and manual preparation separately. Complete that protocol independently; new pilot cases do not replace it. Do not pool the two timing measures.

| Metric | Baseline | Target | How measured | Review period |
|---|---|---|---|---|
| Preparation time | Human baseline unmeasured | Lower assisted median, with all five assisted cases correct | Time enquiry to reviewable draft using matched cases and alternating order. Report median/range, failures and corrections; separate fallback runs. | Two-week pilot |
| Price and specification accuracy | Automated checks reported; staff baseline unmeasured | Every pilot amount reconciles; every selected specification has source evidence | Independently recalculate cents and inspect manufacturer pages. | Each pilot case |
| Policy and review | Prototype blocks demonstrated | Zero prohibited discounts, invented delivery promises or unconfirmed exports | Exercise exceptions and inspect confirmation/PDF records. | Each pilot case |
| Rework | Unmeasured | Fewer corrections, or zero in both methods | Count reviewer corrections and record staff feedback. | End of pilot |

### Risks, guardrails and human approval

| Risk | Consequence | Preventive control | Human owner |
|---|---|---|---|
| Unsupported product or price | Unsuitable or incorrect quotation | Field-level evidence, deterministic pricing and independent checks | Employee / reviewer |
| Unknown terms or stale data | Unreliable customer commitment | Freeze pilot data; resolve tax, stock and delivery outside the prototype | Catalogue maintainer / reviewer |
| Exposed customer information | Privacy loss | De-identify pilot inputs; add authenticated roles and HTTPS before commercial use | Pilot data owner |

The employee checks requirements, product and quantity; the reviewer confirms the latest valid saved draft. Authenticated roles remain a requirement for commercial use. The proposed extension criteria are five correct assisted pilot cases, a lower assisted median and no increase in corrections. Investigate failures before expansion.
