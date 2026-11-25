/**
 * Incremental Server-Sent Events parser (WHATWG event-stream format).
 *
 * `EventSource` cannot send a POST body, so the chat uses `fetch` and feeds the decoded chunks here.
 * Chunks may split anywhere, including inside a line or a CRLF pair.
 */

export interface RawSseEvent {
  event: string;
  data: string;
}

export class SseParser {
  private buffer = "";
  private eventType = "";
  private dataLines: string[] = [];

  /** Feed decoded text; returns the events completed by it. */
  feed(chunk: string): RawSseEvent[] {
    this.buffer += chunk;
    const events: RawSseEvent[] = [];
    let lineEnd: number;
    while ((lineEnd = this.nextLineEnd()) !== -1) {
      const line = this.buffer.slice(0, lineEnd);
      const skip = this.buffer[lineEnd] === "\r" && this.buffer[lineEnd + 1] === "\n" ? 2 : 1;
      this.buffer = this.buffer.slice(lineEnd + skip);
      const event = this.processLine(line);
      if (event) events.push(event);
    }
    return events;
  }

  private nextLineEnd(): number {
    for (let i = 0; i < this.buffer.length; i += 1) {
      const ch = this.buffer[i];
      if (ch === "\n") return i;
      if (ch === "\r") {
        // A trailing lone CR may be the first half of CRLF: wait for the next chunk.
        return i + 1 < this.buffer.length ? i : -1;
      }
    }
    return -1;
  }

  private processLine(line: string): RawSseEvent | null {
    if (line === "") {
      if (this.dataLines.length === 0) {
        this.eventType = "";
        return null;
      }
      const event = { event: this.eventType || "message", data: this.dataLines.join("\n") };
      this.eventType = "";
      this.dataLines = [];
      return event;
    }
    if (line.startsWith(":")) return null; // comment, e.g. keep-alive ": ping"
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") this.eventType = value;
    else if (field === "data") this.dataLines.push(value);
    return null;
  }
}
