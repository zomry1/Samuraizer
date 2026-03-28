export function parseUrls(raw) {
  return [...new Set(
    raw.split(/[\n,]+/)
       .map(s => s.trim())
       .filter(s => s.startsWith("http://") || s.startsWith("https://"))
  )];
}
