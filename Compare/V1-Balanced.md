# Standard Operating Procedure (SOP)


---

## Customer Complaint Intake and Assignment

**Function:** Needs Review
**Sub-Function:** Analyst
**Document Version:** 1.0
**Document Status:** Draft
**Effective Date:** 22-Apr-2026

---

## 1. Document Control

### 1.1 Key Stakeholders
| # | Name | Position / Designation | Email ID |
|---|------|------------------------|----------|
| 1 | Analyst | Needs Review | Needs Review |

---

### 1.2 Version History
| Version | Date | Status (Draft/Final) | Author | Reviewed By | Comments / Changes |
|---------|------|----------------------|--------|-------------|-------------------|
| 1.0 | 22-Apr-2026 | Draft | PFCD Agent | Needs Review | Initial Draft |

---

## Index

1. Document Control
2. Introduction
3. Process Steps
4. Process Exceptions
5. Process Controls
6. Approval Matrix
7. Appendix

---

## 2. Introduction

### 2.1 Process Overview
Collect Complaints from All Channels -> Enter Complaints into CRM -> Validate Mandatory Fields -> Request Missing Information -> Categorize Complaint -> Assign Complaint to Resolution Team -> Attach Supporting Documents -> Update Tracking Spreadsheet

---

### 2.2 Process Objective
- To receive, validate, categorize, assign, and track customer complaints to ensure timely and compliant resolution

---

### 2.3 Frequency
Needs Review

---

### 2.4 SLA
- Accuracy Rate: Needs Review; Turnaround Time: Needs Review

---

### 2.5 RACI
| Task / Stakeholders | Analyst |
|---------------------|--------|
| Collect Complaints from All Channels | R |
| Enter Complaints into CRM | R |
| Validate Mandatory Fields | R |
| Request Missing Information | R |
| Categorize Complaint | R |
| Assign Complaint to Resolution Team | R |
| Attach Supporting Documents | R |

---

### 2.6 SIPOC

**Supplier**
- Analyst, Customer

**Input**
- Customer complaints from multiple channels, Complaint details from email, phone log, or portal, Complaint record, Complaint record with missing fields, Validated complaint record, Categorized complaint, Supporting documents from customer, Complaint details from CRM

**Process**
- Collect Complaints from All Channels, Enter Complaints into CRM, Validate Mandatory Fields, Request Missing Information, Categorize Complaint

**Output**
- List of new complaints to be entered or updated in CRM, Complaint record in CRM, Validated complaint record or identification of missing information, Request for additional information sent to customer, Categorized complaint in CRM, Assigned complaint in CRM, Complaint record with attached evidence, Updated tracking spreadsheet, Acknowledgment email sent to customer

**Customer**
- Analyst, Customer, Management, Resolution team

---

### 2.7 High Level Process Flow
Collect Complaints from All Channels -> Enter Complaints into CRM -> Validate Mandatory Fields -> Request Missing Information -> Categorize Complaint -> Assign Complaint to Resolution Team -> Attach Supporting Documents -> Update Tracking Spreadsheet

---

## 3. Process Steps
### Step 1: Collect Complaints from All Channels
- Description: Analysts review shared mailbox for email complaints, check CRM for portal/web form complaints, and review phone log spreadsheet for phone complaints
- Tools / Systems: Outlook shared mailbox, CRM, Excel phone log
- Inputs: Customer complaints from multiple channels
- Outputs: List of new complaints to be entered or updated in CRM
- Source Timestamp: 
- Screenshot: Not available
- Estimated Effort: 1-2 minutes

### Step 2: Enter Complaints into CRM
- Description: Analysts manually create or update complaint records in CRM for items not already present, copying details from emails, phone logs, or portal submissions
- Tools / Systems: CRM
- Inputs: Complaint details from email, phone log, or portal
- Outputs: Complaint record in CRM
- Source Timestamp: 
- Screenshot: Not available
- Estimated Effort: 2-3 minutes

### Step 3: Validate Mandatory Fields
- Description: Analysts check for presence of customer ID, product, issue category, date of incident, and contact information in CRM record
- Tools / Systems: CRM
- Inputs: Complaint record
- Outputs: Validated complaint record or identification of missing information
- Source Timestamp: 
- Screenshot: Not available
- Estimated Effort: 1-2 minutes

