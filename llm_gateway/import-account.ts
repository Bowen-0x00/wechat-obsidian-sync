import { AuthStorage, type } from "@oh-my-pi/pi-ai";
import { getAntigravityHeaders } from "@oh-my-pi/pi-catalog/wire/gemini-headers";
import { chmod } from "node:fs/promises";

process.umask(0o077);
const dbPath = process.env.LLM_AUTH_DB;
if (!dbPath) throw new Error("LLM_AUTH_DB must name the private credential database");
const input: unknown = await Bun.stdin.json();
const accounts = type({ email: "string", refresh_token: "string", "project_id?": "string" }).array()(Array.isArray(input) ? input : [input]);
if (accounts instanceof type.errors || accounts.length !== 1 || !accounts[0].refresh_token || !accounts[0].email) {
  throw new Error("Expected exactly one account with email and refresh_token on stdin");
}
const auth = await AuthStorage.create(dbPath);
try {
  await auth.credentials.set("google-antigravity", {
    type: "oauth",
    refresh: accounts[0].refresh_token,
    access: "",
    expires: 0,
    email: accounts[0].email,
    projectId: accounts[0].project_id || "aicode-consumers",
  });
  const key = await auth.keys.get("google-antigravity", "credential-import");
  if (!key) throw new Error("Antigravity credential refresh did not produce an access token");
  const credential = type({ token: "string" })(JSON.parse(key));
  if (credential instanceof type.errors) throw new Error("Invalid Antigravity access credential");
  const response = await fetch("https://daily-cloudcode-pa.googleapis.com/v1internal:loadCodeAssist", {
    method: "POST",
    proxy: process.env.PI_PROXY,
    signal: AbortSignal.timeout(20000),
    headers: { Authorization: `Bearer ${credential.token}`, "Content-Type": "application/json", ...getAntigravityHeaders() },
    body: JSON.stringify({ metadata: { ideType: "ANTIGRAVITY" } }),
  });
  if (!response.ok) throw new Error(`Antigravity project discovery failed: HTTP ${response.status}`);
  const project = type({ cloudaicompanionProject: "string" })(await response.json());
  if (project instanceof type.errors) throw new Error("Account has no provisioned Antigravity project; authorize it in Antigravity first");
  const stored = auth.credentials.getOAuth("google-antigravity");
  if (!stored) throw new Error("Imported credential was not saved");
  await auth.credentials.set("google-antigravity", { ...stored, projectId: project.cloudaicompanionProject });
  await chmod(dbPath, 0o600);
  console.log("Imported and refreshed one Antigravity account; credentials were not printed.");
} finally {
  auth.close();
}
