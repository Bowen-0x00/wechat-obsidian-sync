import type { AssistantMessage } from "@oh-my-pi/pi-ai";

export class ModelOutputError extends Error {
  constructor(readonly status: number, readonly type: string, message: string) { super(message); }
}

/** Provider errors and truncation take precedence over the structured-submission requirement. */
export function modelOutput(
  message: AssistantMessage | undefined,
  submission: object | undefined,
  requireSubmission: boolean,
  source: string,
): string {
  if (!message) throw new ModelOutputError(502, "model_output_missing", `${source}；Agent 没有返回模型结果`);
  if (submission !== undefined) return JSON.stringify(submission);
  if (message.stopReason === "error" || message.stopReason === "aborted") {
    const status = message.errorStatus && message.errorStatus >= 400 && message.errorStatus <= 599 ? message.errorStatus : 502;
    throw new ModelOutputError(status, "upstream_model_error", `${source}；${message.errorMessage || `模型请求以 ${message.stopReason} 结束`}`);
  }
  if (message.stopReason === "length") throw new ModelOutputError(502, "model_output_truncated", `${source}；模型输出达到长度上限，未使用不完整分析`);
  if (requireSubmission) throw new ModelOutputError(502, "analysis_not_submitted", `${source}；Agent 未通过 submit_analysis 提交最终对象（结束状态 ${message.stopReason}），未生成评分`);
  if (message.stopReason !== "stop") throw new ModelOutputError(502, "model_output_incomplete", `${source}；模型尚未交付最终回答`);
  const text = message.content.filter(part => part.type === "text").map(part => part.text).join("").trim();
  if (!text) throw new ModelOutputError(502, "model_output_missing", `${source}；模型未返回最终文本`);
  return text;
}
