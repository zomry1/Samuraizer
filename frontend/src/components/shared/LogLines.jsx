// ─── progress items (analyze tab) ─────────────────────────────────────────────

export default function LogLines({ logs }) {
  return (
    <div className="px-4 pb-3 space-y-0.5">
      {logs.map((msg, i) => (
        <div key={i} className="flex items-start gap-2 text-xs text-gray-600 font-mono">
          <span className="text-accent-green/40 flex-shrink-0">›</span>
          <span>{msg}</span>
        </div>
      ))}
    </div>
  );
}
