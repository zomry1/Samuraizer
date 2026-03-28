import { useState, useEffect, useCallback, useMemo } from "react";
import { API, CATEGORIES, CAT_META, SMART_LISTS } from "../../constants";
import Spinner from "../shared/Spinner";
import BulkBar from "../shared/BulkBar";
import EntryCard from "../entries/EntryCard";
import PlaylistCard from "../entries/PlaylistCard";

// ─── knowledge base tab ───────────────────────────────────────────────────────

export default function KnowledgeBaseTab({ refreshKey, lists, onListsChange, onAddToList, onRemoveFromList, onUpdate, customCats = [], onCustomCatsChange }) {
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

  // Use allTags (from /tags, includes children) so child-only tags appear in the cloud
  const tagCounts = useMemo(() => {
    const counts = {};
    for (const { tag, count } of allTags) {
      counts[tag] = count;
    }
    return counts;
  }, [allTags]);

  const activeFilters = useMemo(() => {
    const filters = [];
    if (debouncedSearch) {
      filters.push({
        key: "search",
        label: `Search: ${debouncedSearch}`,
        onClear: () => { setSearch(""); setDebounced(""); },
      });
    }
    if (semanticMode) {
      filters.push({ key: "semantic", label: "Semantic", onClear: () => setSemanticMode(false) });
    }
    if (category !== "all") {
      const label = CAT_META[category]?.label || category;
      filters.push({ key: "category", label: `Category: ${label}`, onClear: () => setCategory("all") });
    }
    if (activeTag) {
      filters.push({ key: "tag", label: `Tag: ${activeTag}`, onClear: () => setActiveTag("") });
    }
    if (sourceFilter !== "all") {
      const label = sourceFilter === "rss" ? "RSS" : "Manual";
      filters.push({ key: "source", label: `Source: ${label}`, onClear: () => setSourceFilter("all") });
    }
    if (activeList) {
      const smart = SMART_LISTS.find(s => s.id === activeList);
      const label = smart ? smart.label : (lists.find(l => l.id === activeList)?.name || "List");
      filters.push({ key: "list", label: `List: ${label}`, onClear: () => setActiveList(null) });
    }
    return filters;
  }, [debouncedSearch, semanticMode, category, activeTag, sourceFilter, activeList, lists]);

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
    fetchTags();
  }

  async function handleEmbedAll() {
    setEmbedProgress("loading");
    try {
      const res = await fetch(`${API}/entries/embed-required`, { method: "POST" });
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let result = null;
      while (true) {
        const { done: streamDone, value } = await reader.read();
        if (value) buf += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf("\n")) !== -1) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (!line) continue;
          try {
            const evt = JSON.parse(line);
            if (evt.type === "progress") {
              setEmbedProgress({ done: evt.done, total: evt.total, failed: evt.failed, name: evt.name });
            } else if (evt.type === "complete") {
              result = evt;
            }
          } catch {}
        }
        if (streamDone) break;
      }
      if (result) setEmbedProgress({ done: result.done, failed: result.failed });
      else setEmbedProgress({ done: 0, failed: -1 });
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

  async function bulkDeleteSelected() {
    if (!window.confirm(`Delete ${selectedIds.size} selected entr${selectedIds.size === 1 ? "y" : "ies"}?`)) return;
    await Promise.all([...selectedIds].map(eid =>
      fetch(`${API}/entries/${eid}`, { method: "DELETE" })
    ));
    setEntries(prev => prev.filter(e => !selectedIds.has(e.id)));
    setSelectedIds(new Set());
    fetchTags();
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
            onDeleteSelected={bulkDeleteSelected}
            onClear={() => setSelectedIds(new Set())} />
        )}

        {/* search + semantic toggle */}
        <div className="flex flex-col gap-3 mb-3">
          <div className="flex flex-col sm:flex-row gap-3">
            <div className={`flex items-center gap-2 bg-surface-1 border rounded px-3 py-2 flex-1 transition-colors
              ${semanticMode ? "border-accent-purple/50 focus-within:border-accent-purple/70" : "border-border focus-within:border-accent-green/50"}`}>
              <span className="text-gray-700 text-xs">{semanticMode ? "✦" : "⌕"}</span>
              <input value={search} onChange={e => setSearch(e.target.value)}
                placeholder={semanticMode ? "Describe what you're looking for…" : "Search names, bullets, tags…"}
                className="flex-1 bg-transparent text-sm text-gray-200 placeholder-gray-700 outline-none font-mono" />
              {(loading || semanticLoading) && <Spinner sm />}
              {search && <button onClick={() => setSearch("")} className="text-gray-600 hover:text-gray-400 text-xs">✕</button>}
            </div>
            <button onClick={() => { setSemanticMode(s => !s); setEntries([]); }}
              title="Toggle semantic / embedding-based search"
              className={`px-3 py-1.5 rounded text-xs font-bold border transition-colors flex items-center gap-1.5
                ${semanticMode
                  ? "text-accent-purple bg-accent-purple/10 border-accent-purple/40"
                  : "text-gray-600 border-border hover:text-gray-400 hover:border-gray-600"}`}>
              ✦ Semantic
            </button>
          </div>

          {/* active filters */}
          {activeFilters.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 mb-2">
              {activeFilters.map(f => (
                <button key={f.key}
                  onClick={f.onClear}
                  className="flex items-center gap-1 text-xs px-2 py-1 rounded bg-surface-2 text-gray-200 hover:bg-surface-3">
                  {f.label} <span className="text-gray-500">✕</span>
                </button>
              ))}
              <button onClick={() => {
                  setSearch(""); setDebounced(""); setSemanticMode(false);
                  setCategory("all"); setActiveTag(""); setSourceFilter("all"); setActiveList(null);
                }}
                className="ml-auto text-xs text-gray-400 hover:text-gray-200">
                clear all
              </button>
            </div>
          )}

          {/* source + category filters */}
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="flex flex-col sm:flex-row items-center gap-2">
              <span className="text-xs font-semibold text-gray-400">Source:</span>
              <div className="flex items-center border border-border rounded overflow-hidden">
                {[ ["all", "All"], ["manual", "Manual"], ["rss", "RSS"] ].map(([val, label]) => (
                  <button key={val} onClick={() => setSourceFilter(val)}
                    className={`px-2.5 py-1.5 text-xs font-bold transition-colors
                      ${sourceFilter === val
                        ? "bg-surface-2 text-gray-200 border-r border-border last:border-r-0"
                        : "text-gray-600 hover:text-gray-400 border-r border-border last:border-r-0"}`}>
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex-1 flex flex-wrap gap-2 items-center">
              <span className="text-xs font-semibold text-gray-400">Category:</span>
              <div className="flex flex-wrap gap-1">
                {CATEGORIES.map(cat => {
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
                {customCats.map(c => {
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
              </div>
              <button onClick={() => setShowCatManager(s => !s)}
                title="Manage custom categories"
                className={`px-2 py-1.5 rounded text-xs border transition-colors
                  ${showCatManager ? "text-gray-300 border-gray-500 bg-surface-2" : "text-gray-600 border-border hover:border-gray-500 hover:text-gray-400"}`}>
                ⊕
              </button>
            </div>
          </div>
        </div>

        {/* custom category manager */}
        {showCatManager && (
          <div className="mb-3 p-3 rounded border border-border bg-surface-1 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-xs font-bold text-gray-200">Custom categories</div>
                <div className="text-xs text-gray-500">Create your own category tags to group entries.</div>
              </div>
              <button onClick={() => setShowCatManager(false)}
                className="text-xs text-gray-500 hover:text-gray-300">Close</button>
            </div>

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

            <form onSubmit={handleAddCat} className="flex flex-col sm:flex-row items-center gap-2">
              <input value={newCatLabel} onChange={e => setNewCatLabel(e.target.value)}
                placeholder="New category name…"
                className="flex-1 bg-surface-2 border border-border rounded px-2 py-1 text-xs text-gray-200 placeholder-gray-700 outline-none focus:border-gray-500" />
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500">Color:</span>
                <div className="flex gap-1">
                  {CAT_PALETTE.filter(col => !customCats.some(c => c.color === col)).map(col => (
                    <button type="button" key={col} onClick={() => setNewCatColor(col)}
                      style={{ backgroundColor: col, outline: newCatColor === col ? `2px solid ${col}` : "none", outlineOffset: "2px" }}
                      className="w-4 h-4 rounded-full transition-transform hover:scale-110" />
                  ))}
                </div>
              </div>
              <button type="submit"
                className="px-3 py-1 rounded text-xs border border-border text-gray-400 hover:text-gray-200 hover:border-gray-500 transition-colors">
                + Add category
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
              {embedProgress && embedProgress !== "loading" && embedProgress.total && (
                <span className="text-accent-blue"><Spinner sm /> Embedding {embedProgress.done} / {embedProgress.total}…</span>
              )}
              {embedProgress && embedProgress !== "loading" && !embedProgress.total && (
                <span className={embedProgress.failed < 0 ? "text-accent-red" : "text-accent-green"}>
                  {embedProgress.failed < 0 ? "Error" : `✓ ${embedProgress.done} embedded${embedProgress.failed > 0 ? `, ${embedProgress.failed} failed` : ""}`}
                </span>
              )}
              <button onClick={handleEmbedAll} disabled={embedProgress === "loading" || (embedProgress && embedProgress.total)}
                className="px-2 py-1 rounded border border-accent-purple/40 text-accent-purple hover:bg-accent-purple/10 transition-colors disabled:opacity-40">
                Re-embed required entries
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
              ["playlist", "blog"].includes(entry.category)
                ? <PlaylistCard key={entry.id} entry={entry}
                    onTagClick={t => setActiveTag(prev => prev === t ? "" : t)}
                    customCats={customCats}
                    onDelete={id => setEntries(prev => prev.filter(e => e.id !== id))}
                    onUpdate={handleUpdate}
                    allTags={allTags}
                    matchedChildIds={entry.matched_child_ids || []} />
                : <EntryCard key={entry.id} entry={entry}
                    onToggleRead={toggleRead} onDelete={deleteEntry}
                    onTagClick={t => setActiveTag(prev => prev === t ? "" : t)}
                    lists={lists} onAddToList={handleAddToList} onRemoveFromList={handleRemoveFromList}
                    onUpdate={handleUpdate}
                    selected={selectedIds.has(entry.id)}
                    onSelect={toggleSelect}
                    customCats={customCats}
                    allTags={allTags} />
            ))}
          </div>
        )}
      </div>

      {/* right sidebar: tag cloud */}
      {Object.keys(tagCounts).length > 0 && (
        <aside className="w-36 flex-shrink-0">
          <div className="sticky top-8">
            <p className="text-xs text-gray-700 uppercase tracking-widest mb-2">Tags</p>
            <div className="space-y-0.5">
              {Object.entries(tagCounts).sort((a, b) => b[1] - a[1]).map(([tag, count]) => (
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
