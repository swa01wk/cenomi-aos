# Known limitations · UAT-1 (draft)

SPEC-23 finalises this list with the client. Items here are by design for UAT, not bugs.

- **Vendors are simulated.** They reply by email to the job's threads on a short timeline. Real vendor mailboxes are
  not connected.
- **ERP is a mock.** Purchase requisitions and orders are written to a mock Oracle Fusion; native Fusion negotiation
  and award records are not in scope.
- **Sign-in is a persona pick without passwords.** The UAT host is protected by HTTPS and basic auth instead. SSO is
  deferred.
- **Governance is deferred:** no policy engine, approval chains or segregation of duties beyond the workflow's own
  decision cards; no kill switch; no telemetry dashboards.
- **Sealed price envelopes** are enforced by visibility rules, not a separate store. Criteria are not version-locked
  after approval.
- **Evaluation** is one evaluator view with agent-suggested scores; multi-evaluator scoring and moderation are not in
  scope.
- **Not in scope:** new-supplier onboarding, pause/cancel/re-tender, award and regret letters (if SPEC-24 is not done),
  extension of deadlines for all bidders.
- **Short windows:** quote and proposal deadlines run in minutes (`AOS_DEMO_CLOCK=1`) so a journey fits a session.
- **Model variance:** the agent's wording differs between runs; the steps and the numbers do not.
