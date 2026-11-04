"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { CalendarClock, LoaderCircle, Megaphone, MessageCircle, Pencil, Plus, Send, Square, Trash2, Users } from "lucide-react";
import { Alert, EmptyState, Modal } from "@/components/ui";
import { ConfirmModal } from "@/components/confirm-modal";
import { ListRowsSkeleton } from "@/components/skeleton";
import { useToast } from "@/components/toast";
import { api, messageFrom } from "@/lib/api";
import { formatWhen } from "@/lib/datetime";
import { useLanguage } from "@/lib/i18n";
import type { Campaign, CampaignRecipient, CampaignStatus, PipelineStage, Template, WhatsAppCloudChannel } from "@/types";

type Tag = { id: string; name: string; color: string };

const STATUS_KEYS = {
  draft: "clients.campaigns.statusDraft", scheduled: "clients.campaigns.statusScheduled", sending: "clients.campaigns.statusSending",
  done: "clients.campaigns.statusDone", cancelled: "clients.campaigns.statusCancelled",
} as const satisfies Record<CampaignStatus, string>;
const STAGE_KEYS = {
  new: "clients.pipeline.stageNew", qualified: "clients.pipeline.stageQualified", booked: "clients.pipeline.stageBooked",
  won: "clients.pipeline.stageWon", lost: "clients.pipeline.stageLost",
} as const satisfies Record<PipelineStage, string>;
const STAGES = Object.keys(STAGE_KEYS) as PipelineStage[];
const RECIPIENT_KEYS = { pending: "clients.campaigns.recipientPending", sent: "clients.campaigns.recipientSent", failed: "clients.campaigns.recipientFailed" } as const;

const channelName = (channel: WhatsAppCloudChannel) => channel.label || channel.display_name || channel.phone_number || channel.phone_number_id;
const templateKey = (template: { name: string; language: string }) => `${template.name}|${template.language}`;
const pct = (part: number, whole: number) => (whole ? Math.round((part / whole) * 100) : 0);
/** Templates a campaign can fill: body variables, and a text or media header. */
const sendable = (template: Template) => template.header?.format !== "LOCATION";

type Draft = {
  id?: string; name: string; channel_id: string; template: string; variables: Record<string, string>; header_value: string;
  tag_ids: string[]; stages: PipelineStage[]; when: "now" | "later"; scheduled_at: string;
};

const emptyDraft = (channelId = ""): Draft => ({
  name: "", channel_id: channelId, template: "", variables: {}, header_value: "", tag_ids: [], stages: [], when: "now", scheduled_at: "",
});

/** WhatsApp campaigns of a client: one approved template sent to a chosen
 * list of contacts, now or at a set time, with how it went. Replies land in
 * each contact's chat, where the agent answers as usual. */
