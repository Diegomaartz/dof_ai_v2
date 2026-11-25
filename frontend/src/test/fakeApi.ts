/** Builders for mocked `/api/v2/chat/` responses: real SSE bytes, no network. */

import type { ChatFinal, ChatSource } from "../types";

export const LFT_CITATION = "[Ley Federal del Trabajo, Art. 61, DOF 30/11/2012]";

export const lftSource: ChatSource = {
  id: "lft#art-61",
  kind: "legislacion",
  citation: LFT_CITATION,
  title: "Ley Federal del Trabajo, Art. 61",
  excerpt: "Artículo 61.- La duración máxima de la jornada será: ocho horas la diurna, siete la nocturna y siete horas y media la mixta.",
  excerpt_is_complete: true,
  url: "https://www.diputados.gob.mx/LeyesBiblio/pdf/LFT.pdf",
  date: "30/11/2012",
  hierarchy: "TITULO TERCERO Condiciones de Trabajo > CAPITULO II Jornada de trabajo",
  is_repealed: false,
};

export const dofSource: ChatSource = {
  id: "dof:5804497",
  kind: "dof",
  citation: "[DECRETO por el que se expide el Reglamento de la Ley Federal de Armas de Fuego y Explosivos, DOF 20/11/2026]",
  title: "DECRETO por el que se expide el Reglamento de la Ley Federal de Armas de Fuego y Explosivos.",
  excerpt: "Artículo 1.- El presente Reglamento tiene por objeto regular la portación.",
  excerpt_is_complete: false,
  url: "https://dof.gob.mx/nota_detalle.php?codigo=5804497&fecha=20/11/2026",
  date: "20/11/2026",
  hierarchy: null,
  is_repealed: false,
};

export const ANSWER = `La jornada diurna tiene una duración máxima de ocho horas ${LFT_CITATION}.`;

export const groundedFinal: ChatFinal = { answer: ANSWER, refused: false, route: "rag", retries: 0, sources: [lftSource] };

export const refusalFinal: ChatFinal = {
  answer: "No se encontró sustento legal en las fuentes consultadas.",
  refused: true,
  route: "rag",
  retries: 2,
  sources: [],
};

export function frame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

export function tokensOf(text: string): string[] {
  return text.split(/(?<= )/).map((t) => frame("token", { text: t }));
}

/** A complete successful stream: statuses, the answer tokens and the final event. */
export function happyStream(final: ChatFinal = groundedFinal, draft: string = final.answer): string[] {
  return [
    frame("status", { node: "router_node", label: "Analizando la consulta" }),
    ": ping\n\n",
    frame("status", { node: "generate_node", label: "Redactando la respuesta" }),
    ...tokensOf(draft),
    frame("final", final),
  ];
}

/**
 * A `fetch` replacement returning an SSE response whose body emits `chunks` (strings, re-split into
 * `splitSize`-byte pieces to exercise chunk boundaries). `gate`, when given, holds the stream open before the
 * chunk at `gateAt` until it resolves, so tests can observe the UI mid-stream.
 */
export function sseFetch(
  chunks: string[],
  options: { splitSize?: number; gate?: Promise<void>; gateAt?: number; calls?: RequestInit[] } = {},
): typeof fetch {
  return (async (_url: RequestInfo | URL, init?: RequestInit) => {
    options.calls?.push(init ?? {});
    const encoder = new TextEncoder();
    const bytes = chunks.map((c) => encoder.encode(c));
    const signal = init?.signal;
    const body = new ReadableStream<Uint8Array>({
      async start(controller) {
        const abort = () => controller.error(new DOMException("The operation was aborted.", "AbortError"));
        signal?.addEventListener("abort", abort);
        for (let i = 0; i < bytes.length; i += 1) {
          if (options.gate && i === (options.gateAt ?? 0)) await options.gate;
          if (signal?.aborted) return;
          const piece = bytes[i]!;
          const size = options.splitSize ?? piece.length;
          for (let offset = 0; offset < piece.length; offset += size) {
            controller.enqueue(piece.slice(offset, offset + size));
          }
        }
        controller.close();
      },
    });
    return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream; charset=utf-8" } });
  }) as typeof fetch;
}

export function jsonFetch(status: number, body: unknown, headers: Record<string, string> = {}): typeof fetch {
  return (async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json", ...headers },
    })) as typeof fetch;
}
