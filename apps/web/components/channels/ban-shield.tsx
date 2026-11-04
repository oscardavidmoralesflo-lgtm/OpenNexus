"use client";

import { useCallback, useEffect, useState } from "react";
import { LoaderCircle, Play, ShieldCheck, ShieldAlert } from "lucide-react";
import { Alert } from "@/components/ui";
import { api, messageFrom } from "@/lib/api";
import { formatWhen } from "@/lib/datetime";
import { useLanguage } from "@/lib/i18n";

type Health = {
  enabled: boolean; warmup_day: number; warmup_days: number; warming_up: boolean;
  outreach_today: number; outreach_limit: number; strangers_today: number; stranger_limit: number;
  replies_today: number; failed_last_hour: number; disconnects_last_hour: number;
  paused_until: string | null; pause_reason: string | null; pause_code: "banned" | "failed" | "disconnects" | "other" | null;
};

/** The ban shield of a QR line: how its warm-up goes, how much of today's
 * allowance of messages it starts is used, and any pause. Replies to people
 * who write are never held back. */
export function BanShield({ channelId }: { channelId: string }) {
  const { t, lang } = useLanguage();
  const base = `/whatsapp/channels/${channelId}/guard`;
  const [health, setHealth] = useState<Health | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try { setHealth(await api<Health>(base)); } catch (err) { setError(messageFrom(err)); }
  }, [base]);
  useEffect(() => { load(); const id = setInterval(load, 30000); return () => clearInterval(id); }, [load]);

  async function call(path: string, init: RequestInit) {
    setBusy(true); setError("");
    try { setHealth(await api<Health>(path, init)); } catch (err) { setError(messageFrom(err)); } finally { setBusy(false); }
  }

  if (!health) return null;
  const used = Math.min(100, Math.round((health.outreach_today / Math.max(1, health.outreach_limit)) * 100));
  const level = health.paused_until ? "paused" : !health.enabled ? "off" : used >= 80 || health.failed_last_hour || health.disconnects_last_hour ? "watch" : "good";

  return <section className="wa-panel ban-shield">
    <div className="wa-panel-head"><span>{level === "paused" || level === "off" ? <ShieldAlert size={19} /> : <ShieldCheck size={19} />}</span><div>
      <h2>{t("clients.whatsapp.shield.title")} <em className={`shield-level level-${level}`}>{t(`clients.whatsapp.shield.level_${level}`)}</em></h2>
      <p>{t("clients.whatsapp.shield.copy")}</p>
    </div></div>
    {error && <Alert>{error}</Alert>}
    {health.paused_until && <div className="shield-paused">
      <p><strong>{t("clients.whatsapp.shield.pausedUntil", { when: formatWhen(health.paused_until, lang) })}</strong> {t(`clients.whatsapp.shield.reason_${health.pause_code ?? "other"}`)}</p>
      <p className="social-meta">{t("clients.whatsapp.shield.pausedHint")}</p>
      <button type="button" className="button secondary" disabled={busy} onClick={() => call(`${base}/resume`, { method: "POST" })}>{busy ? <LoaderCircle className="spin" size={15} /> : <Play size={15} />} {t("clients.whatsapp.shield.resume")}</button>
    </div>}
    {health.enabled && <div className="shield-grid">
      <div><small>{health.warming_up ? t("clients.whatsapp.shield.warmup") : t("clients.whatsapp.shield.warmupDone")}</small>
        <strong>{health.warming_up ? t("clients.whatsapp.shield.day", { day: health.warmup_day, days: health.warmup_days }) : "✓"}</strong>
        {health.warming_up && <div className="shield-steps">{Array.from({ length: health.warmup_days }, (_, i) => <span key={i} className={i < health.warmup_day ? "on" : ""} />)}</div>}</div>
      <div><small>{t("clients.whatsapp.shield.outreach")}</small><strong>{health.outreach_today} <em>/ {health.outreach_limit}</em></strong>
        <div className="campaign-progress"><span style={{ width: `${used}%` }} /></div></div>
      <div><small>{t("clients.whatsapp.shield.strangers")}</small><strong>{health.strangers_today} <em>/ {health.stranger_limit}</em></strong></div>
      <div><small>{t("clients.whatsapp.shield.replies")}</small><strong>{health.replies_today}</strong></div>
    </div>}
    <label className="switch-row"><span><strong>{t("clients.whatsapp.shield.enabled")}</strong><small>{t("clients.whatsapp.shield.enabledHint")}</small></span>
      <input type="checkbox" checked={health.enabled} disabled={busy} onChange={(e) => call(base, { method: "PUT", body: JSON.stringify({ enabled: e.target.checked }) })} /></label>
  </section>;
}
