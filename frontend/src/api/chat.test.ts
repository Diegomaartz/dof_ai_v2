import { describe, expect, it } from "vitest";

import { ANSWER, frame, groundedFinal, happyStream, jsonFetch, sseFetch } from "../test/fakeApi";
import type { ChatEvent } from "../types";
import { ChatApiError, streamChat, toChatEvent } from "./chat";

async function collect(fetchImpl: typeof fetch) {
  const events: ChatEvent[] = [];
  const final = await streamChat("¿Jornada diurna?", (e) => events.push(e), { fetchImpl });
  return { events, final };
}

describe("streamChat", () => {
  it("posts the question as JSON asking for SSE", async () => {
    const calls: RequestInit[] = [];
    await collect(sseFetch(happyStream(), { calls }));
    expect(calls[0]?.method).toBe("POST");
    expect(calls[0]?.body).toBe(JSON.stringify({ question: "¿Jornada diurna?" }));
    expect(calls[0]?.headers).toMatchObject({ Accept: "text/event-stream", "Content-Type": "application/json" });
  });

  it("reports status, tokens and the final event, even with tiny chunks", async () => {
    const { events, final } = await collect(sseFetch(happyStream(), { splitSize: 3 }));
    expect(events.filter((e) => e.type === "status").map((e) => (e.type === "status" ? e.label : ""))).toEqual([
      "Analizando la consulta",
      "Redactando la respuesta",
    ]);
    expect(events.map((e) => (e.type === "token" ? e.text : "")).join("")).toBe(ANSWER);
    expect(events.at(-1)).toEqual({ type: "final", data: groundedFinal });
    expect(final).toEqual(groundedFinal);
  });

  it("decodes multi-byte characters split across chunks", async () => {
    const { final } = await collect(sseFetch(happyStream(), { splitSize: 1 }));
    expect(final.answer).toBe(ANSWER);
  });

  it("rejects with the server message on an error event", async () => {
    const stream = [frame("token", { text: "La" }), frame("error", { code: "agent_unavailable", message: "No disponible." })];
    await expect(collect(sseFetch(stream))).rejects.toEqual(new ChatApiError("agent_unavailable", "No disponible."));
  });

  it("rejects when the stream ends without a final event", async () => {
    await expect(collect(sseFetch([frame("token", { text: "La" })]))).rejects.toMatchObject({ code: "incomplete" });
  });

  it("discards a final event cut off before its terminating blank line", async () => {
    const cut = frame("final", { answer: "x" }).trimEnd();
    await expect(collect(sseFetch([cut]))).rejects.toMatchObject({ code: "incomplete" });
  });

  it("uses the field error message of a 400", async () => {
    const fetchImpl = jsonFetch(400, {
      code: "invalid_request",
      detail: "Solicitud inválida.",
      errors: { question: ["La pregunta no puede estar vacía."] },
    });
    await expect(collect(fetchImpl)).rejects.toEqual(
      new ChatApiError("invalid_request", "La pregunta no puede estar vacía."),
    );
  });

  it("uses the detail of a 429", async () => {
    const fetchImpl = jsonFetch(429, { code: "rate_limited", detail: "Ha excedido el límite de consultas." });
    await expect(collect(fetchImpl)).rejects.toMatchObject({ code: "rate_limited" });
  });

  it("falls back to a Spanish message for non-JSON errors", async () => {
    const fetchImpl = (async () => new Response("<html>Bad gateway</html>", { status: 503 })) as typeof fetch;
    await expect(collect(fetchImpl)).rejects.toEqual(
      new ChatApiError("http_503", "El servicio no está disponible en este momento. Intente de nuevo más tarde."),
    );
  });

  it("reports network failures", async () => {
    const fetchImpl = (async () => {
      throw new TypeError("Failed to fetch");
    }) as typeof fetch;
    await expect(collect(fetchImpl)).rejects.toMatchObject({ code: "network" });
  });

  it("rejects a non-SSE success response", async () => {
    await expect(collect(jsonFetch(200, groundedFinal))).rejects.toMatchObject({ code: "bad_response" });
  });

  it("propagates aborts", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const controller = new AbortController();
    const pending = streamChat("x", () => {}, { fetchImpl: sseFetch(happyStream(), { gate, gateAt: 1 }), signal: controller.signal });
    controller.abort();
    release();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("toChatEvent", () => {
  it("ignores unknown, malformed and incomplete frames", () => {
    expect(toChatEvent({ event: "other", data: "{}" })).toBeNull();
    expect(toChatEvent({ event: "token", data: "no json" })).toBeNull();
    expect(toChatEvent({ event: "token", data: '{"text": 1}' })).toBeNull();
    expect(toChatEvent({ event: "final", data: '{"answer": "x"}' })).toBeNull();
  });
});
