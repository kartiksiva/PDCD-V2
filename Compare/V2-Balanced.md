# Standard Operating Procedure (SOP)

## Customer Complaint Handling
**Function:** Customer Service
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
Complaints are received through multiple channels, manually normalized into CRM, validated for completeness, categorized, routed to the appropriate resolution team, and tracked through acknowledgment and closure. The current process relies heavily on manual analyst effort, email, spreadsheets, and judgment-based routing, with special handling for regulatory and strategic customer cases.

### 2.2 Process Objective
Ensure customer complaints are captured, validated, categorized, routed, and tracked to resolution with appropriate compliance handling and auditability.

### 2.3 Frequency
Daily, continuous intake with morning mailbox/log review and ongoing case handling.

### 2.4 SLA
Not explicitly defined in the evidence; partial turnaround time tracking is maintained and future-state recommendations include SLA timers.

### 2.5 RACI (task × role matrix)
| Task | Customer / Call Agent | System / Call Team | Analyst | Analyst / Management | Analyst / Customer | Analyst Team | Senior Analyst | Service Provider / Process Team | Service Provider | Analyst / Compliance | Process Team | Analyst / Team | Analyst / Process Team | Analyst / System |
|------|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Receive complaint from one of the available channels; phone complaints are first documented manually by an agent before later entry into the queue. | R | — | — | — | — | — | — | — | — | — | — | — | — | — |
| Normalize fragmented complaint intake into CRM; portal and web form complaints go directly to CRM, email complaints remain in a shared mailbox, and phone complaints may be captured in a spreadsheet before manual CRM entry. | — | R | — | — | — | — | — | — | — | — | — | — | — | — |
| Each morning, analysts review the shared mailbox and phone log spreadsheet and create CRM complaint records for items not already captured. | — | — | R | — | — | — | — | — | — | — | — | — | — | — |
| Check each complaint record for mandatory fields such as customer ID, product, issue category, date of incident, and contact information. | — | — | R | — | — | — | — | — | — | — | — | — | — | — |
| If required information is missing, send a template email requesting additional details, sometimes with manually edited wording. | — | — | R | — | — | — | — | — | — | — | — | — | — | — |
| Categorize the complaint in CRM using the available complaint type dropdown list. | — | — | R | — | — | — | — | — | — | — | — | — | — | — |
| Apply judgment to determine the complaint category when the decision is not straightforward. | — | — | R | — | — | — | — | — | — | — | — | — | — | — |
| Manually assign the complaint to a resolution team based on complaint type, product line, region, and customer tier. | — | — | R | — | — | — | — | — | — | — | — | — | — | — |
| For regulatory complaints, copy or notify the compliance team in addition to the primary assignment. | — | — | R | — | — | — | — | — | — | — | — | — | — | — |
| Apply exception handling for strategic customers and escalated accounts during assignment. | — | — | R | — | — | — | — | — | — | — | — | — | — | — |
| Work across supporting systems to process complaint information and evidence, including document repository and ERP for billing-related issues. | — | — | R | — | — | — | — | — | — | — | — | — | — | — |
| Copy complaint text into CRM, attach screenshots manually, rename files, and update the daily tracking spreadsheet. | — | — | R | — | — | — | — | — | — | — | — | — | — | — |
| Maintain a shadow tracking spreadsheet to compensate for CRM reporting not being consistently trusted as current. | — | — | — | R | — | — | — | — | — | — | — | — | — | — |
| If customer information remains incomplete, send follow-up requests and wait for additional documents from the customer. | — | — | — | — | R | — | — | — | — | — | — | — | — | — |
| Wait for missing documents when information is incomplete; no automatic reminder is available if the customer does not respond. | — | — | R | — | — | — | — | — | — | — | — | — | — | — |
| Record received, acknowledged, assigned, and closed dates to support turnaround-time tracking, while recognizing that interim events may not be captured reliably. | — | — | — | — | — | — | — | — | — | — | — | R | — | — |
| Spend analyst effort on complaint intake, setup, and rework, with longer handling time for incomplete or ambiguous complaints. | — | — | R | — | — | — | — | — | — | — | — | — | — | — |
| Allocate intake coverage across a five-analyst rotation, with two analysts focused heavily on intake each day. | — | — | — | — | — | R | — | — | — | — | — | — | — | — |
| Perform complex complaint interpretation, regulatory risk review, and final resolution decisions as human judgment tasks. | — | — | R | — | — | — | — | — | — | — | — | — | — | — |
| Identify case creation, mandatory-field checks, standard follow-up requests, routing, and acknowledgment emails as candidates for standardization or automation. | — | — | — | — | — | — | — | — | — | — | — | — | R | — |
| Generate acknowledgment emails without manual typing while preserving audit-trail evidence of what was sent and when. | — | — | — | — | — | — | — | — | — | — | — | — | — | R |
| Organize complaint attachments received in different formats and naming conventions. | — | — | R | — | — | — | — | — | — | — | — | — | — | — |
| Use senior-analyst routing knowledge when standard guidance is not available. | — | — | — | — | — | — | R | — | — | — | — | — | — | — |
| Apply future-state intake normalization, mandatory-field validation, standardized acknowledgment templates, rules-based categorization suggestions, and assignment recommendations. | — | — | — | — | — | — | — | R | — | — | — | — | — | — |
| Handle regulatory complaints with manual override controls in the future-state workflow. | — | — | — | — | — | — | — | — | — | R | — | — | — | — |
| Use a decision matrix, SLA timers, automated reminders for pending customer information, and a common evidence checklist by complaint type. | — | — | — | — | — | — | — | — | — | — | R | — | — | — |
| Document the as-is process, exceptions, systems, volumes, and candidate automation steps, then return with a recommended future-state workflow. | — | — | — | — | — | — | — | — | R | — | — | — | — | — |

