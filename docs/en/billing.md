# Billing: plans and AI credit

For an operator who hosts OpenNexus for an agency and charges for it. Off by
default (`BILLING_ENABLED=false`): a self-hosted install that brings its own AI
key needs none of this, and nothing changes for it.

## What it adds

- **Plans** that cap how many clients the agency can create. The sandbox
  client never counts. Defaults: Launch (USD 49, 5 clients), Growth (USD 149,
  20) and Unlimited (USD 349).
- **AI credit.** When the agency has no key of its own (or pauses it), the
  platform's key (`BILLING_PLATFORM_KEY`) answers while there is credit. Each
  reply is charged at its reported cost, or the catalog's list price when the
  provider gives none, times `BILLING_CREDIT_MARKUP`. With credit at zero the
  platform stops lending its key. The agency's own key is never charged.
- **Payments** through Stripe: Checkout for plans and top-ups, the customer
  portal for payment method, invoices and cancelation.
- A **Billing** page (shown in the sidebar only when billing is on) with plan,
  balance, the credit ledger, top-ups with an optional bonus, and where the AI
  spend ran (platform credit vs. own key).

It plugs into the core's documented seams, `register_credential_fallback` and
`register_usage_hook`, so the AI path itself is unchanged.

## Configure

```bash
BILLING_ENABLED=true
BILLING_PLATFORM_KEY=sk-or-...           # OpenRouter key the platform answers with
BILLING_CREDIT_MARKUP=1.2                # charge cost × 1.2
BILLING_TOPUP_BONUS_PERCENT=30           # pay 10, get 13
BILLING_TOPUP_AMOUNTS=10,25,50,100
BILLING_DEFAULT_PLAN=launch              # in force until a subscription; empty = subscribe first
BILLING_PLANS=[{"id":"launch","name":"Launch","price_usd":49,"max_clients":5,"stripe_price_id":"price_..."},{"id":"growth","name":"Growth","price_usd":149,"max_clients":20,"stripe_price_id":"price_..."},{"id":"unlimited","name":"Unlimited","price_usd":349,"max_clients":null,"stripe_price_id":"price_..."}]
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

In Stripe, create one recurring price per plan, enable the customer portal,
and add a webhook endpoint at `https://<your domain>/api/billing/webhook` for
`checkout.session.completed`, `customer.subscription.created`,
`customer.subscription.updated`, `customer.subscription.deleted` and
`invoice.payment_failed`. Webhook signatures are verified; each payment and
each usage record is applied exactly once.

## Operator commands

```bash
docker compose --env-file .env.docker exec api python -m app.billing_admin balance
docker compose --env-file .env.docker exec api python -m app.billing_admin grant 25 "Welcome credit"
docker compose --env-file .env.docker exec api python -m app.billing_admin plan growth active
```
