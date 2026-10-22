"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ExternalLink, LoaderCircle, Plug, RefreshCw } from "lucide-react";
import { api, messageFrom } from "@/lib/api";
import { useT, type I18nKey } from "@/lib/i18n";
import { isManager, useCurrentUser } from "@/lib/current-user";
import { Alert } from "@/components/ui";
import { ConfirmModal } from "@/components/confirm-modal";
import type { AgentTool } from "@/types";

type Item = { slug: string; name: string; category: string };
type Connection = { toolkit: string; status: string; tool_id: string | null };
type Catalog = { configured: boolean; catalog: Item[]; connections: Connection[] };
const CATEGORY_KEYS: Record<string, I18nKey> = {
  "Communication & Collaboration": "tools.catalog.categories.communication", "Developer & IT": "tools.catalog.categories.developer",
  "AI Tools": "tools.catalog.categories.ai", "Productivity": "tools.catalog.categories.productivity", "Marketing": "tools.catalog.categories.marketing",
  "Documents & Files": "tools.catalog.categories.documents", "CRM & Sales": "tools.catalog.categories.crm", "Finance & Accounting": "tools.catalog.categories.finance",
  "Analytics & Data": "tools.catalog.categories.analytics", "Scheduling & Calendar": "tools.catalog.categories.calendar", "E-commerce & Payments": "tools.catalog.categories.commerce",
  "Design & Creative": "tools.catalog.categories.design", "HR & Recruiting": "tools.catalog.categories.hr", "Lifestyle & Personal": "tools.catalog.categories.lifestyle",
};

