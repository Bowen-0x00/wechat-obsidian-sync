import { afterEach, expect, test } from "bun:test";
import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { buildModel } from "@oh-my-pi/pi-catalog/build";
import { ModelSettings, mergeCandidate, validateApiUrl, type ModelConfig, type ModelSnapshot } from "./settings";

const directories: string[] = [];
afterEach(async () => { for (const path of directories.splice(0)) await rm(path, { recursive: true, force: true }); });
const config: ModelConfig = { backend: "openai-compatible", base_url: "https://api.example.com/v1", api_key: "secret-old", default_model: "model-a", direct_effort: "low", agent_effort: "high", default_system_prompt: "", agent_instructions: "" };

test("blank keys retain the credential but a new endpoint cannot receive the old key", () => {
  const input = { ...config, revision: "r", api_key: "" };
  expect(mergeCandidate(input, config, "r").api_key).toBe("secret-old");
  expect(() => mergeCandidate({ ...input, base_url: "https://different.example/v1" }, config, "r")).toThrow("新 API Key");
  expect(mergeCandidate({ ...input, base_url: "https://different.example/v1", api_key: "new-key" }, config, "r").api_key).toBe("new-key");
  expect(() => mergeCandidate({ ...input, api_key: "new\nLLM_BACKEND=x" }, config, "r")).toThrow("格式无效");
});

test("URL validation blocks metadata, loopback, plaintext, and embedded credentials", async () => {
  for (const url of ["http://api.example.com/v1", "https://127.0.0.1/v1", "https://169.254.169.254/v1", "https://user:key@api.example.com/v1", "https://api.example.com/v1?key=secret"]) {
    await expect(validateApiUrl(url)).rejects.toThrow();
  }
});

async function fixture(failProbe = false) {
  const directory = await mkdtemp(join(tmpdir(), "wehub-settings-")); directories.push(directory);
  const file = join(directory, "upstream.env");
  await Bun.write(file, "LLM_BACKEND=antigravity\nLLM_DEFAULT_MODEL=model-a\nLLM_UPSTREAM_API_KEY=secret-old\nOTHER_SETTING=keep\n");
  const initial: ModelConfig = { ...config, backend: "antigravity" };
  const prepare = async (value: ModelConfig): Promise<ModelSnapshot> => {
    const copy = Object.freeze({ ...value });
    return { config: copy, models: new Map(), apiKey: async () => copy.api_key, fetcher: fetch };
  };
  // A roster containing a model is the boundary this fixture controls; no provider is contacted.
  const modelSnapshot = async (value: ModelConfig) => {
    const snapshot = await prepare(value);
    const model = buildModel({ id: value.default_model, name: value.default_model, api: "openai-completions", provider: "openai-compatible", baseUrl: value.base_url, reasoning: false, input: ["text"], contextWindow: 1000, maxTokens: 100, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } });
    return { ...snapshot, models: new Map([[model.id, model]]) };
  };
  const settings = await ModelSettings.create({ file, initial, prepare: modelSnapshot, probe: async () => { if (failProbe) throw new Error("provider rejected candidate"); return 12; }, antigravityConfigured: async () => true });
  return { settings, file };
}

test("failed preflight preserves both active configuration and persisted bytes", async () => {
  const { settings, file } = await fixture(true);
  const before = await readFile(file, "utf8");
  const revision = settings.revision;
  await expect(settings.save({ ...config, backend: "antigravity", default_model: "model-b", api_key: "new-secret", revision })).rejects.toThrow("rejected");
  expect(settings.current?.config.default_model).toBe("model-a");
  expect(settings.revision).toBe(revision);
  expect(await readFile(file, "utf8")).toBe(before);
});

test("successful save is private, rejects stale writers, and leaves in-flight snapshots intact", async () => {
  const { settings, file } = await fixture();
  const previous = settings.current;
  if (!previous) throw new Error("Fixture must start with a working model");
  const revision = settings.revision;
  const input = { ...config, backend: "antigravity", default_model: "model-b", api_key: "new-secret", revision };
  const view = await settings.save(input);
  expect(view.default_model).toBe("model-b");
  expect(JSON.stringify(view)).not.toContain("new-secret");
  expect(await previous.apiKey("model-a")).toBe("secret-old");
  expect(await settings.current?.apiKey("model-b")).toBe("new-secret");
  expect((await stat(file)).mode & 0o777).toBe(0o600);
  expect(await readFile(file, "utf8")).toContain("OTHER_SETTING=keep");
  await expect(settings.save(input)).rejects.toThrow("其他窗口");
});

test("an unavailable startup still exposes safe settings and accepts a working replacement", async () => {
  const good = await fixture();
  const working = good.settings.current;
  if (!working) throw new Error("Fixture must start with a working model");
  const initial: ModelConfig = { ...config, backend: "antigravity" };
  const settings = await ModelSettings.create({
    file: good.file, initial,
    prepare: async value => {
      if (value.api_key === "secret-old") throw new Error("Rejected credential secret-old");
      return { ...working, config: Object.freeze({ ...value }), apiKey: async () => value.api_key };
    },
    probe: async () => 1, antigravityConfigured: async () => true,
  });
  const view = await settings.view();
  expect(settings.current).toBeUndefined();
  expect(view.configuration_error).toContain("Rejected credential");
  expect(JSON.stringify(view)).not.toContain("secret-old");
  const restored = await settings.save({ ...initial, api_key: "replacement-key", revision: view.revision });
  expect(restored.configuration_error).toBeUndefined();
  expect(await settings.current?.apiKey("model-a")).toBe("replacement-key");
});

test("model listing allows blank default_model while save/test still require a valid model", async () => {
  const input = { ...config, revision: "r", default_model: "" };
  expect(() => mergeCandidate(input, config, "r")).toThrow("请输入有效模型 ID");
  expect(mergeCandidate(input, config, "r", { requireModel: false }).default_model).toBe("");

  const { settings } = await fixture();
  const snapshot = await settings.candidate(
    { ...config, backend: "antigravity", default_model: "", revision: settings.revision },
    { requireModel: false },
  );
  expect(snapshot.config.default_model).toBe("");
});

test("save persists effort levels and prompt overrides privately and rejects oversized prompts", async () => {
  const { settings, file } = await fixture();
  const promptFile = join(file, "..", "llm-prompts.json");
  await expect(settings.save({ ...config, backend: "antigravity", default_system_prompt: "x".repeat(4001), revision: settings.revision })).rejects.toThrow("4000");

  const view = await settings.save({
    ...config,
    backend: "antigravity",
    direct_effort: "medium",
    agent_effort: "low",
    default_system_prompt: "第一行全局约束\n第二行全局约束",
    agent_instructions: "自定义研究指令",
    revision: settings.revision,
  });

  expect(view.direct_effort).toBe("medium");
  expect(view.agent_effort).toBe("low");
  expect(view.default_system_prompt).toBe("第一行全局约束\n第二行全局约束");
  expect(view.agent_instructions).toBe("自定义研究指令");
  expect(view.default_agent_instructions).toContain("search_history");

  const envContent = await readFile(file, "utf8");
  expect(envContent).toContain("LLM_DIRECT_EFFORT=medium");
  expect(envContent).toContain("LLM_AGENT_EFFORT=low");

  const savedPrompts = JSON.parse(await readFile(promptFile, "utf8"));
  expect(savedPrompts.default_system_prompt).toBe("第一行全局约束\n第二行全局约束");
  expect(savedPrompts.agent_instructions).toBe("自定义研究指令");
  expect((await stat(promptFile)).mode & 0o777).toBe(0o600);
});
