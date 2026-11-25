import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import App from "./App";
import {
  ANSWER,
  LFT_CITATION,
  dofSource,
  frame,
  groundedFinal,
  happyStream,
  jsonFetch,
  lftSource,
  refusalFinal,
  sseFetch,
} from "./test/fakeApi";

async function ask(question = "¿Cuál es la jornada diurna?") {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Pregunta"), question);
  await user.click(screen.getByRole("button", { name: "Consultar" }));
  return user;
}

describe("App", () => {
  it("streams the answer and shows status while working", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const chunks = happyStream();
    render(<App fetchImpl={sseFetch(chunks, { gate, gateAt: chunks.length - 1 })} />);
    await ask();

    expect(await screen.findByText(/Redactando la respuesta/)).toBeInTheDocument();
    expect(screen.getByText(ANSWER)).toBeInTheDocument(); // draft visible before the final event
    expect(screen.getByRole("button", { name: "Detener" })).toBeInTheDocument();

    release();
    expect(await screen.findByRole("button", { name: LFT_CITATION })).toBeInTheDocument();
    expect(screen.queryByText(/Redactando la respuesta/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Consultar" })).toBeInTheDocument();
  });

  it("opens the Fuentes Verificadas panel at the cited source", async () => {
    render(<App fetchImpl={sseFetch(happyStream())} />);
    const user = await ask();

    const toggle = await screen.findByRole("button", { name: /Fuentes Verificadas/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(screen.getByRole("button", { name: LFT_CITATION }));
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    const panel = screen.getByRole("list");
    expect(within(panel).getByText(lftSource.excerpt)).toBeInTheDocument();
    expect(within(panel).getByText(lftSource.hierarchy!)).toBeInTheDocument();
    const link = within(panel).getByRole("link", { name: /Ver documento oficial/ });
    expect(link).toHaveAttribute("href", lftSource.url);
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAttribute("target", "_blank");

    await user.click(toggle);
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("replaces a rejected draft with the refusal", async () => {
    const draft = "La jornada es de ocho horas [Ley Federal del Trabajo, Art. 999, DOF 01/01/1970].";
    render(<App fetchImpl={sseFetch(happyStream(refusalFinal, draft))} />);
    await ask();
    expect(await screen.findByText("Sin sustento legal")).toBeInTheDocument();
    expect(screen.getByText(refusalFinal.answer)).toBeInTheDocument();
    expect(screen.queryByText(/Art\. 999/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Fuentes Verificadas/ })).not.toBeInTheDocument();
  });

  it("discards the draft and shows the error when the stream fails", async () => {
    const stream = [frame("token", { text: "La jornada " }), frame("error", { code: "agent_unavailable", message: "Servicio no disponible." })];
    render(<App fetchImpl={sseFetch(stream)} />);
    await ask();
    expect(await screen.findByRole("alert")).toHaveTextContent("Servicio no disponible.");
    expect(screen.queryByText(/La jornada/)).not.toBeInTheDocument();
  });

  it("shows HTTP errors from the API", async () => {
    render(<App fetchImpl={jsonFetch(429, { code: "rate_limited", detail: "Ha excedido el límite de consultas." })} />);
    await ask();
    expect(await screen.findByRole("alert")).toHaveTextContent("Ha excedido el límite de consultas.");
  });

  it("can stop a running question", async () => {
    const gate = new Promise<void>(() => {}); // never releases: the answer never arrives
    const chunks = happyStream();
    render(<App fetchImpl={sseFetch(chunks, { gate, gateAt: 2 })} />);
    const user = await ask();
    await user.click(await screen.findByRole("button", { name: "Detener" }));
    expect(await screen.findByText("Consulta cancelada.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Consultar" })).toBeInTheDocument();
  });

  it("does not link sources with unsafe URLs and flags partial excerpts", async () => {
    const unsafe = { ...dofSource, url: "javascript:alert(1)" };
    const final = { ...groundedFinal, answer: `Se publicó ${unsafe.citation}.`, route: "mcp" as const, sources: [unsafe] };
    render(<App fetchImpl={sseFetch(happyStream(final))} />);
    const user = await ask("¿Qué publicó el DOF?");
    await user.click(await screen.findByRole("button", { name: /Fuentes Verificadas/ }));
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText(/Extracto parcial/)).toBeInTheDocument();
    expect(screen.getByText("DOF", { selector: "span" })).toBeInTheDocument();
  });

  it("renders answer text as text, never as HTML", async () => {
    const final = { ...groundedFinal, answer: `<img src=x onerror="alert(1)"> ${LFT_CITATION}` };
    const { container } = render(<App fetchImpl={sseFetch(happyStream(final))} />);
    await ask();
    await screen.findByRole("button", { name: LFT_CITATION });
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/<img src=x/)).toBeInTheDocument();
  });

  it("validates the question length before sending", async () => {
    render(<App fetchImpl={sseFetch(happyStream())} />);
    const user = userEvent.setup();
    const input = screen.getByLabelText("Pregunta");
    await user.click(input);
    await user.paste("x".repeat(2001));
    expect(screen.getByRole("button", { name: "Consultar" })).toBeDisabled();
    expect(screen.getByText(/no puede exceder 2000 caracteres/)).toBeInTheDocument();
  });

  it("sends an example question", async () => {
    const calls: RequestInit[] = [];
    render(<App fetchImpl={sseFetch(happyStream(), { calls })} />);
    await userEvent.setup().click(screen.getByRole("button", { name: /jornada de trabajo diurna/ }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(JSON.parse(String(calls[0]?.body))).toEqual({
      question: "¿Cuál es la duración máxima de la jornada de trabajo diurna?",
    });
  });
});