export function IntegrationCatalog({ agentId, tools, onSaved, onRemoved, onReview }: { agentId: string; tools: AgentTool[]; onSaved: (tool: AgentTool) => void; onRemoved: (id: string) => void; onReview: (tool: AgentTool) => void }) {
  const t = useT();
  const manager = isManager(useCurrentUser()?.role);
  const [data, setData] = useState<Catalog | null>(null);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [onlyConnected, setOnlyConnected] = useState(false);
  const [limit, setLimit] = useState(24);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [links, setLinks] = useState<Record<string, string>>({});
  const [disconnect, setDisconnect] = useState<Item | null>(null);
  const load = useCallback(async () => {
    setError("");
    try { setData(await api<Catalog>(`/agents/${agentId}/integrations`)); }
    catch (err) { setError(messageFrom(err)); }
  }, [agentId]);
  useEffect(() => { void load(); }, [load]);
  const filtered = (data?.catalog ?? []).filter((item) => (!category || item.category === category) && (!onlyConnected || data?.connections.some((row) => row.toolkit === item.slug && row.status === "connected")) && `${item.name} ${item.slug} ${t(CATEGORY_KEYS[item.category])}`.toLowerCase().includes(search.trim().toLowerCase()));
  async function start(item: Item) {
    setBusy(item.slug); setError("");
    try {
      const result = await api<{ redirect_url: string }>(`/agents/${agentId}/integrations/${item.slug}/link`, { method: "POST" });
      setLinks((previous) => ({ ...previous, [item.slug]: result.redirect_url }));
      await load();
    } catch (err) { setError(messageFrom(err)); } finally { setBusy(null); }
  }
  async function check(item: Item) {
    setBusy(item.slug); setError("");
    try { onSaved(await api<AgentTool>(`/agents/${agentId}/integrations/${item.slug}/complete`, { method: "POST" })); await load(); }
    catch (err) { setError(messageFrom(err)); } finally { setBusy(null); }
  }
  async function remove(item: Item) {
    const connection = data?.connections.find((row) => row.toolkit === item.slug);
    try {
      await api(`/agents/${agentId}/integrations/${item.slug}`, { method: "DELETE" });
      if (connection?.tool_id) onRemoved(connection.tool_id);
      setLinks((previous) => { const next = { ...previous }; delete next[item.slug]; return next; });
      await load();
    } catch (err) { await load(); throw err; }
  }
  return <section className="panel integration-catalog">
    <div className="panel-head"><div><h3>{t("tools.catalog.heading")}</h3><p>{t("tools.catalog.copy")}</p></div>{manager && <Link className="text-button" href="/settings/integrations">{t("tools.catalog.settings")}</Link>}</div>
    {!data?.configured && data && <div className="security-note">{t("tools.catalog.needSetup")}</div>}
    {error && <Alert type="error">{error} <button className="text-button" onClick={() => void load()}>{t("tools.catalog.retry")}</button></Alert>}
    {!data && !error && <p><LoaderCircle className="spin" size={16} /> {t("tools.catalog.loading")}</p>}
    {data && <>
      <div className="integration-filters"><label>{t("tools.catalog.search")}<input type="search" placeholder={t("tools.catalog.searchPlaceholder")} value={search} onChange={(event) => { setSearch(event.target.value); setLimit(24); }} /></label><label>{t("tools.catalog.category")}<select value={category} onChange={(event) => { setCategory(event.target.value); setLimit(24); }}><option value="">{t("tools.catalog.all")}</option>{Object.keys(CATEGORY_KEYS).map((name) => <option key={name} value={name}>{t(CATEGORY_KEYS[name])}</option>)}</select></label><label className="switch-row compact"><input type="checkbox" checked={onlyConnected} onChange={(event) => { setOnlyConnected(event.target.checked); setLimit(24); }} /> {t("tools.catalog.connectedOnly")}</label></div>
      <p className="field-help">{t("tools.catalog.showing", { count: Math.min(limit, filtered.length), total: filtered.length })}</p>
      <div className="integration-grid">{filtered.slice(0, limit).map((item) => {
        const connection = data.connections.find((row) => row.toolkit === item.slug);
        const tool = tools.find((row) => row.id === connection?.tool_id);
        return <article className="integration-card" key={item.slug}>
          <div className="integration-card-heading"><span className="document-icon"><Plug size={20} /></span><div><h4>{item.name}</h4><small>{t(CATEGORY_KEYS[item.category])}</small></div></div>
          {connection && <span className="pill">{t(connection.status === "connected" ? "tools.catalog.connected" : "tools.catalog.pending")}{tool ? ` · ${t(tool.enabled ? "tools.catalog.enabled" : "tools.catalog.disabled")}` : ""}</span>}
          {links[item.slug] && <><a className="button secondary" href={links[item.slug]} target="_blank" rel="noopener noreferrer"><ExternalLink size={15} /> {t("tools.catalog.authorize")}</a><p className="field-help">{t("tools.catalog.authorizationHint")}</p></>}
          {tool && <p className="field-help">{t("tools.catalog.reviewHint")}</p>}
          {manager && <div className="tools-actions">
            {tool ? <button className="button secondary" onClick={() => onReview(tool)}>{t("tools.catalog.review")}</button> : connection ? <><button className="button primary" disabled={busy !== null || !data.configured} onClick={() => void check(item)}><RefreshCw size={14} /> {t("tools.catalog.check")}</button><button className="text-button" disabled={busy !== null || !data.configured} onClick={() => void start(item)}>{t("tools.catalog.restart")}</button></> : <button className="button secondary" disabled={busy !== null || !data.configured} onClick={() => void start(item)}>{busy === item.slug ? <LoaderCircle className="spin" size={14} /> : <Plug size={14} />} {t("tools.catalog.connect")}</button>}
            {connection && <button className="text-button danger-text" disabled={busy !== null} onClick={() => setDisconnect(item)}>{t("tools.catalog.disconnect")}</button>}
          </div>}
        </article>;
      })}</div>
      {!filtered.length && <p className="inline-empty">{t("tools.catalog.empty")}</p>}
      {limit < filtered.length && <button className="button secondary" onClick={() => setLimit((value) => value + 24)}>{t("tools.catalog.loadMore")}</button>}
    </>}
    {disconnect && <ConfirmModal title={t("tools.catalog.confirmDisconnect", { name: disconnect.name })} message={t("tools.catalog.disconnectHint")} confirmLabel={t("tools.catalog.disconnect")} cancelLabel={t("tools.form.cancel")} onConfirm={() => remove(disconnect)} onClose={() => setDisconnect(null)} />}
  </section>;
}
