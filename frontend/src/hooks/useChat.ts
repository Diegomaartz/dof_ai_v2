/** Conversation state: one user turn and one streamed assistant turn per question. */

import { useCallback, useEffect, useReducer, useRef } from "react";

import { ChatApiError, isAbort, streamChat } from "../api/chat";
import type { ChatEvent, ChatSource, Route } from "../types";

export type AssistantPhase = "streaming" | "done" | "error" | "cancelled";

export interface UserTurn {
  id: string;
  role: "user";
  text: string;
}

export interface AssistantTurn {
  id: string;
  role: "assistant";
  phase: AssistantPhase;
  /** Streamed draft while `phase === "streaming"`; the validated answer once done. */
  text: string;
  statusLabel: string | null;
  refused: boolean;
  route: Route | null;
  sources: ChatSource[];
  error: string | null;
}

export type Turn = UserTurn | AssistantTurn;

export interface ChatState {
  turns: Turn[];
  busy: boolean;
}

export type ChatAction =
  | { type: "start"; question: string; userId: string; assistantId: string }
  | { type: "event"; id: string; event: ChatEvent }
  | { type: "fail"; id: string; message: string }
  | { type: "cancel"; id: string };

export const initialChatState: ChatState = { turns: [], busy: false };

const CANCELLED_MESSAGE = "Consulta cancelada.";

function updateAssistant(state: ChatState, id: string, patch: (turn: AssistantTurn) => AssistantTurn): Turn[] {
  return state.turns.map((turn) => (turn.role === "assistant" && turn.id === id ? patch(turn) : turn));
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "start":
      return {
        busy: true,
        turns: [
          ...state.turns,
          { id: action.userId, role: "user", text: action.question },
          {
            id: action.assistantId,
            role: "assistant",
            phase: "streaming",
            text: "",
            statusLabel: "Enviando consulta",
            refused: false,
            route: null,
            sources: [],
            error: null,
          },
        ],
      };
    case "event": {
      const { event } = action;
      const turns = updateAssistant(state, action.id, (turn) => {
        if (turn.phase !== "streaming") return turn;
        switch (event.type) {
          case "status":
            return { ...turn, statusLabel: event.label };
          case "token":
            return { ...turn, text: turn.text + event.text };
          case "final":
            // The final event is authoritative: a draft rejected by the grounding check becomes the refusal.
            return {
              ...turn,
              phase: "done",
              text: event.data.answer,
              refused: event.data.refused,
              route: event.data.route,
              sources: event.data.sources,
              statusLabel: null,
            };
          case "error":
            return { ...turn, phase: "error", text: "", sources: [], statusLabel: null, error: event.message };
        }
      });
      const finished = event.type === "final" || event.type === "error";
      return { turns, busy: finished ? false : state.busy };
    }
    case "fail":
      return {
        busy: false,
        turns: updateAssistant(state, action.id, (turn) =>
          turn.phase === "streaming"
            ? { ...turn, phase: "error", text: "", sources: [], statusLabel: null, error: action.message }
            : turn,
        ),
      };
    case "cancel":
      return {
        busy: false,
        turns: updateAssistant(state, action.id, (turn) =>
          turn.phase === "streaming"
            ? { ...turn, phase: "cancelled", text: "", sources: [], statusLabel: null, error: CANCELLED_MESSAGE }
            : turn,
        ),
      };
  }
}

let counter = 0;
const nextId = (prefix: string): string => `${prefix}-${Date.now().toString(36)}-${(counter += 1)}`;

export interface UseChat extends ChatState {
  send: (question: string) => Promise<void>;
  stop: () => void;
}

export function useChat(fetchImpl?: typeof fetch): UseChat {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const controller = useRef<AbortController | null>(null);
  const busy = useRef(false);

  useEffect(() => () => controller.current?.abort(), []);

  const send = useCallback(
    async (question: string) => {
      const trimmed = question.trim();
      if (!trimmed || busy.current) return;
      busy.current = true;
      const assistantId = nextId("a");
      const abort = new AbortController();
      controller.current = abort;
      dispatch({ type: "start", question: trimmed, userId: nextId("u"), assistantId });
      try {
        await streamChat(trimmed, (event) => dispatch({ type: "event", id: assistantId, event }), {
          signal: abort.signal,
          fetchImpl,
        });
      } catch (error) {
        if (isAbort(error) || abort.signal.aborted) {
          dispatch({ type: "cancel", id: assistantId });
        } else {
          // After an SSE `error` event the turn is no longer streaming, so this is a no-op; it covers HTTP,
          // network and protocol failures.
          const message = error instanceof ChatApiError ? error.message : "Ocurrió un error inesperado.";
          dispatch({ type: "fail", id: assistantId, message });
        }
      } finally {
        busy.current = false;
        if (controller.current === abort) controller.current = null;
      }
    },
    [fetchImpl],
  );

  const stop = useCallback(() => controller.current?.abort(), []);

  return { ...state, send, stop };
}
