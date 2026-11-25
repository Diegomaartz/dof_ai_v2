import { useState, type FormEvent, type KeyboardEvent } from "react";

import { MAX_QUESTION_CHARS } from "../api/chat";

interface ChatInputProps {
  busy: boolean;
  onSend: (question: string) => void;
  onStop: () => void;
}

export function ChatInput({ busy, onSend, onStop }: ChatInputProps) {
  const [value, setValue] = useState("");
  const trimmed = value.trim();
  const tooLong = value.length > MAX_QUESTION_CHARS;
  const canSend = !busy && trimmed.length > 0 && !tooLong;

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (!canSend) return;
    onSend(trimmed);
    setValue("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-2">
      <label htmlFor="pregunta" className="sr-only">
        Pregunta
      </label>
      <div className="flex items-end gap-2 rounded-xl border border-stone-300 bg-white p-2 shadow-sm focus-within:border-emerald-600 focus-within:ring-2 focus-within:ring-emerald-100">
        <textarea
          id="pregunta"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={onKeyDown}
          rows={2}
          placeholder="Pregunte sobre legislación federal o publicaciones del DOF…"
          aria-describedby="pregunta-ayuda"
          aria-invalid={tooLong}
          className="max-h-48 min-h-[2.75rem] flex-1 resize-y bg-transparent px-2 py-1.5 text-stone-900 placeholder:text-stone-400 focus:outline-none"
        />
        {busy ? (
          <button
            type="button"
            onClick={onStop}
            className="rounded-lg border border-stone-300 px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-100"
          >
            Detener
          </button>
        ) : (
          <button
            type="submit"
            disabled={!canSend}
            className="rounded-lg bg-emerald-800 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-900 disabled:cursor-not-allowed disabled:bg-stone-300"
          >
            Consultar
          </button>
        )}
      </div>
      <p id="pregunta-ayuda" className={`text-right text-xs ${tooLong ? "text-red-700" : "text-stone-400"}`}>
        {tooLong
          ? `La pregunta no puede exceder ${MAX_QUESTION_CHARS} caracteres (${value.length}).`
          : "Enter para enviar · Mayús + Enter para nueva línea"}
      </p>
    </form>
  );
}
