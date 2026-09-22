# HAPHAK GeneraPay

**Digital Giving & Payment Platform**

HAPHAK GeneraPay is a SaaS platform designed to help churches, ministries, NGOs, and other organizations collect, manage, track, and report digital contributions.

The platform is designed for international use, with support for multiple organizations, countries, currencies, and payment methods.

## Vision

Build a secure, accessible, scalable, and easy-to-use digital giving infrastructure that connects organizations with their donors and contributors.

## Core Use Cases

GeneraPay will support:

- Donations
- Tithes
- Offerings
- Campaigns
- Missions
- Construction projects
- Social and community projects
- Events and special collections

## Target Organizations

The platform is initially designed for:

- Churches
- Ministries
- Christian organizations
- NGOs
- Non-profit organizations
- Community organizations

The architecture should remain flexible enough to support additional organization types in the future.

## SaaS Architecture

GeneraPay must be designed as a multi-tenant SaaS platform.

Each organization must have isolated data and resources.

Every organization-owned record must be associated with an `organization_id`.

Security and data isolation must be enforced at the database level.

## Initial MVP

The first version will provide:

1. Organization registration
2. User authentication
3. Organization profile
4. Public giving page
5. Donation creation
6. Contribution types
7. Currency selection
8. Transaction tracking
9. Payment status
10. Digital receipts
11. Organization dashboard
12. Basic reporting

## Contribution Types

The initial contribution types are:

- Donation
- Tithe
- Offering
- Campaign

The architecture should allow additional contribution types to be added later without major database changes.

## Multi-Currency

The system must separate:

- amount
- currency

The initial currencies are:

- USD
- CDF
- EUR

Currency conversion must not be assumed automatically.

Each transaction must preserve its original amount and currency.

## Payment Architecture

GeneraPay should use a payment-provider abstraction layer.

The application must not be tightly coupled to a single payment provider.

Future payment methods may include:

- Mobile Money
- Bank transfer
- Debit cards
- Credit cards
- International payment providers
- Regional payment aggregators

Payment providers should process the actual payment while GeneraPay manages the software experience, transaction records, organization dashboards, receipts, and reporting.

## Payment Flow

Donor  
→ Public Giving Page  
→ Amount & Currency  
→ Contribution Type  
→ Payment Method  
→ Payment Provider  
→ Payment Processing  
→ Webhook  
→ Server-side Verification  
→ Transaction Status  
→ Receipt

The application must never trust a client-side payment success message.

Payment status must be confirmed server-side.

## Security Principles

Security is a core requirement.

The platform must implement:

- Authentication
- Authorization
- Role-based access control
- Database Row Level Security
- Organization-level data isolation
- Secure environment variables
- Webhook verification
- Idempotency
- Audit logs
- Server-side payment verification
- Input validation
- Rate limiting where appropriate
- Secure error handling
- Database backups

Sensitive credentials must never be committed to GitHub.

## Planned Technology Stack

### Frontend

- Next.js
- React
- TypeScript

### Backend

- FastAPI
- Python

### Database

- PostgreSQL
- Supabase

### Authentication

- Supabase Auth

### Version Control

- Git
- GitHub

### AI Development

- OpenAI Codex

## Core Data Model

The initial database architecture is expected to include:

- organizations
- users
- memberships
- donors
- campaigns
- donations
- payment_transactions
- payment_providers
- receipts
- audit_logs

The final schema must be designed before production implementation.

## Product Roadmap

### Phase 1 — Foundation

- Architecture
- Repository
- Database
- Authentication
- Organization model
- Security foundation

### Phase 2 — MVP

- Public giving page
- Contributions
- Transactions
- Basic dashboard
- Receipts

### Phase 3 — Campaigns

- Campaign creation
- Campaign goals
- Progress tracking
- Public campaign pages

### Phase 4 — Payment Expansion

- Multiple payment providers
- Mobile Money
- Cards
- Bank payments
- International payment methods

### Phase 5 — SaaS Expansion

- Multiple organizations
- Organization administration
- Roles and permissions
- Subscription/billing model

### Phase 6 — Advanced Features

- Recurring giving
- Advanced reporting
- QR codes
- WhatsApp integration
- Email/SMS notifications
- API
- White-label capabilities

### Phase 7 — AI

- AI reporting
- Financial insights
- Intelligent organization assistant
- Automated workflows

## Development Principles

GeneraPay development must prioritize:

1. Security
2. Data integrity
3. Simplicity
4. Scalability
5. Maintainability
6. Testability
7. Clear documentation
8. Provider independence
9. Mobile-first user experience
10. Responsible financial technology practices

## Project Status

**Status:** Initial architecture and MVP planning.

## Ownership

**HAPHAK**

HAPHAK GeneraPay is a HAPHAK technology product.

---

**Built for organizations. Designed for global giving.**
