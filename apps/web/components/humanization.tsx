"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { LoaderCircle, Play, Save } from "lucide-react";
import { Alert } from "@/components/ui";
import { api, apiUrl, messageFrom } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { HumanizationConfig } from "@/types";

const VOICES = ["nova", "alloy", "echo", "fable", "onyx", "shimmer", "coral", "sage", "ash", "ballad"];
const DEFAULT_VOICE_MODEL = "openai/gpt-4o-mini-tts";

/** How the agent's WhatsApp replies read and sound: split into short
 * messages, typed at a person's pace, in the customer's own style, or spoken
 * as a voice note. Saved on its own, like the follow-ups. */
export function HumanizationEditor({ agentId, replyDelayOn }: { agentId: string; replyDelayOn: boolean }) {
  const t = useT();
  const [config, setConfig] = useState<HumanizationConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const load = useCallback(async () => setConfig(await api<HumanizationConfig>(`/agents/${agentId}/humanization`)), [agentId]);
  useEffect(() => { load().catch((err) => setError(messageFrom(err))); }, [load]);

  if (!config) return null;
  const set = (patch: Partial<HumanizationConfig>) => { setConfig({ ...config, ...patch }); setSaved(false); };

  async function save() {
    setBusy(true); setError("");
    try { setConfig(await api<HumanizationConfig>(`/agents/${agentId}/humanization`, { method: "PUT", body: JSON.stringify(config) })); setSaved(true); }
    catch (err) { setError(messageFrom(err)); } finally { setBusy(false); }
  }
  async function preview() {
    if (!config) return;
    setPreviewing(true); setError("");
    try {
      const response = await fetch(apiUrl(`/agents/${agentId}/humanization/voice-preview`), {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: t("agents.humanize.previewText"), voice_model: config.voice_model, voice_name: config.voice_name }),
      });
      if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || t("agents.humanize.previewFailed"));
      const url = URL.createObjectURL(await response.blob());
      audioRef.current?.pause();
      audioRef.current = new Audio(url);
      await audioRef.current.play();
    } catch (err) { setError(messageFrom(err)); } finally { setPreviewing(false); }
  }

  return <section className="settings-section">
    <div className="settings-copy"><h3>{t("agents.humanize.heading")}</h3><p>{t("agents.humanize.copy")}</p></div>
    <div className="settings-fields">
      {!replyDelayOn && <Alert type="info">{t("agents.humanize.needsDelay")}</Alert>}

      <label className="switch-row"><span><strong>{t("agents.humanize.split")}</strong><small>{t("agents.humanize.splitHint")}</small></span>
        <input type="checkbox" checked={config.split_replies} onChange={(e) => set({ split_replies: e.target.checked })} /></label>
      {config.split_replies && <label>{t("agents.humanize.maxParts")}
        <select value={config.split_max_parts} onChange={(e) => set({ split_max_parts: Number(e.target.value) })}>{[2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}</select></label>}

      <label>{t("agents.humanize.typing")}
        <select value={config.typing_speed_cps} onChange={(e) => set({ typing_speed_cps: Number(e.target.value) })}>
          <option value={0}>{t("agents.humanize.typingNatural")}</option>
          <option value={12}>{t("agents.humanize.typingCalm")}</option>
          <option value={35}>{t("agents.humanize.typingFast")}</option>
        </select>
        <small className="field-help">{t("agents.humanize.typingHint")}</small></label>

      <label className="switch-row"><span><strong>{t("agents.humanize.mirror")}</strong><small>{t("agents.humanize.mirrorHint")}</small></span>
        <input type="checkbox" checked={config.style_mirror} onChange={(e) => set({ style_mirror: e.target.checked })} /></label>

      <label>{t("agents.humanize.voice")}
        <select value={config.voice_replies} onChange={(e) => set({ voice_replies: e.target.value as HumanizationConfig["voice_replies"] })}>
          <option value="off">{t("agents.humanize.voiceOff")}</option>
          <option value="mirror">{t("agents.humanize.voiceMirror")}</option>
          <option value="always">{t("agents.humanize.voiceAlways")}</option>
        </select>
        <small className="field-help">{t("agents.humanize.voiceHint")}</small></label>
      {config.voice_replies !== "off" && <div className="form-grid">
        <label>{t("agents.humanize.voiceModel")}<input value={config.voice_model} placeholder={DEFAULT_VOICE_MODEL} onChange={(e) => set({ voice_model: e.target.value })} /></label>
        <label>{t("agents.humanize.voiceName")}<input list="humanize-voices" value={config.voice_name} placeholder="nova" onChange={(e) => set({ voice_name: e.target.value })} />
          <datalist id="humanize-voices">{VOICES.map((voice) => <option key={voice} value={voice} />)}</datalist></label>
      </div>}

      {error && <Alert>{error}</Alert>}
      <div className="form-footer split">
        {config.voice_replies !== "off" ? <button type="button" className="button secondary" onClick={preview} disabled={previewing}>{previewing ? <LoaderCircle className="spin" size={15} /> : <Play size={15} />} {t("agents.humanize.preview")}</button> : <span />}
        <span className="escalation-save">{saved && <span className="escalation-saved">{t("agents.escalation.savedNote")}</span>}
          <button type="button" className="button primary" onClick={save} disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />} {t("agents.humanize.save")}</button></span>
      </div>
    </div>
  </section>;
}
