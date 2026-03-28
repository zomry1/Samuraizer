export function escapeHtml(unsafe) {
  return unsafe
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function renderMarkdown(md) {
  if (!md) return "";

  // Split on fenced code blocks (```lang\n...```)
  const parts = md.split(/```([\w-]*)\n([\s\S]*?)```/g);
  let html = "";

  for (let i = 0; i < parts.length; i += 3) {
    const before = parts[i];
    const lang   = parts[i + 1];
    const code   = parts[i + 2];

    if (before) html += renderMarkdownChunk(before);
    if (code !== undefined) {
      const escaped = escapeHtml(code);
      const cls = lang ? `language-${lang}` : "";
      html += `<pre class='bg-surface-2 p-2 rounded text-[11px] overflow-x-auto'><code class='${cls}'>${escaped}</code></pre>`;
    }
  }

  return html;
}

export function renderMarkdownChunk(text) {
  const inline = (t) => {
    let x = escapeHtml(t);
    x = x.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    x = x.replace(/\*(.+?)\*/g, "<em>$1</em>");
    x = x.replace(/`([^`]+)`/g, "<code class='bg-surface-2 px-1 rounded'>$1</code>");
    x = x.replace(/\[([^\]]+)\]\(([^\)]+)\)/g,
      "<a href='$2' target='_blank' rel='noopener noreferrer' class='text-accent-blue hover:underline'>$1</a>");
    return x;
  };

  const lines = text.split(/\r?\n/);
  let html = "";
  let inUL = false;
  let inOL = false;

  const closeLists = () => {
    if (inUL) { html += "</ul>"; inUL = false; }
    if (inOL) { html += "</ol>"; inOL = false; }
  };

  for (let line of lines) {
    const trimmed = line.trim();
    const h       = trimmed.match(/^(#{1,6})\s+(.*)$/);
    const o       = trimmed.match(/^(\d+)\.\s+(.*)$/);
    const u       = trimmed.match(/^[-*+]\s+(.*)$/);

    if (h) {
      closeLists();
      const level = Math.min(6, h[1].length);
      html += `<h${level} class='font-bold mt-3 mb-1 text-sm'>${inline(h[2])}</h${level}>`;
    } else if (o) {
      if (inUL) closeLists();
      if (!inOL) { inOL = true; html += "<ol class='list-decimal list-inside mb-2'>"; }
      html += `<li>${inline(o[2])}</li>`;
    } else if (u) {
      if (inOL) closeLists();
      if (!inUL) { inUL = true; html += "<ul class='list-disc list-inside mb-2'>"; }
      html += `<li>${inline(u[1])}</li>`;
    } else {
      if (!trimmed) {
        closeLists();
        html += "<br/>";
      } else {
        closeLists();
        html += `<p class='mb-1'>${inline(trimmed)}</p>`;
      }
    }
  }

  closeLists();
  return html;
}
