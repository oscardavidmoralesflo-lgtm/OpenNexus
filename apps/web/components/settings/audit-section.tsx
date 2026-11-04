"use client";

import { useCallback, useEffect, useState } from "react";
import { LoaderCircle } from "lucide-react";
import { TableSkeleton } from "@/components/skeleton";
import { useToast } from "@/components/toast";
import { api, messageFrom } from "@/lib/api";
import { useLanguage, type I18nKey } from "@/lib/i18n";
import type { AuditEvent, AuditPage } from "@/types";

const PAGE_SIZE = 50;

// The first word of an action names the area of the dashboard it touched.
const AREAS: Record<string, I18nKey> = {
  account: "settings.audit.areaAccount",
  agency: "settings.audit.areaAgency",
  agents: "settings.audit.areaAgents",
  billing: "settings.audit.areaBilling",
  clients: "settings.audit.areaClients",
  conversations: "settings.audit.areaConversations",
  integrations: "settings.audit.areaIntegrations",
  mcp_access: "settings.audit.areaMcp",
  phone: "settings.audit.areaPhone",
  providers: "settings.audit.areaProviders",
  sandbox: "settings.audit.areaSandbox",
  social: "settings.audit.areaSocial",
  team: "settings.audit.areaTeam",
  webchat: "settings.audit.areaWebchat",
  whatsapp: "settings.audit.areaWhatsapp",
  whatsapp_cloud: "settings.audit.areaWhatsapp",
};
const VERBS: Record<string, I18nKey> = {
  create: "settings.audit.created",
  update: "settings.audit.updated",
  delete: "settings.audit.deleted",
};

// Who changed what in the dashboard, newest first. The server records every
// successful write and each sign-in; this only reads it.
export function AuditSection() {
  const { t, lang } = useLanguage();
  const toast = useToast();
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [area, setArea] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (offset: number, filter: string) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
      if (filter) params.set("action", filter);
      const page = await api<AuditPage>(`/audit?${params}`);
      setEvents((current) => offset && current ? [...current, ...page.events] : page.events);
      setHasMore(page.has_more);
    } catch (err) { toast.error(messageFrom(err)); }
    finally { setLoading(false); }
  }, [toast]);
  useEffect(() => { load(0, area); }, [load, area]);

  const when = (value: string) => new Date(value).toLocaleString(lang === "es" ? "es" : "en", { dateStyle: "medium", timeStyle: "short" });
  function describe(event: AuditEvent): string {
    if (event.action === "auth.sign_in") return t("settings.audit.signedIn");
    if (event.action === "auth.sign_in_failed") return t("settings.audit.signInFailed");
    const words = event.action.split(".");
    const verb = words[words.length - 1];
    const areaKey = AREAS[words[0]];
    return `${VERBS[verb] ? t(VERBS[verb]) : verb} · ${areaKey ? t(areaKey) : words[0]}`;
  }

  return <section className="section-block">
    <div className="section-heading">
      <div><h2>{t("settings.audit.heading")}</h2><p>{t("settings.audit.copy")}</p></div>
      <select value={area} onChange={(e) => setArea(e.target.value)} aria-label={t("settings.audit.colWhat")} style={{ width: "auto" }}>
        <option value="">{t("settings.audit.filterAll")}</option>
        <option value="auth">{t("settings.audit.signedIn")}</option>
        {Object.entries(AREAS).filter(([key]) => key !== "whatsapp_cloud").map(([key, label]) => <option key={key} value={key}>{t(label)}</option>)}
      </select>
    </div>
    {events === null ? <TableSkeleton columns={4} rows={5} /> : events.length === 0
      ? <p className="muted">{t("settings.audit.empty")}</p>
      : <div className="table-shell"><div style={{ overflowX: "auto" }}><table className="data-table"><thead><tr>
          <th>{t("settings.audit.colWhen")}</th><th>{t("settings.audit.colWho")}</th><th>{t("settings.audit.colWhat")}</th><th>{t("settings.audit.colWhere")}</th>
        </tr></thead><tbody>{events.map((event) => {
          return <tr key={event.id}>
            <td style={{ whiteSpace: "nowrap" }}>{when(event.created_at)}</td>
            <td>{event.actor_email || "—"}</td>
            <td title={`${event.method} ${event.path}`}><strong className={event.action === "auth.sign_in_failed" ? "danger-text" : undefined}>{describe(event)}</strong></td>
            <td title={event.user_agent} style={{ whiteSpace: "nowrap" }}><small>{event.ip || "—"}</small></td>
          </tr>;
        })}</tbody></table></div></div>}
    {hasMore && <button type="button" className="button secondary align-start" style={{ marginTop: 14 }} disabled={loading} onClick={() => load(events?.length ?? 0, area)}>
      {loading && <LoaderCircle size={16} className="spin" />} {t("settings.audit.loadMore")}
    </button>}
  </section>;
}
