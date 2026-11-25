import { useState } from "react";

import type { AssistantTurn } from "../hooks/useChat";
import type { ChatSource } from "../types";
import { AnswerText } from "./AnswerText";
import { SourcesPanel, sourceElementId } from "./SourcesPanel";

export function AssistantMessage({ turn }: { turn: AssistantTurn }) {
  const [open, setOpen] = useState(false);
  const [highlightedId, setHighlightedId] = useState<string | null>(null);

  const showSource = (source: ChatSource) => {
    setOpen(true);
    setHighlightedId(source.id);
    const index = turn.sources.findIndex((s) => s.id === source.id);
    requestAnimationFrame(() => {
      const element = document.getElementById(sourceElementId(turn.id, index));
      element?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
      element?.focus({ preventScroll: true });
    });
  };

  return (
    <article
      aria-label="Respuesta de DOF-AI"
      aria-busy={turn.phase === "streaming"}
      className="rounded-xl border border-stone-200 bg-white p-5 shadow-sm"
    >
      {turn.phase === "streaming" && (
        <>
          <p role="status" className="mb-2 flex items-center gap-2 text-sm text-stone-500">
            <span className="size-2 animate-pulse rounded-full bg-emerald-600" aria-hidden="true" />
            {turn.statusLabel ?? "Procesando"}…
          </p>
          {turn.text && <p className="whitespace-pre-wrap leading-relaxed text-stone-600">{turn.text}</p>}
        </>
      )}

      {turn.phase === "done" && turn.refused && (
        <div role="note" className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-amber-900">
          <p className="font-semibold">Sin sustento legal</p>
          <p className="mt-1 text-sm">{turn.text}</p>
          <p className="mt-2 text-xs text-amber-800">
            DOF-AI solo responde con base en las fuentes consultadas. Reformule la pregunta o indique la ley, el
            artículo o la fecha de publicación que le interesa.
          </p>
        </div>
      )}

      {turn.phase === "done" && !turn.refused && (
        <>
          <AnswerText text={turn.text} sources={turn.sources} onCitationClick={showSource} />
          <SourcesPanel
            turnId={turn.id}
            sources={turn.sources}
            open={open}
            onToggle={() => setOpen((value) => !value)}
            highlightedId={highlightedId}
          />
        </>
      )}

      {(turn.phase === "error" || turn.phase === "cancelled") && (
        <p
          role={turn.phase === "error" ? "alert" : "status"}
          className={turn.phase === "error" ? "text-sm text-red-800" : "text-sm text-stone-500"}
        >
          {turn.error}
        </p>
      )}
    </article>
  );
}
