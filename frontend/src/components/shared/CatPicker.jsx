import { useState, useEffect, useRef } from "react";
import { CAT_META, PICKABLE_CATS } from "../../constants";

export default function CatPicker({ current, onPick, onClose, anchorRef, customCats = [] }) {
  const ref = useRef(null);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  useEffect(() => {
    if (anchorRef?.current) {
      const r = anchorRef.current.getBoundingClientRect();
      setPos({ top: r.bottom + 4, left: r.left });
    }
    function h(e) { if (ref.current && !ref.current.contains(e.target)) onClose(); }
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [onClose]);

  return (
    <div ref={ref}
      style={{ position: "fixed", top: pos.top, left: pos.left, zIndex: 9999 }}
      className="bg-surface-1 border border-border rounded shadow-xl py-1 w-40">
      {PICKABLE_CATS.map(cat => {
        const m = CAT_META[cat];
        return (
          <button key={cat} onClick={() => onPick(cat)}
            className="w-full text-left px-3 py-2 text-xs flex items-center gap-2 hover:bg-surface-2 transition-colors">
            <span className={`inline-flex px-1.5 py-0.5 rounded border text-xs font-bold uppercase tracking-wider flex-shrink-0 ${m.color}`}>
              {m.label}
            </span>
            {current === cat && <span className="text-gray-500 ml-auto">✓</span>}
          </button>
        );
      })}
      {customCats.map(c => (
        <button key={c.slug} onClick={() => onPick(c.slug)}
          className="w-full text-left px-3 py-2 text-xs flex items-center gap-2 hover:bg-surface-2 transition-colors">
          <span style={{ color: c.color, borderColor: c.color + "66", backgroundColor: c.color + "1a" }}
            className="inline-flex px-1.5 py-0.5 rounded border text-xs font-bold uppercase tracking-wider flex-shrink-0">
            {c.label}
          </span>
          {current === c.slug && <span className="text-gray-500 ml-auto">✓</span>}
        </button>
      ))}
    </div>
  );
}
