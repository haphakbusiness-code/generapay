# AGENTS.md — HAPHAK GeneraPay

## 1. PROJECT IDENTITY

Project name: HAPHAK GeneraPay

Product type: Multi-tenant SaaS digital giving and payment platform.

Parent company: HAPHAK.

Primary purpose:
Provide churches, ministries, NGOs, non-profit organizations, and community organizations with a secure platform to collect, manage, track, reconcile, and report digital contributions.

Supported contribution types include:
- Donations
- Tithes
- Offerings
- Campaigns
- Missions
- Construction projects
- Social and community projects
- Events and special collections

The product is designed for international expansion.

---

## 2. CORE ARCHITECTURAL PRINCIPLES

GeneraPay MUST be designed as a multi-tenant SaaS from day one.

Every organization-owned record MUST contain:
`organization_id`

Tenant data MUST be isolated at the database level.

Never implement a single-organization architecture that would require a major rewrite later.

The platform MUST separate:
1. The SaaS application layer
2. The payment orchestration layer
3. External payment providers

GeneraPay is initially a software/payment-orchestration platform.

At MVP stage, GeneraPay MUST NOT hold customer funds in a GeneraPay wallet or bank account.

Funds should flow to the organization's merchant/payment account through an appropriate payment service provider, subject to applicable legal, regulatory, contractual, and KYC requirements.

Do not assume regulatory compliance.
Any production payment integration must be reviewed against the applicable rules and provider requirements.

---

## 3. TECHNOLOGY STACK

Frontend:
- Next.js
- React
- TypeScript
- Tailwind CSS
- shadcn/ui where appropriate

Backend:
- Python
- FastAPI

Database:
- PostgreSQL
- Supabase

Authentication:
- Supabase Auth

Database security:
- Supabase Row Level Security (RLS)

Version control:
- Git
- GitHub

AI development:
- OpenAI Codex

Email:
- Resend

Messaging:
- WhatsApp Cloud API
- SMS provider when required

Initial deployment direction:
- Vercel for frontend
- Render or Railway for backend

The final production architecture must be based on security, reliability, cost, scalability, and operational requirements.

---

## 4. REPOSITORY STRUCTURE

The intended structure is:

generapay/
├── web/
├── api/
├── supabase/
│   └── migrations/
├── tests/
├── docs/
├── README.md
├── AGENTS.md
└── .gitignore

Do not create unnecessary directories.

Keep frontend, backend, database migrations, tests, and documentation clearly separated.

---

## 5. DATABASE PRINCIPLES

Use PostgreSQL through Supabase.

Expected core entities include:

- organizations
- organization_members
- donors
- campaigns
- donations
- payment_transactions
- webhook_events
- ledger_entries
- payment_routes
- merchant_accounts
- notifications
- audit_logs
- subscriptions

The final schema must be implemented through version-controlled migrations.

Do not manually modify production schema without a migration.

---

## 6. MONEY AND CURRENCY RULES

Never use floating-point numbers for monetary amounts.

Store monetary values as integer minor units.

Example:

1000 USD minor units = 10.00 USD

Every monetary record must contain:
- amount_minor
- currency

Use ISO 4217 currency codes.

Initial currencies:
- USD
- CDF
- EUR

Do not automatically convert currencies during payment processing.

The original transaction amount and currency must always be preserved.

Currency conversion may be used later for reporting or indicative display, but must never silently alter the original transaction.

---

## 7. PAYMENT ARCHITECTURE

Implement a provider abstraction.

Use a structure conceptually similar to:

PaymentProvider
├── MockProvider
├── ProviderA
├── ProviderB
└── ProviderC

The business logic must not depend directly on one payment provider.

Payment provider selection should be determined by appropriate routing rules such as:
- country
- currency
- payment method
- operator
- provider availability

Potential payment methods may include:
- Mobile Money
- Cards
- Bank transfer
- International payment methods

Do not assume a provider supports a country, currency, operator, or feature without verification.

---

## 8. PAYMENT STATE MACHINE

A donation/payment should normally begin as:

PENDING

Possible final states include:

SUCCESS
FAILED
EXPIRED

Expected flow:

PENDING
    |
    | verified successful payment
    v
SUCCESS
    |
    +--> ledger entry
    |
    +--> receipt

Alternative:

PENDING --> FAILED

or:

PENDING --> EXPIRED

Rules:

1. A SUCCESS transaction must not silently become FAILED.
2. A webhook received twice must not create duplicate financial records.
3. Payment success must be verified server-side.
4. Never trust a client-side success message.
5. Provider references must be stored.
6. Idempotency must be enforced.

---

## 9. IDEMPOTENCY

Every payment initiation and webhook processing flow must be designed to prevent duplicate transactions.

Use unique identifiers such as:
- internal donation reference
- provider transaction ID
- idempotency key
- webhook event ID

Repeated webhook delivery must be safe.