### 2.6 SIPOC (Supplier / Input / Process / Output / Customer)
| Supplier | Input | Process | Output | Customer | Step Anchor | Source Anchor |
|----------|-------|---------|--------|----------|-------------|---------------|
| Customer / Call Agent | Customer complaint | Receive complaint from channel and document phone complaints manually | Complaint intake entry or manually documented phone complaint | Analyst / Intake Process | step-01 | 00:05:37-00:06:14 |
| System / Call Team | Incoming complaint from portal, web form, email, or phone | Normalize fragmented intake into CRM, mailbox, and spreadsheet | Complaint records distributed across CRM, mailbox, and spreadsheet | Analyst | step-02 | 00:08:05-00:08:42 |
| Shared Mailbox / Excel Spreadsheet | Mailbox emails and phone log entries | Review uncaptured items and create complaint records in CRM | Complaint records in CRM | Analyst | step-03 | 00:10:50-00:11:40 |
| CRM | Complaint record | Validate mandatory fields | Validated complaint record or identified missing information | Analyst | step-04 | 00:10:50-00:11:40 |
| Analyst | Incomplete complaint record | Request additional details from customer | Customer request for additional details | Customer | step-05 | 00:12:30-00:13:20 |
| Analyst | Validated complaint record | Classify complaint type in CRM | Complaint type classification | Analyst / Routing | step-06 | 00:15:50-00:16:40 |
| Analyst / Training Deck | Complaint details | Apply judgment to categorize complaint | Categorized complaint | Analyst / Routing | step-07 | 00:17:30-00:18:20 |
| Analyst | Categorized complaint | Assign complaint to resolution team | Assigned resolution team | Resolution Team | step-08 | 00:20:42-00:22:48 |
| Analyst | Regulatory complaint | Notify compliance in addition to primary assignment | Compliance copy / compliance notification | Compliance Team | step-09 | 00:20:42-00:21:24 |
| Analyst | Complaint requiring special handling | Apply exception-based assignment | Exception-based assignment | Resolution Team / Management | step-10 | 00:22:06-00:22:48 |
| Analyst | Complaint information and supporting evidence | Use CRM, document repository, ERP, and other tools to process case information | Processed complaint information across systems | Resolution Team / Management | step-11 | 00:25:50-00:26:40 |
| Email / Customer | Email complaint and attachments | Copy complaint text, attach evidence, and update tracking spreadsheet | Updated CRM record, saved attachments, and reporting spreadsheet entry | Management / Audit | step-12 | 00:27:30-00:28:20 |
| CRM | CRM status data | Maintain shadow tracking record | Independent tracking record | Management | step-13 | 00:28:20-00:29:10 |
| Customer | Incomplete complaint and missing documents | Follow up for additional information | Customer response with additional information | Analyst | step-14 | 00:30:50-00:31:40 |
| Customer | Pending customer documents | Wait for missing documents | Delayed complaint progression | Analyst / Case Queue | step-15 | 00:31:40-00:32:30 |
| Analyst / Team | Complaint lifecycle events | Record lifecycle dates for turnaround tracking | Partial turnaround time tracking | Management | step-16 | 00:33:20-00:34:10 |
| Analyst | New complaint | Spend effort on intake, setup, and rework | Initial setup and rework effort | Process Team / Management | step-17 | 00:35:50-00:36:40 |
| Analyst Team | Complaint intake workload | Allocate intake coverage | Assigned intake coverage | Operations | step-18 | 00:37:30-00:38:20 |
| Analyst | Complaint case | Perform interpretation, risk review, and resolution decisions | Interpretation, risk review, or resolution decision | Resolution Team / Management | step-19 | 00:41:00-00:42:00 |
| Analyst / Process Team | Complaint case | Identify standardization and automation candidates | Standardized intake, follow-up, routing, and acknowledgment activity | Process Design Team | step-20 | 00:41:00-00:44:00 |
| Analyst / System | Acknowledgment requirement | Generate acknowledgment email with audit trail | Acknowledgment email with traceability | Customer / Audit | step-21 | 00:43:00-00:45:00 |
| Customer / Email | Complaint attachments | Organize evidence documents | Organized evidence documents | Analyst / Resolution Team | step-22 | 00:46:00-00:47:00 |
| Senior Analyst | Complaint routing question | Provide routing guidance from tribal knowledge | Routing guidance | Analyst | step-23 | 00:47:00-00:48:00 |
| Process Team | Multi-channel complaint intake | Normalize intake and provide rules-based suggestions | Single standardized intake and routed complaint queue | Analyst / Resolution Team | step-24 | 00:50:00-00:51:40 |
| Compliance | Regulatory complaint | Apply manual override handling | Flagged or manually overridden complaint handling | Compliance / Analyst | step-25 | 00:51:40-00:52:30 |
| Process Team | Complaint case and pending actions | Use decision matrix, SLA timers, reminders, and checklist guidance | Decision support, SLA monitoring, reminders, and checklist guidance | Analyst / Management | step-26 | 00:53:20-00:55:00 |
| Service Provider | Discovery session findings | Document as-is process and recommend future state | Current-state map and future-state recommendation | Process Owner / Stakeholders | step-27 | 00:58:30-00:59:12 |

