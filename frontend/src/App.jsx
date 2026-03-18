import { useState, useEffect, useCallback, useRef } from "react";
import * as d3 from "d3";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

const CATEGORIES = ["all", "tool", "agent", "mcp", "list", "workflow", "cve", "article", "video", "playlist", "blog"];

const CAT_META = {
  tool:     { label: "Tool",     color: "text-accent-green  border-accent-green/40  bg-accent-green/10",  desc: "Exploit / scanner / framework / PoC" },
  agent:    { label: "Agent",    color: "text-accent-blue   border-accent-blue/40   bg-accent-blue/10",   desc: "Claude Code / AI agent resource" },
  mcp:      { label: "MCP",      color: "text-cyan-400      border-cyan-400/40      bg-cyan-400/10",      desc: "Model Context Protocol server/client" },
  list:     { label: "List",     color: "text-orange-400    border-orange-400/40    bg-orange-400/10",    desc: "Blog / article listing page" },
  workflow: { label: "Workflow", color: "text-accent-purple border-accent-purple/40 bg-accent-purple/10", desc: "Process / checklist / pipeline" },
  cve:      { label: "CVE",      color: "text-accent-red    border-accent-red/40    bg-accent-red/10",    desc: "Vulnerability advisory / bug report" },
  article:  { label: "Article",  color: "text-accent-yellow border-accent-yellow/40 bg-accent-yellow/10", desc: "Blog post / research / writeup" },
  video:    { label: "Video",    color: "text-rose-400      border-rose-400/40      bg-rose-400/10",      desc: "YouTube video / talk / walkthrough" },
  playlist: { label: "Playlist", color: "text-violet-400    border-violet-400/40    bg-violet-400/10",    desc: "YouTube playlist" },
  blog:     { label: "Blog",     color: "text-cyan-400      border-cyan-400/40      bg-cyan-400/10",      desc: "Blog / article listing page" },
  // legacy
  skill:    { label: "Agent",    color: "text-accent-blue   border-accent-blue/40   bg-accent-blue/10",   desc: "Claude Code / AI agent resource" },
};

const CAT_HEX = {
  tool: "#3fb950", agent: "#58a6ff", skill: "#58a6ff",
  mcp: "#22d3ee", list: "#fb923c",
  workflow: "#bc8cff", cve: "#f85149", article: "#d29922", video: "#fb7185", playlist: "#a78bfa", blog: "#22d3ee",
};

// ─── shared ───────────────────────────────────────────────────────────────────

function Spinner({ sm }) {
  return (
    <svg className={`animate-spin ${sm ? "h-3 w-3" : "h-4 w-4"} text-accent-green flex-shrink-0`}
      xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  );
}

function Badge({ category, customCats = [] }) {
  const m = CAT_META[category];
  if (m) {
    return (
      <span className={`inline-flex items-center px-2 py-0.5 rounded border text-xs font-bold uppercase tracking-wider flex-shrink-0 ${m.color}`}>
        {m.label}
      </span>
    );
  }
  const custom = customCats.find(c => c.slug === category);
  const color  = custom?.color || "#94a3b8";
  const label  = custom?.label || category;
  return (
    <span style={{ color, borderColor: color + "66", backgroundColor: color + "1a" }}
      className="inline-flex items-center px-2 py-0.5 rounded border text-xs font-bold uppercase tracking-wider flex-shrink-0">
      {label}
    </span>
  );
}

// ─── category picker dropdown ─────────────────────────────────────────────────

const PICKABLE_CATS = ["tool", "agent", "mcp", "list", "workflow", "cve", "article", "video"];

