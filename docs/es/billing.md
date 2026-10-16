# Facturación: planes y crédito de IA

Para quien opera OpenNexus para una agencia y le cobra por ello. Desactivada
por defecto (`BILLING_ENABLED=false`): una instalación propia que trae su propia
clave de IA no necesita nada de esto, y para ella nada cambia.

## Qué agrega

- **Planes** que limitan cuántos clientes puede crear la agencia. El cliente
  del sandbox nunca cuenta. Por defecto: Launch (USD 49, 5 clientes), Growth
  (USD 149, 20) y Unlimited (USD 349).
- **Crédito de IA.** Cuando la agencia no tiene clave propia (o la pausa),
  responde la clave de la plataforma (`BILLING_PLATFORM_KEY`) mientras haya
  crédito. Cada respuesta se cobra a su costo reportado, o al precio de lista
  del catálogo cuando el proveedor no lo da, multiplicado por
  `BILLING_CREDIT_MARKUP`. Con el crédito en cero, la plataforma deja de prestar
  su clave. La clave propia de la agencia nunca se cobra.
- **Pagos** con Stripe: Checkout para planes y recargas, y el portal del
  cliente para método de pago, facturas y cancelación.
- Una página de **Facturación** (en el menú lateral solo con la facturación
  activa) con plan, saldo, el historial de movimientos, recargas con bono
  opcional y dónde corrió el gasto de IA (crédito de la plataforma frente a
  clave propia).

Se conecta a las extensiones documentadas del núcleo,
`register_credential_fallback` y `register_usage_hook`, así que el camino de la
IA no cambia.

## Configurar

```bash
BILLING_ENABLED=true
BILLING_PLATFORM_KEY=sk-or-...           # clave de OpenRouter con la que responde la plataforma
BILLING_CREDIT_MARKUP=1.2                # cobra costo × 1.2
BILLING_TOPUP_BONUS_PERCENT=30           # paga 10, recibe 13
BILLING_TOPUP_AMOUNTS=10,25,50,100
BILLING_DEFAULT_PLAN=launch              # vigente hasta que haya suscripción; vacío = suscribirse primero
BILLING_PLANS=[{"id":"launch","name":"Launch","price_usd":49,"max_clients":5,"stripe_price_id":"price_..."},{"id":"growth","name":"Growth","price_usd":149,"max_clients":20,"stripe_price_id":"price_..."},{"id":"unlimited","name":"Unlimited","price_usd":349,"max_clients":null,"stripe_price_id":"price_..."}]
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

En Stripe, crea un precio recurrente por plan, activa el portal del cliente y
agrega un webhook en `https://<tu dominio>/api/billing/webhook` para
`checkout.session.completed`, `customer.subscription.created`,
`customer.subscription.updated`, `customer.subscription.deleted` e
`invoice.payment_failed`. Las firmas del webhook se verifican; cada pago y cada
registro de uso se aplica exactamente una vez.

## Comandos del operador

```bash
docker compose --env-file .env.docker exec api python -m app.billing_admin balance
docker compose --env-file .env.docker exec api python -m app.billing_admin grant 25 "Crédito de bienvenida"
docker compose --env-file .env.docker exec api python -m app.billing_admin plan growth active
```
