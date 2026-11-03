"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, Printer } from "lucide-react";
import { api, apiUrl, messageFrom } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import { Alert } from "@/components/ui";
import { PanelSkeleton } from "@/components/skeleton";

type Totals = { conversations: number; contacts: number; new_contacts: number; ai_resolved: number; ai_resolved_pct: number; handoffs: number; first_reply_s: number | null; inbound: number; ai_replies: number; human_replies: number };
type Summary = { month: string; totals: Totals; by_channel: { channel: string; conversations: number }[]; by_day: { day: string; conversations: number }[]; ai_cost_usd: number; hours_saved: number };
type MonthlyReport = { client: { id: string; name: string; logo_url: string | null }; agency: { name: string; logo_url: string | null; brand_color: string }; minutes_per_reply: number; current: Summary; previous: Summary };

const CHANNEL_KEYS: Record<string, string> = { whatsapp: "WhatsApp", whatsapp_cloud: "WhatsApp", widget: "Web", webchat: "Web", instagram: "Instagram", messenger: "Messenger", phone: "phone" };

function lastFullMonth() {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function duration(seconds: number | null) {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

// Change from last month as "+12%"; nothing when there is no base to compare.
function delta(now: number, before: number) {
  if (!before) return null;
  const pct = Math.round(((now - before) / before) * 100);
  return `${pct > 0 ? "+" : ""}${pct}%`;
}

// A one-page report for the client: print it or save it as a PDF.
export default function ClientReportPage() {
  const { id } = useParams<{ id: string }>();
  const { t, lang } = useLanguage();
  const [month, setMonth] = useState(lastFullMonth());
  const [report, setReport] = useState<MonthlyReport | null>(null);
  const [error, setError] = useState("");
  const [showCost, setShowCost] = useState(false);

  useEffect(() => {
    setReport(null); setError("");
    api<MonthlyReport>(`/clients/${id}/monthly-report?month=${month}`).then(setReport).catch((err) => setError(messageFrom(err)));
  }, [id, month]);

  const monthLabel = (value: string) => {
    const label = new Date(`${value}-01T12:00:00`).toLocaleDateString(lang, { month: "long", year: "numeric" });
    return label.charAt(0).toUpperCase() + label.slice(1);
  };
  const pct = (value: number) => `${value.toLocaleString(lang, { maximumFractionDigits: 1 })}%`;
  const now = report?.current.totals;
  const before = report?.previous.totals;
  const maxDay = Math.max(1, ...(report?.current.by_day.map((d) => d.conversations) ?? [0]));

  return <div className="page client-report-page">
    <div className="report-toolbar no-print">
      <Link href={`/clients/${id}`} className="text-link"><ArrowLeft size={15} /> {t("clients.report.back")}</Link>
      <label className="range-select"><input type="month" value={month} max={lastFullMonth()} onChange={(e) => e.target.value && setMonth(e.target.value)} aria-label={t("clients.report.month")} /></label>
      <label className="report-toggle"><input type="checkbox" checked={showCost} onChange={(e) => setShowCost(e.target.checked)} /> {t("clients.report.showCost")}</label>
      <button type="button" className="button primary" onClick={() => window.print()} disabled={!report}><Printer size={16} /> {t("clients.report.print")}</button>
    </div>
    <p className="report-hint no-print">{t("clients.report.hint")}</p>
    {error && <Alert>{error}</Alert>}
    {!report && !error && <PanelSkeleton rows={6} />}
    {report && now && before && <article className="client-report" style={{ ["--report-accent" as string]: report.agency.brand_color || "#14213d" }}>
      <header className="client-report-head">
        <div className="client-report-brand">{report.client.logo_url ? <img src={apiUrl(report.client.logo_url)} alt="" /> : <span className="client-report-initials">{report.client.name.slice(0, 2).toUpperCase()}</span>}
          <div><small>{t("clients.report.eyebrow")}</small><h1>{report.client.name}</h1><p>{monthLabel(report.current.month)}</p></div></div>
        <div className="client-report-by">{report.agency.logo_url && <img src={apiUrl(report.agency.logo_url)} alt="" />}<span>{t("clients.report.preparedBy", { agency: report.agency.name })}</span></div>
      </header>

      <p className="client-report-lead">{now.conversations ? t("clients.report.lead", { conversations: now.conversations.toLocaleString(lang), pct: now.ai_resolved_pct.toLocaleString(lang, { maximumFractionDigits: 1 }), hours: report.current.hours_saved.toLocaleString(lang) }) : t("clients.report.leadEmpty")}</p>

      <section className="client-report-kpis">
        {[
          { label: t("clients.report.kConversations"), value: now.conversations.toLocaleString(lang), change: delta(now.conversations, before.conversations) },
          { label: t("clients.report.kResolved"), value: pct(now.ai_resolved_pct), change: null, caption: t("clients.report.kResolvedCaption", { count: now.ai_resolved }) },
          { label: t("clients.report.kFirstReply"), value: duration(now.first_reply_s), change: null, caption: before.first_reply_s != null ? t("clients.report.before", { value: duration(before.first_reply_s) }) : undefined },
          { label: t("clients.report.kNewContacts"), value: now.new_contacts.toLocaleString(lang), change: delta(now.new_contacts, before.new_contacts) },
          { label: t("clients.report.kHours"), value: `${report.current.hours_saved.toLocaleString(lang)} h`, change: null, caption: t("clients.report.kHoursCaption", { minutes: report.minutes_per_reply }) },
          { label: t("clients.report.kHandoffs"), value: now.handoffs.toLocaleString(lang), change: null, caption: t("clients.report.kHandoffsCaption") },
        ].map((kpi) => <div className="client-report-kpi" key={kpi.label}><small>{kpi.label}</small><strong>{kpi.value}</strong>{kpi.change && <span className={kpi.change.startsWith("-") ? "down" : "up"}>{t("clients.report.vsLast", { change: kpi.change })}</span>}{kpi.caption && <p>{kpi.caption}</p>}</div>)}
      </section>

      <section className="client-report-block">
        <h2>{t("clients.report.dailyTitle")}</h2>
        {report.current.by_day.length ? <div className="client-report-chart">{report.current.by_day.map((d) => <div key={d.day} className="client-report-bar" title={`${d.day}: ${d.conversations}`}><span style={{ height: `${Math.round((d.conversations / maxDay) * 100)}%` }} /></div>)}</div> : <p className="client-report-muted">{t("clients.report.leadEmpty")}</p>}
      </section>

      <div className="client-report-grid">
        <section className="client-report-block">
          <h2>{t("clients.report.channelsTitle")}</h2>
          {report.current.by_channel.length ? <table className="client-report-table"><tbody>{report.current.by_channel.map((row) => <tr key={row.channel}><td>{CHANNEL_KEYS[row.channel] === "phone" ? t("clients.report.phone") : CHANNEL_KEYS[row.channel] || row.channel}</td><td>{row.conversations.toLocaleString(lang)}</td></tr>)}</tbody></table> : <p className="client-report-muted">—</p>}
        </section>
        <section className="client-report-block">
          <h2>{t("clients.report.messagesTitle")}</h2>
          <table className="client-report-table"><tbody>
            <tr><td>{t("clients.report.inbound")}</td><td>{now.inbound.toLocaleString(lang)}</td></tr>
            <tr><td>{t("clients.report.aiReplies")}</td><td>{now.ai_replies.toLocaleString(lang)}</td></tr>
            <tr><td>{t("clients.report.humanReplies")}</td><td>{now.human_replies.toLocaleString(lang)}</td></tr>
            {showCost && <tr><td>{t("clients.report.aiCost")}</td><td>${report.current.ai_cost_usd.toFixed(2)}</td></tr>}
          </tbody></table>
        </section>
      </div>
      <footer className="client-report-foot">{t("clients.report.footer", { agency: report.agency.name })}</footer>
    </article>}
  </div>;
}
