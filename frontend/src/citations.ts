/** Locate inline citations in an answer and link them to their verified sources. */

import type { ChatSource } from "./types";

export type AnswerPart = { kind: "text"; text: string } | { kind: "citation"; text: string; source: ChatSource };

// Same rule as the backend grounding check: a bracketed span that is not a Markdown link "[texto](url)".
const CITATION = /\[([^[\]\n]{2,600})\](?!\()/g;

export function normalizeCitation(text: string): string {
  return text.trim().replace(/^\[|\]$/g, "").replace(/\s+/g, " ").toLocaleLowerCase("es-MX");
}

/** Split `answer` into plain text and citations that match one of `sources`; unmatched brackets stay text. */
export function splitAnswer(answer: string, sources: readonly ChatSource[]): AnswerPart[] {
  const byCitation = new Map(sources.map((s) => [normalizeCitation(s.citation), s]));
  const parts: AnswerPart[] = [];
  let last = 0;
  for (const match of answer.matchAll(CITATION)) {
    const source = byCitation.get(normalizeCitation(match[1] ?? ""));
    if (!source) continue;
    const start = match.index ?? 0;
    if (start > last) parts.push({ kind: "text", text: answer.slice(last, start) });
    parts.push({ kind: "citation", text: match[0], source });
    last = start + match[0].length;
  }
  if (last < answer.length) parts.push({ kind: "text", text: answer.slice(last) });
  return parts;
}

/** Return `url` only if it is an absolute http(s) URL; anything else (javascript:, data:, relative) is dropped. */
export function safeExternalUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}
