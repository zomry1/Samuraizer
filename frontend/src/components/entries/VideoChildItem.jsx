import { useState, useEffect } from "react";
import { API } from "../../constants";
import Spinner from "../shared/Spinner";

// ─── video child item (used inside playlist card) ────────────────────────────

export default function VideoChildItem({ child, index, onTagClick, onRetried }) {
  const [retrying, setRetrying] = useState(false);
  const [error, setError]       = useState("");
  const [tags, setTags]         = useState(child.tags || []);
  const [tagInput, setTagInput] = useState("");
  const failed = child.tags?.includes("summary-failed");

  useEffect(() => {
    setTags(child.tags || []);
  }, [child.tags]);

  async function addTag(tag) {
    const newTag = tag.trim();
    if (!newTag) return;
    const newTags = Array.from(new Set([...(tags || []), newTag]));
    const res = await fetch(`${API}/entries/${child.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tags: newTags }),
    });
    if (res.ok) {
      const updated = await res.json();
      setTags(updated.tags || []);
      onRetried?.(updated);
    }
  }

  async function removeTag(tag) {
    const newTags = (tags || []).filter(t => t !== tag);
    const res = await fetch(`${API}/entries/${child.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tags: newTags }),
    });
    if (res.ok) {
      const updated = await res.json();
      setTags(updated.tags || []);
      onRetried?.(updated);
    }
  }

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
          <div className="ml-4 mt-2">
            <div className="flex flex-wrap gap-1 mb-2">
              {(tags || []).map(t => (
                <span key={t} className="flex items-center gap-1 px-2 py-0.5 rounded border border-border bg-surface-2 text-xs font-mono">
                  <button type="button" onClick={() => onTagClick?.(t)}
                    className="text-gray-500 hover:text-accent-blue transition-colors"># {t}</button>
                  <button type="button" onClick={() => removeTag(t)}
                    className="text-gray-600 hover:text-accent-red transition-colors">✕</button>
                </span>
              ))}
            </div>
            <form onSubmit={e => { e.preventDefault(); addTag(tagInput); setTagInput(""); }}
              className="flex gap-2">
              <input value={tagInput} onChange={e => setTagInput(e.target.value)}
                placeholder="Add tag…"
                className="flex-1 px-2 py-1 rounded text-xs font-mono bg-surface-2 border border-border text-gray-200" />
              <button type="submit" className="px-3 py-1 text-xs rounded border border-border text-gray-400 hover:text-gray-200 hover:border-gray-500 transition-colors">
                + Add
              </button>
            </form>
          </div>
        </>
      )}
    </div>
  );
}
