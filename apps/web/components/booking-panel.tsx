"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { Ban, BellRing, CalendarDays, Check, LoaderCircle, MessageCircle, Plus, RotateCcw, Save, Trash2, UserX } from "lucide-react";
import { api, messageFrom } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import { useToast } from "@/components/toast";
import { FormSkeleton } from "@/components/skeleton";
import { weekdayNames } from "@/components/agent-schedule";
import type { Appointment, AppointmentStatus, BookingSettings, ScheduleSlot } from "@/types";

const DAYS = [0, 1, 2, 3, 4, 5, 6];
const STATUS_KEY = {
  confirmed: "clients.booking.statusConfirmed", cancelled: "clients.booking.statusCancelled",
  completed: "clients.booking.statusCompleted", no_show: "clients.booking.statusNoShow",
} as const satisfies Record<AppointmentStatus, string>;

/** A client's appointment book: the hours agents can book in, and the
 * appointments booked so far, with a quick form for the team. */
export function BookingPanel({ clientId, timezone }: { clientId: string; timezone: string }) {
  const { t, lang } = useLanguage();
  const toast = useToast();
  const base = `/clients/${clientId}`;
  const [settings, setSettings] = useState<BookingSettings | null>(null);
  const [items, setItems] = useState<Appointment[] | null>(null);
  const [free, setFree] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState({ starts_at: "", name: "", phone: "", notes: "" });
  const [adding, setAdding] = useState(false);
  const tz = timezone || "UTC";

  const loadList = useCallback(async () => {
    try {
      const [list, slots] = await Promise.all([
        api<{ appointments: Appointment[] }>(`${base}/appointments`),
        api<{ slots: string[] }>(`${base}/booking/slots?days=7`),
      ]);
      setItems(list.appointments); setFree(slots.slots);
    } catch (err) { toast.error(messageFrom(err)); }
  }, [base, toast]);

  useEffect(() => {
    api<BookingSettings>(`${base}/booking`).then(setSettings).catch((err) => toast.error(messageFrom(err)));
    loadList();
  }, [base, loadList, toast]);

  if (!settings || !items) return <FormSkeleton />;

  const names = weekdayNames(lang);
  const set = (patch: Partial<BookingSettings>) => setSettings({ ...settings, ...patch });
  const slotOf = (day: number) => settings.slots.find((slot) => slot.day === day);
  const setDay = (day: number, next: ScheduleSlot | null) =>
    set({ slots: [...settings.slots.filter((slot) => slot.day !== day), ...(next ? [next] : [])].sort((a, b) => a.day - b.day) });
  const fmt = (iso: string, options: Intl.DateTimeFormatOptions) => new Date(iso).toLocaleString(lang, { timeZone: tz, ...options });
  const dayLabel = (iso: string) => {
    const label = fmt(iso, { weekday: "long", day: "numeric", month: "long" });
    return label.charAt(0).toUpperCase() + label.slice(1);
  };
  const timeLabel = (iso: string) => fmt(iso, { hour: "2-digit", minute: "2-digit" });

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      setSettings(await api<BookingSettings>(`${base}/booking`, { method: "PUT", body: JSON.stringify(settings) }));
      toast.success(t("clients.booking.saved"));
      loadList();
    } catch (err) { toast.error(messageFrom(err)); } finally { setSaving(false); }
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    setAdding(true);
    try {
      await api(`${base}/appointments`, { method: "POST", body: JSON.stringify(draft) });
      setDraft({ starts_at: "", name: "", phone: "", notes: "" });
      toast.success(t("clients.booking.added"));
      loadList();
    } catch (err) { toast.error(messageFrom(err)); } finally { setAdding(false); }
  }

  async function update(id: string, status: AppointmentStatus) {
    try {
      await api(`${base}/appointments/${id}`, { method: "PATCH", body: JSON.stringify({ status }) });
      toast.success(t("clients.booking.updated")); loadList();
    } catch (err) { toast.error(messageFrom(err)); }
  }

  async function remove(id: string) {
    try {
      await api(`${base}/appointments/${id}`, { method: "DELETE" });
      toast.success(t("clients.booking.deleted")); loadList();
    } catch (err) { toast.error(messageFrom(err)); }
  }

  const groups = new Map<string, Appointment[]>();
  for (const item of items) {
    const key = fmt(item.starts_at, { year: "numeric", month: "2-digit", day: "2-digit" });
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  const freeByDay = new Map<string, string[]>();
  for (const slot of free) {
    const key = dayLabel(slot);
    freeByDay.set(key, [...(freeByDay.get(key) ?? []), slot]);
  }
  const reminderLine = (item: Appointment) => {
    if (item.status !== "confirmed") return null;
    if (item.reminder_sent_at) return <span className="booking-reminder ok"><BellRing size={13} /> {t("clients.booking.reminderSent")}</span>;
    if (item.reminder_error) return <span className="booking-reminder fail"><BellRing size={13} /> {t("clients.booking.reminderFailed")}</span>;
    if (item.reminder_due_at) return <span className="booking-reminder"><BellRing size={13} /> {t("clients.booking.reminderPending", { when: `${dayLabel(item.reminder_due_at)} ${timeLabel(item.reminder_due_at)}` })}</span>;
    return null;
  };

  return <div className="booking-panel">
    <section className="panel booking-list">
      <div className="panel-head"><div><h3>{t("clients.booking.listTitle")}</h3><p>{t("clients.booking.listCopy")}</p></div></div>
      {items.length === 0 ? <div className="inline-empty"><CalendarDays size={22} /><div><strong>{t("clients.booking.empty")}</strong></div></div> :
        [...groups.values()].map((dayItems) => <div className="booking-group" key={dayItems[0].id}>
          <h4>{dayLabel(dayItems[0].starts_at)}</h4>
          {dayItems.map((item) => <article key={item.id} className={`booking-item ${item.status}`}>
            <div className="booking-time"><strong>{timeLabel(item.starts_at)}</strong><small>{timeLabel(item.ends_at)}</small></div>
            <div className="booking-who">
              <strong>{item.name}{item.phone && <small> · {item.phone}</small>}</strong>
              {item.notes && <p>{item.notes}</p>}
              <div className="booking-meta">
                <span className={`booking-status ${item.status}`}>{t(STATUS_KEY[item.status])}</span>
                <span>{item.source === "agent" ? t("clients.booking.byAgent", { agent: item.agent_name ?? "" }) : t("clients.booking.byTeam")}</span>
                {reminderLine(item)}
              </div>
            </div>
            <div className="booking-actions">
              {item.conversation_id && <Link className="icon-button" href={`/inbox/${item.conversation_id}`} title={t("clients.booking.openChat")} aria-label={t("clients.booking.openChat")}><MessageCircle size={15} /></Link>}
              {item.status === "confirmed" ? <>
                <button type="button" className="icon-button" onClick={() => update(item.id, "completed")} title={t("clients.booking.markCompleted")} aria-label={t("clients.booking.markCompleted")}><Check size={15} /></button>
                <button type="button" className="icon-button" onClick={() => update(item.id, "no_show")} title={t("clients.booking.markNoShow")} aria-label={t("clients.booking.markNoShow")}><UserX size={15} /></button>
                <button type="button" className="icon-button" onClick={() => update(item.id, "cancelled")} title={t("clients.booking.cancel")} aria-label={t("clients.booking.cancel")}><Ban size={15} /></button>
              </> : <button type="button" className="icon-button" onClick={() => update(item.id, "confirmed")} title={t("clients.booking.restore")} aria-label={t("clients.booking.restore")}><RotateCcw size={15} /></button>}
              <button type="button" className="icon-button" onClick={() => remove(item.id)} title={t("clients.booking.remove")} aria-label={t("clients.booking.remove")}><Trash2 size={15} /></button>
            </div>
          </article>)}
        </div>)}
    </section>
    <section className="form-section"><div className="section-copy"><h2>{t("clients.booking.newTitle")}</h2><p>{t("clients.booking.freeTimes")}</p></div><div className="form-fields">
      {freeByDay.size ? <div className="booking-free">{[...freeByDay.entries()].map(([day, slots]) => <div key={day}><small>{day}</small><div>{slots.map((slot) => <button type="button" key={slot} className={`booking-chip${draft.starts_at === slot ? " active" : ""}`} onClick={() => setDraft({ ...draft, starts_at: slot })}>{timeLabel(slot)}</button>)}</div></div>)}</div> : <p className="field-help">{t("clients.booking.noFree")}</p>}
      <form className="booking-new" onSubmit={add}>
        <label>{t("clients.booking.when")}<input value={draft.starts_at ? `${dayLabel(draft.starts_at)} · ${timeLabel(draft.starts_at)}` : ""} readOnly placeholder={t("clients.booking.freeTimes")} /></label>
        <label>{t("clients.booking.name")}<input value={draft.name} maxLength={180} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
        <label>{t("clients.booking.phone")}<input value={draft.phone} maxLength={40} onChange={(e) => setDraft({ ...draft, phone: e.target.value })} /></label>
        <label>{t("clients.booking.notes")}<input value={draft.notes} maxLength={2000} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} /></label>
        <button className="button secondary" disabled={adding || !draft.starts_at || !draft.name.trim()}>{adding ? <LoaderCircle className="spin" size={15} /> : <Plus size={15} />} {t("clients.booking.add")}</button>
      </form>
    </div></section>
    <form className="page-form" onSubmit={save}>
      <section className="form-section"><div className="section-copy"><h2>{t("clients.booking.settingsTitle")}</h2><p>{t("clients.booking.settingsCopy")}</p></div><div className="form-fields">
        <label className="switch-row"><span><strong>{t("clients.booking.enabled")}</strong><small>{t("clients.booking.enabledHint")}</small></span><input type="checkbox" checked={settings.enabled} onChange={(e) => set({ enabled: e.target.checked })} /></label>
        <div className="booking-hours">
          <strong>{t("clients.booking.hoursTitle")}</strong>
          <small>{t("clients.booking.hoursHint", { timezone: tz })}</small>
          {DAYS.map((day) => {
            const slot = slotOf(day);
            return <div className="booking-day" key={day}>
              <label className="booking-day-name"><input type="checkbox" checked={!!slot} onChange={(e) => setDay(day, e.target.checked ? { day, start: "09:00", end: "18:00" } : null)} /> {names[day].charAt(0).toUpperCase() + names[day].slice(1)}</label>
              {slot ? <span className="booking-day-hours">
                <input type="time" value={slot.start} onChange={(e) => setDay(day, { ...slot, start: e.target.value })} aria-label={`${names[day]} start`} />
                <span>{t("clients.booking.to")}</span>
                <input type="time" value={slot.end} onChange={(e) => setDay(day, { ...slot, end: e.target.value })} aria-label={`${names[day]} end`} />
              </span> : <span className="booking-day-closed">{t("clients.booking.closed")}</span>}
            </div>;
          })}
        </div>
        <div className="booking-grid">
          <label>{t("clients.booking.duration")}<input type="number" min={5} max={480} step={5} value={settings.duration_minutes} onChange={(e) => set({ duration_minutes: Number(e.target.value) })} /></label>
          <label>{t("clients.booking.capacity")}<input type="number" min={1} max={50} value={settings.capacity} onChange={(e) => set({ capacity: Number(e.target.value) })} /><span className="field-help">{t("clients.booking.capacityHint")}</span></label>
          <label>{t("clients.booking.notice")}<input type="number" min={0} max={336} value={Math.round(settings.min_notice_minutes / 60)} onChange={(e) => set({ min_notice_minutes: Number(e.target.value) * 60 })} /></label>
          <label>{t("clients.booking.ahead")}<input type="number" min={1} max={365} value={settings.max_days_ahead} onChange={(e) => set({ max_days_ahead: Number(e.target.value) })} /></label>
        </div>
        <label>{t("clients.booking.location")}<input value={settings.location} maxLength={500} placeholder={t("clients.booking.locationPlaceholder")} onChange={(e) => set({ location: e.target.value })} /><span className="field-help">{t("clients.booking.locationHint")}</span></label>
        <label className="switch-row"><span><strong>{t("clients.booking.reminder")}</strong><small>{t("clients.booking.reminderHint")}</small></span><input type="checkbox" checked={settings.reminder_enabled} onChange={(e) => set({ reminder_enabled: e.target.checked })} /></label>
        {settings.reminder_enabled && <label>{t("clients.booking.reminderHours")}<input type="number" min={1} max={72} value={settings.reminder_hours} onChange={(e) => set({ reminder_hours: Number(e.target.value) })} /></label>}
      </div></section>
      <div className="form-footer"><button className="button primary" disabled={saving}>{saving ? <LoaderCircle className="spin" size={17} /> : <Save size={17} />} {t("clients.booking.save")}</button></div>
    </form>


  </div>;
}
