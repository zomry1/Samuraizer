import { useState, useEffect, useRef } from "react";
import { API } from "../../constants";

export default function SettingsTab({ settings, onChange, onSave, saving, status, error, ollamaStatus, ollamaStatusLoading, refreshOllamaStatus, startOllamaServe, onReembedProgress, reembedProgress }) {
  const [localSettings, setLocalSettings] = useState(settings || {});
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [pullingModel, setPullingModel] = useState(false);
  const [pullLogs, setPullLogs] = useState([]);
  const [pullStatus, setPullStatus] = useState("");
  const [embedConfirmOpen, setEmbedConfirmOpen] = useState(false);
  // display global progress in settings page too
  const activeReembed = reembedProgress?.active;
  const reembedDone = reembedProgress?.done || 0;
  const reembedTotal = reembedProgress?.total || 0;
  const [pendingEmbedModel, setPendingEmbedModel] = useState("");
  const [reembedStatus, setReembedStatus] = useState("");
  const [reembedLogs, setReembedLogs] = useState([]);
  const [reembedError, setReembedError] = useState("");
  const reembedLogRef = useRef(null);
  const pullLogRef = useRef(null);

  useEffect(() => {
    if (settings) {
      setLocalSettings(settings);
    }
  }, [settings]);

  if (!settings) {
    return <div>Loading settings…</div>;
  }

  const provider = localSettings.provider || "ollama";
  const ollamaModels = localSettings.ollama_models || ["qwen3:4b", "qwen3:14b", "qwen3:22b", "qwen3:70b"];
  const ollamaEmbedModels = localSettings.ollama_embedding_models || ["qwen3-embedding:8b", "qwen3-embedding:14b"];
  const isOllamaBusy = ollamaStatusLoading || pullingModel;

  const installedModels = (ollamaStatus?.models || []).map(m => m.name);
  const selectedModel = localSettings.ollama_model || "";
  const needsPull = provider === "ollama" && selectedModel && !installedModels.includes(selectedModel);
  const embedModel = localSettings.ollama_embed_model || "";
  const embedNeedsPull = provider === "ollama" && embedModel && !installedModels.includes(embedModel);

  const analyzePromptValid = (localSettings.system_prompt_base || "").includes("{categories}") && (localSettings.system_prompt_base || "").includes("{custom_section}");
  const chatPromptValid = (localSettings.chat_system_prompt || "").includes("{context}");
  const settingsValid = analyzePromptValid && chatPromptValid;

  const selectedModelBorderClass = (!selectedModel || installedModels.includes(selectedModel))
    ? "border-border"
    : "border-red-500";
  const selectedEmbedBorderClass = (!embedModel || installedModels.includes(embedModel))
    ? "border-border"
    : "border-red-500";

  useEffect(() => {
    if (reembedLogRef.current) {
      reembedLogRef.current.scrollTop = reembedLogRef.current.scrollHeight;
    }
  }, [reembedLogs]);

  useEffect(() => {
    if (pullLogRef.current) {
      pullLogRef.current.scrollTop = pullLogRef.current.scrollHeight;
    }
  }, [pullLogs]);

  async function pullModel(model = selectedModel) {
    if (!model) return;
    setPullingModel(true);
    setPullStatus("Pull in progress...");
    setPullLogs([`Starting pull: ${model}`]);
    const seenPullLines = new Set();

    function appendUniqueLog(line) {
      if (!seenPullLines.has(line)) {
        seenPullLines.add(line);
        setPullLogs(prev => [...prev, line]);
      }
    }

    try {
      const res = await fetch(`${API}/ollama/pull`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model }),
      });
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { value, done } = await reader.read();
        if (value) buf += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf("\n")) !== -1) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (!line) continue;
          try {
            const evt = JSON.parse(line);
            if (evt.type === "progress") {
              appendUniqueLog(evt.line);
            } else if (evt.type === "started") {
              appendUniqueLog(evt.message);
            } else if (evt.type === "complete") {
              appendUniqueLog(`Pull complete: ${evt.model}`);
              setPullStatus("Success: model pulled");
              if (model === localSettings.ollama_embed_model) {
                setReembedError("");
              }
            } else if (evt.type === "error") {
              appendUniqueLog(`Error: ${evt.message}`);
              setPullStatus(`Error: ${evt.message}`);
            }
          } catch (err) {
            appendUniqueLog(line);
          }
        }
        if (done) break;
      }
      await refreshOllamaStatus();
      if (model === localSettings.ollama_embed_model) {
        setReembedError("");
        // Automatically prompt re-embed now that model is available
        setPendingEmbedModel(model);
        setEmbedConfirmOpen(true);
      }
    } catch (err) {
      const msg = err.message || String(err);
      setPullLogs(prev => [...prev, `Pull failed: ${msg}`]);
      setPullStatus(`Error: ${msg}`);
    } finally {
      setPullingModel(false);
    }
  }

  async function onEmbedModelSelect(newModel) {
    if (!newModel || newModel === embedModel) {
      return;
    }

    setLocalSettings({ ...localSettings, ollama_embed_model: newModel });
    setPendingEmbedModel(newModel);

    if (!installedModels.includes(newModel)) {
      setReembedError(`Embedding model ${newModel} is not installed yet. Pull it first.`);
      setEmbedConfirmOpen(false);
      return;
    }

    setReembedError("");
    setEmbedConfirmOpen(true);
  }

  async function confirmEmbedModelChange() {
    if (!pendingEmbedModel) return;
    if (!installedModels.includes(pendingEmbedModel)) {
      setReembedError(`Embedding model ${pendingEmbedModel} is not installed yet. Pull it first.`);
      setEmbedConfirmOpen(false);
      return;
    }

    const old = localSettings.ollama_embed_model;
    const newSettings = { ...localSettings, ollama_embed_model: pendingEmbedModel };
    setLocalSettings(newSettings);

    // Persist immediately even if user has not clicked Save.
    await onSave(newSettings);

    setEmbedConfirmOpen(false);
    setPendingEmbedModel("");
    setReembedStatus(`Re-embedding entries for new model ${pendingEmbedModel}...`);
    setReembedError("");
    setReembedLogs([`Embed model changed from ${old || "(unset)"} to ${pendingEmbedModel}.`]);
    onReembedProgress?.({ active: true, done: 0, total: 0 });

    try {
      const res = await fetch(`${API}/entries/embed-all?all=true`, { method: "POST" });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(`${res.status}: ${body}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { value, done } = await reader.read();
        if (value) buf += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf("\n")) !== -1) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (!line) continue;
          try {
            const evt = JSON.parse(line);
            if (evt.type === "progress") {
              setReembedLogs(prev => [...prev, `progress ${evt.done || 0}/${evt.total || "?"} ${evt.name || ""}`]);
              onReembedProgress?.({ active: true, done: evt.done || 0, total: evt.total || 0 });
            } else if (evt.type === "complete") {
              setReembedLogs(prev => [...prev, `Embedding complete: ${evt.done}/${evt.total} done (${evt.failed} failed)`]);
              setReembedStatus("Re-embedding complete");
              onReembedProgress?.({ active: false, done: evt.done || 0, total: evt.total || 0 });
            } else if (evt.type === "error") {
              setReembedLogs(prev => [...prev, `Error: ${evt.message}`]);
              setReembedStatus(`Error: ${evt.message}`);
              onReembedProgress?.(null);
            }
          } catch (_err) {
            setReembedLogs(prev => [...prev, line]);
          }
        }
        if (done) break;
      }
    } catch (err) {
      const msg = err.message || String(err);
      setReembedLogs(prev => [...prev, `Re-embed failed: ${msg}`]);
      setReembedStatus(`Error: ${msg}`);
    }
  }

  function cancelEmbedChange() {
    setEmbedConfirmOpen(false);
    setPendingEmbedModel("");
  }

  return (
    <div className="space-y-4">
      <div className="p-4 border border-border rounded bg-surface-1">
        {activeReembed && (
          <div className="mb-3 rounded border border-blue-500/40 bg-blue-500/10 px-2 py-1 text-xs text-blue-200">
            ⏳ Re-embedding: {reembedDone} / {reembedTotal} entries
          </div>
        )}
        <h2 className="text-sm font-bold mb-3">LLM Provider</h2>
        <div className="flex gap-4">
          <label className="inline-flex items-center gap-2 text-xs">
            <input type="radio" checked={provider === "gemini"} onChange={() => setLocalSettings({ ...localSettings, provider: "gemini" })} />
            Gemini
          </label>
          <label className="inline-flex items-center gap-2 text-xs">
            <input type="radio" checked={provider === "ollama"} onChange={() => setLocalSettings({ ...localSettings, provider: "ollama" })} />
            Ollama
          </label>
        </div>
      </div>

      {provider === "gemini" && (
        <div className="p-4 border border-border rounded bg-surface-1 space-y-2">
          <label className="block text-xs font-bold">Gemini API Key</label>
          <input type="text" value={settings.gemini_api_key || ""}
            onChange={e => onChange({ ...settings, gemini_api_key: e.target.value })}
            className="w-full px-2 py-2 rounded border border-border bg-surface focus:outline-none focus:ring-2 focus:ring-accent-green" />
          <p className="text-[11px] text-gray-500">Set your GEMINI_API_KEY here. This overwrites .env on save.</p>
        </div>
      )}

      {provider === "ollama" && (
        <div className="relative p-4 border border-border rounded bg-surface-1 space-y-3">
          {isOllamaBusy && (
            <div className="absolute inset-0 z-20 bg-black/20 backdrop-blur-sm flex items-center justify-center pointer-events-none">
              <div className="inline-flex items-center gap-2 text-xs text-white">
                <span className="h-3 w-3 rounded-full border-2 border-white border-t-transparent animate-spin"/>
                Working...
              </div>
            </div>
          )}
          <div className="grid grid-cols-1 gap-3">
            <label className="block text-xs font-bold">Ollama URL</label>
            <input type="text" value={localSettings.ollama_url || ""}
              onChange={e => setLocalSettings({ ...localSettings, ollama_url: e.target.value })}
              className="w-full px-2 py-2 rounded border border-border bg-surface focus:outline-none focus:ring-2 focus:ring-accent-green" />
            <p className="text-[11px] text-gray-500">Ollama server URL (default: http://localhost:11434).</p>
          </div>

          <div className="flex items-center justify-between gap-2 p-3 rounded border border-border bg-black/5 text-xs">
            <span>
              Ollama status: <strong>{ollamaStatusLoading ? "Checking…" : ollamaStatus?.running ? "Running" : "Stopped"}</strong>
            </span>
            <div className="flex gap-2">
              <button onClick={refreshOllamaStatus} disabled={ollamaStatusLoading || pullingModel} className="px-2 py-1 bg-surface-2 border border-border rounded text-[11px] disabled:opacity-50 disabled:cursor-wait">Refresh</button>
              {!ollamaStatus?.running && !ollamaStatusLoading && (
                <button onClick={startOllamaServe} className="px-2 py-1 bg-yellow-500 text-black rounded text-[11px]">Start ollama serve</button>
              )}
            </div>
          </div>

          {ollamaStatusLoading ? (
            <div className="p-4 rounded border border-border bg-surface text-center text-sm text-gray-400 flex items-center justify-center gap-2" style={{ opacity: 0, animation: "fadeIn 0.35s ease-out forwards" }}>
              <span className="h-4 w-4 rounded-full border-2 border-gray-300 border-t-transparent animate-spin" />
              <span>Loading Ollama model metadata…</span>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 fade-in">
            <label className="block text-xs font-bold">Installed Ollama models</label>
            <div className="min-h-[72px] p-2 rounded border border-border bg-surface overflow-auto text-[11px]">
              {ollamaStatus?.models?.length ? ollamaStatus.models.map(m => {
                const isInstalled = m.status?.toLowerCase().includes("installed")
                  || m.name === selectedModel
                  || m.name === localSettings.ollama_embed_model;
                return (
                  <div key={m.name} className="flex items-center gap-2">
                    <span>{m.name} ({m.size ? `${(m.size/1024/1024/1024).toFixed(1)}GB` : "unknown"})</span>
                    {isInstalled && (
                      <span className="text-[10px] bg-accent-green/20 text-accent-green px-1.5 py-0.5 rounded">Installed</span>
                    )}
                  </div>
                );
              }) : <span className="text-gray-500">No models found</span>}
            </div>
          </div>
          )}

          <div className="grid grid-cols-1 gap-3">
            <label className="block text-xs font-bold">General model</label>
            <select value={localSettings.ollama_model || "qwen3:4b"}
              onChange={e => setLocalSettings({ ...localSettings, ollama_model: e.target.value })}
              className={`w-full px-2 py-2 rounded border ${selectedModelBorderClass} bg-surface focus:outline-none focus:ring-2 focus:ring-accent-green`}>
              {ollamaModels.map(m => {
                const isInstalled = installedModels.includes(m);
                return (
                  <option key={m} value={m}>
                    {isInstalled ? "✅ " : "⚪ "}{m}
                  </option>
                );
              })}
            </select>
            <p className={`text-[11px] ${needsPull ? "text-red-300" : "text-gray-500"}`}>Suggested: qwen3:4b</p>
            {needsPull && (
              <div className="mt-2 p-2 bg-surface-2 border border-red-500/50 rounded text-xs text-red-200">
                Selected model is not installed.
                <button onClick={pullModel} disabled={pullingModel}
                  className="ml-1 text-accent-blue font-bold underline"
                >{pullingModel ? "Pulling…" : "Pull model now"}</button>
              </div>
            )}
          </div>
          <div className="grid grid-cols-1 gap-3">
            <label className="block text-xs font-bold">Embedding model</label>
            <select value={localSettings.ollama_embed_model || "qwen3-embedding:8b"}
              onChange={e => onEmbedModelSelect(e.target.value)}
              className={`w-full px-2 py-2 rounded border ${selectedEmbedBorderClass} bg-surface focus:outline-none focus:ring-2 focus:ring-accent-green`}>
              {ollamaEmbedModels.map(m => {
                const installed = installedModels.includes(m);
                return (
                  <option key={m} value={m}>
                    {installed ? "✅ " : "⚪ "}{m}
                  </option>
                );
              })}
            </select>
            <p className={`text-[11px] ${embedNeedsPull ? "text-red-300" : "text-gray-500"}`}>Suggested: qwen3-embedding:8b</p>
            {embedModel && embedNeedsPull && (
              <div className="mt-2 p-2 bg-surface-2 border border-red-500/50 rounded text-xs text-red-200">
                Embedding model is not installed.
                <button
                  onClick={() => pullModel(embedModel)} disabled={pullingModel}
                  className="ml-1 inline-flex items-center gap-1 text-accent-blue font-bold underline disabled:opacity-50 disabled:cursor-wait"
                >
                  {pullingModel ? (
                    <><span className="h-3 w-3 rounded-full border-2 border-current border-t-transparent animate-spin" />Pulling…</>
                  ) : (
                    <>Pull model now</>
                  )}
                </button>
              </div>
            )}
          </div>

          {pullStatus && (
            <div className={`p-2 rounded border text-xs font-semibold ${pullStatus.startsWith('Error') ? 'text-accent-red border-accent-red/30 bg-red-950/20' : 'text-accent-green border-accent-green/30 bg-accent-green/10'}`}>
              {pullStatus}
            </div>
          )}

          {reembedStatus && (
            <div className={`p-2 rounded border text-xs font-semibold ${reembedStatus.startsWith('Error') ? 'text-accent-red border-accent-red/30 bg-red-950/20' : 'text-accent-green border-accent-green/30 bg-accent-green/10'}`}>
              {reembedStatus}
            </div>
          )}
          {reembedError && (
            <div className="p-2 rounded border border-accent-red/30 text-accent-red text-xs">
              {reembedError}
            </div>
          )}

          {reembedLogs.length > 0 && (
            <div ref={reembedLogRef} className="p-2 rounded border border-border bg-surface-2 text-xs font-mono max-h-40 overflow-auto">
              {reembedLogs.map((l, i) => {
                const isError = l.toLowerCase().includes("error");
                const isComplete = l.toLowerCase().includes("complete");
                return (
                  <div key={i} className={`py-0.5 ${isError ? "text-red-300" : ""} ${isComplete ? "text-emerald-300" : ""}`}>
                    {l}
                  </div>
                );
              })}
            </div>
          )}

          {embedConfirmOpen && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
              <div className="w-full max-w-md rounded border border-border bg-surface p-4">
                <h3 className="text-sm font-bold mb-2">Change embedding model?</h3>
                <p className="text-[12px] mb-3">
                  Switching the embedding model requires re-embedding every entry in the database.
                  This operation can take a while. Do you want to continue?
                </p>
                <div className="flex justify-end gap-2">
                  <button onClick={cancelEmbedChange} className="px-2 py-1 rounded border border-border text-xs">Cancel</button>
                  <button onClick={confirmEmbedModelChange} className="px-2 py-1 rounded bg-accent-green text-black text-xs">Re-embed</button>
                </div>
              </div>
            </div>
          )}

          {pullLogs.length > 0 && (
            <div className="p-2 rounded border border-border bg-surface-2 text-xs font-mono max-h-40 overflow-auto">
              {pullLogs.map((l, i) => {
                const isError = l.toLowerCase().includes("error");
                const isComplete = l.toLowerCase().includes("complete");
                return (
                  <div
                    key={i}
                    className={`py-0.5 ${isError ? "text-red-300" : ""} ${isComplete ? "text-emerald-300" : ""}`}
                  >
                    {l}
                  </div>
                );
              })}
            </div>
          )}

          <div className="p-3 border border-border rounded bg-surface-2">
            <button onClick={() => setAdvancedOpen(prev => !prev)}
              className="text-xs font-bold text-accent-blue hover:text-accent-green">
              {advancedOpen ? "Hide" : "Show"} advanced Ollama settings
            </button>
            {advancedOpen && (
              <div className="space-y-3 mt-3">
                <div>
                  <label className="block text-xs font-bold">System prompt (analyze)</label>
                  <textarea
                    value={localSettings.system_prompt_base || ""}
                    onChange={e => setLocalSettings({ ...localSettings, system_prompt_base: e.target.value })}
                    rows={6}
                    className="w-full p-2 rounded border border-border bg-surface text-xs font-mono"
                  />
                  {!analyzePromptValid && (
                    <p className="text-[11px] text-accent-red mt-1">
                      Analyze system prompt must include <code>{"{categories}"}</code> and <code>{"{custom_section}"}</code>.
                    </p>
                  )}
                </div>

                <div>
                  <label className="block text-xs font-bold">System prompt (chat)</label>
                  <textarea
                    value={localSettings.chat_system_prompt || ""}
                    onChange={e => setLocalSettings({ ...localSettings, chat_system_prompt: e.target.value })}
                    rows={4}
                    className="w-full p-2 rounded border border-border bg-surface text-xs font-mono"
                  />
                  {!chatPromptValid && (
                    <p className="text-[11px] text-accent-red mt-1">
                      Chat system prompt must include <code>{"{context}"}</code> (includes pulled KB context).
                    </p>
                  )}
                </div>

                <div>
                  <label className="block text-xs font-bold">Ollama chat options (JSON)</label>
                  <textarea
                    value={localSettings.ollama_chat_options || ""}
                    onChange={e => setLocalSettings({ ...localSettings, ollama_chat_options: e.target.value })}
                    rows={4}
                    className="w-full p-2 rounded border border-border bg-surface text-xs font-mono"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold">Ollama analyze options (JSON)</label>
                  <textarea
                    value={localSettings.ollama_analyze_options || ""}
                    onChange={e => setLocalSettings({ ...localSettings, ollama_analyze_options: e.target.value })}
                    rows={4}
                    className="w-full p-2 rounded border border-border bg-surface text-xs font-mono"
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {pullLogs.length > 0 && (
        <div ref={pullLogRef} className="p-3 rounded border border-border bg-surface-2 text-xs font-mono max-h-40 overflow-auto">
          {pullLogs.map((l, i) => <div key={i}>{l}</div>)}
        </div>
      )}
      <div className="flex gap-2 items-center">
        <button onClick={() => onSave(localSettings)} disabled={saving || !settingsValid}
          className="px-3 py-2 rounded bg-accent-green text-black text-xs font-bold transition hover:bg-accent-green/90 disabled:opacity-50">
          {saving ? "Saving…" : "Save Settings"}
        </button>
        {!settingsValid && (
          <span className="text-xs text-accent-red">Please fix system prompt placeholders before saving.</span>
        )}
        {status && <span className="text-xs text-accent-green">{status}</span>}
        {error && <span className="text-xs text-accent-red">{error}</span>}
      </div>
    </div>
  );
}
