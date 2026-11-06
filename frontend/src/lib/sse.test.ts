import { describe, expect, it } from "vitest";

import { readSse, type SseMessage } from "./sse";

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function collect(chunks: string[]): Promise<SseMessage[]> {
  const messages: SseMessage[] = [];
  for await (const message of readSse(streamOf(chunks))) messages.push(message);
  return messages;
}

describe("readSse", () => {
  it("reads named events with JSON data", async () => {
    const messages = await collect([
      'event: meta\ndata: {"provider":"groq"}\n\n',
      'event: delta\ndata: {"text":"Hi"}\n\n',
    ]);
    expect(messages).toEqual([
      { event: "meta", data: '{"provider":"groq"}' },
      { event: "delta", data: '{"text":"Hi"}' },
    ]);
  });

  it("handles messages split across chunks at any point", async () => {
    const text = 'event: delta\ndata: {"text":"Hello"}\n\nevent: done\ndata: {}\n\n';
    const chunks = text.split(""); // one character per chunk
    expect(await collect(chunks)).toEqual([
      { event: "delta", data: '{"text":"Hello"}' },
      { event: "done", data: "{}" },
    ]);
  });

  it("handles CRLF line endings split between chunks", async () => {
    expect(await collect(["event: a\r", "\ndata: 1\r\n\r", "\n"])).toEqual([
      { event: "a", data: "1" },
    ]);
  });

  it("skips keep-alive comments and joins multi-line data", async () => {
    expect(await collect([": ping\n\n", "data: line 1\ndata: line 2\n\n"])).toEqual([
      { event: "message", data: "line 1\nline 2" },
    ]);
  });

  it("keeps multi-byte characters intact when bytes are split across chunks", async () => {
    const bytes = new TextEncoder().encode('data: {"text":"₹ 1,200 · नमस्ते"}\n\n');
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
        controller.close();
      },
    });
    const messages: SseMessage[] = [];
    for await (const message of readSse(stream)) messages.push(message);
    expect(messages).toEqual([{ event: "message", data: '{"text":"₹ 1,200 · नमस्ते"}' }]);
  });

  it("delivers the last message even without a final blank line", async () => {
    expect(await collect(["event: done\ndata: {}"])).toEqual([{ event: "done", data: "{}" }]);
  });
});