export function CampaignsPanel({ clientId }: { clientId: string }) {
  const { t, lang } = useLanguage();
  const toast = useToast();
  const base = `/clients/${clientId}/campaigns`;
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [channels, setChannels] = useState<WhatsAppCloudChannel[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [editing, setEditing] = useState<Draft | null>(null);
  const [deleting, setDeleting] = useState<Campaign | null>(null);
  const [viewing, setViewing] = useState<Campaign | null>(null);

  const load = useCallback(async () => {
    try {
      const [rows, numbers, tagRows] = await Promise.all([
        api<Campaign[]>(base),
        api<WhatsAppCloudChannel[]>(`/whatsapp-cloud/clients/${clientId}/channels`).catch(() => [] as WhatsAppCloudChannel[]),
        api<Tag[]>(`/clients/${clientId}/contact-tags`).catch(() => [] as Tag[]),
      ]);
      setCampaigns(rows); setChannels(numbers); setTags(tagRows);
    } catch (err) { toast.error(messageFrom(err)); }
  }, [base, clientId, toast]);
  useEffect(() => { load(); }, [load]);

  // While one is going out, the numbers move: refresh them every few seconds.
  const live = campaigns?.some((c) => c.status === "sending" || c.status === "scheduled");
  useEffect(() => {
    if (!live) return;
    const id = setInterval(() => { api<Campaign[]>(base).then(setCampaigns).catch(() => {}); }, 8000);
    return () => clearInterval(id);
  }, [live, base]);

  if (!campaigns) return <ListRowsSkeleton />;

  async function cancel(campaign: Campaign) {
    try { await api(`${base}/${campaign.id}/cancel`, { method: "POST" }); toast.success(t("clients.campaigns.stopped")); load(); }
    catch (err) { toast.error(messageFrom(err)); }
  }

  async function remove(campaign: Campaign) {
    try { await api(`${base}/${campaign.id}`, { method: "DELETE" }); setDeleting(null); load(); }
    catch (err) { toast.error(messageFrom(err)); }
  }

  const edit = (campaign: Campaign) => setEditing({
    id: campaign.id, name: campaign.name, channel_id: campaign.channel_id ?? "",
    template: templateKey({ name: campaign.template_name, language: campaign.template_language }),
    variables: campaign.variables, header_value: campaign.header_value,
    tag_ids: campaign.audience.tag_ids ?? [], stages: campaign.audience.stages ?? [], when: "now", scheduled_at: "",
  });

  const totals = campaigns.reduce((sum, c) => ({ sent: sum.sent + c.stats.sent, read: sum.read + c.stats.read, replied: sum.replied + c.stats.replied }), { sent: 0, read: 0, replied: 0 });

  return <div className="campaigns">
    <section className="panel campaigns-head">
      <div><h2>{t("clients.campaigns.title")}</h2><p>{t("clients.campaigns.intro")}</p></div>
      {campaigns.length > 0 && <div className="pipeline-stats">
        <div><small>{t("clients.campaigns.totalSent")}</small><strong>{totals.sent}</strong></div>
        <div><small>{t("clients.campaigns.readRate")}</small><strong>{pct(totals.read, totals.sent)}%</strong></div>
        <div><small>{t("clients.campaigns.replyRate")}</small><strong>{pct(totals.replied, totals.sent)}%</strong></div>
      </div>}
      <button type="button" className="button primary" disabled={!channels.length} onClick={() => setEditing(emptyDraft(channels[0]?.id))}><Plus size={16} /> {t("clients.campaigns.new")}</button>
    </section>

    {!channels.length && <Alert type="info">{t("clients.campaigns.needsCloud")}</Alert>}

    {!campaigns.length ? <EmptyState icon={<Megaphone />} title={t("clients.campaigns.emptyTitle")} description={t("clients.campaigns.emptyCopy")} /> :
      <div className="campaign-list">{campaigns.map((campaign) => {
        const s = campaign.stats;
        const done = s.sent + s.failed;
        return <article key={campaign.id} className="panel campaign-card">
          <header>
            <div><strong>{campaign.name}</strong><small>{campaign.template_name} · {campaign.template_language}{campaign.channel_label ? ` · ${campaign.channel_label}` : ""}</small></div>
            <span className={`campaign-status status-${campaign.status}`}>{t(STATUS_KEYS[campaign.status])}</span>
          </header>
          {campaign.status === "scheduled" && campaign.scheduled_at && <p className="campaign-when"><CalendarClock size={14} /> {t("clients.campaigns.goesOut", { when: formatWhen(campaign.scheduled_at, lang) })}</p>}
          {campaign.status === "draft" && campaign.last_error && <Alert type="error">{t("clients.campaigns.pausedTemplate")}</Alert>}
          {s.total > 0 && <>
            <div className="campaign-progress" aria-label={t("clients.campaigns.progress", { done, total: s.total })}><span style={{ width: `${pct(done, s.total)}%` }} /></div>
            <div className="campaign-stats">
              <div><small>{t("clients.campaigns.statRecipients")}</small><strong>{s.total}</strong></div>
              <div><small>{t("clients.campaigns.statSent")}</small><strong>{s.sent}</strong></div>
              <div><small>{t("clients.campaigns.statDelivered")}</small><strong>{s.delivered}<em>{pct(s.delivered, s.sent)}%</em></strong></div>
              <div><small>{t("clients.campaigns.statRead")}</small><strong>{s.read}<em>{pct(s.read, s.sent)}%</em></strong></div>
              <div><small>{t("clients.campaigns.statReplied")}</small><strong>{s.replied}<em>{pct(s.replied, s.sent)}%</em></strong></div>
              <div><small>{t("clients.campaigns.statFailed")}</small><strong className={s.failed ? "danger-text" : ""}>{s.failed}</strong></div>
            </div>
          </>}
          <footer>
            {campaign.status === "draft" && <button type="button" className="button secondary" onClick={() => edit(campaign)}><Pencil size={15} /> {t("clients.campaigns.editAndSend")}</button>}
            {(campaign.status === "scheduled" || campaign.status === "sending") && <button type="button" className="button secondary" onClick={() => cancel(campaign)}><Square size={15} /> {t("clients.campaigns.stop")}</button>}
            {s.total > 0 && <button type="button" className="text-button" onClick={() => setViewing(campaign)}><Users size={15} /> {t("clients.campaigns.recipients")}</button>}
            {campaign.status !== "sending" && <button type="button" className="text-button danger-text" onClick={() => setDeleting(campaign)}><Trash2 size={15} /> {t("clients.campaigns.delete")}</button>}
          </footer>
        </article>;
      })}</div>}

    {editing && <CampaignEditor clientId={clientId} draft={editing} channels={channels} tags={tags} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />}
    {viewing && <RecipientsModal base={base} campaign={viewing} onClose={() => setViewing(null)} />}
    {deleting && <ConfirmModal title={t("clients.campaigns.deleteTitle")} message={t("clients.campaigns.deleteCopy", { name: deleting.name })} confirmLabel={t("clients.campaigns.delete")} cancelLabel={t("clients.campaigns.cancel")} confirmIcon={<Trash2 size={16} />} onClose={() => setDeleting(null)} onConfirm={() => remove(deleting)} />}
  </div>;
}

function CampaignEditor({ clientId, draft: initial, channels, tags, onClose, onSaved }: {
  clientId: string; draft: Draft; channels: WhatsAppCloudChannel[]; tags: Tag[]; onClose: () => void; onSaved: () => void;
}) {
  const { t } = useLanguage();
  const toast = useToast();
  const base = `/clients/${clientId}/campaigns`;
  const [draft, setDraft] = useState<Draft>(initial);
  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [count, setCount] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (patch: Partial<Draft>) => setDraft((current) => ({ ...current, ...patch }));

  useEffect(() => {
    if (!draft.channel_id) return;
    let stale = false;
    api<Template[]>(`/clients/${clientId}/webhooks/templates?channel_id=${draft.channel_id}`)
      .then((rows) => { if (!stale) setTemplates(rows.filter(sendable)); })
      .catch((err) => { if (!stale) { setTemplates([]); setError(messageFrom(err)); } });
    return () => { stale = true; };
  }, [clientId, draft.channel_id]);

  // The live audience count, as the filters change.
  useEffect(() => {
    const id = setTimeout(() => {
      api<{ count: number }>(`${base}/audience`, { method: "POST", body: JSON.stringify({ tag_ids: draft.tag_ids, stages: draft.stages }) })
        .then((r) => setCount(r.count)).catch(() => setCount(null));
    }, 250);
    return () => clearTimeout(id);
  }, [base, draft.tag_ids, draft.stages]);

  const template = templates?.find((item) => templateKey(item) === draft.template);
  const needsHeader = !!template?.header && (template.header.parameters.length > 0 || ["IMAGE", "VIDEO", "DOCUMENT"].includes(template.header.format));
  const preview = useMemo(() => {
    if (!template) return "";
    const fill = (value: string) => value.replace(/\{first_name\}/g, "Ana").replace(/\{name\}/g, "Ana Pérez");
    let text = template.body;
    template.parameters.forEach((param, i) => {
      const value = fill(draft.variables[param] ?? "") || `{{${param}}}`;
      text = text.split(`{{${param}}}`).join(value).split(`{{${i + 1}}}`).join(value);
    });
    return text;
  }, [template, draft.variables]);

  const toggleIn = <T,>(list: T[], value: T) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  const missing = !!template && template.parameters.some((param) => !(draft.variables[param] ?? "").trim());

  async function save(event: FormEvent, send: boolean) {
    event.preventDefault();
    if (!template) return;
    setBusy(true); setError("");
    try {
      const body = JSON.stringify({
        name: draft.name.trim(), channel_id: draft.channel_id, template_name: template.name, template_language: template.language,
        variables: Object.fromEntries(template.parameters.map((p) => [p, draft.variables[p] ?? ""])),
        header_value: needsHeader ? draft.header_value : "", audience: { tag_ids: draft.tag_ids, stages: draft.stages },
      });
      const saved = await api<Campaign>(draft.id ? `${base}/${draft.id}` : base, { method: draft.id ? "PUT" : "POST", body });
      if (send) {
        const at = draft.when === "later" && draft.scheduled_at ? new Date(draft.scheduled_at).toISOString() : null;
        await api(`${base}/${saved.id}/start`, { method: "POST", body: JSON.stringify({ scheduled_at: at }) });
        toast.success(at ? t("clients.campaigns.scheduled") : t("clients.campaigns.started"));
      } else toast.success(t("clients.campaigns.savedDraft"));
      onSaved();
    } catch (err) { setError(messageFrom(err)); }
    finally { setBusy(false); }
  }

  return <Modal open wide title={draft.id ? t("clients.campaigns.editTitle") : t("clients.campaigns.newTitle")} description={t("clients.campaigns.editorCopy")} onClose={onClose}>
    <form className="modal-form campaign-editor" onSubmit={(e) => save(e, true)}>
      {error && <Alert type="error">{error}</Alert>}
      <label>{t("clients.campaigns.name")}<input required maxLength={120} value={draft.name} onChange={(e) => set({ name: e.target.value })} placeholder={t("clients.campaigns.namePlaceholder")} /></label>
      <div className="campaign-row">
        <label>{t("clients.campaigns.number")}<select value={draft.channel_id} onChange={(e) => { setTemplates(null); set({ channel_id: e.target.value, template: "" }); }}>{channels.map((c) => <option key={c.id} value={c.id}>{channelName(c)}</option>)}</select></label>
        <label>{t("clients.campaigns.template")}<select required value={draft.template} onChange={(e) => set({ template: e.target.value, variables: {} })} disabled={!templates}>
          <option value="">{templates === null ? t("clients.campaigns.loadingTemplates") : templates.length ? t("clients.campaigns.chooseTemplate") : t("clients.campaigns.noTemplates")}</option>
          {templates?.map((item) => <option key={templateKey(item)} value={templateKey(item)}>{item.name} · {item.language}</option>)}
        </select></label>
      </div>

      {template && <div className="campaign-compose">
        <div className="campaign-fields">
          {template.parameters.length > 0 && <p className="field-help">{t("clients.campaigns.variablesHint")}</p>}
          {template.parameters.map((param) => <label key={param}>{`{{${param}}}`}<input value={draft.variables[param] ?? ""} onChange={(e) => set({ variables: { ...draft.variables, [param]: e.target.value } })} placeholder={t("clients.campaigns.variablePlaceholder")} /></label>)}
          {needsHeader && <label>{template.header?.format === "TEXT" ? t("clients.campaigns.headerText") : t("clients.campaigns.headerMedia")}<input required value={draft.header_value} onChange={(e) => set({ header_value: e.target.value })} placeholder={template.header?.format === "TEXT" ? "" : "https://…"} /></label>}
        </div>
        <div className="campaign-preview"><small>{t("clients.campaigns.preview")}</small><div className="campaign-bubble">{preview}{template.footer && <em>{template.footer}</em>}{template.buttons.length > 0 && <div className="campaign-buttons">{template.buttons.map((b, i) => <span key={i}>{b.text}</span>)}</div>}</div></div>
      </div>}

      <fieldset className="campaign-audience">
        <legend>{t("clients.campaigns.audience")}</legend>
        <p className="field-help">{t("clients.campaigns.audienceHint")}</p>
        {tags.length > 0 && <div className="campaign-chips"><small>{t("clients.campaigns.byTag")}</small>{tags.map((tag) => <button type="button" key={tag.id} className={draft.tag_ids.includes(tag.id) ? "chip-toggle active" : "chip-toggle"} style={{ borderColor: tag.color }} onClick={() => set({ tag_ids: toggleIn(draft.tag_ids, tag.id) })}>{tag.name}</button>)}</div>}
        <div className="campaign-chips"><small>{t("clients.campaigns.byStage")}</small>{STAGES.map((stage) => <button type="button" key={stage} className={draft.stages.includes(stage) ? "chip-toggle active" : "chip-toggle"} onClick={() => set({ stages: toggleIn(draft.stages, stage) })}>{t(STAGE_KEYS[stage])}</button>)}</div>
        <p className="campaign-count"><Users size={15} /> {count === null ? "…" : t("clients.campaigns.reaches", { count })}</p>
      </fieldset>

      <div className="campaign-when-pick">
        <label className="radio-row"><input type="radio" checked={draft.when === "now"} onChange={() => set({ when: "now" })} /> {t("clients.campaigns.sendNow")}</label>
        <label className="radio-row"><input type="radio" checked={draft.when === "later"} onChange={() => set({ when: "later" })} /> {t("clients.campaigns.sendLater")}</label>
        {draft.when === "later" && <input type="datetime-local" required value={draft.scheduled_at} onChange={(e) => set({ scheduled_at: e.target.value })} />}
      </div>
      <p className="field-help">{t("clients.campaigns.policy")}</p>

      <div className="modal-actions">
        <button type="button" className="button secondary" disabled={busy || !template || !draft.name.trim()} onClick={(e) => save(e as unknown as FormEvent, false)}>{t("clients.campaigns.saveDraft")}</button>
        <button className="button primary" disabled={busy || !template || missing || !count}>{busy ? <LoaderCircle className="spin" size={16} /> : draft.when === "later" ? <CalendarClock size={16} /> : <Send size={16} />} {draft.when === "later" ? t("clients.campaigns.schedule") : t("clients.campaigns.sendTo", { count: count ?? 0 })}</button>
      </div>
    </form>
  </Modal>;
}

function RecipientsModal({ base, campaign, onClose }: { base: string; campaign: Campaign; onClose: () => void }) {
  const { t, lang } = useLanguage();
  const [rows, setRows] = useState<CampaignRecipient[] | null>(null);
  const [filter, setFilter] = useState<"" | CampaignRecipient["status"]>("");
  useEffect(() => {
    let stale = false;
    api<CampaignRecipient[]>(`${base}/${campaign.id}/recipients${filter ? `?status=${filter}` : ""}`).then((r) => { if (!stale) setRows(r); }).catch(() => { if (!stale) setRows([]); });
    return () => { stale = true; };
  }, [base, campaign.id, filter]);
  return <Modal open wide title={campaign.name} description={t("clients.campaigns.recipientsCopy")} onClose={onClose}>
    <div className="campaign-chips">{(["", "sent", "failed", "pending"] as const).map((value) => <button type="button" key={value || "all"} className={filter === value ? "chip-toggle active" : "chip-toggle"} onClick={() => setFilter(value)}>{value ? t(RECIPIENT_KEYS[value]) : t("clients.campaigns.all")}</button>)}</div>
    {!rows ? <ListRowsSkeleton /> : !rows.length ? <p className="pipeline-empty">{t("clients.campaigns.noRecipients")}</p> :
      <div className="table-shell"><table className="data-table"><thead><tr><th>{t("clients.campaigns.colContact")}</th><th>{t("clients.campaigns.colStatus")}</th><th>{t("clients.campaigns.colSent")}</th><th /></tr></thead><tbody>
        {rows.map((row) => <tr key={row.id}>
          <td><strong>{row.name || row.phone}</strong><br /><small>{row.phone}</small></td>
          <td><span className={`campaign-status status-${row.status}`}>{t(RECIPIENT_KEYS[row.status])}</span>{row.error && <small className="campaign-error">{row.error}</small>}</td>
          <td>{row.sent_at ? formatWhen(row.sent_at, lang) : "—"}</td>
          <td>{row.conversation_id && <Link className="icon-button" href={`/inbox/${row.conversation_id}`} title={t("clients.pipeline.openChat")} aria-label={t("clients.pipeline.openChat")}><MessageCircle size={14} /></Link>}</td>
        </tr>)}
      </tbody></table></div>}
  </Modal>;
}
