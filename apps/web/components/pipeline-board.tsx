"use client";

import Link from "next/link";
import { DragEvent, useCallback, useEffect, useState } from "react";
import { MessageCircle, Search } from "lucide-react";
import { api, messageFrom } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import { useToast } from "@/components/toast";
import { ListRowsSkeleton } from "@/components/skeleton";
import type { PipelineBoard as Board, PipelineCard, PipelineStage } from "@/types";

const STAGE_KEYS = {
  new: "clients.pipeline.stageNew", qualified: "clients.pipeline.stageQualified", booked: "clients.pipeline.stageBooked",
  won: "clients.pipeline.stageWon", lost: "clients.pipeline.stageLost",
} as const satisfies Record<PipelineStage, string>;
const STAGES = Object.keys(STAGE_KEYS) as PipelineStage[];

/** A client's contacts by sales stage. Drag a card to move it, or pick the
 * stage on the card; agents move them too when the pipeline is on. */
export function PipelineBoard({ clientId }: { clientId: string }) {
  const { t, lang } = useLanguage();
  const toast = useToast();
  const base = `/clients/${clientId}/pipeline`;
  const [board, setBoard] = useState<Board | null>(null);
  const [query, setQuery] = useState("");
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<PipelineStage | null>(null);
  // When the board was read: "3 d ago" counts from it.
  const [readAt, setReadAt] = useState(0);

  const load = useCallback(async (q = "") => {
    try { setBoard(await api<Board>(`${base}${q ? `?q=${encodeURIComponent(q)}` : ""}`)); setReadAt(Date.now()); } catch (err) { toast.error(messageFrom(err)); }
  }, [base, toast]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { const id = setTimeout(() => load(query.trim()), 300); return () => clearTimeout(id); }, [query, load]);

  if (!board) return <ListRowsSkeleton />;

  const money = (value: number) => value.toLocaleString(lang, { maximumFractionDigits: 0 });
  const ago = (iso: string) => {
    const days = Math.floor((readAt - new Date(iso).getTime()) / 86400000);
    return days <= 0 ? t("clients.pipeline.today") : t("clients.pipeline.daysAgo", { days });
  };

  async function toggle(enabled: boolean) {
    try { await api(`${base}/settings`, { method: "PUT", body: JSON.stringify({ enabled }) }); setBoard((b) => b && { ...b, enabled }); }
    catch (err) { toast.error(messageFrom(err)); }
  }

  async function move(card: PipelineCard, patch: { stage?: PipelineStage; deal_value?: number; clear_value?: boolean }) {
    try {
      await api(`${base}/contacts/${card.id}`, { method: "PATCH", body: JSON.stringify(patch) });
      load(query.trim());
    } catch (err) { toast.error(messageFrom(err)); }
  }

  function drop(stage: PipelineStage, event: DragEvent) {
    event.preventDefault();
    setOver(null);
    const id = event.dataTransfer.getData("text/plain") || dragging;
    const card = board?.stages.flatMap((s) => s.contacts).find((c) => c.id === id);
    if (card && card.stage !== stage) move(card, { stage });
    setDragging(null);
  }

  function editValue(card: PipelineCard) {
    const raw = window.prompt(t("clients.pipeline.valuePrompt"), card.deal_value != null ? String(card.deal_value) : "");
    if (raw === null) return;
    const clean = raw.replace(/[^\d.,]/g, "").replace(/,/g, "");
    if (!clean) { move(card, { clear_value: true }); return; }
    const value = Number(clean);
    if (Number.isFinite(value) && value >= 0) move(card, { deal_value: value });
  }

  const totalOpen = board.stages.filter((s) => s.stage !== "lost" && s.stage !== "won").reduce((sum, s) => sum + s.value, 0);
  const won = board.stages.find((s) => s.stage === "won");

  return <div className="pipeline">
    <section className="panel pipeline-head">
      <label className="switch-row"><span><strong>{t("clients.pipeline.enabled")}</strong><small>{t("clients.pipeline.enabledHint")}</small></span><input type="checkbox" checked={board.enabled} onChange={(e) => toggle(e.target.checked)} /></label>
      <div className="pipeline-stats">
        <div><small>{t("clients.pipeline.openValue")}</small><strong>{money(totalOpen)}</strong></div>
        <div><small>{t("clients.pipeline.wonValue")}</small><strong>{money(won?.value ?? 0)}</strong></div>
        <div><small>{t("clients.pipeline.wonCount")}</small><strong>{won?.total ?? 0}</strong></div>
      </div>
      <label className="pipeline-search"><Search size={15} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("clients.pipeline.search")} aria-label={t("clients.pipeline.search")} /></label>
    </section>
    <div className="pipeline-board">
      {board.stages.map((column) => <section key={column.stage} className={`pipeline-col stage-${column.stage}${over === column.stage ? " over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setOver(column.stage); }} onDragLeave={() => setOver(null)} onDrop={(e) => drop(column.stage, e)}>
        <header><strong>{t(STAGE_KEYS[column.stage])}</strong><span>{column.total}</span>{column.value > 0 && <small>{money(column.value)}</small>}</header>
        <div className="pipeline-cards">
          {column.contacts.length === 0 && <p className="pipeline-empty">{t("clients.pipeline.empty")}</p>}
          {column.contacts.map((card) => <article key={card.id} className={`pipeline-card${dragging === card.id ? " dragging" : ""}`} draggable
            onDragStart={(e) => { e.dataTransfer.setData("text/plain", card.id); setDragging(card.id); }} onDragEnd={() => setDragging(null)}>
            <div className="pipeline-card-top"><strong>{card.name}</strong>{card.last_conversation_id && <Link href={`/inbox/${card.last_conversation_id}`} className="icon-button" title={t("clients.pipeline.openChat")} aria-label={t("clients.pipeline.openChat")}><MessageCircle size={14} /></Link>}</div>
            {card.phone && card.phone !== card.name && <small>{card.phone}</small>}
            {card.tags.length > 0 && <div className="pipeline-tags">{card.tags.map((tag) => <span key={tag.name} style={{ borderColor: tag.color, color: tag.color }}>{tag.name}</span>)}</div>}
            <div className="pipeline-card-foot">
              <button type="button" className="text-button" onClick={() => editValue(card)}>{card.deal_value != null ? money(card.deal_value) : t("clients.pipeline.addValue")}</button>
              <small>{ago(card.last_activity_at)}</small>
            </div>
            <select className="pipeline-move" value={card.stage} onChange={(e) => move(card, { stage: e.target.value as PipelineStage })} aria-label={t("clients.pipeline.moveTo")}>
              {STAGES.map((stage) => <option key={stage} value={stage}>{t(STAGE_KEYS[stage])}</option>)}
            </select>
          </article>)}
          {column.total > column.contacts.length && <p className="pipeline-empty">{t("clients.pipeline.more", { count: column.total - column.contacts.length })}</p>}
        </div>
      </section>)}
    </div>
  </div>;
}
