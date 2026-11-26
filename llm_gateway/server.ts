import { timingSafeEqual } from "node:crypto";
import { Agent } from "@oh-my-pi/pi-agent-core";
import { completeSimple, streamSimple, type, type AssistantMessage, type Context, type Message, type Model } from "@oh-my-pi/pi-ai";
import { Effort } from "@oh-my-pi/pi-catalog/effort";
import { HistoryReader, historyTools, type DatabasePaths } from "./history";
import { parseJsonObject } from "./protocol";
import { createModelSettings, DEFAULT_RESEARCH_INSTRUCTIONS, SettingsError, type EffortLevel, type ModelSnapshot } from "./settings";
import { ModelRequestError, runModelRequest } from "./request-lifecycle";
import { completedToolTransport } from "./tool-transport";
import { ModelOutputError, modelOutput } from "./model-output";

process.umask(0o077);
const secret = process.env.LLM_GATEWAY_KEY;
if (!secret) throw new Error("LLM_GATEWAY_KEY is required");
const settings = await createModelSettings();
const paths: DatabasePaths = {
  notes: process.env.LLM_NOTES_DB || "/root/wechat_obsidian/data/inbox.db",
  insights: process.env.LLM_INSIGHTS_DB || "/root/insight_extractor/data/insights.db",
  radar: process.env.LLM_RADAR_DB || "/root/social_radar/data/social_radar.db",
  mail: process.env.LLM_MAIL_DB || "/root/mail_assist/data/mail_assist.db",
};

const textPart = type({ type: "'text'", text: "string" });
const imagePart = type({ type: "'image_url'", image_url: { url: "string" } });
const contentType = type("string").or(textPart.or(imagePart).array());
const requestType = type({
  model: "string",
  messages: type({ role: "'system' | 'developer' | 'user' | 'assistant'", content: contentType }).array(),
  "stream?": "boolean", "temperature?": "number", "max_tokens?": "number",
  "reasoning_effort?": "'minimal' | 'low' | 'medium' | 'high'",
  "response_format?": { type: "'json_object' | 'text'" },
  "user?": "string",
});
type CompletionRequest = typeof requestType.infer;

class HttpError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

function contentParts(content: CompletionRequest["messages"][number]["content"]) {
  if (typeof content === "string") return [{ type: "text" as const, text: content }];
  return content.map(part => {
    if (part.type === "text") return part;
    const match = /^data:(image\/(?:png|jpeg|webp|gif));base64,([A-Za-z0-9+/=\r\n]+)$/.exec(part.image_url.url);
    if (!match) throw new HttpError(400, "Images must be supported base64 data URLs; remote URL fetching is not allowed");
    return { type: "image" as const, mimeType: match[1], data: match[2] };
  });
}

function contextOf(request: CompletionRequest, model: Model): Context {
  const systemPrompt: string[] = [];
  const messages: Message[] = [];
  for (const message of request.messages) {
    const parts = contentParts(message.content);
    if (message.role === "system" || message.role === "developer") {
      if (parts.some(part => part.type !== "text")) throw new HttpError(400, "System instructions must contain text only");
      systemPrompt.push(parts.filter(part => part.type === "text").map(part => part.text).join("\n"));
    } else if (message.role === "user") {
      messages.push({ role: "user", content: parts, timestamp: Date.now() });
    } else {
      if (parts.some(part => part.type !== "text")) throw new HttpError(400, "Assistant history must contain text only");
      messages.push({ role: "assistant", content: parts.filter(part => part.type === "text"), api: model.api, provider: model.provider, model: model.id, timestamp: Date.now(), stopReason: "stop", usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } });
    }
  }
  if (!messages.length || messages.at(-1)?.role !== "user") throw new HttpError(400, "A final user message is required");
  if (request.response_format?.type === "json_object") systemPrompt.push("Return the final answer as exactly one valid JSON object, without Markdown fences. Preserve the requested JSON fields. Tool calls may precede that final answer.");
  return { systemPrompt, messages };
}


const effortMap: Record<EffortLevel, Effort> = {
  minimal: Effort.Minimal,
  low: Effort.Low,
  medium: Effort.Medium,
  high: Effort.High,
};

