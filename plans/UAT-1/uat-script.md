# UAT script · UAT-1 (draft)

One case per requirement. SPEC-23 completes the steps and expected results from the journeys; the client fills the
result column. Environment: the UAT host from SPEC-22, personas Faisal (requester), Noura (sourcing buyer), Samir (CDO),
Rami (category manager), Platform admin. Vendors are simulated and reply by email within minutes.

| Case | Requirement | Scenario | Steps | Expected | Result (pass/fail, notes) |
| --- | --- | --- | --- | --- | --- |
| UAT-QQ-01 | R-QQ-01 | Faisal starts through the coordinator (New job, hand-off to the sourcing specialist) or directly from People; the job id starts QQ- | _to write in SPEC-23_ | Faisal starts through the coordinator (New job, hand-off to the sourcing specialist) or directly from People works as described | |
| UAT-QQ-02 | R-QQ-02 | Intake chat builds the brief in the panel; Retry this step on a failed intake | _to write in SPEC-23_ | Intake chat builds the brief in the panel works as described | |
| UAT-QQ-03 | R-QQ-03 | Faisal confirms the brief | _to write in SPEC-23_ | Faisal confirms the brief works as described | |
| UAT-QQ-04 | R-QQ-04 | Noura claims from the queue and shortlists ≥3 ranked suppliers with cited sources | _to write in SPEC-23_ | Noura claims from the queue and shortlists ≥3 ranked suppliers with cited sources works as described | |
| UAT-QQ-05 | R-QQ-05 | RFQ drafts per supplier; a budget leak returns REWORK | _to write in SPEC-23_ | RFQ drafts per supplier works as described | |
| UAT-QQ-06 | R-QQ-06 | Approve and send RFQs; state Awaiting quotes | _to write in SPEC-23_ | Approve and send RFQs works as described | |
| UAT-QQ-07 | R-QQ-07 | Vendor replies by mail become quotes through the agent, injection-safe | _to write in SPEC-23_ | Vendor replies by mail become quotes through the agent, injection-safe works as described | |
| UAT-QQ-08 | R-QQ-08 | Short quote window and clock advance in UAT | _to write in SPEC-23_ | Short quote window and clock advance in UAT works as described | |
| UAT-QQ-09 | R-QQ-09 | Comparison and the five evaluation sheets computed from the real quotes | _to write in SPEC-23_ | Comparison and the five evaluation sheets computed from the real quotes works as described | |
| UAT-QQ-10 | R-QQ-10 | Faisal never sees prices; asking is refused with the rule | _to write in SPEC-23_ | Faisal never sees prices works as described | |
| UAT-QQ-11 | R-QQ-11 | Noura awards one supplier | _to write in SPEC-23_ | Noura awards one supplier works as described | |
| UAT-QQ-12 | R-QQ-12 | PR/PO written once to the ERP; closes only on the receipt; handover | _to write in SPEC-23_ | PR/PO written once to the ERP works as described | |
| UAT-RFP-01 | R-RFP-01 | Start prompt gives an RFP- job | _to write in SPEC-23_ | Start prompt gives an RFP- job works as described | |
| UAT-RFP-02 | R-RFP-02 | Brief confirms for Noura as the starter when intake completes | _to write in SPEC-23_ | Brief confirms for Noura as the starter when intake completes works as described | |
| UAT-RFP-03 | R-RFP-03 | Spec stage: RFP validation, template check, 70/30 scoring agreement, uploads, send-back to the requester | _to write in SPEC-23_ | Spec stage: RFP validation, template check, 70/30 scoring agreement, uploads, send-back to the requester works as described | |
| UAT-RFP-04 | R-RFP-04 | Shortlist ≥3 integrators | _to write in SPEC-23_ | Shortlist ≥3 integrators works as described | |
| UAT-RFP-05 | R-RFP-05 | Master RFP (70/30 QCBS) and vendor copy in Documents, leak-checked, PDF download | _to write in SPEC-23_ | Master RFP (70/30 QCBS) and vendor copy in Documents, leak-checked, PDF download works as described | |
| UAT-RFP-06 | R-RFP-06 | Samir opens it from the Team queue, edits in the panel, approves or sends back; the approval binds to his version | _to write in SPEC-23_ | Samir opens it from the Team queue, edits in the panel, approves or sends back works as described | |
| UAT-RFP-07 | R-RFP-07 | Three Invite drafts; Approve and send; Awaiting proposals | _to write in SPEC-23_ | Three Invite drafts works as described | |
| UAT-RFP-08 | R-RFP-08 | Acks, three questions per vendor and proposals arrive by mail and are triaged | _to write in SPEC-23_ | Acks, three questions per vendor and proposals arrive by mail and are triaged works as described | |
| UAT-RFP-09 | R-RFP-09 | Commercial questions to Noura, technical to Rami; draft in Notes; approve; one answer to all bidders | _to write in SPEC-23_ | Commercial questions to Noura, technical to Rami works as described | |
| UAT-RFP-10 | R-RFP-10 | RFP responses table with the version dropdown per vendor | _to write in SPEC-23_ | RFP responses table with the version dropdown per vendor works as described | |
| UAT-RFP-11 | R-RFP-11 | Agent progress lines in the thread | _to write in SPEC-23_ | Agent progress lines in the thread works as described | |
| UAT-RFP-12 | R-RFP-12 | Deadline or all proposals in moves to Evaluation | _to write in SPEC-23_ | Deadline or all proposals in moves to Evaluation works as described | |
| UAT-RFP-13 | R-RFP-13 | Technical, commercial and weighted sheets; Show scoring rubric | _to write in SPEC-23_ | Technical, commercial and weighted sheets works as described | |
| UAT-RFP-14 | R-RFP-14 | Confirm commercial module review moves to BAFO | _to write in SPEC-23_ | Confirm commercial module review moves to BAFO works as described | |
| UAT-RFP-15 | R-RFP-15 | BAFO: module comparison and scores, drafts to outliers, approve and send, vendor replies, Complete round re-scores | _to write in SPEC-23_ | BAFO: module comparison and scores, drafts to outliers, approve and send, vendor replies, Complete round re-scores works as described | |
| UAT-RFP-16 | R-RFP-16 | Rami recommends a vendor for award | _to write in SPEC-23_ | Rami recommends a vendor for award works as described | |
| UAT-RFP-17 | R-RFP-17 | Requisition to the ERP (Fusion PR) and Closed | _to write in SPEC-23_ | Requisition to the ERP (Fusion PR) and Closed works as described | |
| UAT-RFP-18 | R-RFP-18 | Three role queues; Drafts, Responses, Documents work panel | _to write in SPEC-23_ | Three role queues works as described | |
| UAT-X-01 | R-X-01 | Opening a job never changes it | _to write in SPEC-23_ | Opening a job never changes it works as described | |
| UAT-X-02 | R-X-02 | UAT runs with AOS_DEMO=0: no heals, no bootstrap | _to write in SPEC-23_ | UAT runs with AOS_DEMO=0: no heals, no bootstrap works as described | |
