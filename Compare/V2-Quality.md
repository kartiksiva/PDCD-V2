# Standard Operating Procedure (SOP)

## Customer Complaint Intake, Validation, Categorization, Assignment, Tracking, and Closure
**Function:** Customer Service Operations
**Sub-Function:** Complaint Management
**Document Version:** v1.0
**Document Status:** Draft
**Effective Date:** 22-Apr-2026

---

## 1. Document Control
### 1.1 Key Stakeholders
| # | Name | Position / Designation | Email ID |
|---|------|------------------------|----------|
| 1 | Needs Review | Needs Review | Needs Review |

### 1.2 Version History
| Version | Date | Status | Author | Reviewed By | Comments / Changes |
|---------|------|--------|--------|-------------|-------------------|
| v1.0 | 22-Apr-2026 | Draft | Needs Review | Needs Review | Initial export |

---

## Index
1. Document Control  2. Introduction  3. Process Steps  4. Process Exceptions  5. Process Controls  6. Approval Matrix  7. Appendix

---

## 2. Introduction
### 2.1 Process Overview
This as-is process manages customer complaints received through multiple channels, validates complaint information, creates and updates complaint records in CRM, categorizes and assigns complaints to resolution teams, tracks progress, and closes complaints. The current process is high-volume, heavily manual, and relies on analyst judgment across intake, triage, routing, evidence handling, and reporting.

### 2.2 Process Objective
To receive customer complaints from all intake channels, ensure required information is captured, route each complaint to the appropriate resolution team within applicable SLA timelines, maintain supporting evidence and status tracking, and close the complaint with an auditable record.

### 2.3 Frequency
Daily; approximately 180 to 220 complaints per day on average, with higher volumes on Mondays and after product releases.

### 2.4 SLA
Regulatory complaints require response within 24 hours; standard complaints allow 3 business days for acknowledgement.

### 2.5 RACI (task × role matrix)
| Task | Customer | Call Team Agent | Analyst | Billing Operations | Product Support | Field Service | Compliance | Resolution Team | Customer / Call Team Agent | Analyst / Resolution Team / Compliance | Resolution Team / Compliance / Analyst | Analyst / Resolution Team |
|------|---|---|---|---|---|---|---|---|---|---|---|---|
| Receive customer complaints through intake channels and capture phone complaints for later entry. | — | — | — | — | — | — | — | — | R | — | — | — |
| Review the shared mailbox and phone log spreadsheet and create CRM complaint records for items not already in CRM. | — | — | R | — | — | — | — | — | — | — | — | — |
| Validate whether mandatory complaint fields are present in the complaint record. | — | — | R | — | — | — | — | — | — | — | — | — |
| Request missing information from the customer using a template email that is often edited manually. | — | — | R | — | — | — | — | — | — | — | — | — |
| Categorize the complaint in CRM by selecting a complaint type from the available drop-down values. | — | — | R | — | — | — | — | — | — | — | — | — |
| Assign the complaint manually to the appropriate resolution team and copy compliance for regulatory complaints. | — | — | R | — | — | — | — | — | — | — | — | — |
| Handle complaint evidence and attachments by copying text, manually attaching files, renaming files, and storing evidence in the document repository. | — | — | R | — | — | — | — | — | — | — | — | — |
| Update tracking records and management reporting outside CRM to monitor complaint status. | — | — | R | — | — | — | — | — | — | — | — | — |
| Monitor assigned complaints, address reassignment and pending information delays, and record key milestone dates. | — | — | — | — | — | — | — | — | — | R | — | — |
| Review complaint details requiring human judgment and make final resolution decisions before case closure. | — | — | — | — | — | — | — | — | — | — | R | — |
| Close the complaint and maintain closure date and core lifecycle dates for reporting and audit purposes. | — | — | — | — | — | — | — | — | — | — | — | R |