---

## 3. Process Steps
### Step 1: Receive complaint from one of the available channels; phone complaints are first documented manually by an agent before later entry into the queue. (step-01)
- Description: Receive complaint from one of the available channels; phone complaints are first documented manually by an agent before later entry into the queue.
- Tools / Systems: Email, Web Form, Customer Support Portal, Phone, Manual Log
- Inputs / Outputs: Customer complaint -> Complaint intake entry or manually documented phone complaint
- Source Timestamp (evidence anchor): 00:05:37-00:06:14

### Step 2: Normalize fragmented complaint intake into CRM; portal and web form complaints go directly to CRM, email complaints remain in a shared mailbox, and phone complaints may be captured in a spreadsheet before manual CRM entry. (step-02)
- Description: Normalize fragmented complaint intake into CRM; portal and web form complaints go directly to CRM, email complaints remain in a shared mailbox, and phone complaints may be captured in a spreadsheet before manual CRM entry.
- Tools / Systems: CRM, Shared Mailbox, Excel Spreadsheet
- Inputs / Outputs: Incoming complaint from portal, web form, email, or phone -> Complaint records distributed across CRM, mailbox, and spreadsheet
- Source Timestamp (evidence anchor): 00:08:05-00:08:42

### Step 3: Each morning, analysts review the shared mailbox and phone log spreadsheet and create CRM complaint records for items not already captured. (step-03)
- Description: Each morning, analysts review the shared mailbox and phone log spreadsheet and create CRM complaint records for items not already captured.
- Tools / Systems: Shared Mailbox, Excel Spreadsheet, CRM
- Inputs / Outputs: Mailbox emails and phone log entries -> Complaint records in CRM
- Source Timestamp (evidence anchor): 00:10:50-00:11:40

### Step 4: Check each complaint record for mandatory fields such as customer ID, product, issue category, date of incident, and contact information. (step-04)
- Description: Check each complaint record for mandatory fields such as customer ID, product, issue category, date of incident, and contact information.
- Tools / Systems: CRM
- Inputs / Outputs: Complaint record -> Validated complaint record or identified missing information
- Source Timestamp (evidence anchor): 00:10:50-00:11:40

