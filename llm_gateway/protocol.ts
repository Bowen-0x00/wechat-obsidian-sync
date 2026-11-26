export function parseJsonObject(text: string): Record<string, unknown> {
  const fenced = /```(?:json)?\s*([\s\S]*?)\s*```/.exec(text);
  const candidate = fenced ? fenced[1].trim() : text.slice(text.indexOf("{")).trim();
  if (!candidate.startsWith("{")) throw new Error("Model did not return a JSON object");
  let depth = 0;
  let quoted = false;
  let escaped = false;
  let end = -1;
  for (let index = 0; index < candidate.length; index++) {
    const char = candidate[index];
    if (quoted) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === '"') quoted = false;
      continue;
    }
    if (char === '"') quoted = true;
    else if (char === "{") depth++;
    else if (char === "}" && --depth === 0) { end = index + 1; break; }
  }
  if (end < 0) throw new Error("Model returned an incomplete JSON object");
  const remainder = fenced ? text.slice((fenced.index || 0) + fenced[0].length) : candidate.slice(end);
  if (remainder.includes("{")) throw new Error("Model returned more than one JSON object");
  const parsed: unknown = JSON.parse(candidate.slice(0, end));
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Expected a JSON object from the model");
  return parsed as Record<string, unknown>;
}
