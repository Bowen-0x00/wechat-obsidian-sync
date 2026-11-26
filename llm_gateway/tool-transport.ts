import { type, type FetchImpl } from "@oh-my-pi/pi-ai";

const functionCall = type({ id: "string", type: "'function'", function: { name: "string", arguments: "string" } });
const completion = type({
  id: "string", model: "string", "created?": "number",
  choices: type({
    index: "number", finish_reason: "'stop' | 'length' | 'tool_calls' | 'content_filter' | null",
    message: {
      "role?": "'assistant'", "content?": "string | null", "refusal?": "string | null",
      "reasoning_content?": "string | null", "tool_calls?": functionCall.array(),
    },
  }).array(),
  "usage?": { prompt_tokens: "number", completion_tokens: "number", total_tokens: "number" },
});

/** Complete tool calls atomically on OpenAI-compatible hosts; never reconstruct split or unnamed calls. */
export function completedToolTransport(base: FetchImpl) {
  return {
    onPayload(payload: unknown): unknown {
      if (!payload || typeof payload !== "object" || !("tools" in payload) || !Array.isArray(payload.tools) || !payload.tools.length) return undefined;
      const request = { ...payload, stream: false };
      if ("stream_options" in request) delete request.stream_options;
      return request;
    },
    fetch: (async (input, init) => {
      const response = await base(input, init);
      const path = new URL(input instanceof Request ? input.url : input.toString()).pathname;
      if (!response.ok || !path.endsWith("/chat/completions") || !response.headers.get("content-type")?.includes("application/json")) return response;
      const parsed = completion(await response.json());
      if (parsed instanceof type.errors || !parsed.choices.length || parsed.choices.some(choice => !choice.finish_reason)) {
        throw new Error("上游非流式工具响应格式无效，未执行任何不完整调用");
      }
      // The SDK consumes SSE. Frame the already-complete provider result without changing names, IDs, or arguments.
      const chunk = {
        id: parsed.id, object: "chat.completion.chunk", model: parsed.model, created: parsed.created,
        choices: parsed.choices.map(choice => ({
          index: choice.index, finish_reason: choice.finish_reason,
          delta: {
            role: "assistant", content: choice.message.content, refusal: choice.message.refusal,
            reasoning_content: choice.message.reasoning_content,
            tool_calls: choice.message.tool_calls?.map((call, index) => ({ index, ...call })),
          },
        })),
        usage: parsed.usage,
      };
      const headers = new Headers(response.headers);
      headers.set("Content-Type", "text/event-stream");
      headers.delete("Content-Length"); headers.delete("Content-Encoding");
      return new Response(`data: ${JSON.stringify(chunk)}\n\ndata: [DONE]\n\n`, { status: response.status, headers });
    }) satisfies FetchImpl,
  };
}