### Step 5: If required information is missing, send a template email requesting additional details, sometimes with manually edited wording. (step-05)
- Description: If required information is missing, send a template email requesting additional details, sometimes with manually edited wording.
- Tools / Systems: Email
- Inputs / Outputs: Incomplete complaint record -> Customer request for additional details
- Source Timestamp (evidence anchor): 00:12:30-00:13:20

### Step 6: Categorize the complaint in CRM using the available complaint type dropdown list. (step-06)
- Description: Categorize the complaint in CRM using the available complaint type dropdown list.
- Tools / Systems: CRM
- Inputs / Outputs: Validated complaint record -> Complaint type classification
- Source Timestamp (evidence anchor): 00:15:50-00:16:40

### Step 7: Apply judgment to determine the complaint category when the decision is not straightforward. (step-07)
- Description: Apply judgment to determine the complaint category when the decision is not straightforward.
- Tools / Systems: Training Deck / CRM
- Inputs / Outputs: Complaint details -> Categorized complaint
- Source Timestamp (evidence anchor): 00:17:30-00:18:20

### Step 8: Manually assign the complaint to a resolution team based on complaint type, product line, region, and customer tier. (step-08)
- Description: Manually assign the complaint to a resolution team based on complaint type, product line, region, and customer tier.
- Tools / Systems: CRM
- Inputs / Outputs: Categorized complaint -> Assigned resolution team
- Source Timestamp (evidence anchor): 00:20:42-00:22:48

### Step 9: For regulatory complaints, copy or notify the compliance team in addition to the primary assignment. (step-09)
- Description: For regulatory complaints, copy or notify the compliance team in addition to the primary assignment.
- Tools / Systems: CRM / Compliance Workflow
- Inputs / Outputs: Regulatory complaint -> Compliance copy / compliance notification
- Source Timestamp (evidence anchor): 00:20:42-00:21:24

### Step 10: Apply exception handling for strategic customers and escalated accounts during assignment. (step-10)
- Description: Apply exception handling for strategic customers and escalated accounts during assignment.
- Tools / Systems: CRM
- Inputs / Outputs: Complaint requiring special handling -> Exception-based assignment
- Source Timestamp (evidence anchor): 00:22:06-00:22:48

### Step 11: Work across supporting systems to process complaint information and evidence, including document repository and ERP for billing-related issues. (step-11)
- Description: Work across supporting systems to process complaint information and evidence, including document repository and ERP for billing-related issues.
- Tools / Systems: Outlook, Excel, CRM, Document Repository, ERP
- Inputs / Outputs: Complaint information and supporting evidence -> Processed complaint information across systems
- Source Timestamp (evidence anchor): 00:25:50-00:26:40

### Step 12: Copy complaint text into CRM, attach screenshots manually, rename files, and update the daily tracking spreadsheet. (step-12)
- Description: Copy complaint text into CRM, attach screenshots manually, rename files, and update the daily tracking spreadsheet.
- Tools / Systems: Email, CRM, Document Repository, Tracking Spreadsheet
- Inputs / Outputs: Email complaint and attachments -> Updated CRM record, saved attachments, and reporting spreadsheet entry
- Source Timestamp (evidence anchor): 00:27:30-00:28:20

### Step 13: Maintain a shadow tracking spreadsheet to compensate for CRM reporting not being consistently trusted as current. (step-13)
- Description: Maintain a shadow tracking spreadsheet to compensate for CRM reporting not being consistently trusted as current.
- Tools / Systems: Tracking Spreadsheet, CRM
- Inputs / Outputs: CRM status data -> Independent tracking record
- Source Timestamp (evidence anchor): 00:28:20-00:29:10

### Step 14: If customer information remains incomplete, send follow-up requests and wait for additional documents from the customer. (step-14)
- Description: If customer information remains incomplete, send follow-up requests and wait for additional documents from the customer.
- Tools / Systems: Email
- Inputs / Outputs: Incomplete complaint and missing documents -> Customer response with additional information
- Source Timestamp (evidence anchor): 00:30:50-00:31:40

### Step 15: Wait for missing documents when information is incomplete; no automatic reminder is available if the customer does not respond. (step-15)
- Description: Wait for missing documents when information is incomplete; no automatic reminder is available if the customer does not respond.
- Tools / Systems: Email / Case Management Process
- Inputs / Outputs: Pending customer documents -> Delayed complaint progression
- Source Timestamp (evidence anchor): 00:31:40-00:32:30

