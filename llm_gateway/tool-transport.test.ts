import { afterEach, expect, test } from "bun:test";
import { completeSimple, type } from "@oh-my-pi/pi-ai";
import { buildModel } from "@oh-my-pi/pi-catalog/build";
import { completedToolTransport } from "./tool-transport";

const servers: { stop(closeActiveConnections?: boolean): void }[] = [];
afterEach(() => { for (const server of servers.splice(0)) server.stop(true); });

function upstream(result: object) {
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    const payload: unknown = await request.json();
    if (!payload || typeof payload !== "object" || !("stream" in payload) || payload.stream !== false) {
      return new Response("Tool streams are not supported by this fixture", { status: 400 });
    }
    return Response.json(result);
  } });
  servers.push(server);
  const model = buildModel({ id: "gemini-3.8-flash", name: "Test model", provider: "openai-compatible", api: "openai-completions", baseUrl: `http://127.0.0.1:${server.port}/v1`, reasoning: false, input: ["text"], contextWindow: 1000, maxTokens: 1000, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, compat: { supportsStore: false, supportsStrictMode: false, supportsUsageInStreaming: false } });
  const transport = completedToolTransport(fetch);
  return { model, transport };
}

const context = {
  messages: [{ role: "user" as const, content: "Compare related historical papers.", timestamp: 0 }],
  tools: [
    { name: "search_history", description: "Search papers.", parameters: type({ source: "string", query: "string" }) },
    { name: "read_history", description: "Read one paper.", parameters: type({ source: "string", id: "string" }) },
  ],
};

test("complete tool responses retain the right function IDs, names, and arguments through the SDK", async () => {
  const { model, transport } = upstream({ id: "completion-1", model: "gemini-3.8-flash", choices: [{ index: 0, finish_reason: "tool_calls", message: { role: "assistant", content: null, tool_calls: [
    { id: "call-search", type: "function", function: { name: "search_history", arguments: '{"source":"papers","query":"CXL"}' } },
    { id: "call-read", type: "function", function: { name: "read_history", arguments: '{"source":"papers","id":"paper-1"}' } },
  ] } }], usage: { prompt_tokens: 20, completion_tokens: 15, total_tokens: 35 } });
  const result = await completeSimple(model, context, { apiKey: "test-only", ...transport });
  expect(result.stopReason).toBe("toolUse");
  expect(result.content.filter(part => part.type === "toolCall").map(part => ({ id: part.id, name: part.name, args: part.arguments }))).toEqual([
    { id: "call-search", name: "search_history", args: { source: "papers", query: "CXL" } },
    { id: "call-read", name: "read_history", args: { source: "papers", id: "paper-1" } },
  ]);
  expect(result.usage.input).toBe(20);
  expect(result.usage.output).toBe(15);
});

test("malformed complete tool arguments are rejected at the transport boundary", async () => {
  const { model, transport } = upstream({ id: "completion-invalid", model: "gemini-3.8-flash", choices: [{ index: 0, finish_reason: "tool_calls", message: { tool_calls: [{ id: "bad-call", type: "function", function: { name: "search_history", arguments: { query: "not a wire JSON string" } } }] } }] });
  await expect(transport.fetch(`${model.baseUrl}/chat/completions`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stream: false, tools: context.tools }),
  })).rejects.toThrow("非流式工具响应格式无效");
});

test("a truncated provider completion remains truncated rather than looking like successful tool output", async () => {
  const { model, transport } = upstream({ id: "completion-truncated", model: "gemini-3.8-flash", choices: [{ index: 0, finish_reason: "length", message: { role: "assistant", content: '{"relevance_score":' } }] });
  const result = await completeSimple(model, context, { apiKey: "test-only", ...transport });
  expect(result.stopReason).toBe("length");
});
