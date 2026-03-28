import { useState, useEffect, useRef } from "react";
import * as d3 from "d3";
import { API, CAT_HEX } from "../../constants";
import Badge from "../shared/Badge";

// ─── knowledge graph tab ──────────────────────────────────────────────────────

export default function GraphTab() {
  const canvasRef              = useRef(null);
  const zoomRef                = useRef(null);
  const selectedRef            = useRef(null); // { nodeId, connectedIds: Set }
  const [entries, setEntries]  = useState([]);
  const [tooltip, setTooltip]  = useState(null);
  const [selected, setSelected] = useState(null); // entry object for info panel
  const [nodeCount, setNodeCount] = useState({ entries: 0, tags: 0 });
  const [tagSearch, setTagSearch] = useState("");

  useEffect(() => {
    fetch(`${API}/entries`)
      .then(r => r.json())
      .then(setEntries)
      .catch(console.error);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!entries.length || !canvas) return;

    const ctx = canvas.getContext("2d");
    const W   = canvas.clientWidth  || 900;
    const H   = canvas.clientHeight || 600;
    canvas.width  = W;
    canvas.height = H;

    // Filter entries/tags by tagSearch
    let filteredEntries = entries;
    if (tagSearch.trim()) {
      const tag = tagSearch.trim().toLowerCase();
      filteredEntries = entries.filter(e => e.tags?.some(t => t.toLowerCase().includes(tag)));
    }

    // Build nodes
    const entryNodes = filteredEntries.map(e => ({
      id:    `e-${e.id}`,
      kind:  "entry",
      entry: e,
      r:     9,
      x:     W / 2 + (Math.random() - 0.5) * 200,
      y:     H / 2 + (Math.random() - 0.5) * 200,
    }));

    const tagCount = {};
    filteredEntries.forEach(e => e.tags?.forEach(t => { tagCount[t] = (tagCount[t] || 0) + 1; }));

    const tagNodes = Object.keys(tagCount).map(t => ({
      id:    `t-${t}`,
      kind:  "tag",
      name:  t,
      count: tagCount[t],
      r:     Math.min(5 + tagCount[t] * 1.5, 14),
      x:     W / 2 + (Math.random() - 0.5) * 300,
      y:     H / 2 + (Math.random() - 0.5) * 300,
    }));

    setNodeCount({ entries: entryNodes.length, tags: tagNodes.length });

    const nodes = [...entryNodes, ...tagNodes];
    const links = [];
    filteredEntries.forEach(e => {
      e.tags?.forEach(t => {
        if (tagCount[t]) links.push({ source: `e-${e.id}`, target: `t-${t}` });
      });
    });

    // D3 force simulation
    const sim = d3.forceSimulation(nodes)
      .force("link",    d3.forceLink(links).id(n => n.id).distance(60).strength(0.4))
      .force("charge",  d3.forceManyBody().strength(-80))
      .force("center",  d3.forceCenter(W / 2, H / 2))
      .force("collide", d3.forceCollide(n => n.r + 4));

    let transform = d3.zoomIdentity;

    function draw() {
      const sel = selectedRef.current;
      ctx.save();
      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = "#0d1117";
      ctx.fillRect(0, 0, W, H);
      ctx.translate(transform.x, transform.y);
      ctx.scale(transform.k, transform.k);

      // Links
      links.forEach(l => {
        if (!l.source?.x || !l.target?.x) return;
        const isHighlit = sel && (l.source.id === sel.nodeId || l.target.id === sel.nodeId);
        ctx.globalAlpha = sel ? (isHighlit ? 0.8 : 0.07) : 0.3;
        ctx.strokeStyle = isHighlit ? "#58a6ff" : "#30363d";
        ctx.lineWidth   = isHighlit ? 1.2 : 0.8;
        ctx.beginPath();
        ctx.moveTo(l.source.x, l.source.y);
        ctx.lineTo(l.target.x, l.target.y);
        ctx.stroke();
      });
      ctx.globalAlpha = 1;

      // Tag nodes
      tagNodes.forEach(n => {
        const isConnected = sel?.connectedIds.has(n.id);
        ctx.globalAlpha = sel ? (isConnected ? 1 : 0.15) : 1;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, 2 * Math.PI);
        ctx.fillStyle   = isConnected ? "#1c2d3a" : "#21262d";
        ctx.strokeStyle = isConnected ? "#58a6ff" : "#30363d";
        ctx.lineWidth   = isConnected ? 1.5 : 1;
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle    = isConnected ? "#93c5fd" : "#6e7681";
        ctx.font         = `${Math.max(9, Math.min(n.r, 11))}px monospace`;
        ctx.textAlign    = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(`#${n.name}`, n.x, n.y + n.r + 9);
      });

      // Entry nodes
      entryNodes.forEach(n => {
        const isSelected  = sel?.nodeId === n.id;
        const isConnected = sel?.connectedIds.has(n.id);
        ctx.globalAlpha = sel ? (isSelected || isConnected ? 1 : 0.15) : 1;
        const color = CAT_HEX[n.entry.category] || "#58a6ff";
        ctx.beginPath();
        ctx.arc(n.x, n.y, isSelected ? n.r + 3 : n.r, 0, 2 * Math.PI);
        ctx.fillStyle   = color + (isSelected ? "ff" : "cc");
        ctx.strokeStyle = isSelected ? "#fff" : color;
        ctx.lineWidth   = isSelected ? 2.5 : 1.5;
        ctx.fill();
        ctx.stroke();
        const label = (n.entry.name || n.entry.url).slice(0, 18);
        ctx.fillStyle    = isSelected ? "rgba(255,255,255,0.95)" : "rgba(255,255,255,0.6)";
        ctx.font         = `${isSelected ? 9 : 8}px monospace`;
        ctx.textAlign    = "center";
        ctx.textBaseline = "top";
        ctx.fillText(label, n.x, n.y + (isSelected ? n.r + 5 : n.r + 2));
      });

      ctx.globalAlpha = 1;
      ctx.restore();
    }

    sim.on("tick", draw);

    // Zoom / pan
    const zoom = d3.zoom()
      .scaleExtent([0.1, 8])
      .on("zoom", e => { transform = e.transform; draw(); });
    d3.select(canvas).call(zoom);
    zoomRef.current = { zoom, canvas };

    // Hit-test helper
    let hoveredNode = null;
    function findNode(cx, cy) {
      const mx = transform.invertX(cx), my = transform.invertY(cy);
      for (const n of nodes) {
        const dx = (n.x || 0) - mx, dy = (n.y || 0) - my;
        if (Math.sqrt(dx * dx + dy * dy) <= n.r + 5) return n;
      }
      return null;
    }

    canvas.onmousemove = e => {
      const rect = canvas.getBoundingClientRect();
      hoveredNode = findNode(e.clientX - rect.left, e.clientY - rect.top);
      canvas.style.cursor = hoveredNode ? "pointer" : "default";
      if (hoveredNode) {
        const label = hoveredNode.kind === "entry"
          ? `${hoveredNode.entry.name || hoveredNode.entry.url}\n[${hoveredNode.entry.category}]  ${hoveredNode.entry.tags?.map(t => "#" + t).join(" ") || ""}\n↵ click to focus · dblclick to open`
          : `#${hoveredNode.name} (${hoveredNode.count} entries)`;
        setTooltip({ x: e.clientX - rect.left, y: e.clientY - rect.top, text: label });
      } else {
        setTooltip(null);
      }
    };

    canvas.onmouseleave = () => { hoveredNode = null; setTooltip(null); };

    canvas.onclick = e => {
      const rect = canvas.getBoundingClientRect();
      const hit  = findNode(e.clientX - rect.left, e.clientY - rect.top);

      if (!hit) {
        // Click empty space → deselect
        selectedRef.current = null;
        setSelected(null);
        draw();
        return;
      }

      if (hit.kind === "entry") {
        // Build connected-tag set
        const connectedIds = new Set(
          links
            .filter(l => l.source.id === hit.id || l.target.id === hit.id)
            .map(l => l.source.id === hit.id ? l.target.id : l.source.id)
        );
        selectedRef.current = { nodeId: hit.id, connectedIds };
        setSelected(hit.entry);
        draw();

        // Zoom to fit the subgraph
        const related = nodes.filter(n => n.id === hit.id || connectedIds.has(n.id));
        if (related.length > 0) {
          const xs  = related.map(n => n.x);
          const ys  = related.map(n => n.y);
          const x0  = Math.min(...xs), x1 = Math.max(...xs);
          const y0  = Math.min(...ys), y1 = Math.max(...ys);
          const pad = 70;
          const bw  = x1 - x0 + pad * 2 || 1;
          const bh  = y1 - y0 + pad * 2 || 1;
          const k   = Math.min(3.5, 0.85 * Math.min(W / bw, H / bh));
          const tx  = W / 2 - k * (x0 + x1) / 2;
          const ty  = H / 2 - k * (y0 + y1) / 2;
          d3.select(canvas)
            .transition().duration(550)
            .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(k));
        }
      } else {
        // Clicked a tag node — find all entries connected to it
        const connectedEntryIds = new Set(
          links
            .filter(l => l.source.id === hit.id || l.target.id === hit.id)
            .map(l => l.source.id === hit.id ? l.target.id : l.source.id)
        );
        selectedRef.current = { nodeId: hit.id, connectedIds: connectedEntryIds };
        setSelected(null);
        draw();

        const related = nodes.filter(n => n.id === hit.id || connectedEntryIds.has(n.id));
        if (related.length > 0) {
          const xs  = related.map(n => n.x);
          const ys  = related.map(n => n.y);
          const x0  = Math.min(...xs), x1 = Math.max(...xs);
          const y0  = Math.min(...ys), y1 = Math.max(...ys);
          const pad = 70;
          const bw  = x1 - x0 + pad * 2 || 1;
          const bh  = y1 - y0 + pad * 2 || 1;
          const k   = Math.min(3.5, 0.85 * Math.min(W / bw, H / bh));
          const tx  = W / 2 - k * (x0 + x1) / 2;
          const ty  = H / 2 - k * (y0 + y1) / 2;
          d3.select(canvas)
            .transition().duration(550)
            .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(k));
        }
      }
    };

    canvas.ondblclick = e => {
      const rect = canvas.getBoundingClientRect();
      const hit  = findNode(e.clientX - rect.left, e.clientY - rect.top);
      if (hit?.kind === "entry") window.open(hit.entry.url, "_blank");
    };

    return () => {
      sim.stop();
      d3.select(canvas).on(".zoom", null);
    };
  }, [entries, tagSearch]);

  return (
    <div className="relative w-full" style={{ height: "calc(100vh - 120px)" }}>
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs text-gray-600">
          {nodeCount.entries} entries · {nodeCount.tags} tag nodes ·{" "}
          <span className="text-gray-700">click to focus · dblclick to open URL</span>
        </div>
        <div className="flex items-center gap-3 text-xs flex-wrap justify-end">
          {Object.entries(CAT_HEX).filter(([k]) => k !== "skill").map(([cat, hex]) => (
            <span key={cat} className="flex items-center gap-1 text-gray-500">
              <span className="w-2.5 h-2.5 rounded-full inline-block flex-shrink-0" style={{ background: hex }} />
              {cat}
            </span>
          ))}
          <span className="flex items-center gap-1 text-gray-500">
            <span className="w-2.5 h-2.5 rounded border border-border inline-block bg-surface-2 flex-shrink-0" />
            tag
          </span>
          <input
            type="text"
            className="ml-4 px-2 py-0.5 rounded border border-border bg-surface-2 text-xs text-gray-500 font-mono"
            placeholder="Search tag..."
            value={tagSearch}
            onChange={e => setTagSearch(e.target.value)}
            style={{ minWidth: 90 }}
          />
        </div>
      </div>

      <canvas ref={canvasRef} className="w-full h-full rounded border border-border block" />

      {tooltip && (
        <div className="absolute pointer-events-none bg-surface-1 border border-border rounded px-3 py-2 text-xs text-gray-300 font-mono whitespace-pre max-w-xs"
          style={{ left: tooltip.x + 14, top: tooltip.y - 10, zIndex: 10 }}>
          {tooltip.text}
        </div>
      )}

      {/* selected entry info panel */}
      {selected && (
        <div className="absolute bottom-4 left-4 right-4 sm:right-auto sm:w-80 bg-surface-1 border border-accent-blue/40 rounded-lg p-3 text-xs shadow-xl"
          style={{ zIndex: 10 }}>
          <div className="flex items-start justify-between mb-2">
            <div className="flex items-start gap-2 flex-1 min-w-0 mr-2">
              <Badge category={selected.category} />
              <span className="text-gray-200 font-semibold break-words min-w-0">{selected.name}</span>
            </div>
            <button onClick={() => { selectedRef.current = null; setSelected(null); }}
              className="text-gray-600 hover:text-gray-400 flex-shrink-0">✕</button>
          </div>
          <ul className="space-y-1 mb-2">
            {selected.bullets.map((b, i) => (
              <li key={i} className="flex items-start gap-1.5 text-gray-400">
                <span className="text-accent-green/50 flex-shrink-0">▸</span>{b}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-1 mb-2">
            {selected.tags?.map(t => (
              <span key={t} className="px-1.5 py-0.5 rounded border border-border bg-surface-2 text-gray-500 font-mono">#{t}</span>
            ))}
          </div>
          <a href={selected.url} target="_blank" rel="noreferrer"
            className="text-accent-blue hover:underline font-mono truncate block">
            {selected.url}
          </a>
        </div>
      )}

      {entries.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center text-gray-700 text-sm select-none">
          No entries yet — analyze some URLs first.
        </div>
      )}
    </div>
  );
}