### Step 16: Record received, acknowledged, assigned, and closed dates to support turnaround-time tracking, while recognizing that interim events may not be captured reliably. (step-16)
- Description: Record received, acknowledged, assigned, and closed dates to support turnaround-time tracking, while recognizing that interim events may not be captured reliably.
- Tools / Systems: CRM / Tracking Records
- Inputs / Outputs: Complaint lifecycle events -> Partial turnaround time tracking
- Source Timestamp (evidence anchor): 00:33:20-00:34:10

### Step 17: Spend analyst effort on complaint intake, setup, and rework, with longer handling time for incomplete or ambiguous complaints. (step-17)
- Description: Spend analyst effort on complaint intake, setup, and rework, with longer handling time for incomplete or ambiguous complaints.
- Tools / Systems: CRM / Manual Processing
- Inputs / Outputs: New complaint -> Initial setup and rework effort
- Source Timestamp (evidence anchor): 00:35:50-00:36:40

### Step 18: Allocate intake coverage across a five-analyst rotation, with two analysts focused heavily on intake each day. (step-18)
- Description: Allocate intake coverage across a five-analyst rotation, with two analysts focused heavily on intake each day.
- Tools / Systems: Workforce Allocation
- Inputs / Outputs: Complaint intake workload -> Assigned intake coverage
- Source Timestamp (evidence anchor): 00:37:30-00:38:20

### Step 19: Perform complex complaint interpretation, regulatory risk review, and final resolution decisions as human judgment tasks. (step-19)
- Description: Perform complex complaint interpretation, regulatory risk review, and final resolution decisions as human judgment tasks.
- Tools / Systems: CRM / Case Review Process
- Inputs / Outputs: Complaint case -> Interpretation, risk review, or resolution decision
- Source Timestamp (evidence anchor): 00:41:00-00:42:00

### Step 20: Identify case creation, mandatory-field checks, standard follow-up requests, routing, and acknowledgment emails as candidates for standardization or automation. (step-20)
- Description: Identify case creation, mandatory-field checks, standard follow-up requests, routing, and acknowledgment emails as candidates for standardization or automation.
- Tools / Systems: CRM / Email
- Inputs / Outputs: Complaint case -> Standardized intake, follow-up, routing, and acknowledgment activity
- Source Timestamp (evidence anchor): 00:41:00-00:44:00

### Step 21: Generate acknowledgment emails without manual typing while preserving audit-trail evidence of what was sent and when. (step-21)
- Description: Generate acknowledgment emails without manual typing while preserving audit-trail evidence of what was sent and when.
- Tools / Systems: Email / Audit Trail
- Inputs / Outputs: Acknowledgment requirement -> Acknowledgment email with traceability
- Source Timestamp (evidence anchor): 00:43:00-00:45:00

### Step 22: Organize complaint attachments received in different formats and naming conventions. (step-22)
- Description: Organize complaint attachments received in different formats and naming conventions.
- Tools / Systems: Document Repository / Email Attachments
- Inputs / Outputs: Complaint attachments -> Organized evidence documents
- Source Timestamp (evidence anchor): 00:46:00-00:47:00

### Step 23: Use senior-analyst routing knowledge when standard guidance is not available. (step-23)
- Description: Use senior-analyst routing knowledge when standard guidance is not available.
- Tools / Systems: Informal Knowledge Base
- Inputs / Outputs: Complaint routing question -> Routing guidance
- Source Timestamp (evidence anchor): 00:47:00-00:48:00

### Step 24: Apply future-state intake normalization, mandatory-field validation, standardized acknowledgment templates, rules-based categorization suggestions, and assignment recommendations. (step-24)
- Description: Apply future-state intake normalization, mandatory-field validation, standardized acknowledgment templates, rules-based categorization suggestions, and assignment recommendations.
- Tools / Systems: Future-State Intake and Workflow Automation
- Inputs / Outputs: Multi-channel complaint intake -> Single standardized intake and routed complaint queue
- Source Timestamp (evidence anchor): 00:50:00-00:51:40

### Step 25: Handle regulatory complaints with manual override controls in the future-state workflow. (step-25)
- Description: Handle regulatory complaints with manual override controls in the future-state workflow.
- Tools / Systems: Future-State Workflow / Compliance Controls
- Inputs / Outputs: Regulatory complaint -> Flagged or manually overridden complaint handling
- Source Timestamp (evidence anchor): 00:51:40-00:52:30