function CatPicker({ current, onPick, onClose, anchorRef, customCats = [] }) {
  const ref = useRef(null);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  useEffect(() => {
    if (anchorRef?.current) {
      const r = anchorRef.current.getBoundingClientRect();
      setPos({ top: r.bottom + 4, left: r.left });
    }
    function h(e) { if (ref.current && !ref.current.contains(e.target)) onClose(); }
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [onClose]);

  return (
    <div ref={ref}
      style={{ position: "fixed", top: pos.top, left: pos.left, zIndex: 9999 }}
      className="bg-surface-1 border border-border rounded shadow-xl py-1 w-40">
      {PICKABLE_CATS.map(cat => {
        const m = CAT_META[cat];
        return (
          <button key={cat} onClick={() => onPick(cat)}
            className="w-full text-left px-3 py-2 text-xs flex items-center gap-2 hover:bg-surface-2 transition-colors">
            <span className={`inline-flex px-1.5 py-0.5 rounded border text-xs font-bold uppercase tracking-wider flex-shrink-0 ${m.color}`}>
              {m.label}
            </span>
            {current === cat && <span className="text-gray-500 ml-auto">✓</span>}
          </button>
        );
      })}
      {customCats.map(c => (
        <button key={c.slug} onClick={() => onPick(c.slug)}
          className="w-full text-left px-3 py-2 text-xs flex items-center gap-2 hover:bg-surface-2 transition-colors">
          <span style={{ color: c.color, borderColor: c.color + "66", backgroundColor: c.color + "1a" }}
            className="inline-flex px-1.5 py-0.5 rounded border text-xs font-bold uppercase tracking-wider flex-shrink-0">
            {c.label}
          </span>
          {current === c.slug && <span className="text-gray-500 ml-auto">✓</span>}
        </button>
      ))}
    </div>
  );
}

// ─── list menu (dropdown to add/remove entry from lists) ─────────────────────

function ListMenu({ entry, lists, onAdd, onRemove, onClose }) {
  const [newName, setNewName] = useState("");
  const ref = useRef(null);

  useEffect(() => {
    function handleClick(e) {
      if (ref.current && !ref.current.contains(e.target)) onClose();
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [onClose]);

  return (
    <div ref={ref}
      className="absolute right-0 top-full mt-1 z-50 w-52 bg-surface-1 border border-border rounded shadow-lg py-1">
      {lists.length === 0 && (
        <p className="px-3 py-2 text-xs text-gray-600">No lists yet</p>
      )}
      {lists.map(l => {
        const inList = entry.list_ids?.includes(l.id);
        return (
          <button key={l.id}
            onClick={() => inList ? onRemove(l.id, entry.id) : onAdd(l.id, entry.id)}
            className="w-full text-left flex items-center justify-between px-3 py-2 text-xs hover:bg-surface-2 transition-colors">
            <span className={inList ? "text-accent-green" : "text-gray-400"}>{l.name}</span>
            <span className={inList ? "text-accent-green" : "text-gray-700"}>{inList ? "✓" : "+"}</span>
          </button>
        );
      })}
      <div className="border-t border-border mt-1 pt-1 px-2 pb-1">
        <form onSubmit={e => { e.preventDefault(); if (newName.trim()) { onAdd("new", entry.id, newName.trim()); setNewName(""); } }}
          className="flex gap-1">
          <input value={newName} onChange={e => setNewName(e.target.value)}
            placeholder="New list…"
            className="flex-1 bg-surface-2 border border-border rounded px-2 py-1 text-xs text-gray-300 outline-none focus:border-accent-green/50" />
          <button type="submit"
            className="px-2 py-1 text-xs text-accent-green border border-accent-green/40 rounded hover:bg-accent-green/10 transition-colors">
            +
          </button>
        </form>
      </div>
    </div>
  );
}

// ─── entry card ───────────────────────────────────────────────────────────────

function EntryCard({ entry, onToggleRead, onDelete, onTagClick, lists, onAddToList, onRemoveFromList, onUpdate, selected, onSelect, customCats = [] }) {
  const [deleting, setDeleting]       = useState(false);
  const [toggling, setToggling]       = useState(false);
  const [showLists, setShowLists]     = useState(false);
  const [showCatPick, setShowCatPick] = useState(false);
  const catBtnRef = useRef(null);

  const host = (() => {
    try { return new URL(entry.url).hostname.replace("www.", ""); }
    catch { return entry.url; }
  })();

  async function handleAddToList(listId, entryId, newListName) {
    if (listId === "new") {
      const res  = await fetch(`${API}/lists`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: newListName }) });
      const list = await res.json();
      await fetch(`${API}/lists/${list.id}/entries`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ entry_id: entryId }) });
      onAddToList(list, entryId);
    } else {
      await fetch(`${API}/lists/${listId}/entries`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ entry_id: entryId }) });
      onAddToList({ id: listId }, entryId);
    }
    setShowLists(false);
  }

  async function handleRemoveFromList(listId, entryId) {
    await fetch(`${API}/lists/${listId}/entries/${entryId}`, { method: "DELETE" });
    onRemoveFromList(listId, entryId);
    setShowLists(false);
  }

  async function handleToggleUseful() {
    const res     = await fetch(`${API}/entries/${entry.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ useful: !entry.useful }),
    });
    const updated = await res.json();
    onUpdate?.(updated);
  }

  return (
    <div className="rounded-lg border bg-surface-1 overflow-hidden"
      style={{ borderColor: selected ? "#3fb950" : "#30363d" }}>
      {/* header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-surface-2">
        <div className="flex items-center gap-2 min-w-0">
          {onSelect && (
            <input type="checkbox" checked={!!selected} onChange={() => onSelect(entry.id)}
              onClick={e => e.stopPropagation()}
              className="w-3.5 h-3.5 flex-shrink-0 accent-accent-green cursor-pointer" />
          )}
          <div className="flex-shrink-0">
            <button ref={catBtnRef} onClick={() => setShowCatPick(s => !s)}
              className="flex items-center gap-1 group" title="Change category">
              <Badge category={entry.category} customCats={customCats} />
              <span className="text-gray-700 opacity-0 group-hover:opacity-100 text-xs transition-opacity leading-none">✎</span>
            </button>
            {showCatPick && (
              <CatPicker current={entry.category} anchorRef={catBtnRef} customCats={customCats}
                onPick={async cat => {
                  setShowCatPick(false);
                  onUpdate?.({ ...entry, category: cat }); // optimistic
                  const res = await fetch(`${API}/entries/${entry.id}`, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ category: cat }),
                  });
                  if (res.ok) {
                    const updated = await res.json();
                    onUpdate?.(updated);
                  } else {
                    onUpdate?.({ ...entry }); // revert on failure
                  }
                }}
                onClose={() => setShowCatPick(false)} />
            )}
          </div>
          {entry.name && <span className="text-sm font-semibold text-gray-200 truncate">{entry.name}</span>}
          {entry.source === "rss" && (
            <span className="flex-shrink-0 px-1.5 py-0.5 rounded border border-orange-400/40 bg-orange-400/10 text-orange-400 text-xs font-bold uppercase tracking-wider">RSS</span>
          )}
          <a href={entry.url} target="_blank" rel="noreferrer"
            className="text-xs text-gray-600 hover:text-accent-blue truncate transition-colors font-mono hidden sm:block"
            title={entry.url}>{host}</a>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0 ml-2">
          <span className="text-xs text-gray-700">{new Date(entry.created_at).toLocaleDateString()}</span>

          {/* lists button */}
          <div className="relative">
            <button onClick={() => setShowLists(s => !s)}
              className={`text-xs transition-colors ${entry.list_ids?.length ? "text-accent-purple" : "text-gray-700 hover:text-gray-400"}`}
              title="Add to list">
              {entry.list_ids?.length ? `📋 ${entry.list_ids.length}` : "📋"}
            </button>
            {showLists && (
              <ListMenu entry={entry} lists={lists}
                onAdd={handleAddToList} onRemove={handleRemoveFromList}
                onClose={() => setShowLists(false)} />
            )}
          </div>

          <button onClick={handleToggleUseful}
            className={`text-sm transition-colors ${entry.useful ? "text-yellow-400" : "text-gray-700 hover:text-yellow-400"}`}
            title={entry.useful ? "Useful ★" : "Mark useful"}>
            {entry.useful ? "★" : "☆"}
          </button>
          <button onClick={async () => { setToggling(true); await onToggleRead(entry.id); setToggling(false); }}
            disabled={toggling}
            className={`text-xs transition-colors ${entry.read ? "text-accent-green" : "text-gray-600 hover:text-accent-green/70"}`}>
            {toggling ? <Spinner sm /> : entry.read ? "✓ read" : "○ unread"}
          </button>
          <button onClick={async () => { setDeleting(true); await onDelete(entry.id); }}
            disabled={deleting}
            className="text-xs text-gray-700 hover:text-accent-red transition-colors">
            {deleting ? <Spinner sm /> : "✕"}
          </button>
        </div>
      </div>

      {/* list labels */}
      {entry.list_ids?.length > 0 && lists.length > 0 && (
        <div className="px-4 pt-2 flex flex-wrap gap-1">
          {entry.list_ids.map(lid => {
            const l = lists.find(x => x.id === lid);
            return l ? (
              <span key={lid} className="text-xs px-1.5 py-0.5 rounded bg-accent-purple/10 border border-accent-purple/30 text-accent-purple/80 font-mono">
                {l.name}
              </span>
            ) : null;
          })}
        </div>
      )}

      {/* bullets */}
      <ul className="px-5 pt-3 space-y-1.5">
        {entry.bullets.map((b, i) => (
          <li key={i} className="flex items-start gap-2 text-sm text-gray-400">
            <span className="text-accent-green/50 flex-shrink-0 mt-0.5 text-xs">▸</span>
            <span>{b}</span>
          </li>
        ))}
      </ul>
      {/* tags */}
      {entry.tags?.length > 0 && (
        <div className="flex flex-wrap gap-1 px-5 pt-2 pb-3">
          {entry.tags.map(tag => (
            <button key={tag} onClick={() => onTagClick?.(tag)}
              className="text-xs px-2 py-0.5 rounded border border-border bg-surface-2 text-gray-500
                         hover:border-accent-blue/50 hover:text-accent-blue transition-colors font-mono">
              #{tag}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── bulk action bar ──────────────────────────────────────────────────────────

function BulkBar({ count, lists, onAddToList, onMarkRead, onMarkUseful, onClear }) {
  const [showPick, setShowPick] = useState(false);
  const [newName, setNewName]   = useState("");
  const ref = useRef(null);

  useEffect(() => {
    function h(e) { if (ref.current && !ref.current.contains(e.target)) setShowPick(false); }
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  return (
    <div className="sticky top-0 z-20 mb-4 px-4 py-2.5 bg-surface-1 border border-accent-green/40 rounded-lg flex items-center gap-2 flex-wrap shadow-lg">
      <span className="text-xs font-bold text-accent-green font-mono mr-1">{count} selected</span>

      <div ref={ref} className="relative">
        <button onClick={() => setShowPick(s => !s)}
          className="px-3 py-1.5 text-xs rounded border border-border text-gray-400 hover:text-gray-200 hover:border-gray-500 transition-colors flex items-center gap-1">
          📋 Add to list <span className="text-gray-600">▾</span>
        </button>
        {showPick && (
          <div className="absolute left-0 top-full mt-1 z-50 w-52 bg-surface-1 border border-border rounded shadow-xl py-1">
            {lists.length === 0 && <p className="px-3 py-2 text-xs text-gray-600">No lists yet</p>}
            {lists.map(l => (
              <button key={l.id}
                onClick={() => { onAddToList(l.id); setShowPick(false); }}
                className="w-full text-left px-3 py-2 text-xs text-gray-400 hover:bg-surface-2 hover:text-gray-200 transition-colors">
                {l.name}
              </button>
            ))}
            <div className="border-t border-border mt-1 pt-1 px-2 pb-1">
              <form onSubmit={e => { e.preventDefault(); if (newName.trim()) { onAddToList("new", newName.trim()); setNewName(""); setShowPick(false); } }}
                className="flex gap-1">
                <input value={newName} onChange={e => setNewName(e.target.value)}
                  placeholder="New list…"
                  className="flex-1 bg-surface-2 border border-border rounded px-2 py-1 text-xs text-gray-300 outline-none focus:border-accent-green/50" />
                <button type="submit"
                  className="px-2 py-1 text-xs text-accent-green border border-accent-green/40 rounded hover:bg-accent-green/10">+</button>
              </form>
            </div>
          </div>
        )}
      </div>

      <button onClick={onMarkRead}
        className="px-3 py-1.5 text-xs rounded border border-border text-gray-400 hover:text-accent-green hover:border-accent-green/40 transition-colors">
        ✓ Mark read
      </button>
      <button onClick={onMarkUseful}
        className="px-3 py-1.5 text-xs rounded border border-border text-gray-400 hover:text-yellow-400 hover:border-yellow-400/40 transition-colors">
        ★ Mark useful
      </button>
      <button onClick={onClear}
        className="px-3 py-1.5 text-xs rounded border border-border text-gray-600 hover:text-gray-400 transition-colors ml-auto">
        ✕ Clear
      </button>
    </div>
  );
}

// ─── progress items (analyze tab) ─────────────────────────────────────────────

function LogLines({ logs }) {
  return (
    <div className="px-4 pb-3 space-y-0.5">
      {logs.map((msg, i) => (
        <div key={i} className="flex items-start gap-2 text-xs text-gray-600 font-mono">
          <span className="text-accent-green/40 flex-shrink-0">›</span>
          <span>{msg}</span>
        </div>
      ))}
    </div>
  );
}

// ─── video child item (used inside playlist card) ────────────────────────────

function VideoChildItem({ child, index, onTagClick, onRetried }) {
  const [retrying, setRetrying] = useState(false);
  const [error, setError]       = useState("");
  const failed = child.tags?.includes("summary-failed");

  async function handleRetry() {
    setRetrying(true);
    setError("");
    try {
      const res  = await fetch(`${API}/entries/${child.id}/retry-summary`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Retry failed");
      onRetried(data);
    } catch (e) { setError(e.message); }
    finally { setRetrying(false); }
  }

  return (
    <div className={`px-4 py-3 transition-colors ${failed ? "bg-accent-red/5" : "bg-surface-1 hover:bg-surface-2"}`}>
      <div className="flex items-start gap-2 mb-1">
        <span className="text-xs text-gray-600 flex-shrink-0 mt-0.5 font-mono">{index + 1}.</span>
        <a href={child.url} target="_blank" rel="noopener noreferrer"
          className="text-xs text-violet-400 hover:text-violet-300 hover:underline font-medium flex-1">
          {child.name}
        </a>
        {failed && (
          <button onClick={handleRetry} disabled={retrying}
            className="text-xs text-accent-red hover:text-red-400 border border-accent-red/40 rounded px-1.5 py-0.5 transition-colors flex items-center gap-1 flex-shrink-0">
            {retrying ? <><Spinner sm /> retrying…</> : "↺ Retry"}
          </button>
        )}
      </div>
      {failed ? (
        <p className="ml-4 text-xs text-gray-600 italic">
          Summary failed.{error && <span className="text-accent-red ml-1">{error}</span>}
        </p>
      ) : (
        <>
          <ul className="ml-4 space-y-0.5">
            {child.bullets.map((b, j) => (
              <li key={j} className="text-xs text-gray-500 flex gap-2">
                <span className="text-gray-700 flex-shrink-0">—</span>{b}
              </li>
            ))}
          </ul>
          {child.tags?.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1.5 ml-4">
              {child.tags.map(t => (
                <button key={t} onClick={() => onTagClick?.(t)}
                  className="text-xs text-gray-700 hover:text-gray-500 transition-colors"># {t}</button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ─── playlist card ────────────────────────────────────────────────────────────

function PlaylistCard({ entry, onTagClick, customCats = [], onDelete }) {
  const [open, setOpen]               = useState(false);
  const [children, setChildren]       = useState(entry.children || []);
  const [loadingKids, setLoadingKids] = useState(false);
  const [deleting, setDeleting]       = useState(false);

  const isBlog      = entry.category === "blog";
  const isList      = entry.category === "list" || isBlog;
  const borderColor = isBlog ? "#22d3ee66" : isList ? "#fb923c66" : "#a78bfa66";
  const divColor    = isBlog ? "#22d3ee33" : isList ? "#fb923c33" : "#a78bfa33";
  const childDivColor = isBlog ? "#22d3ee22" : isList ? "#fb923c22" : "#a78bfa22";
  const childLabel  = isList ? "articles" : "videos";
  const typeLabel   = isBlog ? "blog" : isList ? "listing" : "playlist";

  async function handleDelete(e) {
    e.stopPropagation();
    if (!confirm(`Delete ${typeLabel} "${entry.name}" and all its ${childLabel}?`)) return;
    setDeleting(true);
    await fetch(`${API}/entries/${entry.id}`, { method: "DELETE" });
    onDelete?.(entry.id);
  }

  async function handleToggle() {
    if (!open && children.length === 0) {
      setLoadingKids(true);
      try {
        const res  = await fetch(`${API}/entries/${entry.id}/children`);
        const data = await res.json();
        setChildren(data);
      } catch (e) { console.error(e); }
      finally { setLoadingKids(false); }
    }
    setOpen(o => !o);
  }

  return (
    <div className="rounded-lg border overflow-hidden" style={{ borderColor }}>
      {/* header */}
      <div className="flex items-center gap-3 px-4 py-2.5 bg-surface-2 border-b cursor-pointer select-none"
        style={{ borderColor: divColor }} onClick={handleToggle}>
        <Badge category={entry.category} customCats={customCats} />
        <span className="text-sm font-medium text-gray-200 flex-1 truncate">{entry.name}</span>
        <span className="text-xs text-gray-600">{children.length || (entry.children?.length ?? "?")} {childLabel}</span>
        <span className="text-gray-600 text-xs ml-1">{open ? "▲" : "▼"}</span>
        <button onClick={handleDelete} disabled={deleting}
          className="ml-1 text-gray-700 hover:text-accent-red transition-colors text-xs leading-none"
          title={`Delete ${typeLabel}`}>✕</button>
      </div>

      {/* playlist summary bullets */}
      <div className="px-4 py-3 bg-surface-1">
        <ul className="space-y-1">
          {entry.bullets.map((b, i) => (
            <li key={i} className="text-xs text-gray-400 flex gap-2">
              <span className="text-gray-600 flex-shrink-0">—</span>{b}
            </li>
          ))}
        </ul>
        {entry.tags?.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-2">
            {entry.tags.map(t => (
              <button key={t} onClick={() => onTagClick?.(t)}
                className="text-xs text-gray-600 hover:text-gray-400 transition-colors"># {t}</button>
            ))}
          </div>
        )}
      </div>

      {/* children */}
      {open && (
        <div className="border-t divide-y" style={{ borderColor: childDivColor }}>
          {loadingKids && (
            <div className="px-4 py-3 text-xs text-gray-600 flex items-center gap-2">
              <Spinner sm /> Loading {childLabel}…
            </div>
          )}
          {children.map((child, i) => (
            <VideoChildItem key={child.id} child={child} index={i}
              onTagClick={onTagClick}
              onRetried={updated => setChildren(prev => prev.map(c => c.id === updated.id ? updated : c))} />
          ))}
        </div>
      )}
    </div>
  );
}

function ProgressItem({ item, lists, onAddToList, onRemoveFromList, onUpdate, customCats = [] }) {
  const [logsOpen, setLogsOpen] = useState(true);

  if (item.status === "ok") {
    const card = ["playlist", "list", "blog"].includes(item.entry?.category)
      ? <PlaylistCard entry={item.entry} customCats={customCats} />
      : <EntryCard entry={item.entry} onToggleRead={() => {}} onDelete={() => {}}
          lists={lists} onAddToList={onAddToList} onRemoveFromList={onRemoveFromList} onUpdate={onUpdate} customCats={customCats} />;
    return (
      <div>
        {card}
        {item.logs.length > 0 && (
          <div className="mt-1">
            <button onClick={() => setLogsOpen(o => !o)}
              className="text-xs text-gray-700 hover:text-gray-500 transition-colors px-1">
              {logsOpen ? "▾ hide logs" : "▸ show logs"}
            </button>
            {logsOpen && <LogLines logs={item.logs} />}
          </div>
        )}
      </div>
    );
  }
  if (item.status === "error") {
    return (
      <div className="rounded border border-accent-red/30 bg-accent-red/5 overflow-hidden">
        <div className="flex items-start gap-2 px-4 py-3 text-xs text-accent-red">
          <span className="flex-shrink-0">✗</span>
          <div className="min-w-0">
            <div className="font-mono truncate">{item.url}</div>
            <div className="text-accent-red/70 mt-0.5">{item.error}</div>
          </div>
        </div>
        {item.logs.length > 0 && <LogLines logs={item.logs} />}
      </div>
    );
  }
  return (
    <div className="rounded border border-border bg-surface-1 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 text-xs text-gray-600">
        <Spinner sm /><span className="font-mono truncate flex-1">{item.url}</span>
      </div>
      {item.logs.length > 0 && <LogLines logs={item.logs} />}
    </div>
  );
}

// ─── suggest card ─────────────────────────────────────────────────────────────

function SuggestCard({ onTagClick, lists, onAddToList, onRemoveFromList, onUpdate, customCats = [] }) {
  const [entry, setEntry]     = useState(null);
  const [loading, setLoading] = useState(true);

  async function fetchSuggest(excludeId) {
    setLoading(true);
    try {
      const params = excludeId ? `?exclude=${excludeId}` : "";
      const res    = await fetch(`${API}/suggest${params}`);
      const data   = await res.json();
      setEntry(data);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }

  useEffect(() => { fetchSuggest(); }, []);

  async function handleMarkRead() {
    if (!entry) return;
    await fetch(`${API}/entries/${entry.id}/read`, { method: "PATCH" });
    fetchSuggest(entry.id);
  }

  if (loading) return null;
  if (!entry)  return null;

  return (
    <div className="mb-6 rounded-lg border border-accent-blue/30 bg-accent-blue/5 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-accent-blue/20">
        <span className="text-xs text-accent-blue font-bold uppercase tracking-widest">📌 Suggested Read</span>
        <div className="flex items-center gap-2">
          <button onClick={handleMarkRead}
            className="text-xs text-accent-green hover:text-accent-green/70 transition-colors">✓ mark read</button>
          <button onClick={() => fetchSuggest(entry.id)}
            className="text-xs text-gray-600 hover:text-gray-400 transition-colors">skip →</button>
        </div>
      </div>
      <EntryCard entry={entry}
        onToggleRead={async (id) => { await fetch(`${API}/entries/${id}/read`, { method: "PATCH" }); fetchSuggest(id); }}
        onDelete={() => fetchSuggest(entry.id)}
        onTagClick={onTagClick}
        lists={lists} onAddToList={onAddToList} onRemoveFromList={onRemoveFromList}
        onUpdate={updated => { setEntry(e => ({ ...e, ...updated })); onUpdate?.(updated); }}
        customCats={customCats} />
      {entry.preview && (
        <div className="px-5 pb-4">
          <p className="text-xs text-gray-600 font-mono leading-relaxed border-l-2 border-border pl-3 mt-2">
            {entry.preview}…
          </p>
        </div>
      )}
    </div>
  );
}

// ─── RSS tab ──────────────────────────────────────────────────────────────────

function RssTab() {
  const [feeds, setFeeds]       = useState([]);
  const [loading, setLoading]   = useState(true);
  const [url, setUrl]           = useState("");
  const [name, setName]         = useState("");
  const [adding, setAdding]     = useState(false);
  const [error, setError]       = useState("");
  const [polling, setPolling]   = useState({}); // { feedId: true }
  const [pollResult, setPollResult] = useState({}); // { feedId: N }

  async function fetchFeeds() {
    try {
      const data = await (await fetch(`${API}/rss-feeds`)).json();
      setFeeds(Array.isArray(data) ? data : []);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }

  useEffect(() => { fetchFeeds(); }, []);

  async function handleAdd(e) {
    e.preventDefault();
    setError("");
    if (!url.trim()) return;
    setAdding(true);
    try {
      const res  = await fetch(`${API}/rss-feeds`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim(), name: name.trim() }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.error || "Failed to add feed"); return; }
      setFeeds(prev => [data, ...prev]);
      setUrl(""); setName("");
    } catch (e) { setError("Network error"); }
    finally { setAdding(false); }
  }

  async function handleDelete(id) {
    await fetch(`${API}/rss-feeds/${id}`, { method: "DELETE" });
    setFeeds(prev => prev.filter(f => f.id !== id));
  }

  async function handlePoll(id) {
    setPolling(prev => ({ ...prev, [id]: true }));
    setPollResult(prev => ({ ...prev, [id]: null }));
    try {
      const res  = await fetch(`${API}/rss-feeds/${id}/poll`, { method: "POST" });
      const data = await res.json();
      setPollResult(prev => ({ ...prev, [id]: data.added }));
      fetchFeeds();
    } catch (e) { setPollResult(prev => ({ ...prev, [id]: -1 })); }
    finally { setPolling(prev => ({ ...prev, [id]: false })); }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="text-sm font-bold text-gray-300 uppercase tracking-widest mb-1">RSS Feeds</h2>
        <p className="text-xs text-gray-600">Add RSS/Atom feeds — the server checks for new posts every hour and adds them to the Knowledge Base automatically. RSS entries are KB-only and won't appear in Suggested Read.</p>
      </div>

      {/* Add feed form */}
      <form onSubmit={handleAdd} className="flex flex-col gap-2">
        <div className="flex gap-2">
          <input value={url} onChange={e => setUrl(e.target.value)}
            placeholder="Feed URL (https://...)"
            className="flex-1 bg-surface-1 border border-border rounded px-3 py-2 text-xs text-gray-200 placeholder-gray-700 font-mono outline-none focus:border-accent-green/50" />
          <input value={name} onChange={e => setName(e.target.value)}
            placeholder="Name (optional)"
            className="w-40 bg-surface-1 border border-border rounded px-3 py-2 text-xs text-gray-200 placeholder-gray-700 font-mono outline-none focus:border-accent-green/50" />
          <button type="submit" disabled={adding || !url.trim()}
            className="px-4 py-2 rounded border border-accent-green/40 text-accent-green text-xs font-bold hover:bg-accent-green/10 transition-colors disabled:opacity-40">
            {adding ? <Spinner sm /> : "+ Add"}
          </button>
        </div>
        {error && <p className="text-xs text-accent-red">{error}</p>}
      </form>

      {/* Feed list */}
      {loading ? (
        <div className="flex items-center gap-2 text-sm text-gray-700"><Spinner /><span>Loading…</span></div>
      ) : feeds.length === 0 ? (
        <div className="text-xs text-gray-700 mt-4">No feeds yet. Add one above.</div>
      ) : (
        <div className="space-y-2">
          {feeds.map(feed => (
            <div key={feed.id} className="flex items-center justify-between gap-3 px-4 py-3 rounded border border-border bg-surface-1">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-gray-200 truncate">{feed.name || feed.url}</span>
                  <span className="flex-shrink-0 px-1.5 py-0.5 rounded border border-orange-400/40 bg-orange-400/10 text-orange-400 text-xs font-bold">RSS</span>
                </div>
                {feed.name && <p className="text-xs text-gray-600 font-mono truncate mt-0.5">{feed.url}</p>}
                <p className="text-xs text-gray-700 mt-0.5">
                  {feed.last_checked
                    ? `Last checked: ${new Date(feed.last_checked).toLocaleString()}`
                    : "Not yet checked"}
                  {" · "}{feed.entry_count ?? 0} RSS entries in KB
                </p>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                {pollResult[feed.id] != null && (
                  <span className={`text-xs ${pollResult[feed.id] < 0 ? "text-accent-red" : "text-accent-green"}`}>
                    {pollResult[feed.id] < 0 ? "Error" : `+${pollResult[feed.id]} new`}
                  </span>
                )}
                <button onClick={() => handlePoll(feed.id)} disabled={polling[feed.id]}
                  className="px-2 py-1 rounded border border-border text-xs text-gray-500 hover:text-accent-blue hover:border-accent-blue/40 transition-colors disabled:opacity-40 flex items-center gap-1">
                  {polling[feed.id] ? <><Spinner sm />Polling…</> : "↻ Poll now"}
                </button>
                <button onClick={() => handleDelete(feed.id)}
                  className="text-xs text-gray-700 hover:text-accent-red transition-colors">✕</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── knowledge graph tab ──────────────────────────────────────────────────────

function GraphTab() {
  const canvasRef              = useRef(null);
  const zoomRef                = useRef(null);
  const selectedRef            = useRef(null); // { nodeId, connectedIds: Set }
  const [entries, setEntries]  = useState([]);
  const [tooltip, setTooltip]  = useState(null);
  const [selected, setSelected] = useState(null); // entry object for info panel
  const [nodeCount, setNodeCount] = useState({ entries: 0, tags: 0 });
  const [tagSearch, setTagSearch] = useState("");

  useEffect(() => {
    fetch(`${API}/entries`)
      .then(r => r.json())
      .then(setEntries)
      .catch(console.error);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!entries.length || !canvas) return;

    const ctx = canvas.getContext("2d");
    const W   = canvas.clientWidth  || 900;
    const H   = canvas.clientHeight || 600;
    canvas.width  = W;
    canvas.height = H;

    // Filter entries/tags by tagSearch
    let filteredEntries = entries;
    if (tagSearch.trim()) {
      const tag = tagSearch.trim().toLowerCase();
      filteredEntries = entries.filter(e => e.tags?.some(t => t.toLowerCase().includes(tag)));
    }

    // Build nodes
    const entryNodes = filteredEntries.map(e => ({
      id:    `e-${e.id}`,
      kind:  "entry",
      entry: e,
      r:     9,
      x:     W / 2 + (Math.random() - 0.5) * 200,
      y:     H / 2 + (Math.random() - 0.5) * 200,
    }));

    const tagCount = {};
    filteredEntries.forEach(e => e.tags?.forEach(t => { tagCount[t] = (tagCount[t] || 0) + 1; }));

    const tagNodes = Object.keys(tagCount).map(t => ({
      id:    `t-${t}`,
      kind:  "tag",
      name:  t,
      count: tagCount[t],
      r:     Math.min(5 + tagCount[t] * 1.5, 14),
      x:     W / 2 + (Math.random() - 0.5) * 300,
      y:     H / 2 + (Math.random() - 0.5) * 300,
    }));

    setNodeCount({ entries: entryNodes.length, tags: tagNodes.length });

    const nodes = [...entryNodes, ...tagNodes];
    const links = [];
    filteredEntries.forEach(e => {
      e.tags?.forEach(t => {
        if (tagCount[t]) links.push({ source: `e-${e.id}`, target: `t-${t}` });
      });
    });

    // D3 force simulation
    const sim = d3.forceSimulation(nodes)
      .force("link",    d3.forceLink(links).id(n => n.id).distance(60).strength(0.4))
      .force("charge",  d3.forceManyBody().strength(-80))
      .force("center",  d3.forceCenter(W / 2, H / 2))
      .force("collide", d3.forceCollide(n => n.r + 4));

    let transform = d3.zoomIdentity;

    function draw() {
      const sel = selectedRef.current;
      ctx.save();
      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = "#0d1117";
      ctx.fillRect(0, 0, W, H);
      ctx.translate(transform.x, transform.y);
      ctx.scale(transform.k, transform.k);

      // Links
      links.forEach(l => {
        if (!l.source?.x || !l.target?.x) return;
        const isHighlit = sel && (l.source.id === sel.nodeId || l.target.id === sel.nodeId);
        ctx.globalAlpha = sel ? (isHighlit ? 0.8 : 0.07) : 0.3;
        ctx.strokeStyle = isHighlit ? "#58a6ff" : "#30363d";
        ctx.lineWidth   = isHighlit ? 1.2 : 0.8;
        ctx.beginPath();
        ctx.moveTo(l.source.x, l.source.y);
        ctx.lineTo(l.target.x, l.target.y);
        ctx.stroke();
      });
      ctx.globalAlpha = 1;

      // Tag nodes
      tagNodes.forEach(n => {
        const isConnected = sel?.connectedIds.has(n.id);
        ctx.globalAlpha = sel ? (isConnected ? 1 : 0.15) : 1;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, 2 * Math.PI);
        ctx.fillStyle   = isConnected ? "#1c2d3a" : "#21262d";
        ctx.strokeStyle = isConnected ? "#58a6ff" : "#30363d";
        ctx.lineWidth   = isConnected ? 1.5 : 1;
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle    = isConnected ? "#93c5fd" : "#6e7681";
        ctx.font         = `${Math.max(9, Math.min(n.r, 11))}px monospace`;
        ctx.textAlign    = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(`#${n.name}`, n.x, n.y + n.r + 9);
      });

      // Entry nodes
      entryNodes.forEach(n => {
        const isSelected  = sel?.nodeId === n.id;
        const isConnected = sel?.connectedIds.has(n.id);
        ctx.globalAlpha = sel ? (isSelected || isConnected ? 1 : 0.15) : 1;
        const color = CAT_HEX[n.entry.category] || "#58a6ff";
        ctx.beginPath();
        ctx.arc(n.x, n.y, isSelected ? n.r + 3 : n.r, 0, 2 * Math.PI);
        ctx.fillStyle   = color + (isSelected ? "ff" : "cc");
        ctx.strokeStyle = isSelected ? "#fff" : color;
        ctx.lineWidth   = isSelected ? 2.5 : 1.5;
        ctx.fill();
        ctx.stroke();
        const label = (n.entry.name || n.entry.url).slice(0, 18);
        ctx.fillStyle    = isSelected ? "rgba(255,255,255,0.95)" : "rgba(255,255,255,0.6)";
        ctx.font         = `${isSelected ? 9 : 8}px monospace`;
        ctx.textAlign    = "center";
        ctx.textBaseline = "top";
        ctx.fillText(label, n.x, n.y + (isSelected ? n.r + 5 : n.r + 2));
      });

      ctx.globalAlpha = 1;
      ctx.restore();
    }

    sim.on("tick", draw);

    // Zoom / pan
    const zoom = d3.zoom()
      .scaleExtent([0.1, 8])
      .on("zoom", e => { transform = e.transform; draw(); });
    d3.select(canvas).call(zoom);
    zoomRef.current = { zoom, canvas };

    // Hit-test helper
    let hoveredNode = null;
    function findNode(cx, cy) {
      const mx = transform.invertX(cx), my = transform.invertY(cy);
      for (const n of nodes) {
        const dx = (n.x || 0) - mx, dy = (n.y || 0) - my;
        if (Math.sqrt(dx * dx + dy * dy) <= n.r + 5) return n;
      }
      return null;
    }

    canvas.onmousemove = e => {
      const rect = canvas.getBoundingClientRect();
      hoveredNode = findNode(e.clientX - rect.left, e.clientY - rect.top);
      canvas.style.cursor = hoveredNode ? "pointer" : "default";
      if (hoveredNode) {
        const label = hoveredNode.kind === "entry"
          ? `${hoveredNode.entry.name || hoveredNode.entry.url}\n[${hoveredNode.entry.category}]  ${hoveredNode.entry.tags?.map(t => "#" + t).join(" ") || ""}\n↵ click to focus · dblclick to open`
          : `#${hoveredNode.name} (${hoveredNode.count} entries)`;
        setTooltip({ x: e.clientX - rect.left, y: e.clientY - rect.top, text: label });
      } else {
        setTooltip(null);
      }
    };

    canvas.onmouseleave = () => { hoveredNode = null; setTooltip(null); };

    canvas.onclick = e => {
      const rect = canvas.getBoundingClientRect();
      const hit  = findNode(e.clientX - rect.left, e.clientY - rect.top);

      if (!hit) {
        // Click empty space → deselect
        selectedRef.current = null;
        setSelected(null);
        draw();
        return;
      }

      if (hit.kind === "entry") {
        // Build connected-tag set
        const connectedIds = new Set(
          links
            .filter(l => l.source.id === hit.id || l.target.id === hit.id)
            .map(l => l.source.id === hit.id ? l.target.id : l.source.id)
        );
        selectedRef.current = { nodeId: hit.id, connectedIds };
        setSelected(hit.entry);
        draw();

        // Zoom to fit the subgraph
        const related = nodes.filter(n => n.id === hit.id || connectedIds.has(n.id));
        if (related.length > 0) {
          const xs  = related.map(n => n.x);
          const ys  = related.map(n => n.y);
          const x0  = Math.min(...xs), x1 = Math.max(...xs);
          const y0  = Math.min(...ys), y1 = Math.max(...ys);
          const pad = 70;
          const bw  = x1 - x0 + pad * 2 || 1;
          const bh  = y1 - y0 + pad * 2 || 1;
          const k   = Math.min(3.5, 0.85 * Math.min(W / bw, H / bh));
          const tx  = W / 2 - k * (x0 + x1) / 2;
          const ty  = H / 2 - k * (y0 + y1) / 2;
          d3.select(canvas)
            .transition().duration(550)
            .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(k));
        }
      } else {
        // Clicked a tag node — find all entries connected to it
        const connectedEntryIds = new Set(
          links
            .filter(l => l.source.id === hit.id || l.target.id === hit.id)
            .map(l => l.source.id === hit.id ? l.target.id : l.source.id)
        );
        selectedRef.current = { nodeId: hit.id, connectedIds: connectedEntryIds };
        setSelected(null);
        draw();

        const related = nodes.filter(n => n.id === hit.id || connectedEntryIds.has(n.id));
        if (related.length > 0) {
          const xs  = related.map(n => n.x);
          const ys  = related.map(n => n.y);
          const x0  = Math.min(...xs), x1 = Math.max(...xs);
          const y0  = Math.min(...ys), y1 = Math.max(...ys);
          const pad = 70;
          const bw  = x1 - x0 + pad * 2 || 1;
          const bh  = y1 - y0 + pad * 2 || 1;
          const k   = Math.min(3.5, 0.85 * Math.min(W / bw, H / bh));
          const tx  = W / 2 - k * (x0 + x1) / 2;
          const ty  = H / 2 - k * (y0 + y1) / 2;
          d3.select(canvas)
            .transition().duration(550)
            .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(k));
        }
      }
    };

    canvas.ondblclick = e => {
      const rect = canvas.getBoundingClientRect();
      const hit  = findNode(e.clientX - rect.left, e.clientY - rect.top);
      if (hit?.kind === "entry") window.open(hit.entry.url, "_blank");
    };

    return () => {
      sim.stop();
      d3.select(canvas).on(".zoom", null);
    };
  }, [entries, tagSearch]);

  return (
    <div className="relative w-full" style={{ height: "calc(100vh - 120px)" }}>
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs text-gray-600">
          {nodeCount.entries} entries · {nodeCount.tags} tag nodes ·{" "}
          <span className="text-gray-700">click to focus · dblclick to open URL</span>
        </div>
        <div className="flex items-center gap-3 text-xs flex-wrap justify-end">
          {Object.entries(CAT_HEX).filter(([k]) => k !== "skill").map(([cat, hex]) => (
            <span key={cat} className="flex items-center gap-1 text-gray-500">
              <span className="w-2.5 h-2.5 rounded-full inline-block flex-shrink-0" style={{ background: hex }} />
              {cat}
            </span>
          ))}
          <span className="flex items-center gap-1 text-gray-500">
            <span className="w-2.5 h-2.5 rounded border border-border inline-block bg-surface-2 flex-shrink-0" />
            tag
          </span>
          <input
            type="text"
            className="ml-4 px-2 py-0.5 rounded border border-border bg-surface-2 text-xs text-gray-500 font-mono"
            placeholder="Search tag..."
            value={tagSearch}
            onChange={e => setTagSearch(e.target.value)}
            style={{ minWidth: 90 }}
          />
        </div>
      </div>

      <canvas ref={canvasRef} className="w-full h-full rounded border border-border block" />

      {tooltip && (
        <div className="absolute pointer-events-none bg-surface-1 border border-border rounded px-3 py-2 text-xs text-gray-300 font-mono whitespace-pre max-w-xs"
          style={{ left: tooltip.x + 14, top: tooltip.y - 10, zIndex: 10 }}>
          {tooltip.text}
        </div>
      )}

      {/* selected entry info panel */}
      {selected && (
        <div className="absolute bottom-4 left-4 right-4 sm:right-auto sm:w-80 bg-surface-1 border border-accent-blue/40 rounded-lg p-3 text-xs shadow-xl"
          style={{ zIndex: 10 }}>
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <Badge category={selected.category} />
              <span className="text-gray-200 font-semibold truncate">{selected.name}</span>
            </div>
            <button onClick={() => { selectedRef.current = null; setSelected(null); }}
              className="text-gray-600 hover:text-gray-400 ml-2 flex-shrink-0">✕</button>
          </div>
          <ul className="space-y-1 mb-2">
            {selected.bullets.map((b, i) => (
              <li key={i} className="flex items-start gap-1.5 text-gray-400">
                <span className="text-accent-green/50 flex-shrink-0">▸</span>{b}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-1 mb-2">
            {selected.tags?.map(t => (
              <span key={t} className="px-1.5 py-0.5 rounded border border-border bg-surface-2 text-gray-500 font-mono">#{t}</span>
            ))}
          </div>
          <a href={selected.url} target="_blank" rel="noreferrer"
            className="text-accent-blue hover:underline font-mono truncate block">
            {selected.url}
          </a>
        </div>
      )}

      {entries.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center text-gray-700 text-sm select-none">
          No entries yet — analyze some URLs first.
        </div>
      )}
    </div>
  );
}

// ─── analyze tab ──────────────────────────────────────────────────────────────

function parseUrls(raw) {
  return [...new Set(
    raw.split(/[\n,]+/)
       .map(s => s.trim())
       .filter(s => s.startsWith("http://") || s.startsWith("https://"))
  )];
}

function AnalyzeTab({ input, setInput, loading, progress, onSubmit, onBlogSubmit, lists, onAddToList, onRemoveFromList, onUpdate, customCats = [] }) {
  const [blogInput,    setBlogInput]    = useState("");
  const [scanState,    setScanState]    = useState("idle"); // idle | scanning | results
  const [scanError,    setScanError]    = useState("");
  const [scanTitle,    setScanTitle]    = useState("");
  const [scanLinks,    setScanLinks]    = useState([]); // [{url, title, selected}]
  const urls   = parseUrls(input);
  const isBulk = urls.length > 1;
  const done   = progress.filter(p => p.status !== "pending").length;
  const total  = progress.length;

  async function handleScan(e) {
    e.preventDefault();
    const u = blogInput.trim();
    if (!u) return;
    setScanState("scanning");
    setScanError("");
    setScanLinks([]);
    try {
      const res  = await fetch(`${API}/scan-blog`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: u }) });
      const data = await res.json();
      if (data.error) { setScanError(data.error); setScanState("idle"); return; }
      setScanTitle(data.title || u);
      setScanLinks((data.links || []).map(lnk => ({ ...lnk, selected: true })));
      setScanState("results");
    } catch (err) {
      setScanError(err.message);
      setScanState("idle");
    }
  }

  function toggleAll(val) {
    setScanLinks(prev => prev.map(l => ({ ...l, selected: val })));
  }

  function handleAnalyzeSelected() {
    const selected = scanLinks.filter(l => l.selected).map(l => l.url);
    if (!selected.length) return;
    onBlogSubmit(blogInput.trim(), selected, scanTitle);
    setScanState("idle");
    setScanLinks([]);
    setBlogInput("");
  }

  const selectedCount = scanLinks.filter(l => l.selected).length;

  return (
    <div>
      <div className="mb-1.5 text-xs text-gray-700 select-none">
        <span className="text-accent-green">researcher</span>
        <span className="text-gray-600">@samuraizer:~$</span>
        <span className="text-gray-700"> analyze</span>
      </div>

      <div className="flex gap-5">
        {/* LEFT: regular URL input */}
        <div className="flex-1 min-w-0">
          <form onSubmit={onSubmit} className="flex flex-col gap-2">
            <div className="relative bg-surface-1 border border-border rounded focus-within:border-accent-green/50 transition-colors">
              <textarea value={input} onChange={e => setInput(e.target.value)}
                placeholder={"Paste one or more URLs (one per line):\nhttps://github.com/...\nhttps://blog.example.com/..."}
                disabled={loading}
                rows={Math.min(Math.max(urls.length + 1, 2), 8)}
                className="w-full bg-transparent text-sm text-gray-200 placeholder-gray-700 outline-none disabled:opacity-50 font-mono px-3 py-2 resize-none" />
              {urls.length > 0 && (
                <div className="absolute bottom-2 right-2 text-xs text-gray-700 select-none">
                  {urls.length} URL{urls.length !== 1 ? "s" : ""}
                </div>
              )}
            </div>
            <div className="flex items-center gap-3">
              <button type="submit" disabled={loading || urls.length === 0}
                className="px-5 py-2 rounded text-sm font-bold bg-accent-green/10 text-accent-green border border-accent-green/40
                           hover:bg-accent-green/20 disabled:opacity-30 disabled:cursor-not-allowed transition-colors flex items-center gap-2">
                {loading && <Spinner sm />}
                {loading ? (isBulk ? `Analyzing ${done}/${total}…` : "Analyzing…") : (isBulk ? `[ ANALYZE ${urls.length} ]` : "[ ANALYZE ]")}
              </button>
              {loading && isBulk && (
                <div className="flex-1 h-1.5 bg-surface-2 rounded-full overflow-hidden">
                  <div className="h-full bg-accent-green transition-all duration-300"
                    style={{ width: `${total ? (done / total) * 100 : 0}%` }} />
                </div>
              )}
            </div>
          </form>
        </div>

        {/* RIGHT: blog scanner */}
        <div className="w-72 flex-shrink-0 border-l border-border pl-5">
          <div className="text-xs text-cyan-500 mb-2 select-none font-bold tracking-wide">BLOG SCANNER</div>
          <form onSubmit={handleScan} className="flex gap-2 mb-2">
            <input value={blogInput} onChange={e => { setBlogInput(e.target.value); if (scanState === "results") setScanState("idle"); }}
              placeholder="https://blog.example.com/"
              disabled={scanState === "scanning" || loading}
              className="flex-1 min-w-0 bg-surface-1 border border-cyan-400/20 rounded text-xs text-gray-200 placeholder-gray-700 outline-none focus:border-cyan-400/50 disabled:opacity-50 font-mono px-2 py-1.5 transition-colors" />
            <button type="submit" disabled={scanState === "scanning" || loading || !blogInput.trim()}
              className="px-3 py-1.5 rounded text-xs font-bold bg-cyan-400/10 text-cyan-400 border border-cyan-400/40
                         hover:bg-cyan-400/20 disabled:opacity-30 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5">
              {scanState === "scanning" ? <><Spinner sm /> Scanning…</> : "Scan"}
            </button>
          </form>

          {scanError && <div className="text-xs text-accent-red mb-2">{scanError}</div>}

          {scanState === "results" && scanLinks.length > 0 && (
            <div className="flex flex-col gap-2">
              <div className="text-xs text-gray-600 truncate" title={scanTitle}>{scanTitle}</div>
              <div className="flex items-center gap-3 text-xs">
                <button onClick={() => toggleAll(true)}  className="text-cyan-600 hover:text-cyan-400 transition-colors">Select all</button>
                <button onClick={() => toggleAll(false)} className="text-gray-600 hover:text-gray-400 transition-colors">None</button>
                <span className="ml-auto text-gray-700">{selectedCount}/{scanLinks.length}</span>
              </div>
              <div className="max-h-64 overflow-y-auto space-y-0.5 border border-border rounded bg-surface-1 px-2 py-1.5">
                {scanLinks.map((lnk, i) => (
                  <label key={lnk.url} className="flex items-start gap-2 cursor-pointer group py-0.5">
                    <input type="checkbox" checked={lnk.selected}
                      onChange={v => setScanLinks(prev => prev.map((l, j) => j === i ? { ...l, selected: v.target.checked } : l))}
                      className="mt-0.5 flex-shrink-0 accent-cyan-500" />
                    <span className="text-xs text-gray-400 group-hover:text-gray-200 transition-colors leading-tight break-words min-w-0">
                      {lnk.title || lnk.url.split("/").filter(Boolean).pop() || lnk.url}
                    </span>
                  </label>
                ))}
              </div>
              <button onClick={handleAnalyzeSelected} disabled={loading || selectedCount === 0}
                className="w-full py-1.5 rounded text-xs font-bold bg-cyan-400/10 text-cyan-400 border border-cyan-400/40
                           hover:bg-cyan-400/20 disabled:opacity-30 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2">
                {loading ? <><Spinner sm /> Analyzing…</> : `Analyze ${selectedCount} article${selectedCount !== 1 ? "s" : ""}`}
              </button>
            </div>
          )}
        </div>
      </div>

      {progress.length > 0 && (
        <div className="mt-6 space-y-3">
          {progress.map(p => (
            <ProgressItem key={p.url} item={p}
              lists={lists} onAddToList={onAddToList} onRemoveFromList={onRemoveFromList} onUpdate={onUpdate} customCats={customCats} />
          ))}
        </div>
      )}

      {!progress.length && !loading && (
        <div className="mt-6">
          <SuggestCard lists={lists} onAddToList={onAddToList} onRemoveFromList={onRemoveFromList}
            onUpdate={onUpdate} customCats={customCats} />
          <div className="mt-8 text-center select-none opacity-60">
            <div className="text-4xl mb-3 opacity-20">⚔</div>
            <p className="text-sm text-gray-700">Paste one or multiple URLs to analyze and save.</p>
            <p className="text-xs mt-2 text-gray-800">
              {CATEGORIES.slice(1).map((k, i, arr) => (
                <span key={k}>
                  <span className={(CAT_META[k]?.color || "").split(" ")[0]}>{k}</span>
                  {i < arr.length - 1 ? " · " : ""}
                </span>
              ))}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── knowledge base tab ───────────────────────────────────────────────────────

// Virtual smart list IDs (not real DB lists)
const SMART_LISTS = [
  { id: "unread", label: "Unread",  icon: "○", color: "text-accent-green",  param: { read: "0" } },
  { id: "read",   label: "Read",    icon: "●", color: "text-gray-500",      param: { read: "1" } },
  { id: "useful", label: "Useful",  icon: "★", color: "text-yellow-400",    param: { useful: "1" } },
];

function KnowledgeBaseTab({ refreshKey, lists, onListsChange, onAddToList, onRemoveFromList, onUpdate, customCats = [], onCustomCatsChange }) {
  const [entries, setEntries]       = useState([]);
  const [allTags, setAllTags]       = useState([]);
  const [loading, setLoading]       = useState(true);
  const [search, setSearch]         = useState("");
  const [category, setCategory]     = useState("all");
  const [activeTag, setActiveTag]   = useState("");
  const [activeList, setActiveList] = useState(null); // null | "unread"|"read"|"useful" | number
  const [debouncedSearch, setDebounced] = useState("");
  const [newListName, setNewListName]   = useState("");
  const [semanticMode, setSemanticMode]     = useState(false);
  const [semanticLoading, setSemanticLoading] = useState(false);
  const [embedProgress, setEmbedProgress]   = useState(null);
  const [selectedIds, setSelectedIds]       = useState(new Set());
  const [showCatManager, setShowCatManager] = useState(false);
  const [newCatLabel, setNewCatLabel]       = useState("");
  const [newCatColor, setNewCatColor]       = useState("#58a6ff");
  const [sourceFilter, setSourceFilter]     = useState("all"); // "all" | "manual" | "rss"

  const CAT_PALETTE = ["#3fb950","#58a6ff","#22d3ee","#fb923c","#bc8cff","#f85149","#d29922","#fb7185","#34d399","#f97316","#a78bfa","#94a3b8"];

  async function handleAddCat(e) {
    e.preventDefault();
    if (!newCatLabel.trim()) return;
    const res  = await fetch(`${API}/categories`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ label: newCatLabel.trim(), color: newCatColor }) });
    const data = await res.json();
    if (res.ok) { onCustomCatsChange?.(prev => [...prev, data]); setNewCatLabel(""); }
  }

  async function handleDeleteCat(slug) {
    await fetch(`${API}/categories/${slug}`, { method: "DELETE" });
    onCustomCatsChange?.(prev => prev.filter(c => c.slug !== slug));
  }

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  const fetchEntries = useCallback(async () => {
    if (semanticMode) return;
    setLoading(true);
    try {
      const p = new URLSearchParams();
      if (category !== "all") p.set("category", category);
      if (debouncedSearch)    p.set("search", debouncedSearch);
      if (activeTag)          p.set("tag", activeTag);
      if (sourceFilter !== "all") p.set("source", sourceFilter);
      const smart = SMART_LISTS.find(s => s.id === activeList);
      if (smart) {
        Object.entries(smart.param).forEach(([k, v]) => p.set(k, v));
      } else if (activeList) {
        p.set("list_id", String(activeList));
      }
      const res = await fetch(`${API}/entries?${p}`);
      setEntries(await res.json());
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [semanticMode, category, debouncedSearch, activeTag, activeList, sourceFilter, refreshKey]);

  // Semantic search effect
  useEffect(() => {
    if (!semanticMode) return;
    if (!debouncedSearch.trim()) { setEntries([]); return; }
    setSemanticLoading(true);
    fetch(`${API}/search/semantic?q=${encodeURIComponent(debouncedSearch)}`)
      .then(r => r.json())
      .then(data => { setEntries(Array.isArray(data) ? data : []); })
      .catch(console.error)
      .finally(() => setSemanticLoading(false));
  }, [semanticMode, debouncedSearch]);

  const fetchTags = useCallback(async () => {
    try { setAllTags(await (await fetch(`${API}/tags`)).json()); }
    catch (e) { console.error(e); }
  }, [refreshKey]);

  useEffect(() => { fetchEntries(); }, [fetchEntries]);
  useEffect(() => { fetchTags(); },   [fetchTags]);

  async function toggleRead(id) {
    await fetch(`${API}/entries/${id}/read`, { method: "PATCH" });
    setEntries(prev => prev.map(e => e.id === id ? { ...e, read: !e.read } : e));
  }

  async function deleteEntry(id) {
    await fetch(`${API}/entries/${id}`, { method: "DELETE" });
    setEntries(prev => prev.filter(e => e.id !== id));
    fetchTags();
  }

  function handleUpdate(updated) {
    setEntries(prev => prev.map(e => e.id === updated.id ? { ...e, ...updated } : e));
    onUpdate?.(updated);
  }

  async function handleEmbedAll() {
    setEmbedProgress("loading");
    try {
      const res  = await fetch(`${API}/entries/embed-all`, { method: "POST" });
      const data = await res.json();
      setEmbedProgress(data);
    } catch (e) { setEmbedProgress({ done: 0, failed: -1 }); }
  }

  // ── multi-select helpers ──────────────────────────────────────────────────
  function toggleSelect(id) {
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function bulkAddToList(listId, newListName) {
    let targetId = listId;
    if (listId === "new") {
      const res  = await fetch(`${API}/lists`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: newListName }) });
      const list = await res.json();
      onListsChange([list, ...lists]);
      targetId = list.id;
    }
    await Promise.all([...selectedIds].map(eid =>
      fetch(`${API}/lists/${targetId}/entries`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ entry_id: eid }) })
    ));
    setEntries(prev => prev.map(e =>
      selectedIds.has(e.id) && !e.list_ids.includes(targetId)
        ? { ...e, list_ids: [...e.list_ids, targetId] }
        : e
    ));
    fetch(`${API}/lists`).then(r => r.json()).then(onListsChange).catch(() => {});
    setSelectedIds(new Set());
  }

  async function bulkMarkRead() {
    await Promise.all([...selectedIds].map(eid =>
      fetch(`${API}/entries/${eid}/read`, { method: "PATCH" })
    ));
    setEntries(prev => prev.map(e => selectedIds.has(e.id) ? { ...e, read: true } : e));
    setSelectedIds(new Set());
  }

  async function bulkMarkUseful() {
    await Promise.all([...selectedIds].map(eid =>
      fetch(`${API}/entries/${eid}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ useful: true }) })
    ));
    setEntries(prev => prev.map(e => selectedIds.has(e.id) ? { ...e, useful: true } : e));
    setSelectedIds(new Set());
  }

  async function createList(name) {
    const res  = await fetch(`${API}/lists`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
    const list = await res.json();
    onListsChange([list, ...lists]);
    setNewListName("");
  }

  async function deleteList(id) {
    await fetch(`${API}/lists/${id}`, { method: "DELETE" });
    onListsChange(lists.filter(l => l.id !== id));
    if (activeList === id) setActiveList(null);
  }

  function handleAddToList(list, entryId) {
    onAddToList(list, entryId);
    setEntries(prev => prev.map(e =>
      e.id === entryId && !e.list_ids.includes(list.id)
        ? { ...e, list_ids: [...e.list_ids, list.id] }
        : e
    ));
    fetch(`${API}/lists`).then(r => r.json()).then(onListsChange).catch(() => {});
  }

  function handleRemoveFromList(listId, entryId) {
    onRemoveFromList(listId, entryId);
    setEntries(prev => prev.map(e =>
      e.id === entryId ? { ...e, list_ids: e.list_ids.filter(id => id !== listId) } : e
    ));
    fetch(`${API}/lists`).then(r => r.json()).then(onListsChange).catch(() => {});
  }

  const unread    = entries.filter(e => !e.read).length;
  const catCounts = entries.reduce((acc, e) => { acc[e.category] = (acc[e.category] || 0) + 1; return acc; }, {});
  const hasFilter = !semanticMode && (debouncedSearch || category !== "all" || activeTag || activeList != null);

  return (
    <div className="flex gap-6">
      {/* left sidebar: lists */}
      <aside className="w-48 flex-shrink-0">
        <div className="sticky top-8 space-y-3">
          <div>
            <p className="text-xs text-gray-700 uppercase tracking-widest mb-2">Lists</p>
            <div className="space-y-0.5">
              <button onClick={() => { setActiveList(null); setSelectedIds(new Set()); }}
                className={`w-full text-left px-2 py-1.5 rounded text-xs transition-colors ${!activeList ? "text-gray-200 bg-surface-2" : "text-gray-600 hover:text-gray-400"}`}>
                All entries
              </button>

              {/* Smart / auto lists */}
              <div className="pt-1 pb-0.5">
                <p className="text-xs text-gray-800 uppercase tracking-widest px-2 mb-0.5">Smart</p>
                {SMART_LISTS.map(sl => (
                  <button key={sl.id}
                    onClick={() => { setActiveList(al => al === sl.id ? null : sl.id); setSelectedIds(new Set()); }}
                    className={`w-full text-left px-2 py-1.5 rounded text-xs transition-colors flex items-center gap-1.5
                      ${activeList === sl.id ? `${sl.color} bg-surface-2 font-semibold` : "text-gray-600 hover:text-gray-400"}`}>
                    <span className={sl.color}>{sl.icon}</span>
                    {sl.label}
                  </button>
                ))}
              </div>

              {/* User-created lists */}
              {lists.length > 0 && (
                <div className="pt-1">
                  <p className="text-xs text-gray-800 uppercase tracking-widest px-2 mb-0.5">Lists</p>
                  {lists.map(l => (
                    <div key={l.id} className="flex items-center group">
                      <button onClick={() => { setActiveList(l.id === activeList ? null : l.id); setSelectedIds(new Set()); }}
                        className={`flex-1 text-left px-2 py-1.5 rounded-l text-xs transition-colors truncate ${l.id === activeList ? "text-accent-purple bg-accent-purple/10" : "text-gray-500 hover:text-gray-300"}`}>
                        {l.name}
                        <span className="ml-1 text-gray-700">{l.entry_count}</span>
                      </button>
                      <button onClick={() => deleteList(l.id)}
                        className="px-1 py-1.5 text-gray-800 hover:text-accent-red opacity-0 group-hover:opacity-100 transition-all text-xs">
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <form onSubmit={e => { e.preventDefault(); if (newListName.trim()) createList(newListName.trim()); }}
              className="mt-2 flex gap-1">
              <input value={newListName} onChange={e => setNewListName(e.target.value)}
                placeholder="New list…"
                className="flex-1 bg-surface-1 border border-border rounded px-2 py-1 text-xs text-gray-300 outline-none focus:border-accent-green/50" />
              <button type="submit"
                className="px-2 text-xs text-accent-green border border-accent-green/40 rounded hover:bg-accent-green/10">+</button>
            </form>
          </div>
        </div>
      </aside>

      {/* main content */}
      <div className="flex-1 min-w-0">
        {/* bulk action bar */}
        {selectedIds.size > 0 && (
          <BulkBar count={selectedIds.size} lists={lists}
            onAddToList={bulkAddToList}
            onMarkRead={bulkMarkRead}
            onMarkUseful={bulkMarkUseful}
            onClear={() => setSelectedIds(new Set())} />
        )}

        {/* search + semantic toggle */}
        <div className="flex flex-col sm:flex-row gap-3 mb-3">
          <div className={`flex items-center gap-2 bg-surface-1 border rounded px-3 py-2 flex-1 transition-colors
            ${semanticMode ? "border-accent-purple/50 focus-within:border-accent-purple/70" : "border-border focus-within:border-accent-green/50"}`}>
            <span className="text-gray-700 text-xs">{semanticMode ? "✦" : "⌕"}</span>
            <input value={search} onChange={e => setSearch(e.target.value)}
              placeholder={semanticMode ? "Describe what you're looking for…" : "Search names, bullets, tags…"}
              className="flex-1 bg-transparent text-sm text-gray-200 placeholder-gray-700 outline-none font-mono" />
            {(loading || semanticLoading) && <Spinner sm />}
            {search && <button onClick={() => setSearch("")} className="text-gray-600 hover:text-gray-400 text-xs">✕</button>}
          </div>
          <div className="flex items-center gap-1 flex-wrap">
            <button onClick={() => { setSemanticMode(s => !s); setEntries([]); }}
              title="Toggle semantic / embedding-based search"
              className={`px-3 py-1.5 rounded text-xs font-bold border transition-colors flex items-center gap-1.5
                ${semanticMode
                  ? "text-accent-purple bg-accent-purple/10 border-accent-purple/40"
                  : "text-gray-600 border-border hover:text-gray-400 hover:border-gray-600"}`}>
              ✦ Semantic
            </button>
            {/* source filter */}
            {!semanticMode && (
              <div className="flex items-center border border-border rounded overflow-hidden">
                {[["all", "All"], ["manual", "Manual"], ["rss", "RSS"]].map(([val, label]) => (
                  <button key={val} onClick={() => setSourceFilter(val)}
                    className={`px-2.5 py-1.5 text-xs font-bold transition-colors
                      ${sourceFilter === val
                        ? "bg-surface-2 text-gray-200 border-r border-border last:border-r-0"
                        : "text-gray-600 hover:text-gray-400 border-r border-border last:border-r-0"}`}>
                    {label}
                  </button>
                ))}
              </div>
            )}
            {!semanticMode && CATEGORIES.map(cat => {
              const active = category === cat;
              const meta   = CAT_META[cat];
              const count  = cat === "all" ? entries.length : (catCounts[cat] || 0);
              return (
                <button key={cat} onClick={() => setCategory(cat)}
                  className={`px-3 py-1.5 rounded text-xs font-bold uppercase tracking-wider border transition-colors
                    ${active ? (meta ? meta.color : "text-gray-200 border-gray-500 bg-surface-2") : "text-gray-600 border-border hover:border-gray-500 hover:text-gray-400"}`}>
                  {cat === "all" ? "All" : meta?.label}{count > 0 ? ` ${count}` : ""}
                </button>
              );
            })}
            {!semanticMode && customCats.map(c => {
              const active = category === c.slug;
              const count  = catCounts[c.slug] || 0;
              return (
                <button key={c.slug} onClick={() => setCategory(c.slug)}
                  style={active ? { color: c.color, borderColor: c.color + "66", backgroundColor: c.color + "1a" } : {}}
                  className={`px-3 py-1.5 rounded text-xs font-bold uppercase tracking-wider border transition-colors
                    ${active ? "" : "text-gray-600 border-border hover:border-gray-500 hover:text-gray-400"}`}>
                  {c.label}{count > 0 ? ` ${count}` : ""}
                </button>
              );
            })}
            {!semanticMode && (
              <button onClick={() => setShowCatManager(s => !s)}
                title="Manage custom categories"
                className={`px-2 py-1.5 rounded text-xs border transition-colors
                  ${showCatManager ? "text-gray-300 border-gray-500 bg-surface-2" : "text-gray-600 border-border hover:border-gray-500 hover:text-gray-400"}`}>
                ⊕
              </button>
            )}
          </div>
        </div>

        {/* custom category manager */}
        {showCatManager && (
          <div className="mb-3 p-3 rounded border border-border bg-surface-1 space-y-3">
            {customCats.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {customCats.map(c => (
                  <div key={c.slug} className="flex items-center gap-1.5 px-2 py-1 rounded border text-xs font-bold uppercase tracking-wider"
                    style={{ color: c.color, borderColor: c.color + "66", backgroundColor: c.color + "1a" }}>
                    {c.label}
                    <button onClick={() => handleDeleteCat(c.slug)}
                      className="ml-1 text-gray-600 hover:text-accent-red transition-colors leading-none">✕</button>
                  </div>
                ))}
              </div>
            )}
            <form onSubmit={handleAddCat} className="flex items-center gap-2 flex-wrap">
              <input value={newCatLabel} onChange={e => setNewCatLabel(e.target.value)}
                placeholder="Category name…"
                className="bg-surface-2 border border-border rounded px-2 py-1 text-xs text-gray-200 placeholder-gray-700 outline-none focus:border-gray-500 w-36" />
              <div className="flex gap-1">
                {CAT_PALETTE.filter(col => !customCats.some(c => c.color === col)).map(col => (
                  <button type="button" key={col} onClick={() => setNewCatColor(col)}
                    style={{ backgroundColor: col, outline: newCatColor === col ? `2px solid ${col}` : "none", outlineOffset: "2px" }}
                    className="w-4 h-4 rounded-full transition-transform hover:scale-110" />
                ))}
              </div>
              <button type="submit"
                className="px-2 py-1 rounded text-xs border border-border text-gray-400 hover:text-gray-200 hover:border-gray-500 transition-colors">
                + Add
              </button>
            </form>
          </div>
        )}

        {/* semantic search hint */}
        {semanticMode && (
          <div className="mb-3 flex items-center justify-between text-xs text-gray-600">
            <span>Searching by meaning using Gemini embeddings</span>
            <div className="flex items-center gap-2">
              {embedProgress === "loading" && <><Spinner sm /><span>Embedding entries…</span></>}
              {embedProgress && embedProgress !== "loading" && (
                <span className={embedProgress.failed < 0 ? "text-accent-red" : "text-accent-green"}>
                  {embedProgress.failed < 0 ? "Error" : `✓ ${embedProgress.done} embedded${embedProgress.failed > 0 ? `, ${embedProgress.failed} failed` : ""}`}
                </span>
              )}
              <button onClick={handleEmbedAll} disabled={embedProgress === "loading"}
                className="px-2 py-1 rounded border border-accent-purple/40 text-accent-purple hover:bg-accent-purple/10 transition-colors disabled:opacity-40">
                Embed all entries
              </button>
            </div>
          </div>
        )}

        {/* stats */}
        {entries.length > 0 && (
          <div className="flex items-center gap-4 mb-4 text-xs text-gray-600">
            <span>{entries.length} entries</span>
            {unread > 0 && <span className="text-accent-green">{unread} unread</span>}
            {activeTag  && <span className="text-accent-blue">#{activeTag}</span>}
            {activeList && (
              SMART_LISTS.find(s => s.id === activeList)
                ? <span className={SMART_LISTS.find(s => s.id === activeList).color}>
                    {SMART_LISTS.find(s => s.id === activeList).icon} {SMART_LISTS.find(s => s.id === activeList).label}
                  </span>
                : <span className="text-accent-purple">📋 {lists.find(l => l.id === activeList)?.name}</span>
            )}
          </div>
        )}

        {/* list */}
        {(loading || semanticLoading) ? (
          <div className="flex items-center gap-2 text-sm text-gray-700 mt-8"><Spinner /><span>{semanticLoading ? "Searching by meaning…" : "Loading…"}</span></div>
        ) : entries.length === 0 ? (
          <div className="mt-16 text-center select-none">
            <div className="text-4xl mb-3 opacity-20">⚔</div>
            <p className="text-sm text-gray-700">
              {semanticMode
                ? (debouncedSearch ? "No semantic matches found. Try rephrasing." : "Type a description to search by meaning.")
                : hasFilter ? "No entries match your filter." : "No entries yet. Analyze a URL first."}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {semanticMode && entries.length > 0 && (
              <p className="text-xs text-gray-700 mb-2">
                {entries.length} semantic match{entries.length !== 1 ? "es" : ""} — sorted by relevance
              </p>
            )}
            {entries.length > 1 && (
              <div className="flex items-center gap-2 mb-1">
                <button onClick={() => setSelectedIds(prev => prev.size === entries.length ? new Set() : new Set(entries.map(e => e.id)))}
                  className="text-xs text-gray-700 hover:text-gray-400 transition-colors">
                  {selectedIds.size === entries.length ? "deselect all" : "select all"}
                </button>
              </div>
            )}
            {entries.map(entry => (
              ["playlist", "list", "blog"].includes(entry.category)
                ? <PlaylistCard key={entry.id} entry={entry}
                    onTagClick={t => setActiveTag(prev => prev === t ? "" : t)}
                    customCats={customCats}
                    onDelete={id => setEntries(prev => prev.filter(e => e.id !== id))} />
                : <EntryCard key={entry.id} entry={entry}
                    onToggleRead={toggleRead} onDelete={deleteEntry}
                    onTagClick={t => setActiveTag(prev => prev === t ? "" : t)}
                    lists={lists} onAddToList={handleAddToList} onRemoveFromList={handleRemoveFromList}
                    onUpdate={handleUpdate}
                    selected={selectedIds.has(entry.id)}
                    onSelect={toggleSelect}
                    customCats={customCats} />
            ))}
          </div>
        )}
      </div>

      {/* right sidebar: tag cloud */}
      {allTags.length > 0 && (
        <aside className="w-36 flex-shrink-0">
          <div className="sticky top-8">
            <p className="text-xs text-gray-700 uppercase tracking-widest mb-2">Tags</p>
            <div className="space-y-0.5">
              {allTags.map(({ tag, count }) => (
                <button key={tag} onClick={() => setActiveTag(prev => prev === tag ? "" : tag)}
                  className={`w-full text-left px-2 py-1 rounded text-xs font-mono transition-colors truncate
                    ${activeTag === tag
                      ? "border-accent-blue/60 bg-accent-blue/10 text-accent-blue"
                      : "text-gray-600 hover:text-accent-blue/70"}`}>
                  #{tag}<span className="ml-1 text-gray-800">{count}</span>
                </button>
              ))}
              {activeTag && (
                <button onClick={() => setActiveTag("")}
                  className="w-full text-left px-2 py-1 rounded text-xs text-accent-red/70 hover:text-accent-red transition-colors">
                  clear ✕
                </button>
              )}
            </div>
          </div>
        </aside>
      )}
    </div>
  );
}

// ─── root ─────────────────────────────────────────────────────────────────────

export default function App() {
  const [tab, setTab]           = useState("analyze");
  const [refreshKey, setRefreshKey] = useState(0);
  const [lists, setLists]           = useState([]);
  const [customCats, setCustomCats] = useState([]);

  // Analysis state lives here — survives tab switches
  const [input, setInput]       = useState("");
  const [loading, setLoading]   = useState(false);
  const [progress, setProgress] = useState([]);

  useEffect(() => {
    fetch(`${API}/lists`).then(r => r.json()).then(setLists).catch(console.error);
    fetch(`${API}/categories`).then(r => r.json()).then(setCustomCats).catch(console.error);
  }, []);

  function handleInputChange(val) {
    setInput(val);
    if (!loading) setProgress([]);
  }

  function handleAddToList(list, entryId) {
    if (!lists.find(l => l.id === list.id)) {
      setLists(prev => [list, ...prev]);
    }
    setProgress(prev => prev.map(p =>
      p.entry?.id === entryId
        ? { ...p, entry: { ...p.entry, list_ids: [...(p.entry.list_ids || []), list.id] } }
        : p
    ));
  }

  function handleRemoveFromList(listId, entryId) {
    setProgress(prev => prev.map(p =>
      p.entry?.id === entryId
        ? { ...p, entry: { ...p.entry, list_ids: (p.entry.list_ids || []).filter(id => id !== listId) } }
        : p
    ));
  }

  async function handleSubmitUrls(urls) {
    if (!urls.length || loading) return;
    setLoading(true);
    setProgress(urls.map(url => ({ url, status: "pending", logs: [] })));
    const body = urls.length === 1 ? { url: urls[0] } : { urls };
    try {
      const res     = await fetch(`${API}/analyze`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const reader  = res.body.getReader();
      const decoder = new TextDecoder();
      let   buffer  = "";
      while (true) {
        const { value, done: sd } = await reader.read();
        if (sd) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          let msg; try { msg = JSON.parse(line); } catch { continue; }
          setProgress(prev => prev.map(p => {
            if (p.url !== msg.url) return p;
            if (msg.log)   return { ...p, logs: [...p.logs, msg.log] };
            if (msg.entry) return { ...p, status: "ok",    entry: msg.entry };
            if (msg.error) return { ...p, status: "error", error: msg.error };
            return p;
          }));
        }
      }
      setRefreshKey(k => k + 1);
    } catch (err) {
      setProgress(prev => prev.map(p =>
        p.status === "pending" ? { ...p, status: "error", error: err.message } : p
      ));
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const urls = parseUrls(input);
    await handleSubmitUrls(urls);
  }

  async function handleBlogSubmit(url, selectedUrls = null, listingTitle = null) {
    if (loading) return;
    setLoading(true);
    setProgress([{ url, status: "pending", logs: [] }]);
    const body = { url };
    if (selectedUrls) { body.selected_urls = selectedUrls; body.listing_title = listingTitle; }
    try {
      const res     = await fetch(`${API}/analyze-blog`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const reader  = res.body.getReader();
      const decoder = new TextDecoder();
      let   buffer  = "";
      while (true) {
        const { value, done: sd } = await reader.read();
        if (sd) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          let msg; try { msg = JSON.parse(line); } catch { continue; }
          setProgress(prev => prev.map(p => {
            if (p.url !== msg.url) return p;
            if (msg.log)   return { ...p, logs: [...p.logs, msg.log] };
            if (msg.entry) return { ...p, status: "ok",    entry: msg.entry };
            if (msg.error) return { ...p, status: "error", error: msg.error };
            return p;
          }));
        }
      }
      setRefreshKey(k => k + 1);
    } catch (err) {
      setProgress(prev => prev.map(p =>
        p.status === "pending" ? { ...p, status: "error", error: err.message } : p
      ));
    } finally {
      setLoading(false);
    }
  }

  const pendingCount = progress.filter(p => p.status === "pending").length;

  return (
    <div className="min-h-screen bg-surface font-mono flex flex-col">
      <header className="border-b border-border bg-surface-1 flex-shrink-0">
        <div className="max-w-5xl mx-auto px-6 h-12 flex items-center gap-3">
          <span className="text-accent-green font-bold text-base tracking-tight select-none">⚔ SAMURAIZER</span>
          <span className="text-border select-none">│</span>
          <nav className="flex gap-1 ml-2">
            {[
              { id: "analyze", label: "Analyze" },
              { id: "kb",      label: "Knowledge Base" },
              { id: "rss",     label: "RSS" },
              { id: "graph",   label: "Graph" },
            ].map(({ id, label }) => (
              <button key={id} onClick={() => setTab(id)}
                className={`px-3 py-1 rounded text-xs font-bold uppercase tracking-wider transition-colors flex items-center gap-1.5
                  ${tab === id ? "text-accent-green bg-accent-green/10 border border-accent-green/40" : "text-gray-600 hover:text-gray-400"}`}>
                {label}
                {id === "analyze" && loading && (
                  <span className="flex items-center gap-1">
                    <Spinner sm />
                    {pendingCount > 0 && <span className="text-accent-yellow font-mono">{pendingCount}</span>}
                  </span>
                )}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="flex-1 max-w-5xl mx-auto w-full px-6 py-8">
        {tab === "analyze" && (
          <AnalyzeTab input={input} setInput={handleInputChange}
            loading={loading} progress={progress} onSubmit={handleSubmit} onBlogSubmit={handleBlogSubmit}
            lists={lists} onAddToList={handleAddToList} onRemoveFromList={handleRemoveFromList}
            customCats={customCats}
            onUpdate={updated => setProgress(prev => prev.map(p =>
              p.entry?.id === updated.id ? { ...p, entry: { ...p.entry, ...updated } } : p
            ))} />
        )}
        {tab === "kb" && (
          <KnowledgeBaseTab refreshKey={refreshKey}
            lists={lists} onListsChange={setLists}
            onAddToList={handleAddToList} onRemoveFromList={handleRemoveFromList}
            customCats={customCats} onCustomCatsChange={setCustomCats}
            onUpdate={updated => setProgress(prev => prev.map(p =>
              p.entry?.id === updated.id ? { ...p, entry: { ...p.entry, ...updated } } : p
            ))} />
        )}
        {tab === "rss" && <RssTab />}
        {tab === "graph" && <GraphTab />}
      </main>
    </div>
  );
}
