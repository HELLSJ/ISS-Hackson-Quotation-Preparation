# Quotation Desk business proposal

Show Me Your Agents Hackathon | September 2026

**Project:** Quotation Desk  
**Team code:** [Add registered team code]  
**Repository:** https://github.com/HELLSJ/ISS-Hackson-Quotation-Preparation  
**Live workbench:** http://47.131.151.253/

We seek a two-week pilot of Quotation Desk with one quotation employee and one reviewer. The workbench turns an incomplete monitor enquiry into a draft with manufacturer evidence, a calculated price, and a record of every saved version. Its current catalogue covers 50 Dell and Lenovo/ThinkVision models. The pilot would test whether staff can prepare correct quotes with less effort before the business considers customer-facing use.

## The business problem

A customer may ask for "eight USB-C monitors under SGD 2,500." The quotation employee still has to find out whether USB-C means video input, laptop charging, or merely a data port. They then compare models, check source documents, calculate the total, record any discount, seek approval, and prepare a document the customer can receive. A change from eight units to ten can require the same checks again.

For a small sales team, each handoff between enquiry, specification PDF, price sheet, and approval message adds work. A USB-C recommendation can be wrong even when the model name looks right. A calculation mistake or overwritten draft can make an earlier price hard to explain. These are workflow risks, not losses measured at a participating SME. The pilot will record errors and rework rather than assume how often they occur.

Quotation Desk is aimed at quotation staff and sales coordinators who prepare the draft, and a reviewer who confirms it. The initial scope is monitor enquiries within a maintained product catalogue. Stock, delivery dates, tax, customer-specific contracts, and manufacturer prices are outside the prototype's data. Staff must handle those matters through their normal process before making a commercial commitment.

## How the quotation changes

In the target manual workflow, staff clarify the enquiry, search documents, compare specifications, calculate a price, seek approval, and prepare a PDF. In the workbench, the Agent asks the missing question and retrieves candidates with their source pages. A person chooses the SKU; the pricing tool calculates the draft. The user saves a version, reviews any revision, and confirms the chosen version before PDF export. The prototype records the confirmer's name but does not enforce approval roles.

The eight-monitor example shows the division of work. The Agent asks whether the customer needs video over USB-C and laptop power. Once the customer accepts the relevant specification and the user selects Dell P2425HE, the synthetic catalogue price of SGD 289 per unit produces an SGD 2,312 draft at zero discount. At ten units, the total is SGD 2,890, or SGD 390 above the stated budget. The workbench stores both versions and shows the difference. These are demonstration amounts from the project's synthetic price list, not a sales offer or Dell pricing.

A second case concerns Dell U2724D. Its USB-C upstream connection is data-only, so it cannot meet a one-cable video and 90 W laptop-charging request. The catalogue can show U2724DE as a possible alternative, with source evidence, but a person must select it. A third case asks for a 6% discount and next-day delivery. The demo rule caps discounts at 5%, and the dataset has no delivery lead time. The system reports those limits instead of calculating an unauthorized discounted quote or promising a delivery date.

![Browser acceptance screenshot showing the saved quote comparison and its line-level changes](assets/quote-version-comparison.png)

Figure 1. In the v2 browser acceptance run, changing P2425HE from eight to ten units produced a second saved draft. The comparison shows SGD 2,312 before, SGD 2,890 after, and a SGD 578 change. The revised total is SGD 390 above the original SGD 2,500 budget. This screenshot demonstrates the offline browser flow; the v2 Gateway evaluation remains pending.

## Why an Agent belongs in this workflow

Customer language varies, so the Agent interprets the enquiry and asks for missing requirements. It can call three tools: search products, retrieve a product with evidence for each important field, and calculate a draft. Filters distinguish USB-C video input from laptop power and accessory charging. Missing data cannot satisfy a requirement, and a similar model name cannot replace the requested model.

Product facts and prices come from the catalogue and pricing rules, not the Agent's wording. The price tool calculates in integer cents, rounds each line's discount consistently, and rejects discounts above 5%. SQLite keeps each saved version; confirmation is recorded separately. The PDF reads the confirmed version, so a later conversation cannot change its figures. Staff can inspect the tool trace and version history. Live commercial use would require permission checks for the confirmation step.

The workbench runs on AWS Lightsail. It sends model requests through the organizer's LLM Gateway. If that service fails, the page marks its offline fallback; those results are excluded from real-model evaluation. The model handles language, while the catalogue, price tool, and human confirmation control the quote.

## Business value and how to measure it

The workbench brings specifications, price calculations, and draft versions into one place. Staff can check a product choice against its source page and see how a revised price differs from an earlier one. The pilot will measure whether these features reduce preparation time and rework.

