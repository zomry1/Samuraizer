import { useState } from "react";
import { API, CATEGORIES, CAT_META } from "../../constants";
import { parseUrls } from "../../utils/parseUrls";
import Spinner from "../shared/Spinner";
import ProgressItem from "../entries/ProgressItem";
import SuggestCard from "../entries/SuggestCard";

// ─── analyze tab ──────────────────────────────────────────────────────────────

export default function AnalyzeTab({ input, setInput, loading, progress, onSubmit, onBlogSubmit, onPdfSubmit, lists, onAddToList, onRemoveFromList, onUpdate, customCats = [], llmProvider }) {
  const [blogInput,    setBlogInput]    = useState("");
  const [scanState,    setScanState]    = useState("idle"); // idle | scanning | results
  const [scanError,    setScanError]    = useState("");
  const [scanTitle,    setScanTitle]    = useState("");
  const [scanLinks,    setScanLinks]    = useState([]); // [{url, title, selected}]
  const [selectedFile, setSelectedFile] = useState(null);
  const urls   = parseUrls(input);
  const isBulk = urls.length > 1;
  const done   = progress.filter(p => p.status !== "pending").length;
  const total  = progress.length;

  function handleFormSubmit(e) {
    e.preventDefault();
    if (selectedFile) { onPdfSubmit(selectedFile); }
    else              { onSubmit(e); }
  }

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
          <form onSubmit={handleFormSubmit} className="flex flex-col gap-2">
            <div className="relative bg-surface-1 border border-border rounded focus-within:border-accent-green/50 transition-colors">
              <textarea value={input} onChange={e => { setInput(e.target.value); setSelectedFile(null); }}
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
              <button type="submit" disabled={loading || (!selectedFile && urls.length === 0)}
                className="px-5 py-2 rounded text-sm font-bold bg-accent-green/10 text-accent-green border border-accent-green/40
                           hover:bg-accent-green/20 disabled:opacity-30 disabled:cursor-not-allowed transition-colors flex items-center gap-2">
                {loading && <Spinner sm />}
                {loading
                  ? (selectedFile ? "Analyzing file…" : (isBulk ? `Analyzing ${done}/${total}…` : "Analyzing…"))
                  : (selectedFile ? `[ ANALYZE FILE ]` : (isBulk ? `[ ANALYZE ${urls.length} ]` : "[ ANALYZE ]"))}
              </button>
              {loading && isBulk && (
                <div className="flex-1 h-1.5 bg-surface-2 rounded-full overflow-hidden">
                  <div className="h-full bg-accent-green transition-all duration-300"
                    style={{ width: `${total ? (done / total) * 100 : 0}%` }} />
                </div>
              )}
            </div>
            <div className="flex items-center gap-2">
              <label className={`flex items-center gap-2 cursor-pointer select-none text-xs transition-colors ${
                selectedFile ? "text-accent-green" : "text-gray-600 hover:text-gray-400"
              } ${loading ? "opacity-40 pointer-events-none" : ""}` }>
                <input type="file" accept=".pdf,.docx,.pptx,.txt,.md" className="hidden" disabled={loading}
                  onChange={e => {
                    const f = e.target.files?.[0];
                    if (f) { setSelectedFile(f); setInput(""); }
                    e.target.value = "";
                  }} />
                <span className="px-3 py-1.5 rounded border border-border bg-surface-1 hover:border-gray-500 transition-colors whitespace-nowrap overflow-hidden max-w-xs text-ellipsis">
                  📄 {selectedFile ? selectedFile.name : "Upload file (PDF | DOCX | PPTX | TXT)"}
                </span>
              </label>
              {selectedFile && (
                <button type="button" onClick={() => setSelectedFile(null)} disabled={loading}
                  className="text-xs text-gray-700 hover:text-accent-red transition-colors disabled:opacity-30">
                  ✕
                </button>
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

      {llmProvider === "ollama" && (
        <div className="mt-4 flex items-start gap-2 rounded border border-accent-yellow/30 bg-accent-yellow/5 px-4 py-2.5 text-xs text-accent-yellow">
          <span className="flex-shrink-0 text-sm leading-none">⚡</span>
          <span>
            <strong>Local mode (Ollama)</strong> — Analysis speed depends on your hardware (GPU, RAM). First request may be slower while the model loads into memory.
          </span>
        </div>
      )}

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
