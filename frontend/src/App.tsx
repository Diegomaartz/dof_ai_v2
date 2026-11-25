import { useEffect, useRef } from "react";

import { AssistantMessage } from "./components/AssistantMessage";
import { ChatInput } from "./components/ChatInput";
import { useChat } from "./hooks/useChat";

const EXAMPLES = [
  "¿Cuál es la duración máxima de la jornada de trabajo diurna?",
  "¿Qué publicó hoy el Diario Oficial de la Federación?",
  "¿Qué decretos se publicaron en el DOF el 20 de noviembre de 2026?",
];

export default function App({ fetchImpl }: { fetchImpl?: typeof fetch }) {
  const { turns, busy, send, stop } = useChat(fetchImpl);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [turns]);

  return (
    <div className="mx-auto flex min-h-dvh max-w-3xl flex-col px-4">
      <header className="border-b border-stone-200 py-5">
        <h1 className="text-xl font-semibold tracking-tight text-stone-900">
          DOF<span className="text-emerald-800">-AI</span>
        </h1>
        <p className="text-sm text-stone-500">
          Legislación federal mexicana y Diario Oficial de la Federación, con fuentes verificadas.
        </p>
      </header>

      <main className="flex-1 space-y-5 py-6" aria-live="polite">
        {turns.length === 0 && (
          <section className="rounded-xl border border-dashed border-stone-300 p-6 text-center">
            <p className="text-stone-600">
              Cada respuesta cita el artículo, la ley o la publicación del DOF que la sustenta. Si no hay sustento en
              las fuentes, DOF-AI lo indica en lugar de suponer.
            </p>
            <ul className="mt-4 flex flex-col gap-2">
              {EXAMPLES.map((example) => (
                <li key={example}>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void send(example)}
                    className="w-full rounded-lg border border-stone-200 bg-white px-4 py-2 text-left text-sm text-stone-700 hover:border-emerald-600 hover:text-emerald-900"
                  >
                    {example}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        {turns.map((turn) =>
          turn.role === "user" ? (
            <div key={turn.id} className="flex justify-end">
              <p className="max-w-[85%] whitespace-pre-wrap rounded-xl bg-emerald-800 px-4 py-2.5 text-white">
                {turn.text}
              </p>
            </div>
          ) : (
            <AssistantMessage key={turn.id} turn={turn} />
          ),
        )}
        <div ref={endRef} />
      </main>

      <footer className="sticky bottom-0 border-t border-stone-200 bg-stone-50/95 py-4 backdrop-blur">
        <ChatInput busy={busy} onSend={(question) => void send(question)} onStop={stop} />
        <p className="mt-2 text-center text-xs text-stone-400">
          Información con fines informativos; no constituye asesoría legal.
        </p>
      </footer>
    </div>
  );
}