async function completion(request: CompletionRequest, agentMode: boolean, signal: AbortSignal, snapshot: ModelSnapshot) {
  const model = snapshot.models.get(request.model === "default" ? snapshot.config.default_model : request.model);
  if (!model) throw new HttpError(400, "Model is not enabled for the selected backend; query /v1/models");
  const context = contextOf(request, model);
  const globalPrompt = (snapshot.config.default_system_prompt || "").trim();
  const used: string[] = [];
  let submitted: object | undefined;
  let messages: AssistantMessage[];
  let activeAgentEffort: EffortLevel = snapshot.config.agent_effort || "high";
  if (agentMode) {
    activeAgentEffort = request.reasoning_effort || snapshot.config.agent_effort || "high";
    let modelCalls = 0;
    const transport = model.api === "openai-completions" ? completedToolTransport(snapshot.fetcher) : undefined;
    const tools = historyTools(new HistoryReader(paths, request.user), used);
    const agentPrompt = (snapshot.config.agent_instructions || "").trim() || DEFAULT_RESEARCH_INSTRUCTIONS;
    const systemPrompt = [agentPrompt, ...(globalPrompt ? [globalPrompt] : []), ...(context.systemPrompt || [])];
    if (request.response_format?.type === "json_object") {
      const submissionType = type({ analysis: "object" });
      systemPrompt.push("最终结果必须通过 submit_analysis 提交：analysis 参数直接包含调用者要求的 JSON 对象，不要放入字符串，不要用普通文本输出最终答案。先完成需要的历史检索，再提交；可以不产生有价值洞察，但必须如实提交相应 JSON。");
      tools.push({
        name: "submit_analysis", label: "Submit structured analysis",
        description: "Submit the final analysis as a structured object with exactly the fields requested by the caller. This ends analysis; it does not write to the database or send notifications.",
        parameters: submissionType,
        execute: async (_id, input: unknown) => {
          const parsed = submissionType(input);
          if (parsed instanceof type.errors) throw new Error(parsed.summary);
          submitted = parsed.analysis;
          used.push("submit_analysis");
          return { content: [{ type: "text", text: "Structured analysis accepted." }], details: {} };
        },
      });
    }
    const agent = new Agent({
      initialState: { model, systemPrompt, thinkingLevel: effortMap[activeAgentEffort], tools },
      getApiKey: selected => snapshot.apiKey(selected.id),
      deadline: Date.now() + 240000,
      onPayload: transport?.onPayload,
      streamFn: (selected, ctx, options) => streamSimple(selected, ctx, { ...options, fetch: transport?.fetch || snapshot.fetcher, maxTokens: 6000, signal: options?.signal ? AbortSignal.any([signal, options.signal]) : signal }),
    });
    agent.setBeforeModelCall(() => {
      if (submitted) return { stop: true, reason: "Structured analysis submitted" };
      if (++modelCalls > 6) throw new Error("Agent model-call limit reached before a final answer");
    });
    const abort = () => agent.abort(signal.reason);
    signal.addEventListener("abort", abort, { once: true });
    try { await agent.prompt(context.messages, { toolChoice: request.response_format?.type === "json_object" ? "required" : undefined }); }
    finally { signal.removeEventListener("abort", abort); }
    messages = agent.state.messages.filter((message): message is AssistantMessage => message.role === "assistant");
  } else {
    const activeDirectEffort: EffortLevel = request.reasoning_effort || snapshot.config.direct_effort || "low";
    const directContext: Context = globalPrompt ? { ...context, systemPrompt: [globalPrompt, ...(context.systemPrompt || [])] } : context;
    messages = [await completeSimple(model, directContext, { apiKey: await snapshot.apiKey(model.id), reasoning: effortMap[activeDirectEffort], temperature: request.temperature, maxTokens: request.max_tokens || 4000, fetch: snapshot.fetcher, signal })];
  }
  const last = messages.at(-1);
  const source = `模型 ${model.id}；上游 ${snapshot.config.backend} / ${new URL(model.baseUrl).host}`;
  let text = modelOutput(last, submitted, agentMode && request.response_format?.type === "json_object", source);
  if (request.response_format?.type === "json_object") {
    text = JSON.stringify(parseJsonObject(text));
  }
  const promptTokens = messages.reduce((sum, message) => sum + message.usage.input + message.usage.cacheRead, 0);
  const completionTokens = messages.reduce((sum, message) => sum + message.usage.output, 0);
  return {
    id: `chatcmpl-${crypto.randomUUID()}`, object: "chat.completion", created: Math.floor(Date.now() / 1000), model: model.id,
    choices: [{ index: 0, message: { role: "assistant", content: text }, finish_reason: "stop" }],
    usage: { prompt_tokens: promptTokens, completion_tokens: completionTokens, total_tokens: promptTokens + completionTokens },
    agent: agentMode ? { thinking: activeAgentEffort, tool_calls: used } : undefined,
  };
}

