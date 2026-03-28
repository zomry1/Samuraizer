import { useState } from "react";
import PlaylistCard from "./PlaylistCard";
import EntryCard from "./EntryCard";
import LogLines from "../shared/LogLines";
import Spinner from "../shared/Spinner";

export default function ProgressItem({ item, lists, onAddToList, onRemoveFromList, onUpdate, customCats = [] }) {
  const [logsOpen, setLogsOpen] = useState(true);

  if (item.status === "ok") {
    const card = ["playlist", "blog"].includes(item.entry?.category)
      ? <PlaylistCard entry={item.entry} customCats={customCats} onUpdate={onUpdate} />
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
    const ollamaMatch = item.error?.match(/^(Cannot connect to Ollama[^.]*\.)\s*(.*?):\s*\n([\s\S]*)$/);
    const errorContent = ollamaMatch ? (
      <div className="mt-1 space-y-1.5">
        <div className="font-bold text-accent-red">{ollamaMatch[1]}</div>
        <div className="text-accent-red/80">{ollamaMatch[2]}:</div>
        <ol className="list-decimal list-inside space-y-1 text-accent-red/80 pl-1">
          <li>Start Ollama: <code className="bg-accent-red/10 rounded px-1 py-0.5">ollama serve</code></li>
          {ollamaMatch[3].trim().split("\n").map((cmd, i) => (
            <li key={i}>Pull model: <code className="bg-accent-red/10 rounded px-1 py-0.5">{cmd.trim()}</code></li>
          ))}
        </ol>
      </div>
    ) : (
      <div className="text-accent-red/70 mt-0.5">{item.error}</div>
    );
    return (
      <div className="rounded border border-accent-red/30 bg-accent-red/5 overflow-hidden">
        <div className="flex items-start gap-2 px-4 py-3 text-xs text-accent-red">
          <span className="flex-shrink-0">✗</span>
          <div className="min-w-0">
            <div className="font-mono truncate">{item.url}</div>
            {errorContent}
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
