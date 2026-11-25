import { splitAnswer } from "../citations";
import type { ChatSource } from "../types";

interface AnswerTextProps {
  text: string;
  sources: readonly ChatSource[];
  onCitationClick?: (source: ChatSource) => void;
}

/**
 * Render the answer as plain text (never as HTML) with verified citations turned into buttons that open the
 * matching source in the "Fuentes Verificadas" panel.
 */
export function AnswerText({ text, sources, onCitationClick }: AnswerTextProps) {
  const parts = splitAnswer(text, sources);
  return (
    <p className="whitespace-pre-wrap leading-relaxed text-stone-800">
      {parts.map((part, index) =>
        part.kind === "text" ? (
          <span key={index}>{part.text}</span>
        ) : (
          <button
            key={index}
            type="button"
            onClick={() => onCitationClick?.(part.source)}
            className="mx-0.5 inline rounded bg-emerald-50 px-1 py-0.5 text-left align-baseline text-[0.85em] font-medium text-emerald-900 ring-1 ring-emerald-200 transition hover:bg-emerald-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600"
            title="Ver fuente verificada"
          >
            {part.text}
          </button>
        ),
      )}
    </p>
  );
}
