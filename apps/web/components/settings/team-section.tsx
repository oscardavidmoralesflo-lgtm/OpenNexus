"use client";

import { useCallback, useEffect, useState } from "react";
import { Copy, LoaderCircle, MailPlus, ShieldCheck, ShieldOff, Trash2, UserMinus } from "lucide-react";
import { ConfirmModal } from "@/components/confirm-modal";
import { FormSkeleton } from "@/components/skeleton";
import { useToast } from "@/components/toast";
import { Modal } from "@/components/ui";
import { api, messageFrom } from "@/lib/api";
import { isManager } from "@/lib/current-user";
import { useLanguage, type I18nKey } from "@/lib/i18n";
import type { AgencyTeam, TeamInvitationCreated, AgencyMember, TeamRole } from "@/types";

const ROLES: TeamRole[] = ["owner", "admin", "operator", "viewer"];
const ROLE_KEYS: Record<TeamRole, I18nKey> = {
  owner: "settings.team.roleOwner", admin: "settings.team.roleAdmin", operator: "settings.team.roleOperator", viewer: "settings.team.roleViewer",
};
const ROLE_HINTS: Record<TeamRole, I18nKey> = {
  owner: "settings.team.roleOwnerHint", admin: "settings.team.roleAdminHint", operator: "settings.team.roleOperatorHint", viewer: "settings.team.roleViewerHint",
};

// The agency's people: who they are, their role, whether they use two-step
// verification, and invitations still waiting to be accepted.
export function TeamSection() {
  const { t, lang } = useLanguage();
  const toast = useToast();
  const [team, setTeam] = useState<AgencyTeam | null>(null);
  const [inviting, setInviting] = useState(false);
  const [link, setLink] = useState<TeamInvitationCreated | null>(null);
  const [removing, setRemoving] = useState<AgencyMember | null>(null);

  const load = useCallback(async () => {
    try { setTeam(await api<AgencyTeam>("/team")); } catch (err) { toast.error(messageFrom(err)); }
  }, [toast]);
  useEffect(() => { load(); }, [load]);

  const when = (value: string | null) => value ? new Date(value).toLocaleDateString(lang === "es" ? "es" : "en", { dateStyle: "medium" }) : t("settings.team.never");
  async function copy(value: string) {
    try { await navigator.clipboard.writeText(value); toast.success(t("settings.team.copied")); } catch { /* clipboard blocked */ }
  }
  async function changeRole(member: AgencyMember, role: TeamRole) {
    try { await api(`/team/members/${member.id}`, { method: "PATCH", body: JSON.stringify({ role }) }); toast.success(t("settings.team.roleChanged")); load(); }
    catch (err) { toast.error(messageFrom(err)); load(); }
  }
  async function revoke(id: string) {
    try { await api(`/team/invitations/${id}`, { method: "DELETE" }); load(); } catch (err) { toast.error(messageFrom(err)); }
  }
  async function setPolicy(require: boolean) {
    try { setTeam(await api<AgencyTeam>("/team/policy", { method: "PUT", body: JSON.stringify({ require_two_factor: require }) })); toast.success(t("settings.team.policySaved")); }
    catch (err) { toast.error(messageFrom(err)); }
  }

  if (!team) return <FormSkeleton sections={2} />;
  const manager = isManager(team.your_role);
  const owner = team.your_role === "owner";
  // Owners grant any role; admins only operator and viewer.
  const grantable = ROLES.filter((role) => owner || (team.your_role === "admin" && !isManager(role)));
  const canEdit = (member: AgencyMember) => manager && !member.is_you && grantable.includes(member.role);

  return <div className="page-form">
    <section className="form-section">
      <div className="section-copy"><h2>{t("settings.team.heading")}</h2><p>{t("settings.team.copy")}</p>
        {manager && <button type="button" className="button primary align-start" onClick={() => setInviting(true)}><MailPlus size={16} /> {t("settings.team.invite")}</button>}</div>
      <div className="form-fields">
        <div className="table-shell"><table className="data-table"><thead><tr>
          <th>{t("settings.team.colMember")}</th><th>{t("settings.team.colRole")}</th><th>{t("settings.team.colTwoFactor")}</th><th>{t("settings.team.colLastLogin")}</th><th />
        </tr></thead><tbody>{team.members.map((member) => <tr key={member.id}>
          <td><strong>{member.name}</strong>{member.is_you && <> <span className="pill">{t("settings.team.you")}</span></>}<br /><small>{member.email}</small></td>
          <td>{canEdit(member)
            ? <select value={member.role} onChange={(e) => changeRole(member, e.target.value as TeamRole)} aria-label={t("settings.team.colRole")}>{grantable.map((role) => <option key={role} value={role}>{t(ROLE_KEYS[role])}</option>)}</select>
            : <span className={isManager(member.role) ? "pill purple" : "pill"}>{t(ROLE_KEYS[member.role])}</span>}</td>
          <td>{member.two_factor_enabled ? <span className="domain-status ok"><ShieldCheck size={14} /> {t("settings.team.on")}</span> : <span className="domain-status pending"><ShieldOff size={14} /> {t("settings.team.off")}</span>}</td>
          <td>{when(member.last_login_at)}</td>
          <td>{canEdit(member) && <button type="button" className="icon-button danger" aria-label={t("settings.team.remove")} title={t("settings.team.remove")} onClick={() => setRemoving(member)}><UserMinus size={15} /></button>}</td>
        </tr>)}</tbody></table></div>

        {manager && team.invitations.length > 0 && <>
          <h3 className="subheading">{t("settings.team.pending")}</h3>
          <ul className="status-list">{team.invitations.map((invitation) => <li key={invitation.id}>
            <span><strong>{invitation.email}</strong><small>{t(ROLE_KEYS[invitation.role])} · {t("settings.team.expires", { date: when(invitation.expires_at) })}{invitation.invited_by ? ` · ${t("settings.team.invitedBy", { name: invitation.invited_by })}` : ""}</small></span>
            <button type="button" className="button ghost danger-text" onClick={() => revoke(invitation.id)}><Trash2 size={15} /> {t("settings.team.revoke")}</button>
          </li>)}</ul>
        </>}
      </div>
    </section>

    <section className="form-section">
      <div className="section-copy"><h2>{t("settings.team.rolesHeading")}</h2><p>{t("settings.team.rolesCopy")}</p></div>
      <div className="form-fields"><ul className="status-list">{ROLES.map((role) => <li key={role}>
        <span><strong>{t(ROLE_KEYS[role])}</strong><small>{t(ROLE_HINTS[role])}</small></span>
      </li>)}</ul></div>
    </section>

    {owner && <section className="form-section">
      <div className="section-copy"><h2>{t("settings.team.policyHeading")}</h2><p>{t("settings.team.policyCopy")}</p></div>
      <div className="form-fields">
        <label className="switch-row"><span><strong>{t("settings.team.requireTwoFactor")}</strong><small>{t("settings.team.requireTwoFactorHint")}</small></span>
          <input type="checkbox" checked={team.require_two_factor} onChange={(e) => setPolicy(e.target.checked)} /></label>
      </div>
    </section>}

    {inviting && <InviteModal roles={grantable} onClose={() => setInviting(false)} onCreated={(created) => { setInviting(false); setLink(created); load(); }} />}
    <Modal open={Boolean(link)} title={t("settings.team.linkTitle")} description={t("settings.team.linkCopy", { email: link?.email ?? "" })} onClose={() => setLink(null)} wide>
      {link && <div className="form-fields">
        <div className="domain-input"><input value={link.link} readOnly /><button type="button" className="button primary" onClick={() => copy(link.link)}><Copy size={15} /> {t("settings.team.copyLink")}</button></div>
        <small className="field-help">{t("settings.team.linkHint")}</small>
        <div className="modal-actions"><button type="button" className="button secondary" onClick={() => setLink(null)}>{t("settings.team.done")}</button></div>
      </div>}
    </Modal>
    {removing && <ConfirmModal title={t("settings.team.removeTitle", { name: removing.name })} message={t("settings.team.removeCopy")}
      confirmLabel={t("settings.team.remove")} cancelLabel={t("common.cancel")} confirmIcon={<UserMinus size={15} />}
      onConfirm={async () => { await api(`/team/members/${removing.id}`, { method: "DELETE" }); setRemoving(null); toast.success(t("settings.team.removed")); load(); }}
      onClose={() => setRemoving(null)} />}
  </div>;
}

