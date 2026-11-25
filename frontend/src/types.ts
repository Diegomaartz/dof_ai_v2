/** Shapes of the `/api/v2/chat/` contract (see `backend/api/events.py`). */

export type SourceKind = "legislacion" | "dof";
export type Route = "rag" | "mcp" | "hybrid";

export interface ChatSource {
  id: string;
  kind: SourceKind;
  /** Exact inline citation used in the answer, e.g. "[Ley Federal del Trabajo, Art. 61, DOF 30/11/2012]". */
  citation: string;
  title: string;
  /** Verbatim text of the source the answer was built from. */
  excerpt: string;
  excerpt_is_complete: boolean;
  url: string | null;
  date: string | null;
  hierarchy: string | null;
  is_repealed: boolean;
}

export interface ChatFinal {
  answer: string;
  refused: boolean;
  route: Route | null;
  retries: number;
  sources: ChatSource[];
}

export type ChatEvent =
  | { type: "status"; node: string; label: string }
  | { type: "token"; text: string }
  | { type: "final"; data: ChatFinal }
  | { type: "error"; code: string; message: string };