### 2.6 SIPOC (Supplier / Input / Process / Output / Customer)
| Supplier | Input | Process | Output | Customer | Step Anchor | Source Anchor |
|----------|-------|---------|--------|----------|-------------|---------------|
| Customer | Complaint submitted via email, web form, portal, or phone | Receive customer complaints through intake channels and capture phone complaints for later entry | Complaint enters intake sources for processing | Analyst / Call Team Agent | step-01 | 00:05:37-00:06:14 |
| Outlook shared mailbox / Call Team Agent | Email complaints and phone log spreadsheet entries | Review mailbox and phone log and create CRM complaint records for items not already in CRM | Complaint records created in CRM | Analyst / CRM | step-02 | 00:10:50-00:11:40 |
| Analyst / CRM record | Complaint record with customer and issue details | Validate whether mandatory complaint fields are present | Validated complaint or identified missing fields | Analyst | step-03 | 00:10:50-00:11:40 |
| Analyst | Complaint missing required data or evidence | Request missing information from customer using template email | Additional information request sent | Customer | step-04 | 00:12:30-00:13:20 |
| Analyst | Completed complaint details | Categorize complaint in CRM using complaint type drop-down | Complaint type assigned | Analyst / Resolution Team / Compliance | step-05 | 00:15:50-00:16:40 |
| Analyst | Complaint type, product line, region, customer tier, and exceptions context | Manually assign complaint to a resolution team and copy compliance for regulatory complaints | Assigned complaint work item | Billing Operations / Product Support / Field Service / Compliance | step-06 | 00:20:42-00:21:24 |
| Customer / Analyst / Outlook shared mailbox | Complaint text, screenshots, attachments, supporting files | Handle attachments and evidence by copying, attaching, renaming, and storing files | Complaint evidence organized and stored | Resolution Team / Compliance / Analyst | step-07 | 00:27:30-00:28:20 |
| Analyst / CRM | Case status and complaint data | Update tracking spreadsheet for management reporting | Management tracking data | Management / Analysts | step-08 | 00:28:20-00:29:10 |
| Resolution Team / Customer / Analyst | Assigned case, reassignment needs, pending documents, status changes | Monitor complaints, manage delays and reassignments, and record milestone dates | Progressed complaint with updated milestones | Management / Compliance / Resolution Team / Analyst | step-09 | 00:30:50-00:31:40 |
| Resolution Team / Compliance / ERP | Complaint details, evidence, billing data, regulatory review inputs | Perform human review and make final resolution decisions | Resolved complaint | Analyst / Customer | step-10 | 00:41:00-00:42:00 |
| Resolution Team / Analyst | Resolved complaint and closure decision | Close complaint and maintain closure and lifecycle dates | Closed complaint record | Management / Compliance / Customer | step-11 | 00:33:20-00:34:10 |

---

## 3. Process Steps
### Step 1: Receive customer complaints through intake channels and capture phone complaints for later entry. (step-01)
- Description: Receive customer complaints through intake channels and capture phone complaints for later entry.
- Tools / Systems: Customer support portal, web form, Outlook shared mailbox, Excel phone log, CRM
- Inputs / Outputs: Customer complaint submitted via email, web form, portal, or phone call -> Complaint available in CRM or pending in shared mailbox / phone log for intake processing
- Source Timestamp (evidence anchor): 00:05:37-00:06:14, 00:08:05-00:08:42

### Step 2: Review the shared mailbox and phone log spreadsheet and create CRM complaint records for items not already in CRM. (step-02)
- Description: Review the shared mailbox and phone log spreadsheet and create CRM complaint records for items not already in CRM.
- Tools / Systems: Outlook shared mailbox, Excel phone log, CRM
- Inputs / Outputs: Email complaints, phone log entries, existing CRM queue -> New complaint records created in CRM for items not already recorded
- Source Timestamp (evidence anchor): 00:10:50-00:11:40, 00:08:42-00:09:19

### Step 3: Validate whether mandatory complaint fields are present in the complaint record. (step-03)
- Description: Validate whether mandatory complaint fields are present in the complaint record.
- Tools / Systems: CRM
- Inputs / Outputs: New or existing complaint record in CRM -> Complaint marked complete for triage or identified as missing required information
- Source Timestamp (evidence anchor): 00:10:50-00:11:40, 00:30:50-00:31:40

### Step 4: Request missing information from the customer using a template email that is often edited manually. (step-04)
- Description: Request missing information from the customer using a template email that is often edited manually.
- Tools / Systems: Outlook shared mailbox, CRM
- Inputs / Outputs: Complaint record with missing mandatory fields or missing documents -> Follow-up request sent to customer for additional details or evidence
- Source Timestamp (evidence anchor): 00:12:30-00:13:20, 00:13:20-00:14:10, 00:31:40-00:32:30