function InviteModal({ roles, onClose, onCreated }: { roles: TeamRole[]; onClose: () => void; onCreated: (created: TeamInvitationCreated) => void }) {
  const { t } = useLanguage();
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<TeamRole>(roles.includes("operator") ? "operator" : roles[0]);
  const [busy, setBusy] = useState(false);
  async function submit() {
    setBusy(true);
    try { onCreated(await api<TeamInvitationCreated>("/team/invitations", { method: "POST", body: JSON.stringify({ email: email.trim(), role }) })); }
    catch (err) { toast.error(messageFrom(err)); } finally { setBusy(false); }
  }
  return <Modal open title={t("settings.team.invite")} description={t("settings.team.inviteCopy")} onClose={onClose}>
    <div className="form-fields">
      <label>{t("settings.team.email")}<input type="email" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} placeholder="persona@agencia.com" /></label>
      <label>{t("settings.team.colRole")}<select value={role} onChange={(e) => setRole(e.target.value as TeamRole)}>{roles.map((item) => <option key={item} value={item}>{t(ROLE_KEYS[item])}</option>)}</select>
        <small className="field-help">{t(ROLE_HINTS[role])}</small></label>
      <div className="modal-actions">
        <button type="button" className="button secondary" onClick={onClose}>{t("common.cancel")}</button>
        <button type="button" className="button primary" disabled={busy || !email.includes("@")} onClick={submit}>{busy ? <LoaderCircle className="spin" size={15} /> : <MailPlus size={15} />} {t("settings.team.createLink")}</button>
      </div>
    </div>
  </Modal>;
}
