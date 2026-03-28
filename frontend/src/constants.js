export const API = import.meta.env.VITE_API_URL || "";

export const CATEGORIES = ["all", "tool", "agent", "mcp", "list", "workflow", "cve", "article", "video", "playlist", "blog"];

export const CAT_META = {
  tool:     { label: "Tool",     color: "text-accent-green  border-accent-green/40  bg-accent-green/10",  desc: "Exploit / scanner / framework / PoC" },
  agent:    { label: "Agent",    color: "text-accent-blue   border-accent-blue/40   bg-accent-blue/10",   desc: "Claude Code / AI agent resource" },
  mcp:      { label: "MCP",      color: "text-cyan-400      border-cyan-400/40      bg-cyan-400/10",      desc: "Model Context Protocol server/client" },
  list:     { label: "List",     color: "text-orange-400    border-orange-400/40    bg-orange-400/10",    desc: "Blog / article listing page" },
  workflow: { label: "Workflow", color: "text-accent-purple border-accent-purple/40 bg-accent-purple/10", desc: "Process / checklist / pipeline" },
  cve:      { label: "CVE",      color: "text-accent-red    border-accent-red/40    bg-accent-red/10",    desc: "Vulnerability advisory / bug report" },
  article:  { label: "Article",  color: "text-accent-yellow border-accent-yellow/40 bg-accent-yellow/10", desc: "Blog post / research / writeup" },
  video:    { label: "Video",    color: "text-rose-400      border-rose-400/40      bg-rose-400/10",      desc: "YouTube video / talk / walkthrough" },
  playlist: { label: "Playlist", color: "text-violet-400    border-violet-400/40    bg-violet-400/10",    desc: "YouTube playlist" },
  blog:     { label: "Blog",     color: "text-cyan-400      border-cyan-400/40      bg-cyan-400/10",      desc: "Blog / article listing page" },
  // legacy
  skill:    { label: "Agent",    color: "text-accent-blue   border-accent-blue/40   bg-accent-blue/10",   desc: "Claude Code / AI agent resource" },
};

export const CAT_HEX = {
  tool: "#3fb950", agent: "#58a6ff", skill: "#58a6ff",
  mcp: "#22d3ee", list: "#fb923c",
  workflow: "#bc8cff", cve: "#f85149", article: "#d29922", video: "#fb7185", playlist: "#a78bfa", blog: "#22d3ee",
};

// ─── category picker dropdown ─────────────────────────────────────────────────

export const PICKABLE_CATS = ["tool", "agent", "mcp", "list", "workflow", "cve", "article", "video"];

// Virtual smart list IDs (not real DB lists)
export const SMART_LISTS = [
  { id: "unread", label: "Unread",  icon: "○", color: "text-accent-green",  param: { read: "0" } },
  { id: "read",   label: "Read",    icon: "●", color: "text-gray-500",      param: { read: "1" } },
  { id: "useful", label: "Useful",  icon: "★", color: "text-yellow-400",    param: { useful: "1" } },
];

export const FALLBACK_CHAT_MODELS = [
  { id: "gemini-2.5-flash", label: "2.5 Flash (fast)" },
  { id: "gemini-2.5-pro",   label: "2.5 Pro (deep)" },
  { id: "gemini-1.5-flash", label: "1.5 Flash" },
  { id: "gemini-1.5-pro",   label: "1.5 Pro" },
];

export const LEVEL_STYLES = {
  DEBUG:    { badge: "bg-gray-800 text-gray-500 border-gray-700",               row: "text-gray-600" },
  INFO:     { badge: "bg-accent-green/10 text-accent-green border-accent-green/40",   row: "" },
  WARNING:  { badge: "bg-accent-yellow/10 text-accent-yellow border-accent-yellow/40", row: "text-accent-yellow" },
  ERROR:    { badge: "bg-red-900/30 text-red-400 border-red-600/40",             row: "text-red-400" },
  CRITICAL: { badge: "bg-red-800/50 text-red-300 border-red-400/50",             row: "text-red-300 font-bold" },
};

// Minimum-level ordering — module-level constant, never stale inside closures
export const LEVEL_ORDER = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40, CRITICAL: 50 };
