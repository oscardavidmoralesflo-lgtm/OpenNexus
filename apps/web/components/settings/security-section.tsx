"use client";

import { useCallback, useEffect, useState } from "react";
import { Copy, Download, KeyRound, LoaderCircle, ShieldAlert, ShieldCheck, ShieldOff, Smartphone } from "lucide-react";
import { FormSkeleton } from "@/components/skeleton";
import { useToast } from "@/components/toast";
import { Alert, Modal } from "@/components/ui";
import { PasswordInput } from "@/components/password-input";
import { api, messageFrom } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { TwoFactorSetup, TwoFactorStatus } from "@/types";

// The signed-in person's two-step verification: set it up with any
// authenticator app, keep recovery codes, or turn it off.
export function SecuritySection() {
  const t = useT();
  const toast = useToast();
  const [status, setStatus] = useState<TwoFactorStatus | null>(null);
  const [setup, setSetup] = useState<TwoFactorSetup | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [disabling, setDisabling] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setStatus(await api<TwoFactorStatus>("/account/2fa")); } catch (err) { toast.error(messageFrom(err)); }
  }, [toast]);
  useEffect(() => { load(); }, [load]);

  async function start() {
    setBusy(true);
    try { setSetup(await api<TwoFactorSetup>("/account/2fa/setup", { method: "POST" })); setCode(""); } catch (err) { toast.error(messageFrom(err)); } finally { setBusy(false); }
  }
  async function enable() {
    setBusy(true);
    try {
      const result = await api<{ recovery_codes: string[] }>("/account/2fa/enable", { method: "POST", body: JSON.stringify({ code }) });
      setSetup(null); setCodes(result.recovery_codes); toast.success(t("settings.security.enabled")); load();
    } catch (err) { toast.error(messageFrom(err)); } finally { setBusy(false); }
  }
  async function copy(value: string) {
    try { await navigator.clipboard.writeText(value); toast.success(t("settings.security.copied")); } catch { /* clipboard blocked */ }
  }
  function download(list: string[]) {
    const blob = new Blob([`${t("settings.security.codesFileTitle")}\n\n${list.join("\n")}\n`], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = "opennexus-recovery-codes.txt"; anchor.click();
    URL.revokeObjectURL(url);
  }

  if (!status) return <FormSkeleton sections={2} />;
  return <div className="page-form">
    {status.required_by_agency && !status.enabled && <Alert type="info">{t("settings.security.requiredNotice")}</Alert>}
    <section className="form-section">
      <div className="section-copy"><h2>{t("settings.security.heading")}</h2><p>{t("settings.security.copy")}</p></div>
      <div className="form-fields">
        <ul className="status-list"><li>
          <span><strong><Smartphone size={14} /> {t("settings.security.authenticator")}</strong>
            <small>{status.enabled ? t("settings.security.codesLeft", { count: status.recovery_codes_left }) : t("settings.security.authenticatorHint")}</small></span>
          {status.enabled ? <span className="domain-status ok"><ShieldCheck size={15} /> {t("settings.security.on")}</span> : <span className="domain-status pending"><ShieldAlert size={15} /> {t("settings.security.off")}</span>}
        </li></ul>

        {!status.enabled && !setup && <button type="button" className="button primary align-start" onClick={start} disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : <ShieldCheck size={16} />} {t("settings.security.turnOn")}</button>}

        {setup && <div className="two-factor-setup">
          <img src={setup.qr_svg} alt={t("settings.security.qrAlt")} width={200} height={200} />
          <div className="form-fields">
            <ol className="steps-list">
              <li>{t("settings.security.step1")}</li>
              <li>{t("settings.security.step2")}</li>
              <li>{t("settings.security.step3")}</li>
            </ol>
            <label>{t("settings.security.manualKey")}<div className="domain-input"><input value={setup.secret} readOnly /><button type="button" className="button ghost" onClick={() => copy(setup.secret)}><Copy size={15} /></button></div></label>
            <label>{t("settings.security.code")}<input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" maxLength={6} placeholder="123456" /></label>
            <div className="domain-actions">
              <button type="button" className="button primary" onClick={enable} disabled={busy || code.replace(/\D/g, "").length !== 6}>{busy ? <LoaderCircle className="spin" size={15} /> : <ShieldCheck size={15} />} {t("settings.security.confirm")}</button>
              <button type="button" className="button ghost" onClick={() => setSetup(null)}>{t("common.cancel")}</button>
            </div>
          </div>
        </div>}

        {status.enabled && <div className="domain-actions">
          <button type="button" className="button secondary" onClick={() => setRegenerating(true)}><KeyRound size={15} /> {t("settings.security.newCodes")}</button>
          {!status.required_by_agency && <button type="button" className="button ghost danger-text" onClick={() => setDisabling(true)}><ShieldOff size={15} /> {t("settings.security.turnOff")}</button>}
        </div>}
      </div>
    </section>

    <Modal open={Boolean(codes)} title={t("settings.security.codesTitle")} description={t("settings.security.codesCopy")} onClose={() => setCodes(null)}>
      {codes && <div className="form-fields">
        <ul className="recovery-codes">{codes.map((item) => <li key={item}><code>{item}</code></li>)}</ul>
        <div className="modal-actions">
          <button type="button" className="button ghost" onClick={() => copy(codes.join("\n"))}><Copy size={15} /> {t("settings.security.copy_")}</button>
          <button type="button" className="button ghost" onClick={() => download(codes)}><Download size={15} /> {t("settings.security.download")}</button>
          <button type="button" className="button primary" onClick={() => setCodes(null)}>{t("settings.security.saved")}</button>
        </div>
      </div>}
    </Modal>
    {regenerating && <CodeModal title={t("settings.security.newCodes")} description={t("settings.security.newCodesCopy")} withPassword={false}
      onClose={() => setRegenerating(false)}
      onSubmit={async (value) => { const result = await api<{ recovery_codes: string[] }>("/account/2fa/recovery-codes", { method: "POST", body: JSON.stringify({ code: value.code }) }); setRegenerating(false); setCodes(result.recovery_codes); load(); }} />}
    {disabling && <CodeModal title={t("settings.security.turnOff")} description={t("settings.security.turnOffCopy")} withPassword
      onClose={() => setDisabling(false)}
      onSubmit={async (value) => { setStatus(await api<TwoFactorStatus>("/account/2fa/disable", { method: "POST", body: JSON.stringify(value) })); setDisabling(false); toast.success(t("settings.security.disabled")); }} />}
  </div>;
}

function CodeModal({ title, description, withPassword, onClose, onSubmit }: {
  title: string; description: string; withPassword: boolean; onClose: () => void;
  onSubmit: (value: { code: string; password?: string }) => Promise<void>;
}) {
  const t = useT();
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit() {
    setBusy(true); setError("");
    try { await onSubmit(withPassword ? { code, password } : { code }); } catch (err) { setError(messageFrom(err)); } finally { setBusy(false); }
  }
  return <Modal open title={title} description={description} onClose={onClose}>
    <div className="form-fields">
      {withPassword && <label>{t("settings.security.password")}<PasswordInput value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>}
      <label>{t("settings.security.codeOrRecovery")}<input value={code} onChange={(e) => setCode(e.target.value)} autoComplete="one-time-code" maxLength={20} autoFocus={!withPassword} /></label>
      {error && <Alert>{error}</Alert>}
      <div className="modal-actions">
        <button type="button" className="button secondary" onClick={onClose}>{t("common.cancel")}</button>
        <button type="button" className="button primary" disabled={busy || code.trim().length < 6 || (withPassword && !password)} onClick={submit}>{busy && <LoaderCircle className="spin" size={15} />} {t("settings.security.continue")}</button>
      </div>
    </div>
  </Modal>;
}
