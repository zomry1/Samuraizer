import { useState, useEffect, useRef } from "react";
import { API, FALLBACK_CHAT_MODELS } from "../../constants";
import { renderMarkdown } from "../../utils/markdown";
import Spinner from "../shared/Spinner";

// ─── chat ─────────────────────────────────────────────────────────────────────

export default function ChatTab({ reembedProgress }) {
  const [sessions,       setSessions]       = useState([]);
  const [activeSession,  setActiveSession]  = useState(null);
  const [messages,       setMessages]       = useState([]);
  const [chatInput,      setChatInput]      = useState("");
  const [chatLoading,    setChatLoading]    = useState(false);
  const [model,          setModel]          = useState("");
  const [chatModels,     setChatModels]     = useState(FALLBACK_CHAT_MODELS);
  const [defaultModel,   setDefaultModel]   = useState("gemini-2.5-flash");
  const [renamingId,     setRenamingId]     = useState(null);
  const [renameVal,      setRenameVal]      = useState("");
  // Pinned entries & autocomplete
  const [pinnedEntries,  setPinnedEntries]  = useState([]);
  const [mention,        setMention]        = useState(null);   // string being typed after @
  const [suggestions,    setSuggestions]    = useState([]);
  const [suggestionIdx,  setSuggestionIdx]  = useState(0);
  // Browse modal
  const [showBrowse,     setShowBrowse]     = useState(false);
  const [browseSearch,   setBrowseSearch]   = useState("");
  const [browseResults,  setBrowseResults]  = useState([]);
  // RAG warning
  const [ragWarning,     setRagWarning]     = useState(null);   // {message, entry_count} | null
  const [localEmbedding, setLocalEmbedding] = useState(null);  // {active, done, total}
  const embedding = reembedProgress || localEmbedding;

  const bottomRef   = useRef(null);
  const textareaRef = useRef(null);

  // Load sessions and provider info on mount
  useEffect(() => {
    fetch(`${API}/chat/sessions`).then(r => r.json()).then(setSessions).catch(console.error);
    fetch(`${API}/provider`).then(r => r.json()).then(data => {
      if (data.models?.length) setChatModels(data.models);
      if (data.default_model) {
        setDefaultModel(data.default_model);
        setModel(prev => prev || data.default_model);
      }
    }).catch(() => {
      setModel(prev => prev || "gemini-2.5-flash");
    });
    // Check embedding health
    fetch(`${API}/embeddings/status`).then(r => r.json()).then(data => {
      if (data.ok === false && !data.error) {
        const missing = Math.max(0, data.missing || 0);
        if (missing > 0) {
          const modelLabel = data.model ? ` for ${data.model}` : "";
          setRagWarning({
            message: `${missing} of ${data.total || 0} entries need embedding${modelLabel}. Chat answers may be incomplete until you re-embed.`,
            entry_count: missing,
          });
        }
      }
    }).catch(() => {});
  }, []);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Autocomplete: fetch suggestions when mention query changes
  useEffect(() => {
    if (mention === null || mention === undefined) { setSuggestions([]); return; }
    const q = mention.trim();
    if (!q) { setSuggestions([]); return; }
    fetch(`${API}/entries/search?q=${encodeURIComponent(q)}`)
      .then(r => r.json())
      .then(rows => { setSuggestions(rows); setSuggestionIdx(0); })
      .catch(() => setSuggestions([]));
  }, [mention]);

  // Browse modal: search entries
  useEffect(() => {
    if (!showBrowse) return;
    const q = browseSearch.trim();
    fetch(`${API}/entries/search?q=${encodeURIComponent(q || " ")}`)
      .then(r => r.json())
      .then(setBrowseResults)
      .catch(() => setBrowseResults([]));
  }, [showBrowse, browseSearch]);

  async function loadSession(session) {
    setActiveSession(session);
    setModel(session.model || defaultModel);
    setPinnedEntries([]);
    const msgs = await fetch(`${API}/chat/sessions/${session.id}/messages`)
      .then(r => r.json()).catch(() => []);
    setMessages(msgs.map(m => ({ ...m, sources: m.sources || [] })));
  }

  async function newChat() {
    setActiveSession(null);
    setMessages([]);
    setChatInput("");
    setPinnedEntries([]);
  }

  async function deleteSession(e, id) {
    e.stopPropagation();
    await fetch(`${API}/chat/sessions/${id}`, { method: "DELETE" });
    setSessions(prev => prev.filter(s => s.id !== id));
    if (activeSession?.id === id) { setActiveSession(null); setMessages([]); }
  }

  async function saveRename(id) {
    const title = renameVal.trim();
    if (!title) { setRenamingId(null); return; }
    await fetch(`${API}/chat/sessions/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    setSessions(prev => prev.map(s => s.id === id ? { ...s, title } : s));
    setRenamingId(null);
  }

  function addPin(entry) {
    setPinnedEntries(prev => prev.find(p => p.id === entry.id) ? prev : [...prev, entry]);
  }
  function removePin(id) {
    setPinnedEntries(prev => prev.filter(p => p.id !== id));
  }

  function pickSuggestion(entry) {
    // Replace the @query in the textarea with just the trimmed text (no @)
    const val = chatInput;
    const replaced = val.replace(/@([\w\s\-.]*)$/, "");
    setChatInput(replaced);
    setMention(null);
    setSuggestions([]);
    addPin(entry);
    textareaRef.current?.focus();
  }

  function handleInputChange(e) {
    const val = e.target.value;
    setChatInput(val);
    // Detect @mention trigger: look for @ followed by text at end of string
    const m = val.match(/@([\w\s\-.]*)$/);
    if (m) {
      setMention(m[1]);
    } else {
      setMention(null);
      setSuggestions([]);
    }
  }

  async function sendMessage() {
    const question = chatInput.trim();
    if (!question || chatLoading) return;
    setChatLoading(true);
    setChatInput("");
    setMention(null);
    setSuggestions([]);

    let session = activeSession;
    if (!session) {
      try {
        const res = await fetch(`${API}/chat/sessions`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model }),
        });
        session = await res.json();
        setActiveSession(session);
        setSessions(prev => [session, ...prev]);
      } catch (err) {
        setChatLoading(false);
        return;
      }
    }

    const pinnedLabels = pinnedEntries.map(p => `@${p.name}`).join(" ");
    const displayText  = pinnedLabels ? `${pinnedLabels}\n${question}` : question;
    const userMsg      = { role: "user",      text: displayText, sources: [], pinned: pinnedEntries.length > 0 };
    const assistantMsg = { role: "assistant", text: "",          sources: [] };
    setMessages(prev => [...prev, userMsg, assistantMsg]);

    const body = { question, session_id: session.id, model };
    if (pinnedEntries.length > 0) body.pinned_ids = pinnedEntries.map(p => p.id);

    try {
      const res = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const errText = await res.text();
        throw new Error(errText || res.statusText || "Chat request failed");
      }
      if (!res.body) {
        throw new Error("No response body from chat endpoint");
      }
      const reader  = res.body.getReader();
      const decoder = new TextDecoder();
      let   buffer  = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          let msg; try { msg = JSON.parse(line); } catch { continue; }
          if (msg.type === "no_rag") {
            setRagWarning({ message: msg.message, entry_count: msg.entry_count });
          } else if (msg.type === "sources") {
            setMessages(prev => {
              const next = [...prev];
              next[next.length - 1] = { ...next[next.length - 1], sources: msg.entries };
              return next;
            });
          } else if (msg.type === "chunk") {
            setMessages(prev => {
              const next = [...prev];
              next[next.length - 1] = { ...next[next.length - 1], text: next[next.length - 1].text + msg.text };
              return next;
            });
          } else if (msg.type === "done") {
            const newTitle = msg.title;
            if (newTitle) {
              setActiveSession(prev => ({ ...prev, title: newTitle }));
              setSessions(prev => prev.map(s => s.id === session.id ? { ...s, title: newTitle, updated_at: new Date().toISOString() } : s));
            }
            fetch(`${API}/chat/sessions`).then(r => r.json()).then(setSessions).catch(console.error);
          } else if (msg.type === "error") {
            setMessages(prev => {
              const next = [...prev];
              next[next.length - 1] = { ...next[next.length - 1], text: `⚠ Error: ${msg.message}` };
              return next;
            });
          }
        }
      }
    } catch (err) {
      setMessages(prev => {
        const next = [...prev];
        next[next.length - 1] = { ...next[next.length - 1], text: `⚠ ${err.message}` };
        return next;
      });
    } finally {
      setChatLoading(false);
    }
  }

  function handleKeyDown(e) {
    // Autocomplete navigation
    if (suggestions.length > 0) {
      if (e.key === "ArrowDown") { e.preventDefault(); setSuggestionIdx(i => Math.min(i + 1, suggestions.length - 1)); return; }
      if (e.key === "ArrowUp")   { e.preventDefault(); setSuggestionIdx(i => Math.max(i - 1, 0)); return; }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        if (suggestions[suggestionIdx]) pickSuggestion(suggestions[suggestionIdx]);
        return;
      }
      if (e.key === "Escape") { setMention(null); setSuggestions([]); return; }
    }
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  }

  return (
    <div className="flex gap-0 h-[calc(100vh-7rem)]" style={{ minHeight: 0 }}>
      {/* ── Sidebar ── */}
      <aside className="w-56 flex-shrink-0 border-r border-border flex flex-col gap-0 pr-3">
        <button onClick={newChat}
          className="w-full mb-3 px-3 py-1.5 rounded border border-accent-green/40 bg-accent-green/10 text-accent-green text-xs font-bold uppercase tracking-wider hover:bg-accent-green/20 transition-colors">
          + New Chat
        </button>
        <div className="overflow-y-auto flex-1 space-y-0.5">
          {sessions.length === 0 && (
            <p className="text-xs text-gray-700 px-1">No saved chats yet.</p>
          )}
          {sessions.map(s => (
            <div key={s.id}
              onClick={() => loadSession(s)}
              className={`group flex items-center gap-1 px-2 py-1.5 rounded cursor-pointer text-xs transition-colors
                ${activeSession?.id === s.id
                  ? "bg-accent-green/10 text-accent-green border border-accent-green/30"
                  : "text-gray-500 hover:text-gray-300 hover:bg-surface-1"}`}>
              {renamingId === s.id ? (
                <input autoFocus value={renameVal}
                  onChange={e => setRenameVal(e.target.value)}
                  onBlur={() => saveRename(s.id)}
                  onKeyDown={e => { if (e.key === "Enter") saveRename(s.id); if (e.key === "Escape") setRenamingId(null); }}
                  onClick={e => e.stopPropagation()}
                  className="flex-1 bg-transparent border-b border-accent-green/50 outline-none text-xs text-gray-200 min-w-0" />
              ) : (
                <span className="flex-1 truncate"
                  onDoubleClick={e => { e.stopPropagation(); setRenamingId(s.id); setRenameVal(s.title || ""); }}>
                  {s.title || <span className="italic text-gray-700">Untitled</span>}
                </span>
              )}
              <button onClick={e => deleteSession(e, s.id)}
                className="opacity-0 group-hover:opacity-100 text-gray-700 hover:text-accent-red transition-all flex-shrink-0 text-[10px]">✕</button>
            </div>
          ))}
        </div>
      </aside>

      {/* ── Chat area ── */}
      <div className="flex-1 flex flex-col min-w-0 pl-4">
        {/* Model picker */}
        <div className="flex items-center gap-3 mb-3 flex-shrink-0">
          <span className="text-xs text-gray-700 uppercase tracking-widest">Model</span>
          <select value={model} onChange={e => setModel(e.target.value)}
            disabled={!!activeSession}
            className="bg-surface-1 border border-border text-gray-300 text-xs px-2 py-1 rounded outline-none disabled:opacity-50">
            {chatModels.map(m => (
              <option key={m.id} value={m.id}>{m.label}</option>
            ))}
          </select>
          {activeSession && (
            <span className="text-[10px] text-gray-700">model locked to session — start a new chat to change</span>
          )}
        </div>

        {/* Re-embed progress banner */}
        {embedding?.active && (
          <div className="mb-3 flex items-center gap-3 rounded border border-blue-500/40 bg-blue-500/10 px-4 py-2.5 text-xs text-blue-200 flex-shrink-0">
            <span className="text-base">⏳</span>
            <span className="flex-1">
              Embedding {embedding.done} / {embedding.total}…
            </span>
          </div>
        )}

        {/* RAG warning toast */}
        {ragWarning && (
          <div className="mb-3 flex items-center gap-3 rounded border border-amber-500/40 bg-amber-500/10 px-4 py-2.5 text-xs text-amber-300 flex-shrink-0">
            <span className="text-base">⚠</span>
            <span className="flex-1">
              {ragWarning.message}
            </span>
            <button
              disabled={embedding?.active}
              onClick={async () => {
                setLocalEmbedding({ active: true, done: 0, total: 0 });
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
                          setLocalEmbedding({ active: true, done: evt.done, total: evt.total });
                        } else if (evt.type === "complete") {
                          result = evt;
                        }
                      } catch {}
                    }
                    if (streamDone) break;
                  }
                  setRagWarning(null);
                  // Re-check status in case not everything got fixed
                  fetch(`${API}/embeddings/status`).then(r => r.json()).then(st => {
                    if (!st.ok && !st.error) {
                      const bad = st.missing || 0;
                      if (bad > 0) {
                        setRagWarning({ message: `Still ${bad} entries need embedding.`, entry_count: bad });
                      }
                    }
                  }).catch(() => {});
                  const r = result || { done: 0, failed: 0 };
                  if (r.done > 0 || r.failed > 0) {
                    setMessages(prev => [...prev, {
                      role: "assistant",
                      text: `✅ Embeddings regenerated — ${r.done} entries embedded${r.failed ? `, ${r.failed} failed` : ""}. Ask your question again for RAG-powered answers.`,
                      sources: [],
                    }]);
                  } else {
                    // no actual work done (up to date), no repetitive message
                  }
                } catch (e) {
                  setMessages(prev => [...prev, { role: "assistant", text: `⚠ Embed failed: ${e.message}`, sources: [] }]);
                } finally {
                  setLocalEmbedding(null);
                }
              }}
              className="whitespace-nowrap rounded border border-amber-500/50 bg-amber-500/20 px-3 py-1 text-amber-200 font-bold uppercase tracking-wider hover:bg-amber-500/30 transition-colors disabled:opacity-50"
            >
              {embedding && embedding.active
                ? embedding.total > 0
                  ? `Embedding ${embedding.done} / ${embedding.total}…`
                  : "Embedding…"
                : "Embed All Entries"}
            </button>
            <button onClick={() => setRagWarning(null)} className="text-amber-500/60 hover:text-amber-300 text-sm">✕</button>
          </div>
        )}

        {/* Messages */}
        <div className="flex-1 overflow-y-auto space-y-4 pr-1" style={{ minHeight: 0 }}>
          {messages.length === 0 && (
            <div className="text-center text-gray-700 text-sm mt-16">
              <div className="text-3xl mb-3">⚔</div>
              <p>Ask anything about your knowledge base.</p>
              <p className="text-xs mt-1 text-gray-800">Answers are grounded in your saved articles and repos.</p>
              <p className="text-xs mt-1 text-gray-800">Type <span className="text-accent-green font-mono">@</span> to pin specific articles as context.</p>
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[80%] rounded-lg px-4 py-2.5 text-sm
                ${msg.role === "user"
                  ? "bg-accent-green/15 border border-accent-green/30 text-gray-200"
                  : "bg-surface-1 border border-border text-gray-300"}`}>
                {msg.role === "assistant" && (
                  <div className="text-[10px] text-accent-green mb-1 font-bold tracking-widest">⚔ SAMURAIZER</div>
                )}
                {msg.text ? (
                  <div
                    className="text-xs leading-relaxed"
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.text) }}
                  />
                ) : msg.role === "assistant" ? (
                  <div className="flex items-center gap-2 text-gray-700"><Spinner sm /><span className="text-xs">Thinking…</span></div>
                ) : null}
                {/* Source cards */}
                {msg.role === "assistant" && msg.sources && msg.sources.length > 0 && (
                  <div className="mt-3 pt-2 border-t border-border/50 space-y-1.5">
                    <p className="text-[10px] text-gray-700 uppercase tracking-widest mb-1">Sources used</p>
                    {msg.sources.map(src => (
                      <div key={src.id} className="flex items-center gap-2 bg-surface rounded px-2 py-1">
                        <a href={src.url} target="_blank" rel="noopener noreferrer"
                          className="flex-1 text-[10px] text-accent-blue hover:underline truncate">{src.name}</a>
                        {src.pinned ? (
                          <span className="text-[9px] text-accent-yellow flex-shrink-0">📌 pinned</span>
                        ) : (
                          <div className="flex items-center gap-1 flex-shrink-0">
                            <div className="w-12 h-1 rounded bg-border overflow-hidden">
                              <div className="h-full bg-accent-green rounded" style={{ width: `${Math.round(src.score * 100)}%` }} />
                            </div>
                            <span className="text-[9px] text-gray-700">{Math.round(src.score * 100)}%</span>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Pinned entry chips */}
        {pinnedEntries.length > 0 && (
          <div className="flex-shrink-0 flex flex-wrap gap-1.5 mt-2 px-1">
            {pinnedEntries.map(p => (
              <span key={p.id}
                className="inline-flex items-center gap-1 bg-accent-yellow/10 border border-accent-yellow/30 text-accent-yellow rounded px-2 py-0.5 text-[10px]">
                📌 {p.name}
                <button onClick={() => removePin(p.id)}
                  className="ml-0.5 text-accent-yellow/60 hover:text-accent-yellow leading-none">✕</button>
              </span>
            ))}
          </div>
        )}

        {/* Input bar */}
        <div className="flex-shrink-0 mt-2 relative">
          {/* Autocomplete dropdown */}
          {suggestions.length > 0 && (
            <div className="absolute bottom-full mb-1 left-0 right-0 z-50 bg-surface-1 border border-border rounded shadow-lg max-h-48 overflow-y-auto">
              {suggestions.map((entry, idx) => (
                <div key={entry.id}
                  onMouseDown={e => { e.preventDefault(); pickSuggestion(entry); }}
                  className={`px-3 py-2 cursor-pointer text-xs flex flex-col gap-0.5
                    ${idx === suggestionIdx ? "bg-accent-green/15 text-accent-green" : "text-gray-300 hover:bg-surface"}`}>
                  <span className="font-medium truncate">{entry.name}</span>
                  <span className="text-[10px] text-gray-700 truncate">{entry.url}</span>
                </div>
              ))}
            </div>
          )}
          <div className="flex gap-2 items-end">
            <textarea
              ref={textareaRef}
              value={chatInput}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              disabled={chatLoading}
              rows={2}
              placeholder="Ask a question… (@ to pin articles, Enter to send)"
              className="flex-1 bg-surface-1 border border-border rounded px-3 py-2 text-xs text-gray-200 placeholder-gray-700 outline-none focus:border-accent-green/50 resize-none disabled:opacity-50 font-mono" />
            {/* @ browse button */}
            <button onClick={() => { setShowBrowse(true); setBrowseSearch(""); }}
              title="Browse entries to pin"
              className="px-3 py-2 rounded bg-surface-1 border border-border text-accent-yellow text-xs hover:bg-accent-yellow/10 hover:border-accent-yellow/40 transition-colors flex-shrink-0 font-bold">
              @
            </button>
            <button onClick={sendMessage} disabled={chatLoading || !chatInput.trim()}
              className="px-4 py-2 rounded bg-accent-green/20 border border-accent-green/40 text-accent-green text-xs font-bold uppercase tracking-wider hover:bg-accent-green/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex-shrink-0">
              {chatLoading ? <Spinner sm /> : "Send"}
            </button>
          </div>
        </div>
      </div>

      {/* ── Browse modal ── */}
      {showBrowse && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
          onClick={() => setShowBrowse(false)}>
          <div className="bg-surface-1 border border-border rounded-lg shadow-2xl w-[520px] max-h-[70vh] flex flex-col"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <span className="text-sm font-bold text-accent-green tracking-wider">Pin Articles to Chat</span>
              <button onClick={() => setShowBrowse(false)} className="text-gray-700 hover:text-gray-300 text-xs">✕ Close</button>
            </div>
            <div className="px-4 py-2 border-b border-border">
              <input autoFocus
                value={browseSearch}
                onChange={e => setBrowseSearch(e.target.value)}
                placeholder="Search entries…"
                className="w-full bg-surface border border-border rounded px-3 py-1.5 text-xs text-gray-200 outline-none focus:border-accent-green/50 placeholder-gray-700" />
            </div>
            <div className="flex-1 overflow-y-auto">
              {browseResults.length === 0 && (
                <p className="text-xs text-gray-700 text-center py-8">No entries found.</p>
              )}
              {browseResults.map(entry => {
                const pinned = !!pinnedEntries.find(p => p.id === entry.id);
                return (
                  <div key={entry.id}
                    className={`flex items-start gap-3 px-4 py-3 border-b border-border/40 cursor-pointer hover:bg-surface transition-colors
                      ${pinned ? "bg-accent-yellow/5" : ""}`}
                    onClick={() => { pinned ? removePin(entry.id) : addPin(entry); }}>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-gray-200 truncate">{entry.name}</p>
                      <p className="text-[10px] text-gray-700 truncate">{entry.url}</p>
                      {entry.category && (
                        <span className="text-[9px] text-accent-blue mt-0.5 inline-block">{entry.category}</span>
                      )}
                    </div>
                    <span className={`flex-shrink-0 text-[10px] font-bold px-2 py-0.5 rounded border
                      ${pinned
                        ? "bg-accent-yellow/15 border-accent-yellow/40 text-accent-yellow"
                        : "bg-surface border-border text-gray-600"}`}>
                      {pinned ? "📌 pinned" : "+ pin"}
                    </span>
                  </div>
                );
              })}
            </div>
            <div className="px-4 py-2 border-t border-border flex items-center justify-between">
              <span className="text-[10px] text-gray-700">{pinnedEntries.length} pinned</span>
              <button onClick={() => setShowBrowse(false)}
                className="px-3 py-1 rounded bg-accent-green/20 border border-accent-green/40 text-accent-green text-xs font-bold hover:bg-accent-green/30 transition-colors">
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
