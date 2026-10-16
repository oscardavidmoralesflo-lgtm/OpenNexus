"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Bot, Copy, ExternalLink, MessageCircle, Phone, Plus, RefreshCw, Share2, Sparkles } from "lucide-react";
import { ConfirmModal } from "@/components/confirm-modal";
import { TableSkeleton } from "@/components/skeleton";
import { useToast } from "@/components/toast";
import { EmptyState, PageHead, StatusBadge } from "@/components/ui";
import { api, messageFrom } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { Sandbox, SandboxAgent } from "@/types";

// One WhatsApp number where every prospect tries the agent built for them:
// each agent has a code, and whoever sends it talks to that agent.
export default function SandboxPage() {
  const t = useT();
  const toast = useToast();
  const [state, setState] = useState<Sandbox | null>(null);
  const [rotating, setRotating] = useState<SandboxAgent | null>(null);

  const load = useCallback(async () => {
    try { setState(await api<Sandbox>("/sandbox", { method: "POST" })); } catch (err) { toast.error(messageFrom(err)); }
  }, [toast]);
  useEffect(() => { load(); }, [load]);

  async function copy(value: string, done = t("sandbox.copied")) {
    try { await navigator.clipboard.writeText(value); toast.success(done); } catch { /* clipboard blocked */ }
  }
  const invite = (agent: SandboxAgent) => t("sandbox.inviteText", {
    agent: agent.name,
    code: agent.code,
    link: agent.share_link || state?.number?.phone_number || "",
  });

  const head = <PageHead eyebrow={t("sandbox.eyebrow")} title={state?.name || t("sandbox.title")} description={t("sandbox.description")}
    action={state && <Link href={`/agents/new?client=${state.client_id}`} className="button primary"><Plus size={18} /> {t("sandbox.newAgent")}</Link>} />;
  if (!state) return <div className="page">{head}<TableSkeleton columns={5} /></div>;

  const connected = state.number?.status === "connected";
  return <div className="page">
    {head}

    <section className="sandbox-number">
      <span className="metric-icon green"><Phone size={20} /></span>
      <div>
        <strong>{t("sandbox.numberTitle")}</strong>
        {state.number ? <small>{state.number.phone_number || state.number.display_name || t("sandbox.numberPending")} · <span className={`domain-status ${connected ? "ok" : "pending"}`}>{connected ? t("sandbox.connected") : t("sandbox.notConnected")}</span></small>
          : <small>{t("sandbox.numberCopy")}</small>}
      </div>
      <Link href={`/clients/${state.client_id}/channels`} className={state.number ? "button secondary" : "button primary"}>{state.number ? t("sandbox.manageNumber") : t("sandbox.connectNumber")}</Link>
    </section>

    <ol className="sandbox-steps">
      <li><Bot size={18} /><span><strong>{t("sandbox.step1")}</strong><small>{t("sandbox.step1Hint")}</small></span></li>
      <li><Share2 size={18} /><span><strong>{t("sandbox.step2")}</strong><small>{t("sandbox.step2Hint")}</small></span></li>
      <li><MessageCircle size={18} /><span><strong>{t("sandbox.step3")}</strong><small>{t("sandbox.step3Hint")}</small></span></li>
    </ol>

    {state.agents.length ? <div className="table-shell"><table className="data-table"><thead><tr>
      <th>{t("sandbox.colAgent")}</th><th>{t("sandbox.colCode")}</th><th>{t("sandbox.colProspects")}</th><th>{t("sandbox.colStatus")}</th><th />
    </tr></thead><tbody>{state.agents.map((agent) => <tr key={agent.id}>
      <td><Link href={`/agents/${agent.id}`} className="entity-cell"><span className="entity-avatar"><Bot size={16} /></span><span><strong>{agent.name}</strong><small>{agent.model || t("sandbox.noModel")}</small></span></Link></td>
      <td><button type="button" className="sandbox-code" onClick={() => copy(agent.code)} title={t("sandbox.copyCode")}>{agent.code} <Copy size={13} /></button></td>
      <td>{agent.prospects}</td>
      <td><StatusBadge active={agent.is_active} /></td>
      <td><div className="row-actions">
        <button type="button" className="button ghost" onClick={() => copy(invite(agent), t("sandbox.inviteCopied"))}><Share2 size={15} /> {t("sandbox.copyInvite")}</button>
        {agent.share_link && <a className="button ghost" href={agent.share_link} target="_blank" rel="noreferrer"><ExternalLink size={15} /> {t("sandbox.openChat")}</a>}
        <button type="button" className="icon-button" aria-label={t("sandbox.newCode")} title={t("sandbox.newCode")} onClick={() => setRotating(agent)}><RefreshCw size={15} /></button>
      </div></td>
    </tr>)}</tbody></table></div>
      : <EmptyState icon={<Sparkles />} title={t("sandbox.emptyTitle")} description={t("sandbox.emptyCopy")}
        action={<Link href={`/agents/new?client=${state.client_id}`} className="button primary"><Plus size={18} /> {t("sandbox.newAgent")}</Link>} />}

    {rotating && <ConfirmModal title={t("sandbox.newCodeTitle", { name: rotating.name })} message={t("sandbox.newCodeCopy", { code: rotating.code })}
      confirmLabel={t("sandbox.newCode")} cancelLabel={t("common.cancel")} confirmIcon={<RefreshCw size={15} />} danger={false}
      onConfirm={async () => { setState(await api<Sandbox>(`/sandbox/agents/${rotating.id}/code`, { method: "POST" })); setRotating(null); toast.success(t("sandbox.codeRotated")); }}
      onClose={() => setRotating(null)} />}
  </div>;
}
