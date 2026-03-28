import { useState, useEffect, useRef } from "react";

// ─── bulk action bar ──────────────────────────────────────────────────────────

export default function BulkBar({ count, lists, onAddToList, onMarkRead, onMarkUseful, onDeleteSelected, onClear }) {
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
      <button onClick={onDeleteSelected}
        className="px-3 py-1.5 text-xs rounded border border-border text-accent-red hover:text-white hover:bg-accent-red hover:border-accent-red transition-colors">
        🗑️ Delete
      </button>
      <button onClick={onClear}
        className="px-3 py-1.5 text-xs rounded border border-border text-gray-600 hover:text-gray-400 transition-colors ml-auto">
        ✕ Clear
      </button>
    </div>
  );
}
