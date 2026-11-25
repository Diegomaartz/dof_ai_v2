import { describe, expect, it } from "vitest";

import { SseParser } from "./sse";

const feedAll = (parser: SseParser, chunks: string[]) => chunks.flatMap((c) => parser.feed(c));

describe("SseParser", () => {
  it("parses complete frames", () => {
    const events = new SseParser().feed('event: token\ndata: {"text":"a"}\n\nevent: final\ndata: {}\n\n');
    expect(events).toEqual([
      { event: "token", data: '{"text":"a"}' },
      { event: "final", data: "{}" },
    ]);
  });

  it("handles frames split at every character", () => {
    const text = 'event: status\ndata: {"label":"Analizando"}\n\n';
    expect(feedAll(new SseParser(), [...text])).toEqual([{ event: "status", data: '{"label":"Analizando"}' }]);
  });

  it("handles CRLF, including a CRLF split across chunks", () => {
    expect(feedAll(new SseParser(), ["event: token\r", "\ndata: x\r\n\r", "\n"])).toEqual([
      { event: "token", data: "x" },
    ]);
  });

  it("ignores comments such as keep-alive pings", () => {
    expect(new SseParser().feed(": ping\n\nevent: token\ndata: y\n\n")).toEqual([{ event: "token", data: "y" }]);
  });

  it("joins multi-line data and defaults the event type", () => {
    expect(new SseParser().feed("data: uno\ndata:dos\n\n")).toEqual([{ event: "message", data: "uno\ndos" }]);
  });

  it("does not leak the event type into the next frame", () => {
    expect(new SseParser().feed("event: token\n\ndata: z\n\n")).toEqual([{ event: "message", data: "z" }]);
  });

  it("keeps an incomplete frame buffered", () => {
    const parser = new SseParser();
    expect(parser.feed("event: token\ndata: a")).toEqual([]);
    expect(parser.feed("\n\n")).toEqual([{ event: "token", data: "a" }]);
  });
});