Processing the same event twice must produce the same final result without creating duplicate ledger entries or receipts.

---

## 10. WEBHOOK SECURITY

Webhook endpoints must:

1. Receive the provider request.
2. Validate the provider signature where supported.
3. Store the incoming event safely.
4. Check whether the event has already been processed.
5. Verify the transaction with the provider API where possible.
6. Update the transaction state.
7. Create the ledger entry only when appropriate.
8. Trigger notifications safely.

Never trust an unsigned or unverified client claim of payment success.

---

## 11. LEDGER

Financial ledger entries are critical.

The ledger must be treated as immutable.

Conceptual fields:

- id
- organization_id
- donation_id
- type
- amount_minor
- currency
- created_at

Possible entry types:
- donation
- fee
- platform_fee
- payout

Do not update historical ledger entries to correct accounting history.

Corrections should use compensating entries when appropriate.

The ledger must allow reconciliation between:
- donations
- payment transactions
- provider records
- organizational reporting

---

## 12. RECONCILIATION

The system should support reconciliation of pending and completed transactions.

A background process may:
- check pending payments
- re-query provider status
- resolve uncertain transactions
- expire transactions after the configured timeout

Do not permanently leave payments in PENDING without a defined reconciliation strategy.

The initial MVP may use a lightweight scheduler.

A more advanced queue architecture can be introduced later if scale requires it.

---

## 13. SECURITY

Security is non-negotiable.

Implement:

- Authentication
- Authorization
- Role-based access control
- Supabase RLS
- Organization-level isolation
- Input validation
- Secure API design
- Webhook verification
- Idempotency
- Audit logs
- Secure error handling
- Rate limiting where appropriate
- HTTPS in production
- Secure secrets management
- Backups
- Monitoring

Never commit:
- API keys
- access tokens
- database passwords
- provider secrets
- private keys
- service-role keys
- production credentials

Never place secrets in frontend code.

Use environment variables and appropriate secret-management mechanisms.

---

## 14. ROLES

The initial organization roles may include:

- owner
- admin
- treasurer
- viewer

Permissions must be explicit.

A viewer must not automatically receive financial-management permissions.

A treasurer must not automatically receive organization-owner permissions.

Implement least privilege.

---

## 15. AUTHENTICATION

Use Supabase Auth initially.

Organization membership must be separate from authentication identity.

Conceptually:

User
  |
  +--> Organization Membership
          |
          +--> Role

Do not assume that a user belongs to only one organization.

The architecture should allow one user to belong to multiple organizations in the future.

---

## 16. PUBLIC DONATION PAGE

The public donation page should eventually support a structure similar to:

/{organization-slug}

It should display:
- organization identity
- logo
- contribution type
- amount
- currency
- payment method
- donor information when required
- confirmation status

The page must be mobile-first.

The donor should be able to complete a contribution with as few unnecessary steps as possible.

---

## 17. DASHBOARD

Organization dashboard should eventually provide:

- total contributions
- contributions by period
- contributions by type
- contributions by currency
- successful payments
- pending payments
- failed payments
- campaigns
- donor history where permitted
- receipts
- exports

Every query must respect organization-level authorization.

Never expose another organization's information.

---

## 18. MVP DEVELOPMENT STRATEGY

Build incrementally.

Do NOT implement the complete platform in one giant change.

Recommended order:

### Step 1 — Foundation
- repository
- architecture
- configuration
- health checks

### Step 2 — Database
- migrations
- organizations
- memberships
- RLS
- seed/demo organization

### Step 3 — Authentication
- login
- organization membership
- roles

### Step 4 — Mock Payment
- PaymentProvider interface
- MockProvider
- payment states
- webhooks
- idempotency
- reconciliation

### Step 5 — Public Giving Page
- organization slug
- amount
- currency
- contribution type
- donor information
- mock payment flow

### Step 6 — Dashboard
- authentication
- transactions
- statistics
- filtering
- export

### Step 7 — Receipts
- email
- optional SMS/WhatsApp

### Step 8 — Real Payment Provider
- sandbox first
- provider adapter
- webhook
- server verification
- reconciliation

### Step 9 — Pilot
- selected organizations
- monitoring
- backups
- security review
- operational procedures

Only after these foundations are stable should advanced features be introduced.

---

## 19. DEVELOPMENT WORKFLOW FOR CODEX

Codex must work incrementally.

Before modifying code:

1. Inspect the repository.
2. Read README.md.
3. Read AGENTS.md.
4. Understand existing architecture.
5. Identify affected files.
6. Propose the implementation when the task is complex.
7. Make the smallest safe change.
8. Run relevant tests.
9. Run lint/type checks when applicable.
10. Review the resulting diff.
11. Report what changed and what was tested.

Do not rewrite unrelated files.

Do not delete existing functionality without explicit justification.

Do not introduce dependencies without explaining why they are needed.

Prefer simple, maintainable solutions.

---

## 20. TESTING

