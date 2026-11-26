import { expect, test } from "bun:test";
import { ModelRequestError, runModelRequest } from "./request-lifecycle";

const context = { backend: "openai-compatible", model: "gemini-3.8-flash", upstreamHost: "api.example.com", agent: false };

function waitForAbort(signal: AbortSignal): Promise<never> {
  const { promise, reject } = Promise.withResolvers<never>();
  const fail = () => reject(new Error("Request was aborted"));
  if (signal.aborted) fail();
  else signal.addEventListener("abort", fail, { once: true });
  return promise;
}

test("gateway deadline identifies a locally aborted slow model, not a generic upstream 502", async () => {
  const error = await runModelRequest(waitForAbort, new AbortController().signal, 10, context).catch((error: unknown) => error);
  expect(error).toBeInstanceOf(ModelRequestError);
  if (!(error instanceof ModelRequestError)) throw new Error("Expected a structured timeout");
  expect(error.status).toBe(504);
  expect(error.type).toBe("gateway_timeout");
  expect(error.message).toContain("gemini-3.8-flash");
  expect(error.message).toContain("api.example.com");
});

test("caller cancellation and an upstream error remain distinct from the gateway deadline", async () => {
  const client = new AbortController();
  client.abort(new Error("Client closed connection"));
  let called = false;
  const cancelled = await runModelRequest(async () => { called = true; return "unused"; }, client.signal, 1000, context).catch((error: unknown) => error);
  expect(called).toBe(false);
  expect(cancelled).toBeInstanceOf(ModelRequestError);
  if (!(cancelled instanceof ModelRequestError)) throw new Error("Expected caller cancellation");
  expect(cancelled.status).toBe(499);
  const upstream = new Error("Upstream returned HTTP 429");
  const original = await runModelRequest(async () => { throw upstream; }, new AbortController().signal, 1000, context).catch((error: unknown) => error);
  expect(original).toBe(upstream);
});

test("a result returned after cancellation cannot be accepted as a successful completion", async () => {
  const client = new AbortController();
  const result = runModelRequest(async () => { client.abort(); return "partial answer"; }, client.signal, 1000, context);
  await expect(result).rejects.toMatchObject({ status: 499, type: "client_disconnected" });
});