### Step 26: Use a decision matrix, SLA timers, automated reminders for pending customer information, and a common evidence checklist by complaint type. (step-26)
- Description: Use a decision matrix, SLA timers, automated reminders for pending customer information, and a common evidence checklist by complaint type.
- Tools / Systems: Future-State Workflow Design
- Inputs / Outputs: Complaint case and pending actions -> Decision support, SLA monitoring, reminders, and checklist guidance
- Source Timestamp (evidence anchor): 00:53:20-00:55:00

### Step 27: Document the as-is process, exceptions, systems, volumes, and candidate automation steps, then return with a recommended future-state workflow. (step-27)
- Description: Document the as-is process, exceptions, systems, volumes, and candidate automation steps, then return with a recommended future-state workflow.
- Tools / Systems: Process Documentation
- Inputs / Outputs: Discovery session findings -> Current-state map and future-state recommendation
- Source Timestamp (evidence anchor): 00:58:30-00:59:12

---

## 4. Process Exceptions
| Exception Scenario | Description | Action Required | Owner |
|--------------------|-------------|-----------------|-------|
| Incomplete complaint records require customer follow-up. | Incomplete complaint records require customer follow-up. | Needs Review | Needs Review |
| Customers may need to respond multiple times due to inconsistent request wording. | Customers may need to respond multiple times due to inconsistent request wording. | Needs Review | Needs Review |
| Missing documents can delay progression with no automatic reminder in the current state. | Missing documents can delay progression with no automatic reminder in the current state. | Needs Review | Needs Review |
| Regulatory complaints require compliance notification and may require manual override. | Regulatory complaints require compliance notification and may require manual override. | Needs Review | Needs Review |
| Strategic customers and escalated accounts require special handling. | Strategic customers and escalated accounts require special handling. | Needs Review | Needs Review |
| Less experienced analysts may misclassify complaints. | Less experienced analysts may misclassify complaints. | Needs Review | Needs Review |
| CRM reporting may be incomplete or not trusted, requiring shadow tracking. | CRM reporting may be incomplete or not trusted, requiring shadow tracking. | Needs Review | Needs Review |
| Attachments arrive in varied formats and naming conventions, requiring manual organization. | Attachments arrive in varied formats and naming conventions, requiring manual organization. | Needs Review | Needs Review |

## 5. Process Controls
| Control # | Process Step | Control Description | Manual/System | Preventive/Detective |
|-----------|--------------|---------------------|---------------|----------------------|
| control-01 | step-04 | Mandatory-field validation of customer ID, product, issue category, date of incident, and contact information. | manual | detective |
| control-02 | step-05 | Template-based customer request for missing information. | manual | preventive |
| control-03 | step-06 | Dropdown-based complaint type selection in CRM. | system | preventive |
| control-04 | step-09 | Compliance copy/notification for regulatory complaints. | system | preventive |
| control-05 | step-12 | Manual attachment and tracking spreadsheet updates provide evidence of processing. | manual | detective |
| control-06 | step-16 | Recording received, acknowledged, assigned, and closed dates for turnaround tracking. | manual | detective |
| control-07 | step-21 | Audit trail preservation for acknowledgment emails. | system | detective |
| control-08 | step-25 | Manual override for regulatory complaint handling in future state. | manual | preventive |

## 6. Approval Matrix
| Role | Responsibility |
|------|----------------|
| Analyst | Validate complaint completeness, categorize, route, follow up, and maintain case records. |
| Senior Analyst | Provide routing guidance for complex or ambiguous cases. |
| Process Team | Define standard work, decision matrices, SLA logic, and automation opportunities. |
| Compliance | Review or receive regulatory complaint notifications and support override handling. |
| Management | Monitor tracking, turnaround, and operational performance. |
| Service Provider | Document current state and recommend future-state workflow. |

