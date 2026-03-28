import { CAT_META } from "../../constants";

export default function Badge({ category, customCats = [] }) {
  const m = CAT_META[category];
  if (m) {
    return (
      <span className={`inline-flex items-center px-2 py-0.5 rounded border text-xs font-bold uppercase tracking-wider flex-shrink-0 ${m.color}`}>
        {m.label}
      </span>
    );
  }
  const custom = customCats.find(c => c.slug === category);
  const color  = custom?.color || "#94a3b8";
  const label  = custom?.label || category;
  return (
    <span style={{ color, borderColor: color + "66", backgroundColor: color + "1a" }}
      className="inline-flex items-center px-2 py-0.5 rounded border text-xs font-bold uppercase tracking-wider flex-shrink-0">
      {label}
    </span>
  );
}