Financial logic must be tested.

Tests should cover at minimum:

- authentication
- organization isolation
- RLS
- role permissions
- donation creation
- amount validation
- currency validation
- payment state transitions
- idempotency
- duplicate webhooks
- webhook verification
- ledger creation
- reconciliation
- receipt generation

Critical financial workflows require automated tests before production.

---

## 21. ERROR HANDLING

Errors must be:
- explicit
- structured
- safe
- useful for debugging

Never expose:
- secrets
- stack traces
- provider credentials
- database credentials
- internal sensitive data

Production error messages should be user-friendly.

Internal logs may contain technical details subject to security and privacy requirements.

---

## 22. OBSERVABILITY

Production should eventually include:

- structured logs
- error monitoring
- health checks
- payment metrics
- webhook metrics
- reconciliation metrics
- database monitoring
- audit logs

A payment reference should make it possible to trace a transaction through:

donation
→ payment_transaction
→ webhook_event
→ ledger_entry
→ notification

This reference-based tracing approach should be used when diagnosing payment issues.

---

## 23. API DESIGN

Backend APIs should be versionable.

Prefer clear REST-style endpoints.

Examples:

GET /health

POST /api/v1/donations

GET /api/v1/donations

POST /api/v1/payments/webhooks/{provider}

Use request validation and response schemas.

Do not expose internal database structures unnecessarily.

---

## 24. FRONTEND PRINCIPLES

The frontend must be:

- responsive
- mobile-first
- accessible
- simple
- fast
- professional

Avoid unnecessary complexity.

Use reusable components.

Keep business logic out of presentation components when possible.

---

## 25. INTERNATIONALIZATION

GeneraPay is intended for international use.

Architecture should eventually support:
- multiple countries
- multiple currencies
- multiple languages
- local payment methods
- regional payment providers

Do not hard-code DRC-specific assumptions into the core architecture.

DRC is the initial target market, not the permanent architectural limit.

---

## 26. REGULATORY AND PAYMENT PROVIDER RULES

The project must not assume that a payment provider is:
- licensed
- available
- authorized
- compatible
- affordable
- compliant

These must be verified before production use.

For each provider evaluate:
- regulatory status where applicable
- supported countries
- supported currencies
- supported operators
- sandbox availability
- webhook capabilities
- signature verification
- merchant accounts
- subaccounts
- settlement process
- transaction fees
- support
- contractual requirements
- KYC requirements

Never present an unverified provider capability as a confirmed fact.

---

## 27. PRIVACY

Handle donor information carefully.

Collect only information necessary for the intended function.

Potential personal data includes:
- name
- phone
- email
- donation history

Respect applicable privacy and data-protection requirements.

Do not expose donor information publicly unless explicitly intended and legally appropriate.

Anonymous giving must be supported where operationally possible.

---

## 28. AI RULES

AI is an enhancement, not the financial authority.

AI must never:
- confirm a payment by itself
- modify a financial ledger without controlled business logic
- bypass authentication
- bypass authorization
- bypass payment verification
- invent financial figures

AI may later assist with:
- reporting
- summaries
- trend analysis
- organization assistance
- communication
- natural-language queries

All financial answers generated by AI must be based on verified database records.

---

## 29. PRODUCT EXPANSION ROADMAP

After the MVP:

V2:
- campaigns
- QR codes
- EUR
- international PSPs
- cards

V3:
- recurring giving
- WhatsApp
- SMS
- SaaS subscriptions

V4:
- white-label
- custom domains
- public API
- mobile application
- USSD where appropriate

V5:
- AI assistant
- advanced financial insights
- automated reports

---

## 30. NON-NEGOTIABLE RULES

1. Never compromise tenant isolation.
2. Never use floating-point values for money.
3. Never trust client-side payment success.
4. Never skip webhook verification.
5. Never allow duplicate payment processing.
6. Never modify immutable financial history casually.
7. Never commit secrets.
8. Never expose another organization's data.
9. Never add a payment provider without an adapter.
10. Never make unverified regulatory or provider claims.
11. Never introduce unnecessary complexity.
12. Never modify unrelated code without justification.
13. Always test critical financial logic.
14. Always preserve transaction traceability.
15. Security and data integrity take priority over speed.

---

## 31. CURRENT PROJECT STATUS

Repository:
generapay

Product:
HAPHAK GeneraPay

Current stage:
Foundation / architecture

Completed:
- GitHub repository
- README.md

Next planned tasks:
- AGENTS.md
- Supabase project
- database architecture
- migrations
- application skeleton
- Codex development workflow

---

## 32. FINAL PRINCIPLE

Build GeneraPay as if it will eventually serve organizations across multiple countries.

Start simple.

Keep the architecture clean.

Protect the money trail.

Protect organization data.

Make every financial operation traceable.

Do not build tomorrow's complexity today, but never create today's architecture in a way that prevents tomorrow's growth.