## 7. Appendix
### Automation Opportunities
| ID | Description | Quantification | Automation Signal |
|----|-------------|----------------|-------------------|
| auto-01 | Normalize all complaint intake into a single queue with direct capture from email, web form, portal, and phone. | Currently multiple intake paths create manual re-entry and duplication; phone complaints and emails require additional handling. | high |
| auto-02 | Automate mandatory-field validation and completeness checks at intake. | Reduces repeated manual review of customer ID, product, category, incident date, and contact info across all cases. | high |
| auto-03 | Use templates and case-driven workflows for acknowledgment and missing-information follow-up emails. | Standard work identified by the team; current process includes manual editing and repeated customer follow-up. | high |
| auto-04 | Implement rules-based categorization and assignment recommendations using a decision matrix. | Would reduce judgment-based routing across complaint type, product line, region, and customer tier. | high |
| auto-05 | Automate attachment ingestion, file naming, and evidence organization. | Current analysts spend time handling varied formats and naming conventions manually. | medium |
| auto-06 | Add automated reminders and SLA timers for pending customer information and case aging. | Current process lacks automatic reminders and relies on manual waiting. | high |
| auto-07 | Replace shadow spreadsheets with trusted CRM reporting and audit-ready lifecycle tracking. | Current team maintains a separate tracking spreadsheet because CRM reporting is not trusted consistently. | high |

### FAQs
1. **Q:** Is complaint intake fully automated today?
   **A:** No. Intake is fragmented across email, web form, portal, phone, shared mailbox, and spreadsheet-based logging, with manual CRM entry for some channels.
2. **Q:** What information is required before a case can move forward?
   **A:** The evidence cites customer ID, product, issue category, date of incident, and contact information as mandatory fields.
3. **Q:** How are complaints categorized and assigned?
   **A:** Analysts categorize complaints in CRM and then manually assign them based on complaint type, product line, region, and customer tier.
4. **Q:** How are regulatory complaints handled?
   **A:** They are copied or notified to compliance in addition to the primary assignment, and the future state calls for manual override controls.
5. **Q:** What are the main current-state pain points?
   **A:** Manual re-entry, fragmented intake, inconsistent categorization, missing-information delays, shadow tracking, and reliance on tribal knowledge.

### Evidence Bundle Manifest

**Evidence Strength:** medium

| Anchor | Type | Confidence | Linked Steps | OCR Snippet |
|--------|------|------------|-------------|-------------|
| `00:05:37-00:06:14` | timestamp_range | 0.92 | step-01 | — |
| `00:08:05-00:08:42` | timestamp_range | 0.94 | step-02 | — |
| `00:10:50-00:11:40` | timestamp_range | 0.95 | step-03, step-04 | — |
| `00:12:30-00:13:20` | timestamp_range | 0.93 | step-05 | — |
| `00:15:50-00:16:40` | timestamp_range | 0.95 | step-06 | — |
| `00:17:30-00:18:20` | timestamp_range | 0.88 | step-07 | — |
| `00:20:42-00:22:48` | timestamp_range | 0.95 | step-08 | — |
| `00:20:42-00:21:24` | timestamp_range | 0.94 | step-09 | — |
| `00:22:06-00:22:48` | timestamp_range | 0.84 | step-10 | — |
| `00:25:50-00:26:40` | timestamp_range | 0.93 | step-11 | — |
| `00:27:30-00:28:20` | timestamp_range | 0.96 | step-12 | — |
| `00:28:20-00:29:10` | timestamp_range | 0.86 | step-13 | — |
| `00:30:50-00:31:40` | timestamp_range | 0.90 | step-14 | — |
| `00:31:40-00:32:30` | timestamp_range | 0.89 | step-15 | — |
| `00:33:20-00:34:10` | timestamp_range | 0.91 | step-16 | — |
| `00:35:50-00:36:40` | timestamp_range | 0.90 | step-17 | — |
| `00:37:30-00:38:20` | timestamp_range | 0.86 | step-18 | — |
| `00:41:00-00:42:00` | timestamp_range | 0.93 | step-19 | — |
| `00:41:00-00:44:00` | timestamp_range | 0.89 | step-20 | — |
| `00:43:00-00:45:00` | timestamp_range | 0.89 | step-21 | — |
| `00:46:00-00:47:00` | timestamp_range | 0.90 | step-22 | — |
| `00:47:00-00:48:00` | timestamp_range | 0.84 | step-23 | — |
| `00:50:00-00:51:40` | timestamp_range | 0.87 | step-24 | — |
| `00:51:40-00:52:30` | timestamp_range | 0.90 | step-25 | — |
| `00:53:20-00:55:00` | timestamp_range | 0.90 | step-26 | — |
| `00:58:30-00:59:12` | timestamp_range | 0.86 | step-27 | — |

> No frame captures available for this job.

### Frame captures
- No frame captures available.