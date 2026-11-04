"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { CheckCircle2, CircleDashed, LoaderCircle, Play, Plus, Trash2, XCircle } from "lucide-react";
import { api, messageFrom } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import { useToast } from "@/components/toast";
import { PanelSkeleton } from "@/components/skeleton";
import type { AgentTestCase, AgentTestSuite } from "@/types";

// The quality lab: questions an agent should answer well, run and graded on demand.
export function AgentQualityTab({ agentId }: { agentId: string }) {
  const { t, lang } = useLanguage();
  const toast = useToast();
  const [suite, setSuite] = useState<AgentTestSuite | null>(null);
  const [question, setQuestion] = useState("");
  const [expectation, setExpectation] = useState("");
  const [running, setRunning] = useState<string | "all" | null>(null);
  const [adding, setAdding] = useState(false);
  const base = `/agents/${agentId}/tests`;

  const load = useCallback(async () => {
    try { setSuite(await api<AgentTestSuite>(base)); } catch (err) { toast.error(messageFrom(err)); }
  }, [base, toast]);
  useEffect(() => { load(); }, [load]);

  async function add(event: FormEvent) {
    event.preventDefault();
    setAdding(true);
    try {
      await api<AgentTestCase>(base, { method: "POST", body: JSON.stringify({ question, expectation }) });
      setQuestion(""); setExpectation(""); toast.success(t("agents.quality.added")); load();
    } catch (err) { toast.error(messageFrom(err)); } finally { setAdding(false); }
  }
  async function run(caseId?: string) {
    setRunning(caseId ?? "all");
    try {
      setSuite(await api<AgentTestSuite>(`${base}/run${caseId ? `?case_id=${caseId}` : ""}`, { method: "POST" }));
    } catch (err) { toast.error(messageFrom(err)); } finally { setRunning(null); }
  }
  async function remove(caseId: string) {
    try { await api(`${base}/${caseId}`, { method: "DELETE" }); toast.success(t("agents.quality.deleted")); load(); } catch (err) { toast.error(messageFrom(err)); }
  }

  if (!suite) return <PanelSkeleton rows={4} />;
  const when = (value: string) => new Date(value).toLocaleString(lang, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  return <div className="quality-lab">
    <section className="panel">
      <div className="panel-head"><div><h3>{t("agents.quality.heading")}</h3><p>{t("agents.quality.copy")}</p></div>
        <button type="button" className="button primary" onClick={() => run()} disabled={running !== null || suite.cases.length === 0}>
          {running === "all" ? <><LoaderCircle className="spin" size={16} /> {t("agents.quality.running")}</> : <><Play size={16} /> {t("agents.quality.runAll")}</>}
        </button>
      </div>
      <div className="quality-body">
      {suite.cases.length > 0 && <div className="quality-summary">
        <span className="quality-chip pass"><CheckCircle2 size={14} /> {t("agents.quality.passed", { count: suite.passed })}</span>
        <span className="quality-chip fail"><XCircle size={14} /> {t("agents.quality.failed", { count: suite.failed })}</span>
        <span className="quality-chip"><CircleDashed size={14} /> {t("agents.quality.notRun", { count: suite.not_run })}</span>
      </div>}
      <form className="quality-form" onSubmit={add}>
        <label>{t("agents.quality.question")}<input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder={t("agents.quality.questionPlaceholder")} maxLength={2000} /></label>
        <label>{t("agents.quality.expectation")}<input value={expectation} onChange={(e) => setExpectation(e.target.value)} placeholder={t("agents.quality.expectationPlaceholder")} maxLength={2000} /></label>
        <button type="submit" className="button secondary" disabled={adding || question.trim().length < 2}>{adding ? <LoaderCircle className="spin" size={15} /> : <Plus size={15} />} {t("agents.quality.add")}</button>
      </form>
      <p className="quality-note">{t("agents.quality.note")}</p>
      </div>
    </section>
    {suite.cases.length === 0 ? <div className="inline-empty"><CircleDashed size={22} /><div><strong>{t("agents.quality.empty")}</strong></div></div> :
      <div className="quality-list">{suite.cases.map((item) => {
        const state = item.last_passed === true ? "pass" : item.last_passed === false ? "fail" : "idle";
        return <article key={item.id} className={`quality-case ${state}`}>
          <header>
            <span className={`quality-chip ${state === "idle" ? "" : state}`}>{state === "pass" ? <CheckCircle2 size={14} /> : state === "fail" ? <XCircle size={14} /> : <CircleDashed size={14} />} {t(state === "pass" ? "agents.quality.statusPassed" : state === "fail" ? "agents.quality.statusFailed" : "agents.quality.statusNotRun")}</span>
            {item.last_score != null && <small>{t("agents.quality.score", { score: item.last_score })}</small>}
            <div className="quality-actions">
              <button type="button" className="button ghost" onClick={() => run(item.id)} disabled={running !== null}>{running === item.id ? <LoaderCircle className="spin" size={14} /> : <Play size={14} />} {t("agents.quality.runOne")}</button>
              <button type="button" className="icon-button" onClick={() => remove(item.id)} title={t("agents.quality.remove")} aria-label={t("agents.quality.remove")}><Trash2 size={15} /></button>
            </div>
          </header>
          <strong className="quality-question">{item.question}</strong>
          {item.expectation && <p className="quality-expect">{t("agents.quality.expectation")} {item.expectation}</p>}
          {item.last_answer != null && <div className="quality-answer"><small>{t("agents.quality.answer")}</small><p>{item.last_answer}</p></div>}
          {item.last_reason && <p className="quality-reason">{item.last_reason}</p>}
          {item.last_run_at && <small className="quality-when">{t("agents.quality.lastRun", { when: when(item.last_run_at) })}</small>}
        </article>;
      })}</div>}
  </div>;
}
