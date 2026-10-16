"use client";

import { FormEvent, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { LoaderCircle, ShieldCheck, UserPlus } from "lucide-react";
import { Alert } from "@/components/ui";
import { PasswordInput } from "@/components/password-input";
import { api, messageFrom } from "@/lib/api";
import { useT, type I18nKey } from "@/lib/i18n";
import type { TeamRole } from "@/types";

type Preview = { agency_name: string; email: string; role: TeamRole; expires_at: string };
const ROLE_KEYS: Record<TeamRole, I18nKey> = {
  owner: "settings.team.roleOwner", admin: "settings.team.roleAdmin", operator: "settings.team.roleOperator", viewer: "settings.team.roleViewer",
};

// Joining the agency's team from an invitation link: the person picks their
// name and password, and is signed in.
export default function InvitePage() {
  const t = useT();
  const router = useRouter();
  const { token } = useParams<{ token: string }>();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<Preview>(`/auth/invitations/${encodeURIComponent(token)}`).then(setPreview).catch((err) => setError(messageFrom(err)));
  }, [token]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError("");
    const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      await api(`/auth/invitations/${encodeURIComponent(token)}/accept`, { method: "POST", body: JSON.stringify(data) });
      router.push("/");
      router.refresh();
    } catch (err) { setError(messageFrom(err)); } finally { setBusy(false); }
  }

  return <main className="access-page agency-access">
    <header className="access-topbar">
      <div className="access-brand"><span className="opennexus-icon"><img src="/brand/opennexus-mark.svg" alt="" /></span><strong>OpenNexus</strong></div>
    </header>
    <div className="access-layout invite-layout">
      <section className="access-form-wrap">
        <div className="access-card">
          <span className="access-card-label"><UserPlus size={15} /> {t("invite.label")}</span>
          {preview ? <>
            <h2>{t("invite.title", { agency: preview.agency_name })}</h2>
            <p>{t("invite.subtitle", { role: t(ROLE_KEYS[preview.role]) })}</p>
            <form onSubmit={submit} className="access-form">
              <label>{t("auth.email")}<input value={preview.email} readOnly disabled /></label>
              <label>{t("auth.yourName")}<input name="name" required minLength={2} autoFocus placeholder={t("auth.yourNamePlaceholder")} /></label>
              <label>{t("auth.password")}<PasswordInput name="password" required minLength={8} autoComplete="new-password" placeholder={t("auth.passwordPlaceholder")} /></label>
              {error && <Alert>{error}</Alert>}
              <button className="button primary full" disabled={busy}>{busy && <LoaderCircle className="spin" size={17} />}{t("invite.submit")}</button>
            </form>
          </> : error ? <><h2>{t("invite.invalidTitle")}</h2><Alert>{error}</Alert></>
            : <p role="status"><LoaderCircle className="spin" size={17} /> {t("common.loading")}</p>}
          <p className="access-security"><ShieldCheck size={14} /> {t("auth.securityNote")}</p>
        </div>
      </section>
    </div>
  </main>;
}
