import { useState } from "react";

import { safeExternalUrl } from "../citations";
import type { ChatSource } from "../types";

const EXCERPT_PREVIEW_CHARS = 700;

interface SourcesPanelProps {
  turnId: string;
  sources: readonly ChatSource[];
  open: boolean;
  onToggle: () => void;
  highlightedId: string | null;
}

export const sourceElementId = (turnId: string, index: number): string => `fuente-${turnId}-${index}`;

/** Collapsible "Fuentes Verificadas" panel: the exact excerpts the answer cites, with links to the DOF. */
export function SourcesPanel({ turnId, sources, open, onToggle, highlightedId }: SourcesPanelProps) {
  if (sources.length === 0) return null;
  const panelId = `fuentes-${turnId}`;
  return (
    <section className="mt-4 rounded-lg border border-stone-200 bg-stone-50/80">
      <h3>
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          aria-controls={panelId}
          className="flex w-full items-center justify-between gap-2 rounded-lg px-4 py-2.5 text-left text-sm font-semibold text-stone-700 hover:bg-stone-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600"
        >
          <span>
            Fuentes Verificadas <span className="font-normal text-stone-500">({sources.length})</span>
          </span>
          <span aria-hidden="true" className={`transition-transform ${open ? "rotate-180" : ""}`}>
            ▾
          </span>
        </button>
      </h3>
      {open && (
        <ol id={panelId} className="space-y-3 px-4 pb-4">
          {sources.map((source, index) => (
            <SourceCard
              key={source.id}
              id={sourceElementId(turnId, index)}
              source={source}
              highlighted={source.id === highlightedId}
            />
          ))}
        </ol>
      )}
    </section>
  );
}

function SourceCard({ id, source, highlighted }: { id: string; source: ChatSource; highlighted: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const url = safeExternalUrl(source.url);
  const long = source.excerpt.length > EXCERPT_PREVIEW_CHARS;
  const excerpt = long && !expanded ? `${source.excerpt.slice(0, EXCERPT_PREVIEW_CHARS).trimEnd()}…` : source.excerpt;
  const isDof = source.kind === "dof";

  return (
    <li
      id={id}
      tabIndex={-1}
      className={`rounded-md border bg-white p-3 shadow-sm transition ${
        highlighted ? "border-emerald-500 ring-2 ring-emerald-200" : "border-stone-200"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span
          className={`rounded px-1.5 py-0.5 font-semibold uppercase tracking-wide ${
            isDof ? "bg-sky-100 text-sky-900" : "bg-emerald-100 text-emerald-900"
          }`}
        >
          {isDof ? "DOF" : "Legislación"}
        </span>
        {source.is_repealed && (
          <span className="rounded bg-red-100 px-1.5 py-0.5 font-semibold uppercase tracking-wide text-red-800">
            Derogado
          </span>
        )}
        {source.date && <span className="text-stone-500">DOF {source.date}</span>}
      </div>
      <p className="mt-1.5 font-medium text-stone-900">{source.title}</p>
      {source.hierarchy && <p className="mt-0.5 text-xs text-stone-500">{source.hierarchy}</p>}
      <p className="mt-1 font-mono text-xs text-stone-600">{source.citation}</p>
      <blockquote className="mt-2 whitespace-pre-wrap border-l-2 border-stone-300 pl-3 text-sm leading-relaxed text-stone-700">
        {excerpt}
      </blockquote>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        {long && (
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="font-medium text-emerald-800 underline-offset-2 hover:underline"
          >
            {expanded ? "Mostrar menos" : "Mostrar texto completo"}
          </button>
        )}
        {!source.excerpt_is_complete && (
          <span className="text-amber-800">Extracto parcial: consulte el documento oficial para el texto íntegro.</span>
        )}
        {url && (
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-emerald-800 underline-offset-2 hover:underline"
          >
            {isDof ? "Ver en el DOF" : "Ver documento oficial"}
            <span className="sr-only"> (se abre en una pestaña nueva)</span> ↗
          </a>
        )}
      </div>
    </li>
  );
}
