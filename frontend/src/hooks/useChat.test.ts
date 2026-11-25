import { describe, expect, it } from "vitest";

import { groundedFinal, lftSource, refusalFinal } from "../test/fakeApi";
import { chatReducer, initialChatState, type AssistantTurn, type ChatState } from "./useChat";

const started = chatReducer(initialChatState, { type: "start", question: "¿Jornada?", userId: "u1", assistantId: "a1" });
const assistant = (state: ChatState) => state.turns.find((t): t is AssistantTurn => t.role === "assistant")!;
const token = (text: string) => ({ type: "event" as const, id: "a1", event: { type: "token" as const, text } });

describe("chatReducer", () => {
  it("adds the user turn and a streaming assistant turn", () => {
    expect(started.busy).toBe(true);
    expect(started.turns.map((t) => t.role)).toEqual(["user", "assistant"]);
    expect(assistant(started).phase).toBe("streaming");
  });

  it("accumulates tokens and status labels while streaming", () => {
    let state = chatReducer(started, { type: "event", id: "a1", event: { type: "status", node: "retrieve_node", label: "Buscando" } });
    state = chatReducer(chatReducer(state, token("La ")), token("jornada"));
    expect(assistant(state)).toMatchObject({ text: "La jornada", statusLabel: "Buscando", phase: "streaming" });
  });

  it("replaces the draft with the authoritative final answer", () => {
    const drafted = chatReducer(started, token("Borrador con una cita inventada [Ley X, Art. 999]"));
    const done = chatReducer(drafted, { type: "event", id: "a1", event: { type: "final", data: refusalFinal } });
    expect(assistant(done)).toMatchObject({ phase: "done", refused: true, text: refusalFinal.answer, sources: [] });
    expect(done.busy).toBe(false);
  });

  it("keeps the verified sources of a grounded answer", () => {
    const done = chatReducer(started, { type: "event", id: "a1", event: { type: "final", data: groundedFinal } });
    expect(assistant(done).sources).toEqual([lftSource]);
  });

  it("discards streamed text on an error event", () => {
    const drafted = chatReducer(started, token("La jornada"));
    const failed = chatReducer(drafted, {
      type: "event",
      id: "a1",
      event: { type: "error", code: "agent_unavailable", message: "No disponible." },
    });
    expect(assistant(failed)).toMatchObject({ phase: "error", text: "", error: "No disponible." });
    // A later transport-level failure for the same turn does not overwrite the server's message.
    const again = chatReducer(failed, { type: "fail", id: "a1", message: "Otro" });
    expect(assistant(again).error).toBe("No disponible.");
  });

  it("ignores events after the turn finished", () => {
    const done = chatReducer(started, { type: "event", id: "a1", event: { type: "final", data: groundedFinal } });
    expect(assistant(chatReducer(done, token(" extra"))).text).toBe(groundedFinal.answer);
  });

  it("marks a cancelled turn and drops its draft", () => {
    const cancelled = chatReducer(chatReducer(started, token("La")), { type: "cancel", id: "a1" });
    expect(assistant(cancelled)).toMatchObject({ phase: "cancelled", text: "", error: "Consulta cancelada." });
    expect(cancelled.busy).toBe(false);
  });
});