function authorized(request: Request): boolean {
  const supplied = Buffer.from(request.headers.get("authorization") || "");
  const expected = Buffer.from(`Bearer ${secret}`);
  return supplied.length === expected.length && timingSafeEqual(supplied, expected);
}

const server = Bun.serve({
  hostname: "127.0.0.1", port: Number(process.env.LLM_GATEWAY_PORT || 18890), idleTimeout: 255, maxRequestBodySize: 16 * 1024 * 1024,
  async fetch(request) {
    let candidate: unknown;
    const snapshot = settings.current;
    try {
      if (!authorized(request)) throw new HttpError(401, "Invalid local gateway credential");
      const path = new URL(request.url).pathname;
      if (request.method === "GET" && path === "/health") {
        const view = await settings.view();
        return Response.json({ status: snapshot ? "ok" : "configuration_error", provider: view.backend, default_model: view.default_model }, { status: snapshot ? 200 : 503 });
      }
      if (request.method === "GET" && path === "/settings") return Response.json({ code: 0, settings: await settings.view() }, { headers: { "Cache-Control": "no-store" } });
      if (request.method === "POST" && ["/settings/models", "/settings/test", "/settings/save"].includes(path)) {
        candidate = await request.json();
        if (path === "/settings/models") return Response.json({ code: 0, models: [...(await settings.candidate(candidate, { requireModel: false })).models.keys()].sort() }, { headers: { "Cache-Control": "no-store" } });
        if (path === "/settings/test") return Response.json({ code: 0, test: await settings.test(candidate) }, { headers: { "Cache-Control": "no-store" } });
        return Response.json({ code: 0, settings: await settings.save(candidate) }, { headers: { "Cache-Control": "no-store" } });
      }
      if (!snapshot) throw new HttpError(503, "模型通道不可用，请在网页模型设置中检查 API 地址、密钥和模型");
      if (request.method === "GET" && (path === "/v1/models" || path === "/agent/v1/models")) {
        return Response.json({ object: "list", data: [...snapshot.models.keys()].map(id => ({ id, object: "model", owned_by: snapshot.config.backend })) });
      }
      const agentMode = path === "/agent/v1/chat/completions";
      if (request.method !== "POST" || (!agentMode && path !== "/v1/chat/completions")) throw new HttpError(404, "Unknown gateway route");
      const input: unknown = await request.json();
      const parsed = requestType(input);
      if (parsed instanceof type.errors) throw new HttpError(400, parsed.summary);
      if (parsed.stream) throw new HttpError(400, "Streaming is not supported by this internal synchronous gateway");
      const modelId = parsed.model === "default" ? snapshot.config.default_model : parsed.model;
      const selected = snapshot.models.get(modelId);
      const response = await runModelRequest(
        signal => completion(parsed, agentMode, signal, snapshot),
        request.signal, agentMode ? 240000 : 45000,
        { backend: snapshot.config.backend, model: modelId, upstreamHost: selected?.baseUrl ? new URL(selected.baseUrl).host : "unknown", agent: agentMode },
      );
      return Response.json(response);
    } catch (error) {
      const status = error instanceof HttpError || error instanceof SettingsError || error instanceof ModelRequestError || error instanceof ModelOutputError ? error.status : 502;
      let message = settings.redact(error instanceof Error ? error.message : "Model request failed", candidate);
      if (snapshot?.config.api_key) message = message.replaceAll(snapshot.config.api_key, "[REDACTED]");
      const body = new URL(request.url).pathname.startsWith("/settings")
        ? { code: status, error: message, field: error instanceof SettingsError ? error.field : undefined }
        : { code: status, error: { message, type: error instanceof ModelRequestError || error instanceof ModelOutputError ? error.type : "gateway_error", code: status } };
      return Response.json(body, { status, headers: { "Cache-Control": "no-store" } });
    }
  },
});
console.log(`Model gateway listening on ${server.hostname}:${server.port}; model_ready=${!!settings.current}; agent thinking=high`);