The pilot should compare manual and assisted work on the same five de-identified cases, with the same catalogue and pricing rules. Timing starts when the operator reads the enquiry and ends when a result is ready for review. An Agent response counts only if its SKU choice, calculation, or policy block is correct. Report sample size, median, and range for each method, along with any manual corrections. The pilot will measure the actual difference; no percentage saving is assumed in advance.

| Outcome | Evidence available now | Pilot acceptance measure |
|---|---|---|
| Preparation time | A five-case v1 Gateway run had a 12.705-second median Agent response. Human timing is pending; this timing excludes the full staff review and approval journey. | Measure matched manual and assisted cases; report both medians, ranges, and the observed difference. |
| Price accuracy | The pricing rules and saved-quote flow have automated checks; 15 v1 expected quote amounts were independently reconciled. | Every pilot total matches an independent recalculation in cents. |
| Specification traceability | The v2 catalogue has 50 SKUs and 400 field-level evidence records. | Every specification used to justify a pilot recommendation has a manufacturer source and page. |
| Policy and approval | The prototype blocks discounts above 5%; saved drafts cannot be exported until confirmed. | No prohibited discount or unconfirmed PDF in the pilot cases. |
| Service quality | No SME response-time or conversion baseline has been measured. | Record time to a reviewable quote, corrections, and staff feedback before making customer-service claims. |

If the pilot validates a time saving, the business can estimate labor value as minutes saved per quote multiplied by monthly quotation volume and loaded staff cost per minute. Those inputs are currently unknown. Faster response might affect conversion, but a separate sales baseline and a longer observation period would be needed to test that claim.

## What has been demonstrated

The current v2 data package contains 50 monitor models, 44 official Dell and Lenovo source documents, 754 source pages, 50 synthetic prices, and 400 field-level evidence records. Local data validation passed. A browser acceptance run loaded all 50 records, displayed Lenovo source evidence, saved and compared two draft versions, confirmed the second, downloaded its PDF, and checked that the displayed, stored, and exported amounts agreed. The run used the OfflineDriver; it establishes the browser and quotation lifecycle on v2, not v2 model accuracy.

The real organizer Gateway was evaluated on the earlier 12-SKU v1 catalogue. Ten of the 20 cases in its untouched sealed first pass had at least one failed check. After documented fixes, a separate run passed all 20 cases with no fallback. That repaired result shows the approach can work with the Gateway on v1. A fresh evaluation is required before reporting a model score for the 50-SKU v2 catalogue.

The recorded five-case v1 Gateway timing has five correct Agent results and a 12.705-second median, with a range from 9.025 to 19.633 seconds. The five matching human observations have not been completed, so no comparative efficiency result exists. The current Lenovo expansion has passed machine checks and browser loading; the independent spot check by someone other than the import author remains open.

## Evidence to inspect

The repository contains the [v2 data validation report](https://github.com/HELLSJ/ISS-Hackson-Quotation-Preparation/blob/main/data/validation/report.json), [v2 browser acceptance record](https://github.com/HELLSJ/ISS-Hackson-Quotation-Preparation/blob/main/reports/evaluation/browser_acceptance/20260923T151456Z/report.md), [v1 sealed Gateway evaluation](https://github.com/HELLSJ/ISS-Hackson-Quotation-Preparation/blob/main/reports/evaluation/runs/20260922T073451Z-gateway-fixed-02/report.md), and [v1 Gateway timing report](https://github.com/HELLSJ/ISS-Hackson-Quotation-Preparation/blob/main/reports/evaluation/timing/20260922T073821Z-gateway-first-pass/report.md). The live workbench is at http://47.131.151.253/.

## Pilot plan and path to use

We propose a two-week pilot with one quotation employee and one reviewer. Use de-identified enquiries, freeze the catalogue and prices, complete the Lenovo spot check, and run the 50-SKU v2 Gateway evaluation. Record fallback separately. The employee would work matched manual and assisted cases; the reviewer would check corrections, source links, version history, policy blocks, and confirmed PDFs before deciding on a broader trial.

The pilot can run on the existing FastAPI and SQLite application with an assigned maintainer for product facts and synthetic business rules. For live commercial use, the business would need approved prices, tax handling, inventory and delivery data, role-based access, HTTPS, backup and recovery, monitoring, and a documented approval policy. Manufacturer source documents also need an appropriate linking or distribution approach. The same typed catalogue schema and tools can accept additional models or brands, but each new source and field needs verification. A shared database and CRM or ERP integration would be considered only when volume and operating needs justify them.

After two weeks, the reviewer can decide whether to extend the trial using the matched timing results, independent price checks, source-page review, and confirmation history. Five matched cases can justify a broader test, but cannot establish a lasting productivity gain. The team would investigate any failed case before expanding use.
