import { useState, useEffect } from "react";
import { API } from "./constants";
import { parseUrls } from "./utils/parseUrls";
import Spinner from "./components/shared/Spinner";
import ErrorBoundary from "./components/shared/ErrorBoundary";
import AnalyzeTab from "./components/tabs/AnalyzeTab";
import KnowledgeBaseTab from "./components/tabs/KnowledgeBaseTab";
import RssTab from "./components/tabs/RssTab";
import GraphTab from "./components/tabs/GraphTab";
import ChatTab from "./components/tabs/ChatTab";
import SettingsTab from "./components/tabs/SettingsTab";
import LogsTab from "./components/tabs/LogsTab";

// ─── root ─────────────────────────────────────────────────────────────────────

export default function App() {
  const [tab, setTab]           = useState("analyze");
  const [refreshKey, setRefreshKey] = useState(0);
  const [lists, setLists]           = useState([]);
  const [customCats, setCustomCats] = useState([]);
  const [llmProvider, setLlmProvider] = useState(null); // "gemini" | "ollama"

  const [settings, setSettings]         = useState(null);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsStatus, setSettingsStatus] = useState("");
  const [settingsError, setSettingsError] = useState("");
  const [ollamaStatus, setOllamaStatus] = useState({running: null, models: []});
  const [reembedProgress, setReembedProgress] = useState(null); // {active, done, total}
  const [ollamaStatusLoading, setOllamaStatusLoading] = useState(false);

  useEffect(() => {
    let interval = null;

    const fetchReembedStatus = async () => {
      try {
        const res = await fetch(`${API}/entries/embed-all/status`);
        if (!res.ok) return;
        const data = await res.json();
        setReembedProgress(data.active ? data : null);
      } catch {
        // ignore
      }
    };

    fetchReembedStatus();
    interval = setInterval(fetchReembedStatus, 3000);

    return () => clearInterval(interval);
  }, []);

  // Analysis state lives here — survives tab switches
  const [input, setInput]       = useState("");
  const [loading, setLoading]   = useState(false);
  const [progress, setProgress] = useState([]);

  useEffect(() => {
    fetch(`${API}/lists`).then(r => r.json()).then(setLists).catch(console.error);
    fetch(`${API}/categories`).then(r => r.json()).then(setCustomCats).catch(console.error);
    fetch(`${API}/provider`).then(r => r.json()).then(d => setLlmProvider(d.provider || null)).catch(() => {});
    const loadOllamaStatus = () => {
      setOllamaStatusLoading(true);
      fetch(`${API}/ollama/status`).then(r => r.json()).then(d => setOllamaStatus(d)).catch(() => setOllamaStatus({running: false, models: []})).finally(() => setOllamaStatusLoading(false));
    };
    loadOllamaStatus();
    fetch(`${API}/settings`).then(r => r.json()).then(setSettings).catch(err => {
      console.error(err);
      setSettings({
        provider: "ollama",
        gemini_api_key: "",
        ollama_url: "http://localhost:11434",
        ollama_model: "qwen3:4b",
        ollama_embed_model: "qwen3-embedding:8b",
        system_prompt_base: "",
        chat_system_prompt: "",
        ollama_chat_options: JSON.stringify({ temperature: 0.1, num_predict: 2048, top_k: 50, top_p: 0.95 }, null, 2),
        ollama_analyze_options: JSON.stringify({ temperature: 0.3, num_predict: 5000, top_k: 10, top_p: 0.05 }, null, 2),
        ollama_models: ["qwen3:4b", "qwen3:14b", "qwen3:22b", "qwen3:70b"],
        ollama_embedding_models: ["qwen3-embedding:8b", "qwen3-embedding:14b"],
      });
    });
  }, []);

  function handleInputChange(val) {
    setInput(val);
    if (!loading) setProgress([]);
  }

  function handleAddToList(list, entryId) {
    if (!lists.find(l => l.id === list.id)) {
      setLists(prev => [list, ...prev]);
    }
    setProgress(prev => prev.map(p =>
      p.entry?.id === entryId
        ? { ...p, entry: { ...p.entry, list_ids: [...(p.entry.list_ids || []), list.id] } }
        : p
    ));
  }

  function handleRemoveFromList(listId, entryId) {
    setProgress(prev => prev.map(p =>
      p.entry?.id === entryId
        ? { ...p, entry: { ...p.entry, list_ids: (p.entry.list_ids || []).filter(id => id !== listId) } }
        : p
    ));
  }

  async function saveSettings(newSettings) {
    const toSave = newSettings || settings;
    if (!toSave) return;
    setSettingsSaving(true);
    setSettingsStatus("");
    setSettingsError("");
    try {
      const res = await fetch(`${API}/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(toSave),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Could not save settings");
      }
      setSettings(toSave);
      setSettingsStatus("Settings saved. Reload or switch tab for the new provider to take effect.");
      setLlmProvider(data.provider || toSave.provider);
    } catch (err) {
      setSettingsError(err.message || "Could not save settings");
    } finally {
      setSettingsSaving(false);
    }
  }

  async function refreshOllamaStatus() {
    setOllamaStatusLoading(true);
    try {
      const res = await fetch(`${API}/ollama/status`);
      const data = await res.json();
      setOllamaStatus(data);
    } catch (err) {
      setOllamaStatus({ running: false, models: [] });
    } finally {
      setOllamaStatusLoading(false);
    }
  }

  async function startOllamaServe() {
    setOllamaStatusLoading(true);
    try {
      const res = await fetch(`${API}/ollama/serve`, { method: "POST" });
      const data = await res.json();
      if (!res.ok && !data.ok) {
        throw new Error(data.error || "Could not start ollama serve");
      }
      setOllamaStatus({ running: true, models: [], message: data.message });
      setTimeout(refreshOllamaStatus, 2000);
    } catch (err) {
      setOllamaStatus({ running: false, models: [] });
      setSettingsError(err.message || "Could not start Ollama");
    } finally {
      setOllamaStatusLoading(false);
    }
  }

  async function handleSubmitUrls(urls) {
    if (!urls.length || loading) return;
    setLoading(true);
    setProgress(urls.map(url => ({ url, status: "pending", logs: [] })));
    const body = urls.length === 1 ? { url: urls[0] } : { urls };
    try {
      const res     = await fetch(`${API}/analyze`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const reader  = res.body.getReader();
      const decoder = new TextDecoder();
      let   buffer  = "";
      while (true) {
        const { value, done: sd } = await reader.read();
        if (sd) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          let msg; try { msg = JSON.parse(line); } catch { continue; }
          setProgress(prev => prev.map(p => {
            if (p.url !== msg.url) return p;
            if (msg.log)   return { ...p, logs: [...p.logs, msg.log] };
            if (msg.entry) return { ...p, status: "ok",    entry: msg.entry };
            if (msg.error) return { ...p, status: "error", error: msg.error };
            return p;
          }));
        }
      }
      setRefreshKey(k => k + 1);
    } catch (err) {
      setProgress(prev => prev.map(p =>
        p.status === "pending" ? { ...p, status: "error", error: err.message } : p
      ));
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const urls = parseUrls(input);
    await handleSubmitUrls(urls);
  }

  async function handleFileSubmit(file) {
    if (loading) return;
    setLoading(true);
    setProgress([{ url: file.name, status: "pending", logs: [] }]);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res     = await fetch(`${API}/analyze-file`, { method: "POST", body: formData });
      const reader  = res.body.getReader();
      const decoder = new TextDecoder();
      let   buffer  = "";
      while (true) {
        const { value, done: sd } = await reader.read();
        if (sd) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          let msg; try { msg = JSON.parse(line); } catch { continue; }
          setProgress(prev => prev.map(p => {
            if (p.url !== msg.url) return p;
            if (msg.log)   return { ...p, logs: [...p.logs, msg.log] };
            if (msg.entry) return { ...p, status: "ok",    entry: msg.entry };
            if (msg.error) return { ...p, status: "error", error: msg.error };
            return p;
          }));
        }
      }
      setRefreshKey(k => k + 1);
    } catch (err) {
      setProgress(prev => prev.map(p =>
        p.status === "pending" ? { ...p, status: "error", error: err.message } : p
      ));
    } finally {
      setLoading(false);
    }
  }

  async function handleBlogSubmit(url, selectedUrls = null, listingTitle = null) {
    if (loading) return;
    setLoading(true);
    setProgress([{ url, status: "pending", logs: [] }]);
    const body = { url };
    if (selectedUrls) { body.selected_urls = selectedUrls; body.listing_title = listingTitle; }
    try {
      const res     = await fetch(`${API}/analyze-blog`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const reader  = res.body.getReader();
      const decoder = new TextDecoder();
      let   buffer  = "";
      while (true) {
        const { value, done: sd } = await reader.read();
        if (sd) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          let msg; try { msg = JSON.parse(line); } catch { continue; }
          setProgress(prev => prev.map(p => {
            if (p.url !== msg.url) return p;
            if (msg.log)   return { ...p, logs: [...p.logs, msg.log] };
            if (msg.entry) return { ...p, status: "ok",    entry: msg.entry };
            if (msg.error) return { ...p, status: "error", error: msg.error };
            return p;
          }));
        }
      }
      setRefreshKey(k => k + 1);
    } catch (err) {
      setProgress(prev => prev.map(p =>
        p.status === "pending" ? { ...p, status: "error", error: err.message } : p
      ));
    } finally {
      setLoading(false);
    }
  }

  const pendingCount = progress.filter(p => p.status === "pending").length;

  return (
    <div className="min-h-screen bg-surface font-mono flex flex-col">
      <header className="border-b border-border bg-surface-1 flex-shrink-0">
        <div className="max-w-7xl mx-auto px-6 h-12 flex items-center gap-3">
          <span className="text-accent-green font-bold text-base tracking-tight select-none">⚔ SAMURAIZER</span>
          <span className="text-border select-none">│</span>
          <nav className="flex gap-1 ml-2">
            {[
              { id: "analyze", label: "Analyze" },
              { id: "kb",      label: "Knowledge Base" },
              { id: "subscriptions", label: "Subscriptions" },
              { id: "graph",   label: "Graph" },
              { id: "chat",    label: "💬 Chat" },
              { id: "settings", label: "Settings" },
              { id: "logs",    label: "Logs" },
            ].map(({ id, label }) => (
              <button key={id} onClick={() => setTab(id)}
                className={`px-3 py-1 rounded text-xs font-bold uppercase tracking-wider transition-colors flex items-center gap-1.5
                  ${tab === id ? "text-accent-green bg-accent-green/10 border border-accent-green/40" : "text-gray-600 hover:text-gray-400"}`}>
                {label}
                {id === "analyze" && loading && (
                  <span className="flex items-center gap-1">
                    <Spinner sm />
                    {pendingCount > 0 && <span className="text-accent-yellow font-mono">{pendingCount}</span>}
                  </span>
                )}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="flex-1 max-w-7xl mx-auto w-full px-6 py-8">
        {reembedProgress?.active && (
          <div className="mb-4 rounded border border-blue-500/40 bg-blue-500/10 px-4 py-2 text-xs text-blue-200">
            ⏳ Re-embedding: {reembedProgress.done} / {reembedProgress.total} entries
          </div>
        )}
        {tab === "analyze" && (
          <AnalyzeTab input={input} setInput={handleInputChange}
            loading={loading} progress={progress} onSubmit={handleSubmit} onBlogSubmit={handleBlogSubmit}
            onPdfSubmit={handleFileSubmit} llmProvider={llmProvider}
            lists={lists} onAddToList={handleAddToList} onRemoveFromList={handleRemoveFromList}
            customCats={customCats}
            onUpdate={updated => setProgress(prev => prev.map(p =>
              p.entry?.id === updated.id ? { ...p, entry: { ...p.entry, ...updated } } : p
            ))} />
        )}
        {tab === "kb" && (
          <ErrorBoundary>
            <KnowledgeBaseTab refreshKey={refreshKey}
              lists={lists} onListsChange={setLists}
              onAddToList={handleAddToList} onRemoveFromList={handleRemoveFromList}
              customCats={customCats} onCustomCatsChange={setCustomCats}
              onUpdate={updated => setProgress(prev => prev.map(p =>
                p.entry?.id === updated.id ? { ...p, entry: { ...p.entry, ...updated } } : p
              ))} />
          </ErrorBoundary>
        )}
        {tab === "subscriptions" && <RssTab />}
        {tab === "graph" && <GraphTab />}
        {tab === "chat" && <ChatTab reembedProgress={reembedProgress} />}
        {tab === "settings" && (
          <SettingsTab
            settings={settings}
            onChange={setSettings}
            onSave={saveSettings}
            saving={settingsSaving}
            status={settingsStatus}
            error={settingsError}
            ollamaStatus={ollamaStatus}
            ollamaStatusLoading={ollamaStatusLoading}
            refreshOllamaStatus={refreshOllamaStatus}
            startOllamaServe={startOllamaServe}
            onReembedProgress={setReembedProgress}
            reembedProgress={reembedProgress}
          />
        )}
        {tab === "logs" && <LogsTab />}
      </main>
    </div>
  );
}
