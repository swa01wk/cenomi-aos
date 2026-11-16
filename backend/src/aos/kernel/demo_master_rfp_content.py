"""Shareable Master RFP body for the RFP-0001 client demo (matches agent-authored depth)."""

from __future__ import annotations

from typing import Any

TITLE = "Full redesign of Cenomi Malls public marketing website with CMS and REST API"


def demo_master_rfp_content() -> dict[str, Any]:
    return {
        "title": TITLE,
        "scope_summary": _SCOPE,
        "functional_requirements": _FUNCTIONAL,
        "technical_requirements": _TECHNICAL,
        "delivery_timeline": _TIMELINE,
        "proposal_deadline": (
            "Proposals due five calendar days from invitation (demo environment may compress this to minutes). "
            "Late submissions require written approval from the sourcing buyer."
        ),
        "evaluation_criteria": _EVALUATION,
        "budget_guidance": {"amount": 5_200_000, "currency": "SAR"},
    }


_SCOPE = """\
Cenomi Centers Company (“Cenomi Malls”) is procuring a single integrator to design, build, and transition a new \
public marketing web platform for the mall portfolio. The program replaces the current public site and related \
content tooling with a modern bilingual experience (Arabic and English), a CMS that mall marketing and tenant \
relations teams can operate without developer intervention, and a REST API layer that powers future mobile apps \
and partner integrations.

The scope covers all consumer-facing marketing pages (mall home, directory, campaigns, events, offers, store \
detail, dining, entertainment, services, careers, and corporate sustainability narratives), tenant and brand \
story pages approved for publication, lead-capture flows (leasing enquiries, VIP club, event registration), \
and operational content modules (opening hours, parking, wayfinding, prayer times where applicable, and \
accessibility statements). Content migration from the existing site is in scope for agreed page and media \
volumes; the supplier must provide a migration plan, tooling, and reconciliation report.

Out of scope for phase one unless added through change control: Salesforce CRM sync, full tenant portal \
authentication, e-commerce transactions, and bespoke mobile native apps (the REST API is in scope; native \
apps are not). The supplier will work with Cenomi IT, Marketing, Tenant Relations, and the Chief Digital \
Officer’s office. All vendor communications on scope clarifications route through the category manager after \
draft answers are approved."""

_FUNCTIONAL = """\
Content management and authoring
• Bilingual CMS with side-by-side or linked EN/AR authoring, mandatory for all public and tenant-facing modules \
at launch unless explicitly deferred in writing with Cenomi approval.
• Role-based publishing workflow: author, reviewer, legal/compliance check, publish — with audit trail.
• Reusable components for campaigns, hero modules, carousels, video, and mall-specific landing templates.
• Scheduled publish and embargo; preview URLs for stakeholders before go-live.

Marketing and tenant experience
• Mall and store directory with search, filters (category, floor, offers), and map integration hooks.
• Tenant/brand pages using approved templates; no unapproved third-party scripts without security review.
• Lead forms (leasing, VIP, events) with configurable fields, consent capture aligned with PDPL, and export to \
agreed endpoints (CSV/API). Salesforce CRM is not in phase one.

Quality, accessibility, and analytics
• WCAG 2.1 AA for all public templates; supplier provides accessibility conformance report before UAT exit.
• SEO: metadata, structured data for malls and events, sitemap, redirects from legacy URLs documented in \
migration plan.
• Tag management (e.g. GA4) via approved container; implementation guide for Marketing.

Support and documentation
• Administrator and author training (minimum two sessions per language), runbooks, and handover pack.
• Twelve months warranty and hypercare from go-live with defined severity levels and response targets."""

_TECHNICAL = """\
Architecture and hosting
• Primary hosting for CMS and API in Saudi Arabia (Azure region approved by Cenomi IT). DR pattern documented; \
non-PII static assets may use approved secondary region.
• Separate staging, UAT, and production environments; infrastructure as code or documented build procedures.
• SSO for content authors via Azure AD; MFA aligned with Cenomi policy.

API and integrations
• REST APIs documented in OpenAPI 3.1; versioned endpoints for mall directory, events, offers, and lead submission.
• API gateway integration (existing Cenomi gateway or agreed alternative); rate limits and API keys managed with IT.
• No GraphQL requirement in phase one.

Security and compliance
• OWASP-aligned secure SDLC; dependency scanning; secrets management without credentials in source control.
• One external penetration test before production cutover with remediation sprint for critical/high findings.
• PDPL-aware handling of personal data in forms; data residency in KSA for PII.

Performance and operations
• Target Core Web Vitals thresholds agreed in contract; load test report before launch.
• Monitoring, alerting, and on-call runbook for P1/P2 during hypercare; integration with Cenomi IT monitoring \
where required."""

_TIMELINE = """\
Phase 0 — Mobilisation (weeks 1–2): kick-off, refined backlog, environment provisioning, migration inventory.
Phase 1 — Design (weeks 3–8): UX/UI for priority templates, CMS component library, API design sign-off.
Phase 2 — Build (weeks 9–28): iterative sprints, CMS configuration, API implementation, content migration waves.
Phase 3 — UAT and training (weeks 29–36): bilingual UAT scripts, defect burn-down, author training, accessibility audit.
Phase 4 — Go-live and hypercare (weeks 37–40): cutover, redirect validation, hypercare through month 12 post launch.
Total indicative duration: ten months phased; supplier proposals may suggest minor adjustments with justification."""

_EVALUATION = """\
Evaluation follows the **agreed scoring method** (Documents → Scoring agreement): two-envelope QCBS with \
**70% technical / 30% commercial** and **minimum technical score 70** before commercial envelopes are scored.

Technical envelope (100 points internally) — weighted criteria: scope and methodology (25%), staffing (20%), \
equipment and sustainability (15%), SLA and quality reporting (25%), experience and references (15%). Evaluators \
use the 0–5 scale per criterion (see Technical eval rubric after proposals arrive).

Commercial envelope — **fixed-price module BoQ** (MOD-01–MOD-05); lowest qualified bid sets QCBS commercial points. \
Procurement validates like-for-like scope before comparison.

Suppliers submit **separate technical and commercial proposals**. Cenomi standard RFP terms, PDPL, and KSA hosting \
apply. Clarifications route: commercial → Procurement; technical → category manager."""