### Step 5: Categorize the complaint in CRM by selecting a complaint type from the available drop-down values. (step-05)
- Description: Categorize the complaint in CRM by selecting a complaint type from the available drop-down values.
- Tools / Systems: CRM
- Inputs / Outputs: Complete complaint record and supporting details -> Complaint type assigned in CRM
- Source Timestamp (evidence anchor): 00:15:50-00:16:40, 00:17:30-00:18:20, 00:18:20-00:19:10

### Step 6: Assign the complaint manually to the appropriate resolution team and copy compliance for regulatory complaints. (step-06)
- Description: Assign the complaint manually to the appropriate resolution team and copy compliance for regulatory complaints.
- Tools / Systems: CRM
- Inputs / Outputs: Categorized complaint, product line, region, customer tier, and account context -> Complaint assigned to billing operations, product support, or field service; compliance copied for regulatory complaints
- Source Timestamp (evidence anchor): 00:20:42-00:21:24, 00:22:06-00:22:48, 00:30:50-00:31:40

### Step 7: Handle complaint evidence and attachments by copying text, manually attaching files, renaming files, and storing evidence in the document repository. (step-07)
- Description: Handle complaint evidence and attachments by copying text, manually attaching files, renaming files, and storing evidence in the document repository.
- Tools / Systems: Outlook shared mailbox, CRM, document repository
- Inputs / Outputs: Complaint text, screenshots, attachments, supporting evidence -> Complaint narrative and evidence linked or stored for case processing
- Source Timestamp (evidence anchor): 00:25:50-00:26:40, 00:27:30-00:28:20, 00:46:00-00:47:00

### Step 8: Update tracking records and management reporting outside CRM to monitor complaint status. (step-08)
- Description: Update tracking records and management reporting outside CRM to monitor complaint status.
- Tools / Systems: CRM, tracking spreadsheet
- Inputs / Outputs: Complaint status and case data from CRM and analyst updates -> Tracking spreadsheet updated for daily management reporting
- Source Timestamp (evidence anchor): 00:27:30-00:28:20, 00:28:20-00:29:10

### Step 9: Monitor assigned complaints, address reassignment and pending information delays, and record key milestone dates. (step-09)
- Description: Monitor assigned complaints, address reassignment and pending information delays, and record key milestone dates.
- Tools / Systems: CRM, tracking spreadsheet
- Inputs / Outputs: Assigned complaint, customer responses, status changes, reassignment needs -> Complaint progresses through acknowledgement, assignment, and closure milestones
- Source Timestamp (evidence anchor): 00:30:50-00:31:40, 00:33:20-00:34:10, 00:44:00-00:45:00

### Step 10: Review complaint details requiring human judgment and make final resolution decisions before case closure. (step-10)
- Description: Review complaint details requiring human judgment and make final resolution decisions before case closure.
- Tools / Systems: CRM, ERP, document repository
- Inputs / Outputs: Assigned complaint, evidence, billing data if applicable, regulatory review inputs -> Resolved complaint and case ready for closure in tracked systems
- Source Timestamp (evidence anchor): 00:25:50-00:26:40, 00:41:00-00:42:00

### Step 11: Close the complaint and maintain closure date and core lifecycle dates for reporting and audit purposes. (step-11)
- Description: Close the complaint and maintain closure date and core lifecycle dates for reporting and audit purposes.
- Tools / Systems: CRM, tracking spreadsheet
- Inputs / Outputs: Resolved complaint and closure decision -> Closed complaint with received, acknowledged, assigned, and closed dates captured where available
- Source Timestamp (evidence anchor): 00:33:20-00:34:10, 00:44:00-00:45:00

---