### Step 4: Request Missing Information
- Description: If mandatory fields are missing, analyst sends a template email to the customer requesting additional details. Template is often edited manually
- Tools / Systems: Outlook
- Inputs: Complaint record with missing fields
- Outputs: Request for additional information sent to customer
- Source Timestamp: 
- Screenshot: Not available
- Estimated Effort: 2-5 minutes

### Step 5: Categorize Complaint
- Description: Analyst selects complaint type in CRM from dropdown (billing, service quality, product defect, delivery issue, regulatory, or other)
- Tools / Systems: CRM
- Inputs: Validated complaint record
- Outputs: Categorized complaint in CRM
- Source Timestamp: 
- Screenshot: Not available
- Estimated Effort: 1-2 minutes

### Step 6: Assign Complaint to Resolution Team
- Description: Analyst manually assigns complaint to billing operations, product support, or field service team based on complaint type, product line, region, and customer tier. Regulatory complaints are also copied to compliance
- Tools / Systems: CRM
- Inputs: Categorized complaint
- Outputs: Assigned complaint in CRM
- Source Timestamp: 
- Screenshot: Not available
- Estimated Effort: 1-2 minutes

### Step 7: Attach Supporting Documents
- Description: Analyst attaches relevant evidence and documents to CRM record, renames files, and organizes attachments as needed
- Tools / Systems: CRM, document repository
- Inputs: Supporting documents from customer
- Outputs: Complaint record with attached evidence
- Source Timestamp: 
- Screenshot: Not available
- Estimated Effort: 1-3 minutes

### Step 8: Update Tracking Spreadsheet
- Description: Analyst updates a separate tracking spreadsheet for management reporting, duplicating key complaint data from CRM
- Tools / Systems: Excel tracking spreadsheet
- Inputs: Complaint details from CRM
- Outputs: Updated tracking spreadsheet
- Source Timestamp: 
- Screenshot: Not available
- Estimated Effort: 1-2 minutes

### Step 9: Send Acknowledgment Email
- Description: Analyst sends acknowledgment email to customer, often manually typed or edited from a template
- Tools / Systems: Outlook
- Inputs: Complaint record
- Outputs: Acknowledgment email sent to customer
- Source Timestamp: 
- Screenshot: Not available
- Estimated Effort: 1-2 minutes


## 4. Process Exceptions
| Exception Scenario | Description | Action Required | Owner |
|--------------------|-------------|-----------------|-------|
| No direct evidence found | No direct evidence found | No direct evidence found | No direct evidence found |

## 5. Process Controls
| Control # | Process Step | Control Description | Manual / System | Preventive / Detective |
|-----------|-------------|---------------------|-----------------|------------------------|
| C1 | Categorize Complaint | Required fields and validation checks must be completed before the process continues. | Manual | Preventive |

## 6. Approval Matrix
| Role | Responsibility |
|------|----------------|
| Analyst | Review documented responsibilities and approvals. |

## 7. Appendix
### Automation Opportunities
| ID | Description | Quantification | Automation Signal |
|----|-------------|----------------|-------------------|
| AUTO-01 | Fragmented intake across multiple channels and systems | Complaints received via email, portal, web form, and phone; manual consolidation required daily | High |
| AUTO-02 | Inconsistent data validation and follow-up for missing information | Analysts manually check mandatory fields and send varied requests; multiple follow-ups needed in some cases | High |
| AUTO-03 | Subjective complaint categorization and overuse of 'other' | No strict decision tree; misclassification affects SLA handling | Medium |
| AUTO-04 | Manual assignment and routing based on analyst judgment | Assignment rules are partly documented and partly tribal knowledge; 20% of complaints assigned to wrong team | High |
| AUTO-05 | Duplicate data entry into CRM and tracking spreadsheet | Analysts copy complaint details into both CRM and Excel for reporting | High |



### Frequently Asked Questions (FAQs)
| # | Topic | Top Tips |
|---|-------|----------|
| 1 | Process overview | Collect Complaints from All Channels -> Enter Complaints into CRM -> Validate Mandatory Fields -> Request Missing Information -> Categorize Complaint |

---
