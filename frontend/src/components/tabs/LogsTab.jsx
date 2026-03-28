import { useState, useEffect, useRef, useMemo } from "react";
import { API, LEVEL_STYLES, LEVEL_ORDER } from "../../constants";
import Spinner from "../shared/Spinner";

// ─── logs tab ─────────────────────────────────────────────────────────────────

const LEVELS = ["ALL", "DEBUG", "INFO", "WARNING", "ERROR"];

export default function LogsTab() {
  const [logs, setLogs]             = useState([]);
  const [levelFilter, setLevelFilter] = useState("ALL");
  const [nameFilter, setNameFilter]   = useState("ALL"); // "ALL" | "ollama"
  const [autoScroll, setAutoScroll]   = useState(true);
  const lastIdRef  = useRef(0);
  const bottomRef  = useRef(null);

  async function fetchLogs(since) {
    try {
      const data = await (await fetch(`${API}/logs?since=${since}`)).json();
      if (data.length) {
        lastIdRef.current = data[data.length - 1].id;
        setLogs(prev => [...prev, ...data]);
      }
    } catch { /* ignore network errors */ }
  }

  useEffect(() => {
    fetchLogs(0);
    const iv = setInterval(() => fetchLogs(lastIdRef.current), 3000);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs, autoScroll]);

  async function handleClear() {
    try {
      await fetch(`${API}/logs`, { method: "DELETE" });
      setLogs([]);
      lastIdRef.current = 0;
    } catch { /* ignore */ }
  }

  const counts = useMemo(() => {
    const c = { ALL: logs.length, DEBUG: 0, INFO: 0, WARNING: 0, ERROR: 0 };
    for (const l of logs) {
      const ord = LEVEL_ORDER[l.level] ?? 20;
      if (ord >= 10) c.DEBUG++;
      if (ord >= 20) c.INFO++;
      if (ord >= 30) c.WARNING++;
      if (ord >= 40) c.ERROR++;
    }
    return c;
  }, [logs]);

  // Computed directly (no useMemo) so levelFilter is always the current render value
  const minOrd  = levelFilter === "ALL" ? 0 : (LEVEL_ORDER[levelFilter] ?? 0);
  const visible = logs.filter(l => {
    if (levelFilter !== "ALL" && (LEVEL_ORDER[l.level] ?? 20) < minOrd) return false;
    if (nameFilter === "ollama" && l.name !== "ollama") return false;
    return true;
  });

  const ollamaCount = useMemo(() => logs.filter(l => l.name === "ollama").length, [logs]);

  const activeBtnCls = {
    ALL:     "bg-accent-green/10 text-accent-green border-accent-green/40",
    DEBUG:   "bg-gray-800 text-gray-300 border-gray-600",
    INFO:    "bg-accent-green/10 text-accent-green border-accent-green/40",
    WARNING: "bg-accent-yellow/10 text-accent-yellow border-accent-yellow/40",
    ERROR:   "bg-red-900/30 text-red-400 border-red-500/40",
  };

  return (
    <div className="flex flex-col gap-3" style={{ height: "calc(100vh - 8rem)" }}>
      {/* toolbar */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex gap-1">
          {LEVELS.map(lv => (
            <button key={lv} onClick={() => setLevelFilter(lv)}
              className={`px-2.5 py-0.5 rounded border text-xs font-bold uppercase tracking-wide transition-colors
                ${levelFilter === lv ? activeBtnCls[lv] : "text-gray-600 border-gray-800 hover:text-gray-400 hover:border-gray-600"}`}>
              {lv}
              {counts[lv] != null && <span className="ml-1 opacity-60">{counts[lv]}</span>}
            </button>
          ))}
        </div>
        <div className="w-px h-5 bg-gray-700" />
        <button onClick={() => setNameFilter(f => f === "ollama" ? "ALL" : "ollama")}
          className={`px-2.5 py-0.5 rounded border text-xs font-bold uppercase tracking-wide transition-colors
            ${nameFilter === "ollama"
              ? "bg-purple-900/30 text-purple-400 border-purple-500/40"
              : "text-gray-600 border-gray-800 hover:text-gray-400 hover:border-gray-600"}`}>
          🦙 OLLAMA
          {ollamaCount > 0 && <span className="ml-1 opacity-60">{ollamaCount}</span>}
        </button>
        <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none ml-auto">
          <input type="checkbox" checked={autoScroll} onChange={e => setAutoScroll(e.target.checked)}
            className="accent-accent-green" />
          Auto-scroll
        </label>
        <button onClick={handleClear}
          className="px-3 py-1 rounded border border-red-800/50 text-red-500 text-xs hover:bg-red-900/20 transition-colors">
          Clear
        </button>
      </div>

      {/* log list */}
      <div className="flex-1 overflow-y-auto border border-border rounded bg-surface-1 p-3 font-mono text-xs">
        {visible.length === 0 && (
          <div className="text-gray-700 text-center py-8">No log entries.</div>
        )}
        {visible.map(l => {
          const sty = LEVEL_STYLES[l.level] || LEVEL_STYLES.INFO;
          return (
            <div key={l.id} className={`flex items-start gap-2 py-0.5 leading-snug ${sty.row}`}>
              <span className="flex-shrink-0 text-gray-600 tabular-nums">{l.ts}</span>
              <span className={`flex-shrink-0 px-1.5 rounded border text-[10px] font-bold uppercase leading-[1.4] ${sty.badge}`}>{l.level}</span>
              <span className="flex-shrink-0 text-gray-700 max-w-[120px] truncate" title={l.name}>{l.name}</span>
              <span className="break-all">{l.msg}</span>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
