import { useState, useEffect } from "react";
import { API } from "../../constants";
import Spinner from "../shared/Spinner";

// ─── RSS tab ──────────────────────────────────────────────────────────────────

export default function RssTab() {
  const [feeds, setFeeds]       = useState([]);
  const [loading, setLoading]   = useState(true);
  const [url, setUrl]           = useState("");
  const [name, setName]         = useState("");
  const [adding, setAdding]     = useState(false);
  const [error, setError]       = useState("");
  const [polling, setPolling]   = useState({}); // { feedId: true }
  const [pollResult, setPollResult] = useState({}); // { feedId: N }

  // YouTube channel subscriptions state
  const [channels, setChannels]         = useState([]);
  const [chLoading, setChLoading]       = useState(true);
  const [chUrl, setChUrl]               = useState("");
  const [chName, setChName]             = useState("");
  const [chPreviewing, setChPreviewing] = useState(false);
  const [chPreview, setChPreview]       = useState(null);   // { channel_id, name, videos }
  const [chSelected, setChSelected]     = useState(new Set()); // selected video URLs
  const [chAdding, setChAdding]         = useState(false);
  const [chError, setChError]           = useState("");
  const [chPolling, setChPolling]       = useState({});
  const [chPollResult, setChPollResult] = useState({});

  async function fetchFeeds() {
    try {
      const data = await (await fetch(`${API}/rss-feeds`)).json();
      setFeeds(Array.isArray(data) ? data : []);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }

  async function fetchChannels() {
    try {
      const data = await (await fetch(`${API}/yt-channels`)).json();
      setChannels(Array.isArray(data) ? data : []);
    } catch (e) { console.error(e); }
    finally { setChLoading(false); }
  }

  useEffect(() => { fetchFeeds(); fetchChannels(); }, []);

  async function handleAdd(e) {
    e.preventDefault();
    setError("");
    if (!url.trim()) return;
    setAdding(true);
    try {
      const res  = await fetch(`${API}/rss-feeds`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim(), name: name.trim() }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.error || "Failed to add feed"); return; }
      setFeeds(prev => [data, ...prev]);
      setUrl(""); setName("");
    } catch (e) { setError("Network error"); }
    finally { setAdding(false); }
  }

  async function handleDelete(id) {
    await fetch(`${API}/rss-feeds/${id}`, { method: "DELETE" });
    setFeeds(prev => prev.filter(f => f.id !== id));
  }

  async function handlePoll(id) {
    setPolling(prev => ({ ...prev, [id]: true }));
    setPollResult(prev => ({ ...prev, [id]: null }));
    try {
      const res  = await fetch(`${API}/rss-feeds/${id}/poll`, { method: "POST" });
      const data = await res.json();
      setPollResult(prev => ({ ...prev, [id]: data.added }));
      fetchFeeds();
    } catch (e) { setPollResult(prev => ({ ...prev, [id]: -1 })); }
    finally { setPolling(prev => ({ ...prev, [id]: false })); }
  }

  // Step 1: fetch channel videos for selection
  async function handleChPreview(e) {
    e.preventDefault();
    setChError("");
    if (!chUrl.trim()) return;
    setChPreviewing(true);
    setChPreview(null);
    try {
      const res  = await fetch(`${API}/yt-channels/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: chUrl.trim() }),
      });
      const data = await res.json();
      if (!res.ok) { setChError(data.error || "Failed to preview channel"); return; }
      setChPreview(data);
      // Pre-select all videos by default
      setChSelected(new Set(data.videos.map(v => v.url)));
    } catch (e) { setChError("Network error"); }
    finally { setChPreviewing(false); }
  }

  function toggleVideo(url) {
    setChSelected(prev => {
      const next = new Set(prev);
      next.has(url) ? next.delete(url) : next.add(url);
      return next;
    });
  }

  function toggleAllVideos(selectAll) {
    if (!chPreview) return;
    setChSelected(selectAll ? new Set(chPreview.videos.map(v => v.url)) : new Set());
  }

  // Step 2: subscribe + queue selected videos for analysis
  async function handleChSubscribe(analyzeSelected) {
    if (!chPreview) return;
    setChAdding(true);
    setChError("");
    try {
      const body = {
        url:          chUrl.trim(),
        name:         chName.trim() || chPreview.name,
        analyze_urls: analyzeSelected ? [...chSelected] : [],
      };
      const res  = await fetch(`${API}/yt-channels`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) { setChError(data.error || "Failed to subscribe"); return; }
      setChannels(prev => [data, ...prev]);
      setChUrl(""); setChName(""); setChPreview(null); setChSelected(new Set());
    } catch (e) { setChError("Network error"); }
    finally { setChAdding(false); }
  }

  async function handleChDelete(id) {
    await fetch(`${API}/yt-channels/${id}`, { method: "DELETE" });
    setChannels(prev => prev.filter(c => c.id !== id));
  }

  async function handleChPoll(id) {
    setChPolling(prev => ({ ...prev, [id]: true }));
    setChPollResult(prev => ({ ...prev, [id]: null }));
    try {
      const res  = await fetch(`${API}/yt-channels/${id}/poll`, { method: "POST" });
      const data = await res.json();
      setChPollResult(prev => ({ ...prev, [id]: data.added }));
      fetchChannels();
    } catch (e) { setChPollResult(prev => ({ ...prev, [id]: -1 })); }
    finally { setChPolling(prev => ({ ...prev, [id]: false })); }
  }

  return (
    <div className="max-w-2xl space-y-10">
      {/* ── RSS Feeds ───────────────────────────────────────── */}
      <div className="space-y-6">
        <div>
          <h2 className="text-sm font-bold text-gray-300 uppercase tracking-widest mb-1">RSS Feeds</h2>
          <p className="text-xs text-gray-600">Add RSS/Atom feeds — the server checks for new posts every hour and adds them to the Knowledge Base automatically. RSS entries are KB-only and won't appear in Suggested Read.</p>
        </div>

        {/* Add feed form */}
        <form onSubmit={handleAdd} className="flex flex-col gap-2">
          <div className="flex gap-2">
            <input value={url} onChange={e => setUrl(e.target.value)}
              placeholder="Feed URL (https://...)"
              className="flex-1 bg-surface-1 border border-border rounded px-3 py-2 text-xs text-gray-200 placeholder-gray-700 font-mono outline-none focus:border-accent-green/50" />
            <input value={name} onChange={e => setName(e.target.value)}
              placeholder="Name (optional)"
              className="w-40 bg-surface-1 border border-border rounded px-3 py-2 text-xs text-gray-200 placeholder-gray-700 font-mono outline-none focus:border-accent-green/50" />
            <button type="submit" disabled={adding || !url.trim()}
              className="px-4 py-2 rounded border border-accent-green/40 text-accent-green text-xs font-bold hover:bg-accent-green/10 transition-colors disabled:opacity-40">
              {adding ? <Spinner sm /> : "+ Add"}
            </button>
          </div>
          {error && <p className="text-xs text-accent-red">{error}</p>}
        </form>

        {/* Feed list */}
        {loading ? (
          <div className="flex items-center gap-2 text-sm text-gray-700"><Spinner /><span>Loading…</span></div>
        ) : feeds.length === 0 ? (
          <div className="text-xs text-gray-700 mt-4">No feeds yet. Add one above.</div>
        ) : (
          <div className="space-y-2">
            {feeds.map(feed => (
              <div key={feed.id} className="flex items-center justify-between gap-3 px-4 py-3 rounded border border-border bg-surface-1">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-gray-200 truncate">{feed.name || feed.url}</span>
                    <span className="flex-shrink-0 px-1.5 py-0.5 rounded border border-orange-400/40 bg-orange-400/10 text-orange-400 text-xs font-bold">RSS</span>
                  </div>
                  {feed.name && <p className="text-xs text-gray-600 font-mono truncate mt-0.5">{feed.url}</p>}
                  <p className="text-xs text-gray-700 mt-0.5">
                    {feed.last_checked
                      ? `Last checked: ${new Date(feed.last_checked).toLocaleString()}`
                      : "Not yet checked"}
                    {" · "}{feed.entry_count ?? 0} RSS entries in KB
                  </p>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  {pollResult[feed.id] != null && (
                    <span className={`text-xs ${pollResult[feed.id] < 0 ? "text-accent-red" : "text-accent-green"}`}>
                      {pollResult[feed.id] < 0 ? "Error" : `+${pollResult[feed.id]} new`}
                    </span>
                  )}
                  <button onClick={() => handlePoll(feed.id)} disabled={polling[feed.id]}
                    className="px-2 py-1 rounded border border-border text-xs text-gray-500 hover:text-accent-blue hover:border-accent-blue/40 transition-colors disabled:opacity-40 flex items-center gap-1">
                    {polling[feed.id] ? <><Spinner sm />Polling…</> : "↻ Poll now"}
                  </button>
                  <button onClick={() => handleDelete(feed.id)}
                    className="text-xs text-gray-700 hover:text-accent-red transition-colors">✕</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── YouTube Subscriptions ───────────────────────────── */}
      <div className="space-y-6">
        <div>
          <h2 className="text-sm font-bold text-gray-300 uppercase tracking-widest mb-1">YouTube Subscriptions</h2>
          <p className="text-xs text-gray-600">Subscribe to a YouTube channel — new videos will be automatically analysed and added to the Knowledge Base every hour. Paste any channel URL (e.g. <span className="font-mono">https://www.youtube.com/@handle</span>).</p>
        </div>

        {/* Step 1: URL form */}
        <form onSubmit={handleChPreview} className="flex flex-col gap-2">
          <div className="flex gap-2">
            <input value={chUrl} onChange={e => { setChUrl(e.target.value); setChPreview(null); }}
              placeholder="Channel URL (https://www.youtube.com/@...)"
              className="flex-1 bg-surface-1 border border-border rounded px-3 py-2 text-xs text-gray-200 placeholder-gray-700 font-mono outline-none focus:border-red-400/50" />
            <input value={chName} onChange={e => setChName(e.target.value)}
              placeholder="Label (optional)"
              className="w-36 bg-surface-1 border border-border rounded px-3 py-2 text-xs text-gray-200 placeholder-gray-700 font-mono outline-none focus:border-red-400/50" />
            <button type="submit" disabled={chPreviewing || chAdding || !chUrl.trim()}
              className="px-4 py-2 rounded border border-red-400/40 text-red-400 text-xs font-bold hover:bg-red-400/10 transition-colors disabled:opacity-40 flex items-center gap-1">
              {chPreviewing ? <><Spinner sm />Loading…</> : "Preview"}
            </button>
          </div>
          {chError && <p className="text-xs text-accent-red">{chError}</p>}
        </form>

        {/* Step 2: Video selection panel */}
        {chPreview && (
          <div className="border border-red-400/20 rounded bg-surface-1 p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-xs font-bold text-gray-200">{chPreview.name}</span>
                <span className="ml-2 text-xs text-gray-600">{chPreview.videos.length} recent videos</span>
              </div>
              <div className="flex items-center gap-3">
                <button onClick={() => toggleAllVideos(true)}
                  className="text-xs text-gray-500 hover:text-gray-300 transition-colors">Select all</button>
                <span className="text-gray-700">·</span>
                <button onClick={() => toggleAllVideos(false)}
                  className="text-xs text-gray-500 hover:text-gray-300 transition-colors">None</button>
                <button onClick={() => { setChPreview(null); setChSelected(new Set()); }}
                  className="text-xs text-gray-700 hover:text-accent-red transition-colors ml-2">✕ Cancel</button>
              </div>
            </div>

            {/* Video list with checkboxes */}
            <div className="space-y-1 max-h-64 overflow-y-auto pr-1">
              {chPreview.videos.map(v => (
                <label key={v.url}
                  className="flex items-start gap-2 px-2 py-1.5 rounded hover:bg-white/5 cursor-pointer group">
                  <input type="checkbox" checked={chSelected.has(v.url)}
                    onChange={() => toggleVideo(v.url)}
                    className="mt-0.5 flex-shrink-0 accent-red-400" />
                  <div className="min-w-0">
                    <p className="text-xs text-gray-300 group-hover:text-gray-100 transition-colors leading-snug">{v.title}</p>
                    {v.published && (
                      <p className="text-xs text-gray-700 mt-0.5">
                        {new Date(v.published).toLocaleDateString()}
                      </p>
                    )}
                  </div>
                </label>
              ))}
            </div>

            {/* Subscribe actions */}
            <div className="flex items-center gap-3 pt-1 border-t border-border">
              <button onClick={() => handleChSubscribe(true)} disabled={chAdding}
                className="px-4 py-2 rounded border border-red-400/40 text-red-400 text-xs font-bold hover:bg-red-400/10 transition-colors disabled:opacity-40 flex items-center gap-1">
                {chAdding ? <><Spinner sm />Subscribing…</> : `Subscribe & analyze ${chSelected.size} selected`}
              </button>
              <button onClick={() => handleChSubscribe(false)} disabled={chAdding}
                className="px-3 py-2 rounded border border-border text-xs text-gray-500 hover:text-gray-300 hover:border-gray-600 transition-colors disabled:opacity-40">
                Subscribe only (no backfill)
              </button>
            </div>
          </div>
        )}

        {/* Subscribed channel list */}
        {chLoading ? (
          <div className="flex items-center gap-2 text-sm text-gray-700"><Spinner /><span>Loading…</span></div>
        ) : channels.length === 0 ? (
          <div className="text-xs text-gray-700 mt-4">No subscriptions yet. Preview a channel above to subscribe.</div>
        ) : (
          <div className="space-y-2">
            {channels.map(ch => (
              <div key={ch.id} className="flex items-center justify-between gap-3 px-4 py-3 rounded border border-border bg-surface-1">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-gray-200 truncate">{ch.name || ch.channel_id}</span>
                    <span className="flex-shrink-0 px-1.5 py-0.5 rounded border border-red-400/40 bg-red-400/10 text-red-400 text-xs font-bold">🎥 YT</span>
                  </div>
                  {ch.name && <p className="text-xs text-gray-600 font-mono truncate mt-0.5">{ch.channel_url}</p>}
                  <p className="text-xs text-gray-700 mt-0.5">
                    {ch.last_checked
                      ? `Last checked: ${new Date(ch.last_checked).toLocaleString()}`
                      : "Not yet checked"}
                  </p>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  {chPollResult[ch.id] != null && (
                    <span className={`text-xs ${chPollResult[ch.id] < 0 ? "text-accent-red" : "text-accent-green"}`}>
                      {chPollResult[ch.id] < 0 ? "Error" : `+${chPollResult[ch.id]} new`}
                    </span>
                  )}
                  <button onClick={() => handleChPoll(ch.id)} disabled={chPolling[ch.id]}
                    className="px-2 py-1 rounded border border-border text-xs text-gray-500 hover:text-accent-blue hover:border-accent-blue/40 transition-colors disabled:opacity-40 flex items-center gap-1">
                    {chPolling[ch.id] ? <><Spinner sm />Polling…</> : "↻ Poll now"}
                  </button>
                  <button onClick={() => handleChDelete(ch.id)}
                    className="text-xs text-gray-700 hover:text-accent-red transition-colors">✕</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
