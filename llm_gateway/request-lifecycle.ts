export interface ModelRequestContext {
  backend: string;
  model: string;
  upstreamHost: string;
  agent: boolean;
}

export class ModelRequestError extends Error {
  constructor(
    readonly status: 499 | 504,
    readonly type: "client_disconnected" | "gateway_timeout",
    message: string,
  ) { super(message); }
}

/** Own the request deadline so caller cancellation cannot be mistaken for an upstream failure. */
export async function runModelRequest<T>(
  operation: (signal: AbortSignal) => Promise<T>,
  clientSignal: AbortSignal,
  timeoutMs: number,
  context: ModelRequestContext,
): Promise<T> {
  const deadline = new AbortController();
  const timeout = new ModelRequestError(
    504, "gateway_timeout",
    `模型 ${context.model}；上游 ${context.backend} / ${context.upstreamHost}；${context.agent ? "研究 agent" : "直接请求"}超过 ${timeoutMs / 1000} 秒截止时间，已由本机网关中止。API 配置未切换。`,
  );
  const timer = setTimeout(() => deadline.abort(timeout), timeoutMs);
  const signal = AbortSignal.any([clientSignal, deadline.signal]);
  try {
    signal.throwIfAborted();
    const result = await operation(signal);
    signal.throwIfAborted();
    return result;
  } catch (error) {
    if (signal.aborted && signal.reason === timeout) throw timeout;
    if (signal.aborted && clientSignal.aborted) {
      throw new ModelRequestError(499, "client_disconnected", `模型 ${context.model}；调用客户端已断开或取消请求，并非 API 认证或地区拒绝。`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}
