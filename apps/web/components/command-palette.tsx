"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { ArrowRight, BarChart3, Bot, Building2, History, Inbox, KeyRound, LayoutDashboard, Plus, Search, Settings, ShieldCheck, Sparkles, Users } from "lucide-react";
import { api } from "@/lib/api";
import { useT, type I18nKey } from "@/lib/i18n";
import { isManager } from "@/lib/current-user";
import type { Agent, Client, User } from "@/types";

type Item = { id: string; label: string; detail?: string; href: string; icon: typeof Search; group: "go" | "create" | "clients" | "agents" };

// Static destinations; `manager` hides the ones operators and viewers cannot open.
const PAGES: { href: string; labelKey: I18nKey; icon: typeof Search; manager?: boolean; group: Item["group"] }[] = [
  { href: "/", labelKey: "nav.home", icon: LayoutDashboard, group: "go" },
  { href: "/inbox", labelKey: "nav.inbox", icon: Inbox, group: "go" },
  { href: "/clients", labelKey: "nav.clients", icon: Building2, group: "go" },
  { href: "/agents", labelKey: "nav.agents", icon: Bot, group: "go" },
  { href: "/reports", labelKey: "nav.reports", icon: BarChart3, group: "go" },
  { href: "/sandbox", labelKey: "nav.sandbox", icon: Sparkles, manager: true, group: "go" },
  { href: "/settings/providers", labelKey: "palette.providers", icon: KeyRound, manager: true, group: "go" },
  { href: "/settings/team", labelKey: "palette.team", icon: Users, group: "go" },
  { href: "/settings/security", labelKey: "palette.security", icon: ShieldCheck, group: "go" },
  { href: "/settings/audit", labelKey: "palette.activity", icon: History, manager: true, group: "go" },
  { href: "/settings", labelKey: "nav.settings", icon: Settings, manager: true, group: "go" },
  { href: "/clients/new", labelKey: "palette.newClient", icon: Plus, manager: true, group: "create" },
  { href: "/agents/new", labelKey: "palette.newAgent", icon: Plus, manager: true, group: "create" },
];

const GROUP_KEYS: Record<Item["group"], I18nKey> = {
  go: "palette.groupGo", create: "palette.groupCreate", clients: "palette.groupClients", agents: "palette.groupAgents",
};

// Lowercase without accents, so "clinica" finds "Clínica".
function fold(value: string) {
  return value.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

// Ctrl+K (Cmd+K on a Mac) opens a search over pages, clients and agents.
export function CommandPalette({ user, open, onOpenChange }: { user: User; open: boolean; onOpenChange: (open: boolean) => void }) {
  const t = useT();
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [clients, setClients] = useState<Client[] | null>(null);
  const [agents, setAgents] = useState<Agent[] | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const manager = isManager(user.role);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        onOpenChange(!open);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  // Fresh lists each time it opens, so a client created a minute ago shows up.
  useEffect(() => {
    if (!open) return;
    setQuery(""); setActive(0);
    api<Client[]>("/clients").then(setClients).catch(() => setClients([]));
    api<Agent[]>("/agents").then(setAgents).catch(() => setAgents([]));
  }, [open]);

  const items = useMemo(() => {
    const pages: Item[] = PAGES.filter((page) => manager || !page.manager)
      .map((page) => ({ id: page.href, label: t(page.labelKey), href: page.href, icon: page.icon, group: page.group }));
    const records: Item[] = [
      ...(clients ?? []).filter((client) => !client.is_sandbox).map((client) => ({ id: `c-${client.id}`, label: client.name, href: `/clients/${client.id}`, icon: Building2, group: "clients" as const })),
      ...(agents ?? []).map((agent) => ({ id: `a-${agent.id}`, label: agent.name, detail: agent.client?.name, href: `/agents/${agent.id}`, icon: Bot, group: "agents" as const })),
    ];
    const needle = fold(query.trim());
    if (!needle) return [...pages, ...records.slice(0, 8)];
    return [...pages, ...records].filter((item) => fold(`${item.label} ${item.detail ?? ""}`).includes(needle)).slice(0, 30);
  }, [agents, clients, manager, query, t]);

  useEffect(() => { setActive(0); }, [query]);
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const go = useCallback((item: Item | undefined) => {
    if (!item) return;
    onOpenChange(false);
    router.push(item.href);
  }, [onOpenChange, router]);

  function onInputKey(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") { event.preventDefault(); setActive((i) => Math.min(items.length - 1, i + 1)); }
    else if (event.key === "ArrowUp") { event.preventDefault(); setActive((i) => Math.max(0, i - 1)); }
    else if (event.key === "Enter") { event.preventDefault(); go(items[active]); }
    else if (event.key === "Escape") { event.preventDefault(); onOpenChange(false); }
  }

  if (!open || typeof document === "undefined") return null;
  let lastGroup: Item["group"] | null = null;
  return createPortal(
    <div className="modal-backdrop palette-backdrop" onMouseDown={() => onOpenChange(false)}>
      <section className="palette" role="dialog" aria-modal="true" aria-label={t("palette.title")} onMouseDown={(event) => event.stopPropagation()}>
        <label className="palette-search"><Search size={17} />
          <input autoFocus value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={onInputKey} placeholder={t("palette.placeholder")}
            role="combobox" aria-expanded="true" aria-controls="palette-list" aria-activedescendant={items[active] ? `palette-${items[active].id}` : undefined} />
          <kbd>Esc</kbd>
        </label>
        <div className="palette-list" id="palette-list" role="listbox" ref={listRef}>
          {items.length === 0 && <p className="palette-empty">{t("palette.empty")}</p>}
          {items.map((item, index) => {
            const heading = item.group !== lastGroup ? <div className="palette-group" key={`g-${item.group}`}>{t(GROUP_KEYS[item.group])}</div> : null;
            lastGroup = item.group;
            const Icon = item.icon;
            return [heading, <button type="button" key={item.id} id={`palette-${item.id}`} data-index={index} role="option" aria-selected={index === active}
              className={index === active ? "palette-item active" : "palette-item"} onMouseMove={() => setActive(index)} onClick={() => go(item)}>
              <Icon size={16} /><span>{item.label}</span>{item.detail && <small>{item.detail}</small>}<ArrowRight size={14} className="palette-enter" />
            </button>];
          })}
        </div>
        <footer className="palette-foot"><span><kbd>↑</kbd><kbd>↓</kbd> {t("palette.move")}</span><span><kbd>Enter</kbd> {t("palette.open")}</span></footer>
      </section>
    </div>,
    document.body,
  );
}
