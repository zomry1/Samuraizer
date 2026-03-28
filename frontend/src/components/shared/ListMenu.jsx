import { useState, useEffect, useRef } from "react";

// ─── list menu (dropdown to add/remove entry from lists) ─────────────────────

export default function ListMenu({ entry, lists, onAdd, onRemove, onClose }) {
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
