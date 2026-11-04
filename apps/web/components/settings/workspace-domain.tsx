"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Copy, ExternalLink, Globe2, LoaderCircle, RefreshCw, Save, ShieldAlert, ShieldCheck, Trash2 } from "lucide-react";
import { FormSkeleton } from "@/components/skeleton";
import { useToast } from "@/components/toast";
import { api, messageFrom } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { WorkspaceDomain } from "@/types";

// The workspace's addresses: the branded subdomain the deployment gives every
// agency (when it serves them under a base domain), and the agency's own
// domain for sign-in, dashboard and client portals, verified by a TXT record.
export function WorkspaceDomainSection() {
  const t = useT();
  const toast = useToast();
  const [state, setState] = useState<WorkspaceDomain | null>(null);
  const [input, setInput] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (check = false) => {
    try { const next = await api<WorkspaceDomain>(`/agency/domain${check ? "?check=true" : ""}`); setState(next); setInput(next.domain || ""); }
    catch (err) { toast.error(messageFrom(err)); }
  }, [toast]);
  useEffect(() => { load(true); }, [load]);

  async function run(action: () => Promise<WorkspaceDomain>, success: string) {
    setBusy(true);
    try { const next = await action(); setState(next); setInput(next.domain || ""); setEditing(false); toast.success(success); }
    catch (err) { toast.error(messageFrom(err)); } finally { setBusy(false); }
  }
  const save = () => run(() => api<WorkspaceDomain>("/agency/domain", { method: "PUT", body: JSON.stringify({ domain: input.trim().toLowerCase() }) }), t("settings.domain.saved"));
  const verify = () => run(() => api<WorkspaceDomain>("/agency/domain/verify", { method: "POST" }), t("settings.domain.verified"));
  const remove = () => run(() => api<WorkspaceDomain>("/agency/domain", { method: "DELETE" }), t("settings.domain.removed"));
  async function copy(value: string) {
    try { await navigator.clipboard.writeText(value); toast.success(t("settings.domain.copied")); } catch { /* clipboard blocked: nothing to do */ }
  }

  if (!state) return <FormSkeleton sections={2} />;
  const showForm = editing || !state.domain;

  return <div className="page-form">
    <section className="form-section domain-section">
      <div className="section-copy"><h2>{t("settings.domain.heading")}</h2><p>{t("settings.domain.copy")}</p></div>
      <div className="form-fields">
        <label>{t("settings.domain.accessUrl")}
          <div className="domain-input"><Globe2 size={16} /><input value={state.primary_url} disabled readOnly />
            <button type="button" className="button ghost" onClick={() => copy(state.primary_url)}><Copy size={15} /> {t("settings.domain.copyLink")}</button>
            <a className="button ghost" href={state.primary_url} target="_blank" rel="noreferrer"><ExternalLink size={15} /> {t("settings.domain.open")}</a>
          </div>
        </label>
        {state.branded_url && state.branded_url !== state.primary_url && <p className="muted">{t("settings.domain.brandedAlso", { url: state.branded_url })}</p>}
      </div>
    </section>

    <section className="form-section domain-section">
      <div className="section-copy"><h2>{t("settings.domain.ownHeading")}</h2><p>{t("settings.domain.ownCopy")}</p></div>
      <div className="form-fields">
        {showForm ? <label>{t("settings.domain.label")}
          <div className="domain-input"><Globe2 size={16} /><input value={input} onChange={(e) => setInput(e.target.value)} placeholder="app.your-agency.com" />
            <button type="button" className="button secondary" onClick={save} disabled={busy || !input.trim()}><Save size={15} /> {t("settings.domain.save")}</button>
            {editing && <button type="button" className="button ghost" onClick={() => { setEditing(false); setInput(state.domain || ""); }}>{t("common.cancel")}</button>}
          </div>
        </label> : <div className="domain-input"><Globe2 size={16} /><input value={state.domain || ""} disabled readOnly />
          <button type="button" className="button secondary" onClick={() => setEditing(true)}>{t("settings.domain.change")}</button>
        </div>}

        {state.domain && !editing && <>
          <ul className="status-list">
            <li><span><strong>{t("settings.domain.ownership")}</strong><small>{t("settings.domain.ownershipHint")}</small></span>
              <StatusPill ok={state.verified} okLabel={t("settings.domain.active")} pendingLabel={t("settings.domain.pending")} /></li>
            <li><span><strong>{t("settings.domain.ssl")}</strong><small>{t("settings.domain.sslHint")}</small></span>
              <StatusPill ok={state.ssl_ready} okLabel={t("settings.domain.active")} pendingLabel={t("settings.domain.pending")} /></li>
            <li><span><strong>{t("settings.domain.dns")}</strong><small>{t("settings.domain.dnsHint")}</small></span>
              <StatusPill ok={state.dns_ok} okLabel={t("settings.domain.active")} pendingLabel={t("settings.domain.notPointing")} /></li>
          </ul>

          {(!state.verified || !state.dns_ok) && <div className="dns-instructions">
            <p>{t("settings.domain.dnsIntro")}</p>
            <table className="dns-table"><thead><tr><th>{t("settings.domain.dnsType")}</th><th>{t("settings.domain.dnsHost")}</th><th>{t("settings.domain.dnsValue")}</th></tr></thead><tbody>
              <tr><td>CNAME</td><td><code>{state.domain}</code></td><td><code>{state.cname_target || t("settings.domain.gatewayHost")}</code></td></tr>
              {!state.verified && <tr><td>TXT</td><td><code>{state.txt_host}</code></td><td><code>{state.txt_value}</code></td></tr>}
            </tbody></table>
            <div className="domain-actions">
              {!state.verified && <button type="button" className="button primary" onClick={verify} disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <ShieldCheck size={15} />} {t("settings.domain.verify")}</button>}
              <button type="button" className="button ghost" onClick={() => load(true)} disabled={busy}><RefreshCw size={15} /> {t("settings.domain.recheck")}</button>
            </div>
          </div>}

          <div className="form-footer"><button type="button" className="button danger" onClick={remove} disabled={busy}><Trash2 size={15} /> {t("settings.domain.remove")}</button></div>
        </>}
      </div>
    </section>
  </div>;
}

function StatusPill({ ok, okLabel, pendingLabel }: { ok: boolean; okLabel: string; pendingLabel: string }) {
  return <span className={`domain-status ${ok ? "ok" : "pending"}`}>{ok ? <CheckCircle2 size={15} /> : <ShieldAlert size={15} />} {ok ? okLabel : pendingLabel}</span>;
}
