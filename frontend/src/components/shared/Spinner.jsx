// ─── shared ───────────────────────────────────────────────────────────────────

export default function Spinner({ sm }) {
  return (
    <svg className={`animate-spin ${sm ? "h-3 w-3" : "h-4 w-4"} text-accent-green flex-shrink-0`}
      xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  );
}
