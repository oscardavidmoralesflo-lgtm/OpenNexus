"use client";

import { FormEvent, useEffect, useState } from "react";
import { CheckCircle2, ExternalLink, LoaderCircle, Save } from "lucide-react";
import { api, messageFrom } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { Alert } from "@/components/ui";

export function IntegrationAccessSection() {
  const t = useT();
  const [state, setState] = useState<{ configured: boolean; api_key_masked: string } | null>(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const load = () => api<{ configured: boolean; api_key_masked: string }>("/integrations/access").then(setState).catch((err) => setError(messageFrom(err)));
  useEffect(() => { void load(); }, []);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setSaved(false);
    try {
      setState(await api("/integrations/access", { method: "PUT", body: JSON.stringify({ api_key: key.trim() }) }));
      setKey(""); setSaved(true);
    } catch (err) { setError(messageFrom(err)); } finally { setBusy(false); }
  }
  return <section className="section-block">
    <div className="section-heading"><div><h2>{t("tools.catalog.settingsHeading")}</h2><p>{t("tools.catalog.settingsCopy")}</p></div></div>
    <p>{t("tools.catalog.setupSteps")}</p>
    <p className="security-note">{t("tools.catalog.dataHint")}</p>
    {error && <Alert type="error">{error}</Alert>}
    {saved && <Alert type="success">{t("tools.catalog.keySaved")}</Alert>}
    {!state && !error && <p>{t("tools.catalog.loading")}</p>}
    {state?.configured && <p className="key-configured-status"><CheckCircle2 size={18} /> {t("tools.catalog.configured", { key: state.api_key_masked })}</p>}
    <form className="form-fields" onSubmit={submit}>
      <label>{t(state?.configured ? "tools.catalog.replaceKey" : "tools.catalog.serviceKey")}<input type="password" autoComplete="off" required minLength={8} maxLength={500} value={key} onChange={(event) => setKey(event.target.value)} /></label>
      <div className="tools-actions"><button className="button primary" disabled={busy || key.trim().length < 8}>{busy ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />} {t("tools.catalog.saveKey")}</button><a className="button secondary" href="https://platform.composio.dev/" target="_blank" rel="noopener noreferrer"><ExternalLink size={16} /> {t("tools.catalog.getKey")}</a></div>
    </form>
  </section>;
}
