"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, Check, CreditCard, ExternalLink, Gift, History, KeyRound, LoaderCircle, Plus, Wallet } from "lucide-react";
import { FormSkeleton } from "@/components/skeleton";
import { useToast } from "@/components/toast";
import { Alert, Modal, PageHead } from "@/components/ui";
import { Segmented } from "@/components/reports/filter-bar";
import { api, messageFrom } from "@/lib/api";
import { useLanguage, type I18nKey } from "@/lib/i18n";
import type { BillingOverview, BillingSpend, CreditTransaction } from "@/types";

const RANGES = [7, 30, 90] as const;
const KIND_KEYS: Record<string, I18nKey> = {
  topup: "billing.kindTopup", bonus: "billing.kindBonus", usage: "billing.kindUsage", adjustment: "billing.kindAdjustment",
};

function usd(value: number): string {
  if (Math.abs(value) > 0 && Math.abs(value) < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

export default function BillingPage() {
  const { t, lang } = useLanguage();
  const toast = useToast();
  const [overview, setOverview] = useState<BillingOverview | null>(null);
  const [spend, setSpend] = useState<BillingSpend | null>(null);
  const [days, setDays] = useState<(typeof RANGES)[number]>(30);
  const [ledger, setLedger] = useState<CreditTransaction[] | null>(null);
  const [topup, setTopup] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setOverview(await api<BillingOverview>("/billing")); } catch (err) { toast.error(messageFrom(err)); }
  }, [toast]);
  useEffect(() => {
    load();
    const params = new URLSearchParams(window.location.search);
    if (params.get("topup") === "success") setNotice(t("billing.topupSuccess"));
    if (params.get("checkout") === "success") setNotice(t("billing.checkoutSuccess"));
  }, [load, t]);
  useEffect(() => {
    if (!overview?.enabled) return;
    api<BillingSpend>(`/billing/spend?days=${days}`).then(setSpend).catch(() => {});
  }, [overview?.enabled, days]);

  async function redirect(key: string, path: string, body?: object) {
    setBusy(key);
    try { const { url } = await api<{ url: string }>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }); window.location.assign(url); }
    catch (err) { toast.error(messageFrom(err)); setBusy(null); }
  }
  async function openLedger() {
    try { setLedger(await api<CreditTransaction[]>("/billing/transactions")); } catch (err) { toast.error(messageFrom(err)); }
  }
  const when = (value: string) => new Date(value).toLocaleString(lang === "es" ? "es" : "en", { dateStyle: "medium", timeStyle: "short" });

  const back = <Link href="/" className="back-link"><ArrowLeft size={16} /> {t("billing.back")}</Link>;
  if (!overview) return <div className="page">{back}<FormSkeleton sections={3} /></div>;
  if (!overview.enabled) return <div className="page">{back}<PageHead eyebrow={t("billing.eyebrow")} title={t("billing.title")} description={t("billing.disabled")} /></div>;

  const plan = overview.plan;
  const limit = plan?.max_clients;
  return <div className="page">
    {back}
    <PageHead eyebrow={plan ? t("billing.currentPlan", { plan: plan.name, used: overview.clients_used, limit: limit ?? "∞" }) : t("billing.eyebrow")}
      title={t("billing.title")} description={t("billing.description")} />
    {notice && <Alert type="success">{notice}</Alert>}
    {overview.subscribed ? <div className="billing-banner ok"><Check size={16} /> {t("billing.planActive", { plan: plan?.name ?? "" })}</div>
      : overview.subscription_status === "past_due" ? <div className="billing-banner warn">{t("billing.pastDue")}</div>
      : <div className="billing-banner">{plan ? t("billing.trial", { plan: plan.name }) : t("billing.noPlan")}</div>}

    <section className="billing-card">
      <header><div><h2><Wallet size={18} /> {t("billing.creditTitle")}</h2><p>{overview.own_key ? t("billing.creditOwnKey") : t("billing.creditCopy")}</p></div>
        <div className="row-actions">
          <button type="button" className="button ghost" onClick={openLedger}><History size={15} /> {t("billing.movements")}</button>
          <button type="button" className="button primary" disabled={!overview.payments} onClick={() => setTopup(true)}><Plus size={15} /> {t("billing.addCredit")}</button>
        </div>
      </header>
      <div className="billing-balance"><small>USD</small><strong>{usd(overview.credit_balance)}</strong></div>
      {!overview.platform_key && <p className="muted">{t("billing.noPlatformKey")}</p>}
      {overview.topup_bonus_percent > 0 && <div className="billing-promo"><Gift size={18} /><span><strong>{t("billing.promoTitle", { percent: overview.topup_bonus_percent })}</strong><small>{t("billing.promoCopy")}</small></span></div>}
    </section>

    <section className="billing-plans">
      {overview.plans.map((item) => {
        const current = overview.subscribed && plan?.id === item.id;
        return <article key={item.id} className={current ? "current" : ""}>
          <small>{current ? t("billing.yourPlan") : " "}</small>
          <h3>{item.name}</h3>
          <strong>${item.price_usd}<span>/{t("billing.month")}</span></strong>
          <p>{item.max_clients === null ? t("billing.unlimitedClients") : t("billing.upToClients", { count: item.max_clients })}</p>
          {current ? <span className="pill purple">{t("billing.current")}</span>
            : <button type="button" className="button secondary" disabled={!overview.payments || busy !== null} onClick={() => redirect(`plan:${item.id}`, "/billing/checkout", { plan_id: item.id })}>
              {busy === `plan:${item.id}` ? <LoaderCircle className="spin" size={15} /> : null} {t("billing.choosePlan")}</button>}
        </article>;
      })}
    </section>

    <section className="billing-card">
      <header><div><h2><KeyRound size={18} /> {t("billing.spendTitle")}</h2><p>{t("billing.spendCopy")}</p></div>
        <div className="row-actions">
          <Segmented value={days} onChange={setDays} label={t("billing.period")} options={RANGES.map((value) => ({ value, label: t(`billing.last${value}`) }))} />
          <Link href="/reports/costs" className="button ghost">{t("billing.openReports")}</Link>
        </div>
      </header>
      {spend && <div className="billing-split">
        <div><small>{t("billing.platformCredit")}</small><strong>USD {usd(spend.platform.usd).slice(1)}</strong><p>{t("billing.share", { percent: spend.platform.percent, replies: spend.platform.replies })}</p><div className="meter"><span style={{ width: `${spend.platform.percent}%` }} /></div></div>
        <div><small>{t("billing.ownKey")}</small><strong>USD {usd(spend.own.usd).slice(1)}</strong><p>{t("billing.share", { percent: spend.own.percent, replies: spend.own.replies })}</p><div className="meter"><span style={{ width: `${spend.own.percent}%` }} /></div></div>
      </div>}
    </section>

    <section className="billing-card">
      <header><div><h2><CreditCard size={18} /> {t("billing.manageTitle")}</h2><p>{t("billing.manageCopy")}</p></div>
        <button type="button" className="button secondary" disabled={!overview.payments || busy !== null} onClick={() => redirect("portal", "/billing/portal")}>
          {busy === "portal" ? <LoaderCircle className="spin" size={15} /> : <ExternalLink size={15} />} {t("billing.manage")}</button>
      </header>
      {overview.customer_id && <p className="muted">ID: <code>{overview.customer_id}</code></p>}
      {!overview.payments && <p className="muted">{t("billing.noPayments")}</p>}
    </section>

    <Modal open={topup} title={t("billing.addCredit")} description={t("billing.topupCopy")} onClose={() => setTopup(false)}>
      <div className="billing-amounts">{overview.topup_amounts.map((amount) => {
        const bonus = amount * overview.topup_bonus_percent / 100;
        return <button key={amount} type="button" className="button secondary" disabled={busy !== null} onClick={() => redirect(`topup:${amount}`, "/billing/topup", { amount })}>
          {busy === `topup:${amount}` && <LoaderCircle className="spin" size={15} />} <strong>USD {amount}</strong>{bonus > 0 && <small>+{usd(bonus)}</small>}</button>;
      })}</div>
    </Modal>
    <Modal open={ledger !== null} title={t("billing.movements")} onClose={() => setLedger(null)} wide>
      {ledger && (ledger.length ? <div className="table-shell"><table className="data-table"><thead><tr><th>{t("billing.colDate")}</th><th>{t("billing.colConcept")}</th><th>{t("billing.colAmount")}</th><th>{t("billing.colBalance")}</th></tr></thead><tbody>
        {ledger.map((row) => <tr key={row.id}><td>{when(row.created_at)}</td><td><strong>{KIND_KEYS[row.kind] ? t(KIND_KEYS[row.kind]) : row.kind}</strong><br /><small>{row.description}</small></td>
          <td className={row.amount_usd < 0 ? "danger-text" : ""}>{row.amount_usd < 0 ? "−" : "+"}{usd(Math.abs(row.amount_usd))}</td><td>{usd(row.balance_after)}</td></tr>)}
      </tbody></table></div> : <p className="muted">{t("billing.noMovements")}</p>)}
    </Modal>
  </div>;
}
