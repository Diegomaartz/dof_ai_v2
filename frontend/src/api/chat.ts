/** Client for `POST /api/v2/chat/` streamed over SSE. The SPA talks to no other backend service. */

import type { ChatEvent, ChatFinal } from "../types";
import { SseParser, type RawSseEvent } from "./sse";

export const API_BASE_URL: string = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");
export const CHAT_URL = `${API_BASE_URL}/api/v2/chat/`;
export const MAX_QUESTION_CHARS = 2000;

export class ChatApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ChatApiError";
  }
}

const NETWORK_MESSAGE = "No fue posible conectar con el servidor. Verifique su conexión e intente de nuevo.";
const INCOMPLETE_MESSAGE = "La conexión se interrumpió antes de completar la respuesta. Intente de nuevo.";
const FALLBACK_MESSAGES: Record<number, string> = {
  400: "La solicitud no es válida.",
  429: "Ha excedido el límite de consultas. Intente de nuevo en unos minutos.",
  503: "El servicio no está disponible en este momento. Intente de nuevo más tarde.",
};

export interface StreamChatOptions {
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
}

/**
 * Ask a question and report each event as it arrives. Resolves after the terminal `final` event; rejects with
 * {@link ChatApiError} on HTTP, protocol or `error` events, and with the abort error when `signal` aborts.
 */
export async function streamChat(
  question: string,
  onEvent: (event: ChatEvent) => void,
  { signal, fetchImpl = fetch }: StreamChatOptions = {},
): Promise<ChatFinal> {
  let response: Response;
  try {
    response = await fetchImpl(CHAT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ question }),
      signal,
    });
  } catch (error) {
    if (isAbort(error)) throw error;
    throw new ChatApiError("network", NETWORK_MESSAGE);
  }

  if (!response.ok) throw await httpError(response);
  if (!response.body || !(response.headers.get("Content-Type") ?? "").includes("text/event-stream")) {
    throw new ChatApiError("bad_response", "El servidor respondió en un formato inesperado.");
  }

  const parser = new SseParser();
  const decoder = new TextDecoder();
  const reader = response.body.getReader();
  try {
    for (;;) {
      let chunk: ReadableStreamReadResult<Uint8Array>;
      try {
        chunk = await reader.read();
      } catch (error) {
        if (isAbort(error) || signal?.aborted) throw error;
        throw new ChatApiError("incomplete", INCOMPLETE_MESSAGE);
      }
      const text = chunk.done ? decoder.decode() + "\n\n" : decoder.decode(chunk.value, { stream: true });
      for (const raw of parser.feed(text)) {
        const event = toChatEvent(raw);
        if (!event) continue;
        onEvent(event);
        if (event.type === "final") return event.data;
        if (event.type === "error") throw new ChatApiError(event.code, event.message);
      }
      if (chunk.done) throw new ChatApiError("incomplete", INCOMPLETE_MESSAGE);
    }
  } finally {
    reader.releaseLock();
  }
}

/** Validate and convert one SSE frame. Unknown or malformed frames are ignored. */
export function toChatEvent(raw: RawSseEvent): ChatEvent | null {
  let data: unknown;
  try {
    data = JSON.parse(raw.data);
  } catch {
    return null;
  }
  if (!isRecord(data)) return null;
  switch (raw.event) {
    case "status":
      return typeof data.label === "string" ? { type: "status", node: String(data.node ?? ""), label: data.label } : null;
    case "token":
      return typeof data.text === "string" ? { type: "token", text: data.text } : null;
    case "final":
      return isFinal(data) ? { type: "final", data } : null;
    case "error":
      return {
        type: "error",
        code: typeof data.code === "string" ? data.code : "error",
        message: typeof data.message === "string" ? data.message : FALLBACK_MESSAGES[503]!,
      };
    default:
      return null;
  }
}

async function httpError(response: Response): Promise<ChatApiError> {
  let code = `http_${response.status}`;
  let message = FALLBACK_MESSAGES[response.status] ?? `Error del servidor (${response.status}).`;
  try {
    const body: unknown = await response.json();
    if (isRecord(body)) {
      if (typeof body.code === "string") code = body.code;
      const fieldErrors = isRecord(body.errors) && Array.isArray(body.errors.question) ? body.errors.question : null;
      if (fieldErrors && typeof fieldErrors[0] === "string") message = fieldErrors[0];
      else if (typeof body.detail === "string") message = body.detail;
    }
  } catch {
    // Non-JSON error body (e.g. a proxy page): keep the fallback message.
  }
  return new ChatApiError(code, message);
}

function isFinal(data: Record<string, unknown>): data is Record<string, unknown> & ChatFinal {
  return typeof data.answer === "string" && typeof data.refused === "boolean" && Array.isArray(data.sources);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
