import { useState, useEffect, useMemo, useRef } from "react";
import { API } from "../../constants";
import Badge from "../shared/Badge";
import CatPicker from "../shared/CatPicker";
import ListMenu from "../shared/ListMenu";
import Spinner from "../shared/Spinner";

// ─── entry card ───────────────────────────────────────────────────────────────

export default function EntryCard({ entry, onToggleRead, onDelete, onTagClick, lists, onAddToList, onRemoveFromList, onUpdate, selected, onSelect, customCats = [], allTags = [] }) {
  const [deleting, setDeleting]       = useState(false);
  const [toggling, setToggling]       = useState(false);
  const [showLists, setShowLists]     = useState(false);
  const [showCatPick, setShowCatPick] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [draftName, setDraftName]     = useState(entry.name || "");
  const [tags, setTags]               = useState(entry.tags || []);
  const [tagInput, setTagInput]       = useState("");
  const catBtnRef = useRef(null);

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

  async function addTag(tag) {
    const newTag = tag.trim();
    if (!newTag) return;
    const nextTags = Array.from(new Set([...(tags || []), newTag]));
    const res = await fetch(`${API}/entries/${entry.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tags: nextTags }),
    });
    if (res.ok) {
      const updated = await res.json();
      setTags(updated.tags || []);
      onUpdate?.(updated);
    }
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

  async function handleAddTag(e) {
    e.preventDefault();
    await addTag(tagInput);
    setTagInput("");
  }

  async function handleRemoveTag(tag) {
    const nextTags = (tags || []).filter(t => t !== tag);
    const res = await fetch(`${API}/entries/${entry.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tags: nextTags }),
    });
    if (res.ok) {
      const updated = await res.json();
      setTags(updated.tags || []);
      onUpdate?.(updated);
    }
  }

  function handleCardClick(e) {
    // If the user clicked on an interactive element, don't navigate.
    if (e.target.closest("button,a,input,textarea,select")) return;
    const target = (entry.has_pdf || entry.url?.startsWith('pdf:')) ? `${API}/entries/${entry.id}/pdf` : entry.url;
    if (target) window.open(target, "_blank");
  }

  function handleCardKeyDown(e) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      const target = (entry.has_pdf || entry.url?.startsWith('pdf:')) ? `${API}/entries/${entry.id}/pdf` : entry.url;
      if (target) window.open(target, "_blank");
    }
  }

  return (
    <div
      className="rounded-lg border bg-surface-1 overflow-hidden"
      style={{ borderColor: selected ? "#3fb950" : "#30363d" }}
    >
      {/* header */}
      <div
        className="flex items-center justify-between px-4 py-2 border-b border-border bg-surface-2 cursor-pointer"
        onClick={handleCardClick}
        onKeyDown={handleCardKeyDown}
        role="button"
        tabIndex={0}
      >
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
          {entry.name && (
            <div className="flex items-center gap-2 min-w-0">
              {editingName ? (
                <form onSubmit={saveName} onClick={e => e.stopPropagation()} className="flex items-center gap-2 min-w-0">
                  <input
                    value={draftName}
                    onChange={e => setDraftName(e.target.value)}
                    className="text-sm font-semibold text-gray-200 truncate bg-surface-2 px-2 py-1 rounded border border-border focus:outline-none focus:border-accent-blue"
                    autoFocus
                  />
                  <button type="submit" className="text-xs text-accent-green hover:text-accent-green/80">Save</button>
                  <button type="button" onClick={() => { setDraftName(entry.name || ""); setEditingName(false); }}
                    className="text-xs text-gray-500 hover:text-gray-300">Cancel</button>
                </form>
              ) : (
                <>
                  <a href={entry.url} target="_blank" rel="noreferrer"
                    className="text-sm font-semibold text-gray-200 truncate hover:text-accent-blue transition-colors"
                    title={entry.name}>
                    {entry.name}
                  </a>
                  <button type="button" onClick={e => { e.stopPropagation(); setEditingName(true); }}
                    className="text-xs text-gray-500 hover:text-gray-300" title="Edit name">✎</button>
                </>
              )}
            </div>
          )}
          {entry.source === "rss" && (
            <span className="flex-shrink-0 px-1.5 py-0.5 rounded border border-orange-400/40 bg-orange-400/10 text-orange-400 text-xs font-bold uppercase tracking-wider">RSS</span>
          )}
          <a href={(entry.has_pdf || entry.url?.startsWith("pdf:")) ? `${API}/entries/${entry.id}/pdf` : entry.url}
            target="_blank" rel="noreferrer"
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
          {entry.has_pdf && (
            <a href={`${API}/entries/${entry.id}/pdf?dl=1`} target="_blank" rel="noreferrer"
              onClick={e => e.stopPropagation()}
              className="text-xs text-gray-700 hover:text-accent-blue transition-colors" title="Download PDF">
              ⬇ PDF
            </a>
          )}
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
      <div className="px-5 pt-2 pb-3">
        <div className="flex flex-wrap gap-1 mb-2">
          {(tags || []).map(tag => (
            <span key={tag} className="flex items-center gap-1 px-2 py-0.5 rounded border border-border bg-surface-2 text-xs font-mono">
              <button type="button" onClick={() => onTagClick?.(tag)}
                className="text-gray-500 hover:text-accent-blue transition-colors">
                #{tag}
              </button>
              <button type="button" onClick={() => handleRemoveTag(tag)}
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
  );
}
