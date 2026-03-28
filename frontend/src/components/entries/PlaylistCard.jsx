import { useState, useEffect, useMemo } from "react";
import { API } from "../../constants";
import Badge from "../shared/Badge";
import Spinner from "../shared/Spinner";
import VideoChildItem from "./VideoChildItem";

// ─── playlist card ────────────────────────────────────────────────────────────

export default function PlaylistCard({ entry, onTagClick, customCats = [], onDelete, onUpdate, allTags = [], matchedChildIds = [] }) {
  const hasChildMatches               = matchedChildIds.length > 0;
  const [open, setOpen]               = useState(hasChildMatches);
  const [children, setChildren]       = useState(entry.children || []);
  const [loadingKids, setLoadingKids] = useState(false);
  const [deleting, setDeleting]       = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [draftName, setDraftName]     = useState(entry.name || "");
  const [tags, setTags]               = useState(entry.tags || []);
  const [tagInput, setTagInput]       = useState("");

  // Auto-open and fetch children when a filter highlights matching children
  useEffect(() => {
    if (matchedChildIds.length > 0) {
      setOpen(true);
      if (children.length === 0) {
        setLoadingKids(true);
        fetch(`${API}/entries/${entry.id}/children`)
          .then(r => r.json())
          .then(data => { setChildren(data); setLoadingKids(false); })
          .catch(() => setLoadingKids(false));
      }
    }
  }, [matchedChildIds.length > 0]); // eslint-disable-line react-hooks/exhaustive-deps

  const visibleChildren = hasChildMatches
    ? children.filter(c => matchedChildIds.includes(c.id))
    : children;

  useEffect(() => {
    setDraftName(entry.name || "");
  }, [entry.name]);

  const tagSuggestions = useMemo(() => {
    const q = tagInput.trim().toLowerCase();
    if (!q) return [];
    return (allTags || [])
      .map(t => t.tag)
      .filter(t => t.toLowerCase().includes(q) && !(tags || []).includes(t))
      .slice(0, 6);
  }, [tagInput, allTags, tags]);

  useEffect(() => {
    setTags(entry.tags || []);
  }, [entry.tags]);

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

  async function saveName(e) {
    e?.preventDefault();
    const nextName = (draftName || "").trim();
    if (!nextName) {
      setDraftName(entry.name || "");
      setEditingName(false);
      return;
    }
    if (nextName === entry.name) {
      setEditingName(false);
      return;
    }
    const res = await fetch(`${API}/entries/${entry.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: nextName }),
    });
    if (res.ok) {
      const updated = await res.json();
      onUpdate?.(updated);
    }
    setEditingName(false);
  }

  async function addTag(tag) {
    const newTag = tag.trim();
    if (!newTag) return;
    const newTags = Array.from(new Set([...(tags || []), newTag]));
    const res = await fetch(`${API}/entries/${entry.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tags: newTags }),
    });
    if (res.ok) {
      const updated = await res.json();
      setTags(updated.tags || []);
      onUpdate?.(updated);
    }
  }

  async function handleAddTag(e) {
    e.preventDefault();
    await addTag(tagInput);
    setTagInput("");
  }

  async function handleRemoveTag(tag) {
    const newTags = (tags || []).filter(t => t !== tag);
    const res = await fetch(`${API}/entries/${entry.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tags: newTags }),
    });
    if (res.ok) {
      const updated = await res.json();
      setTags(updated.tags || []);
      onUpdate?.(updated);
    }
  }

  return (
    <div className="rounded-lg border overflow-hidden" style={{ borderColor }}>
      {/* header */}
      <div className="flex items-center gap-3 px-4 py-2.5 bg-surface-2 border-b cursor-pointer select-none"
        style={{ borderColor: divColor }} onClick={handleToggle}>
        <Badge category={entry.category} customCats={customCats} />
        <div className="flex items-center gap-2 flex-1 min-w-0">
          {editingName ? (
            <form onSubmit={saveName} onClick={e => e.stopPropagation()} className="flex items-center gap-2 flex-1 min-w-0">
              <input
                value={draftName}
                onChange={e => setDraftName(e.target.value)}
                className="text-sm font-medium text-gray-200 truncate bg-surface-2 px-2 py-1 rounded border border-border focus:outline-none focus:border-accent-blue flex-1"
                autoFocus
              />
              <button type="submit" className="text-xs text-accent-green hover:text-accent-green/80">Save</button>
              <button type="button" onClick={e => { e.stopPropagation(); setDraftName(entry.name || ""); setEditingName(false); }}
                className="text-xs text-gray-500 hover:text-gray-300">Cancel</button>
            </form>
          ) : (
            <>
              <a href={entry.url} target="_blank" rel="noreferrer"
                onClick={e => e.stopPropagation()}
                className="text-sm font-medium text-gray-200 flex-1 truncate hover:text-accent-blue transition-colors"
                title={entry.name}>
                {entry.name}
              </a>
              <button type="button" onClick={e => { e.stopPropagation(); setEditingName(true); }}
                className="text-xs text-gray-500 hover:text-gray-300" title="Edit name">✎</button>
            </>
          )}
        </div>
        <span className="text-xs text-gray-600">
          {hasChildMatches
            ? <><span className="text-accent-green font-bold">{matchedChildIds.length}</span> / {children.length || (entry.children?.length ?? "?")} {childLabel}</>  
            : `${children.length || (entry.children?.length ?? "?")} ${childLabel}`}
        </span>
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
        <div className="px-1 mt-2">
          <div className="flex flex-wrap gap-1 mb-2">
            {(tags || []).map(t => (
              <span key={t} className="flex items-center gap-1 px-2 py-0.5 rounded border border-border bg-surface-2 text-xs font-mono">
                <button type="button" onClick={() => onTagClick?.(t)}
                  className="text-gray-500 hover:text-accent-blue transition-colors"># {t}</button>
                <button type="button" onClick={() => handleRemoveTag(t)}
                  className="text-gray-600 hover:text-accent-red transition-colors">✕</button>
              </span>
            ))}
          </div>
          <form onSubmit={handleAddTag} className="flex flex-col gap-2">
            <div className="flex gap-2">
              <input value={tagInput} onChange={e => setTagInput(e.target.value)}
                placeholder="Add tag…"
                className="flex-1 px-2 py-1 rounded text-xs font-mono bg-surface-2 border border-border text-gray-200" />
              <button type="submit" className="px-3 py-1 text-xs rounded border border-border text-gray-400 hover:text-gray-200 hover:border-gray-500 transition-colors">
                + Add
              </button>
            </div>
            {tagSuggestions.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {tagSuggestions.map(s => (
                  <button key={s} type="button" onClick={() => { addTag(s); setTagInput(""); }}
                    className="text-xs px-2 py-0.5 rounded border border-border bg-surface-2 text-gray-500 hover:text-accent-blue transition-colors">
                    {s}
                  </button>
                ))}
              </div>
            )}
          </form>
        </div>
      </div>

      {/* children */}
      {open && (
        <div className="border-t divide-y" style={{ borderColor: childDivColor }}>
          {loadingKids && (
            <div className="px-4 py-3 text-xs text-gray-600 flex items-center gap-2">
              <Spinner sm /> Loading {childLabel}…
            </div>
          )}
          {visibleChildren.map((child, i) => (
            <VideoChildItem key={child.id} child={child} index={i}
              onTagClick={onTagClick}
              onRetried={updated => setChildren(prev => prev.map(c => c.id === updated.id ? updated : c))} />
          ))}
        </div>
      )}
    </div>
  );
}
