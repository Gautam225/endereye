/**
 * Reads a Server-Sent Events stream (https://html.spec.whatwg.org/#event-stream-interpretation).
 * Used instead of EventSource because EventSource cannot send POST requests.
 */

export interface SseMessage {
  event: string;
  data: string;
}

export async function* readSse(stream: ReadableStream<Uint8Array>): AsyncGenerator<SseMessage> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let event = "";
  let data: string[] = [];

  function* handle(line: string): Generator<SseMessage> {
    if (line === "") {
      // A blank line ends one message.
      if (data.length > 0) yield { event: event || "message", data: data.join("\n") };
      event = "";
      data = [];
      return;
    }
    if (line.startsWith(":")) return; // comment, e.g. keep-alive ": ping"
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }); // keeps multi-byte characters intact
      // A chunk may end between "\r" and "\n": keep a trailing "\r" until the next chunk.
      const hold = buffer.endsWith("\r") ? "\r" : "";
      const lines = (hold ? buffer.slice(0, -1) : buffer).split(/\r\n|\r|\n/);
      buffer = (lines.pop() ?? "") + hold;
      for (const line of lines) yield* handle(line);
    }
    buffer += decoder.decode();
    if (buffer) yield* handle(buffer.replace(/\r$/, ""));
    yield* handle(""); // the stream may end without a final blank line
  } finally {
    reader.releaseLock();
  }
}
