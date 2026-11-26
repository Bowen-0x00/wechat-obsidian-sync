import { expect, test } from "bun:test";
import type { AssistantMessage } from "@oh-my-pi/pi-ai";
import { ModelOutputError, modelOutput } from "./model-output";

const message: AssistantMessage = { role: "assistant", content: [], api: "openai-completions", provider: "openai-compatible", model: "gemini-3.8-flash", timestamp: 0, stopReason: "stop", usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } };
const source = "模型 gemini-3.8-flash；上游 api.example.com";

test("provider failure is preserved instead of being hidden by a missing analysis submission", () => {
  const failure = { ...message, stopReason: "error" as const, errorMessage: "Upstream HTTP 429 capacity exceeded", errorStatus: 429 };
  let caught: unknown;
  try { modelOutput(failure, undefined, true, source); } catch (error) { caught = error; }
  expect(caught).toBeInstanceOf(ModelOutputError);
  if (!(caught instanceof ModelOutputError)) throw new Error("Expected model output failure");
  expect(caught.status).toBe(429);
  expect(caught.type).toBe("upstream_model_error");
  expect(caught.message).toContain("capacity exceeded");
  expect(caught.message).toContain("gemini-3.8-flash");
});

test("truncation and a completed-but-unsubmitted analysis stay distinct failures", () => {
  expect(() => modelOutput({ ...message, stopReason: "length" }, undefined, true, source)).toThrow("长度上限");
  expect(() => modelOutput({ ...message, content: [{ type: "text", text: '{"relevance_score":90}' }] }, undefined, true, source)).toThrow("未通过 submit_analysis");
});
