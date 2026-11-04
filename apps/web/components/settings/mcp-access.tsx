"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Copy, KeyRound, LoaderCircle, Plus, RefreshCw, Trash2, Wrench, XCircle } from "lucide-react";
import { ConfirmModal } from "@/components/confirm-modal";
import { Segmented } from "@/components/reports/filter-bar";
import { FormSkeleton } from "@/components/skeleton";
import { useToast } from "@/components/toast";
import { Modal } from "@/components/ui";
import { api, messageFrom } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import type { McpAccess, McpActivity, McpToken, McpTokenCreated } from "@/types";

type Client = "claude" | "cursor" | "codex";

// External AI agents (Claude Code, Cursor, Codex…) reach the workspace over
// MCP with a personal token. This tab hands out tokens, shows how to wire
// each client, and keeps the log of what the connected agents did.
export function McpAccessSection() {
  const { t, lang } = useLanguage();
  const toast = useToast();
  const [info, setInfo] = useState<McpAccess | null>(null);
  const [tokens, setTokens] = useState<McpToken[]>([]);
  const [activity, setActivity] = useState<McpActivity[]>([]);
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<McpTokenCreated | null>(null);
  const [revoking, setRevoking] = useState<McpToken | null>(null);
  const [client, setClient] = useState<Client>("claude");
  const [refreshing, setRefreshing] = useState(false);

  const loadActivity = useCallback(async () => {
    setRefreshing(true);
    try { setActivity(await api<McpActivity[]>("/mcp-access/activity")); } catch (err) { toast.error(messageFrom(err)); } finally { setRefreshing(false); }
  }, [toast]);
  const load = useCallback(async () => {
    try {
      const [i, tk] = await Promise.all([api<McpAccess>("/mcp-access"), api<McpToken[]>("/mcp-access/tokens")]);
      setInfo(i); setTokens(tk);
    } catch (err) { toast.error(messageFrom(err)); }
    loadActivity();
  }, [toast, loadActivity]);
  useEffect(() => { load(); }, [load]);

  async function copy(value: string) {
    try { await navigator.clipboard.writeText(value); toast.success(t("settings.mcp.copied")); } catch { /* clipboard blocked */ }
  }
  const when = (value: string | null) => value ? new Date(value).toLocaleString(lang === "es" ? "es" : "en", { dateStyle: "medium", timeStyle: "short" }) : t("settings.mcp.never");

  if (!info) return <FormSkeleton sections={3} />;
  const secret = created?.secret ?? "<TOKEN>";
  const snippets: Record<Client, string> = {
    claude: `claude mcp add --transport http opennexus ${info.endpoint} --header "Authorization: Bearer ${secret}"`,
    cursor: JSON.stringify({ mcpServers: { opennexus: { url: info.endpoint, headers: { Authorization: `Bearer ${secret}` } } } }, null, 2),
    codex: `[mcp_servers.opennexus]\nurl = "${info.endpoint}"\nhttp_headers = { Authorization = "Bearer ${secret}" }`,
  };

  return <div className="page-form">
    <section className="form-section"><div className="section-copy"><h2>{t("settings.mcp.roleHeading")}</h2></div><div className="form-fields"><p>{t("settings.mcp.roleCopy")}</p></div></section>
    <section className="form-section">
      <div className="section-copy"><h2>{t("settings.mcp.heading")}</h2><p>{t("settings.mcp.copy")}</p></div>
      <div className="form-fields">
        <label>{t("settings.mcp.endpoint")}
          <div className="domain-input"><input value={info.endpoint} readOnly disabled /><button type="button" className="button ghost" onClick={() => copy(info.endpoint)}><Copy size={15} /> {t("settings.mcp.copyLink")}</button></div>
        </label>
        <Segmented value={client} onChange={setClient} label={t("settings.mcp.clientLabel")}
          options={[{ value: "claude", label: "Claude Code" }, { value: "cursor", label: "Cursor" }, { value: "codex", label: "Codex" }]} />
        <pre className="code-snippet"><code>{snippets[client]}</code><button type="button" className="icon-button" aria-label={t("settings.mcp.copyLink")} onClick={() => copy(snippets[client])}><Copy size={15} /></button></pre>
        <small className="field-help">{t("settings.mcp.snippetHint")}</small>
      </div>
    </section>

    <section className="form-section">
      <div className="section-copy"><h2>{t("settings.mcp.toolsHeading")}</h2><p>{t("settings.mcp.toolsCopy")}</p></div>
      <div className="form-fields">
        <ul className="status-list">{info.tools.map((tool) => <li key={tool.name}>
          <span><strong><Wrench size={13} /> {tool.name}</strong><small>{tool.description}</small></span>
          <span className={tool.writes ? "pill purple" : "pill"}>{tool.writes ? t("settings.mcp.writes") : t("settings.mcp.reads")}</span>
        </li>)}</ul>
      </div>
    </section>

    <section className="form-section">
      <div className="section-copy"><h2>{t("settings.mcp.tokensHeading")}</h2><p>{t("settings.mcp.tokensCopy")}</p>
        <button type="button" className="button primary align-start" onClick={() => setCreating(true)}><Plus size={16} /> {t("settings.mcp.createToken")}</button></div>
      <div className="form-fields">
        {tokens.length ? <div className="table-shell"><table className="data-table"><thead><tr><th>{t("settings.mcp.colName")}</th><th>{t("settings.mcp.colAccess")}</th><th>{t("settings.mcp.colCreatedBy")}</th><th>{t("settings.mcp.colLastUsed")}</th><th /></tr></thead><tbody>
          {tokens.map((token) => <tr key={token.id}>
            <td><strong>{token.name}</strong><br /><code>{token.prefix}…</code></td>
            <td><span className={token.read_only ? "pill" : "pill purple"}>{token.read_only ? t("settings.mcp.readOnly") : t("settings.mcp.fullAccess")}</span></td>
            <td>{token.created_by}</td>
            <td>{when(token.last_used_at)}</td>
            <td><button type="button" className="button ghost danger-text" onClick={() => setRevoking(token)}><Trash2 size={15} /> {t("settings.mcp.revoke")}</button></td>
          </tr>)}
        </tbody></table></div> : <p className="muted">{t("settings.mcp.noTokens")}</p>}
      </div>
    </section>

    <section className="form-section">
      <div className="section-copy"><h2>{t("settings.mcp.activityHeading")}</h2><p>{t("settings.mcp.activityCopy")}</p>
        <button type="button" className="button ghost align-start" onClick={loadActivity} disabled={refreshing}>{refreshing ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />} {t("settings.mcp.refresh")}</button></div>
      <div className="form-fields">
        {activity.length ? <ul className="status-list">{activity.map((row) => <li key={row.id}>
          <span><strong>{row.ok ? <CheckCircle2 size={13} /> : <XCircle size={13} />} {row.tool}</strong>
            <small>{when(row.created_at)} · {row.token_name || t("settings.mcp.revokedToken")}{row.summary ? ` · ${row.summary}` : ""}</small></span>
          <span className={row.ok ? "domain-status ok" : "domain-status pending"}>{row.ok ? t("settings.mcp.ok") : t("settings.mcp.failed")}</span>
        </li>)}</ul> : <p className="muted">{t("settings.mcp.noActivity")}</p>}
      </div>
    </section>

    {creating && <CreateTokenModal onClose={() => setCreating(false)} onCreated={(token) => { setCreating(false); setCreated(token); load(); }} />}
    <Modal open={Boolean(created)} title={t("settings.mcp.createdTitle")} description={t("settings.mcp.createdCopy")} onClose={() => setCreated(null)} wide>
      {created && <div className="form-fields">
        <div className="domain-input"><KeyRound size={16} /><input value={created.secret} readOnly /><button type="button" className="button primary" onClick={() => copy(created.secret)}><Copy size={15} /> {t("settings.mcp.copyLink")}</button></div>
        <pre className="code-snippet"><code>{snippets[client]}</code></pre>
        <div className="modal-actions"><button type="button" className="button secondary" onClick={() => setCreated(null)}>{t("settings.mcp.done")}</button></div>
      </div>}
    </Modal>
    {revoking && <ConfirmModal title={t("settings.mcp.revokeTitle", { name: revoking.name })} message={t("settings.mcp.revokeCopy")} confirmLabel={t("settings.mcp.revoke")} cancelLabel={t("common.cancel")} confirmIcon={<Trash2 size={15} />}
      onConfirm={async () => { await api(`/mcp-access/tokens/${revoking.id}`, { method: "DELETE" }); setRevoking(null); toast.success(t("settings.mcp.revoked")); load(); }}
      onClose={() => setRevoking(null)} />}
  </div>;
}

