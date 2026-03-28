import { useState, useEffect } from "react";
import { API } from "../../constants";
import EntryCard from "./EntryCard";

// ─── suggest card ─────────────────────────────────────────────────────────────

export default function SuggestCard({ onTagClick, lists, onAddToList, onRemoveFromList, onUpdate, customCats = [] }) {
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