## 4. Process Exceptions
| Exception Scenario | Description | Action Required | Owner |
|--------------------|-------------|-----------------|-------|
| Phone complaints require manual spreadsheet capture before CRM entry. | Phone complaints require manual spreadsheet capture before CRM entry. | Needs Review | Needs Review |
| Complaint information may be incomplete or ambiguous, requiring customer follow-up. | Complaint information may be incomplete or ambiguous, requiring customer follow-up. | Needs Review | Needs Review |
| Template follow-up emails are manually edited, causing inconsistent requests. | Template follow-up emails are manually edited, causing inconsistent requests. | Needs Review | Needs Review |
| Complaint categorization is subjective due to lack of a strict rulebook. | Complaint categorization is subjective due to lack of a strict rulebook. | Needs Review | Needs Review |
| The 'other' category is overused. | The 'other' category is overused. | Needs Review | Needs Review |
| Strategic customers and escalated accounts follow exception routing logic. | Strategic customers and escalated accounts follow exception routing logic. | Needs Review | Needs Review |
| About 20 percent of complaints are initially assigned to the wrong team. | About 20 percent of complaints are initially assigned to the wrong team. | Needs Review | Needs Review |
| Wrong-team assignments may bounce around for a day or two before correction. | Wrong-team assignments may bounce around for a day or two before correction. | Needs Review | Needs Review |
| Attachments arrive in different formats and naming conventions. | Attachments arrive in different formats and naming conventions. | Needs Review | Needs Review |
| Billing-related issues may require ERP access. | Billing-related issues may require ERP access. | Needs Review | Needs Review |
| Stage-level timestamps are incomplete because not every interim step is captured reliably. | Stage-level timestamps are incomplete because not every interim step is captured reliably. | Needs Review | Needs Review |

## 5. Process Controls
| Control # | Process Step | Control Description | Manual/System | Preventive/Detective |
|-----------|--------------|---------------------|---------------|----------------------|
| control-01 | step-03 | Analyst checks whether mandatory complaint fields are present before triage. | manual | preventive |
| control-02 | step-04 | Analyst requests additional customer details when complaint information is missing. | manual | preventive |
| control-03 | step-05 | Complaint categorization in CRM determines SLA handling and downstream routing. | manual | preventive |
| control-04 | step-06 | Regulatory complaints are copied to compliance as part of assignment handling. | manual | preventive |
| control-05 | step-09 | Key milestone dates received, acknowledged, assigned, and closed are tracked for monitoring. | manual | detective |
| control-06 | step-11 | Audit trail expectation exists for what was sent and when, especially for acknowledgements and compliance-sensitive communications. | manual | detective |

## 6. Approval Matrix
| Role | Responsibility |
|------|----------------|
| Analyst | Performs intake review, creates CRM records, validates fields, requests missing information, categorizes complaints, assigns cases, handles evidence, and updates tracking. |
| Call Team Agent | Documents phone complaints in the phone log spreadsheet for later CRM entry. |
| Billing Operations | Resolves complaints assigned for billing-related issues. |
| Product Support | Resolves complaints assigned for product-related issues. |
| Field Service | Resolves complaints assigned for field or delivery/service execution issues. |
| Compliance | Reviews regulatory complaint handling and must be copied on regulatory complaints; reviews proposed rules affecting regulatory handling and retention. |
| Customer | Submits complaints and provides additional details or documents when requested. |
| Management | Consumes daily reporting from the tracking spreadsheet and oversees operational performance. |

## 7. Appendix
### Automation Opportunities
| ID | Description | Quantification | Automation Signal |
|----|-------------|----------------|-------------------|
| auto-01 | Normalize all complaint sources into a single intake queue and auto-create CRM cases from email, portal, web form, and phone-log inputs where possible. | Volume is approximately 180 to 220 complaints per day; fragmented intake is cited as a major issue. | high |
| auto-02 | Automate mandatory-field validation at intake and flag incomplete submissions before analyst review. | Straightforward intake takes 8 to 10 minutes; incomplete or ambiguous complaints take 15 minutes or more. | high |
| auto-03 | Standardize and automate missing-information and acknowledgement emails with audit trail capture. | Current follow-up wording varies by analyst; no automatic reminder exists if the customer does not respond. | high |
| auto-04 | Implement rules-based categorization support using complaint type guidance and escalation flags for regulatory items with manual override. | Misclassification affects SLA handling; regulatory complaints require response within 24 hours and standard complaints allow 3 business days for acknowledgement. | high |
| auto-05 | Implement rules-based assignment and routing to billing operations, product support, field service, and compliance based on complaint type, product line, region, customer tier, and exception rules. | Around 20 percent of complaints are assigned to the wrong team initially, causing 1 to 2 day delays. | high |
| auto-06 | Automate attachment ingestion, file naming, and evidence storage linkage to reduce manual document handling. | Analysts manually copy complaint text, attach screenshots, rename files, and organize attachments in different formats and naming conventions. | high |
| auto-07 | Eliminate duplicate updates by synchronizing CRM status data with management reporting outputs. | Analysts update a tracking spreadsheet because CRM reporting is not trusted; duplicate data entry is explicitly identified. | high |
| auto-08 | Add SLA timers, pending-information reminders, and stage-level event tracking. | Key dates tracked are received, acknowledged, assigned, and closed, but not every interim step is captured reliably. | high |
| auto-09 | Develop decision matrices and evidence checklists embedded in workflow to reduce knowledge dependency on senior analysts. | Two senior analysts know routing nuances much better than everyone else. | medium |