function CreateTokenModal({ onClose, onCreated }: { onClose: () => void; onCreated: (token: McpTokenCreated) => void }) {
  const { t } = useLanguage();
  const toast = useToast();
  const [name, setName] = useState("");
  const [readOnly, setReadOnly] = useState(false);
  const [busy, setBusy] = useState(false);
  async function submit() {
    setBusy(true);
    try { onCreated(await api<McpTokenCreated>("/mcp-access/tokens", { method: "POST", body: JSON.stringify({ name: name.trim(), read_only: readOnly }) })); }
    catch (err) { toast.error(messageFrom(err)); } finally { setBusy(false); }
  }
  return <Modal open title={t("settings.mcp.createToken")} description={t("settings.mcp.createCopy")} onClose={onClose}>
    <div className="form-fields">
      <label>{t("settings.mcp.tokenName")}<input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder={t("settings.mcp.tokenNamePlaceholder")} /></label>
      <label className="switch-row"><span><strong>{t("settings.mcp.readOnly")}</strong><small>{t("settings.mcp.readOnlyHint")}</small></span><input type="checkbox" checked={readOnly} onChange={(e) => setReadOnly(e.target.checked)} /></label>
      <div className="modal-actions">
        <button type="button" className="button secondary" onClick={onClose}>{t("common.cancel")}</button>
        <button type="button" className="button primary" disabled={busy || !name.trim()} onClick={submit}>{busy ? <LoaderCircle className="spin" size={15} /> : <KeyRound size={15} />} {t("settings.mcp.create")}</button>
      </div>
    </div>
  </Modal>;
}