### FAQs
1. **Q:** What starts the complaint management process?
   **A:** The process starts when a customer complaint is received through email, web form, customer support portal, or phone.
2. **Q:** How many complaints are handled each day?
   **A:** The team receives about 180 to 220 complaints per day on average, with higher volumes on Mondays and after product releases.
3. **Q:** Which systems are used in the current process?
   **A:** The process uses an Outlook shared mailbox, Excel phone log, CRM, a document repository, ERP for some billing issues, and a separate tracking spreadsheet for reporting.
4. **Q:** What are the main complaint categories?
   **A:** Analysts select billing, service quality, product defect, delivery issue, regulatory, or other in CRM.
5. **Q:** What are the key SLA requirements?
   **A:** Regulatory complaints require response within 24 hours, while standard complaints allow 3 business days for acknowledgement.
6. **Q:** Where do the biggest delays occur?
   **A:** The biggest delays occur in intake validation and reassignment, and about 20 percent of complaints are initially assigned to the wrong team.
7. **Q:** Which activities clearly require human judgment?
   **A:** Complex complaint interpretation, regulatory risk review, and final resolution decisions require human review.
8. **Q:** Why is there a separate tracking spreadsheet?
   **A:** The spreadsheet is used because the team does not trust CRM reporting to be updated consistently.

### Evidence Bundle Manifest

**Evidence Strength:** low

| Anchor | Type | Confidence | Linked Steps | OCR Snippet |
|--------|------|------------|-------------|-------------|
| `00:05:37-00:06:14` | timestamp_range | 0.56 | step-01 | — |
| `00:08:05-00:08:42` | timestamp_range | 0.56 | step-01 | — |
| `00:10:50-00:11:40` | timestamp_range | 0.58 | step-02, step-03 | — |
| `00:08:42-00:09:19` | timestamp_range | 0.49 | step-02 | — |
| `00:30:50-00:31:40` | timestamp_range | 0.49 | step-03, step-06, step-09 | — |
| `00:12:30-00:13:20` | timestamp_range | 0.58 | step-04 | — |
| `00:13:20-00:14:10` | timestamp_range | 0.54 | step-04 | — |
| `00:31:40-00:32:30` | timestamp_range | 0.56 | step-04 | — |
| `00:15:50-00:16:40` | timestamp_range | 0.59 | step-05 | — |
| `00:17:30-00:18:20` | timestamp_range | 0.57 | step-05 | — |
| `00:18:20-00:19:10` | timestamp_range | 0.58 | step-05 | — |
| `00:20:42-00:21:24` | timestamp_range | 0.58 | step-06 | — |
| `00:22:06-00:22:48` | timestamp_range | 0.58 | step-06 | — |
| `00:25:50-00:26:40` | timestamp_range | 0.52 | step-07, step-10 | — |
| `00:27:30-00:28:20` | timestamp_range | 0.59 | step-07, step-08 | — |
| `00:46:00-00:47:00` | timestamp_range | 0.57 | step-07 | — |
| `00:28:20-00:29:10` | timestamp_range | 0.58 | step-08 | — |
| `00:33:20-00:34:10` | timestamp_range | 0.57 | step-09, step-11 | — |
| `00:44:00-00:45:00` | timestamp_range | 0.50 | step-09, step-11 | — |
| `00:41:00-00:42:00` | timestamp_range | 0.57 | step-10 | — |

> No frame captures available for this job.

### Frame captures
- No frame captures available.