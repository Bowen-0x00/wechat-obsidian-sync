import { afterEach, beforeEach, expect, test } from "bun:test";
import { Database } from "bun:sqlite";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { HistoryReader, type DatabasePaths } from "./history";

let directory: string;
let database: Database;
let paths: DatabasePaths;
beforeEach(() => {
  directory = mkdtempSync(join(tmpdir(), "wehub-history-"));
  const path = join(directory, "history.db");
  paths = { notes: path, insights: path, radar: path, mail: path };
  database = new Database(path);
  database.exec(`
    CREATE TABLE inbox_notes (id INTEGER PRIMARY KEY, title TEXT, tldr TEXT, raw_content TEXT, content_markdown TEXT, created_at TEXT, url TEXT, from_user TEXT);
    CREATE TABLE note_chat_history (id INTEGER PRIMARY KEY, note_id INTEGER, from_user TEXT, role TEXT, content TEXT, created_at TEXT);
    INSERT INTO inbox_notes VALUES (1, 'CXL 100% evidence', 'memory', 'own evidence', '', '2026-11-01', 'https://example.com/1', 'owner-a');
    INSERT INTO inbox_notes VALUES (2, 'CXL other owner', 'memory', 'private evidence', '', '2026-11-02', 'https://example.com/2', 'owner-b');
  `);
});
afterEach(() => { database.close(); rmSync(directory, { recursive: true, force: true }); });

test("an actor cannot search or read another owner's notes", () => {
  const reader = new HistoryReader(paths, "owner-a");
  expect(reader.search("notes", "CXL").map(item => item.id)).toEqual(["1"]);
  expect(reader.read("notes", "1").content).toBe("own evidence");
  expect(() => reader.read("notes", "2")).toThrow("not authorized");
});

test("search treats wildcard characters literally and rejects unbounded limits", () => {
  const reader = new HistoryReader(paths);
  expect(reader.search("notes", "%").map(item => item.id)).toEqual(["1"]);
  expect(() => reader.search("notes", "CXL", 11)).toThrow("1 to 10");
  expect(() => reader.read("notes", "1 OR 1=1")).toThrow("not found");
});

test("chat history returns the actor's latest messages in chronological order", () => {
  const insert = database.query("INSERT INTO note_chat_history VALUES (?, 1, ?, 'user', ?, '2026-11-01')");
  for (let id = 1; id <= 20; id++) insert.run(id, id % 2 ? "owner-b" : "owner-a", `message-${id}`);
  const reader = new HistoryReader(paths, "owner-a");
  expect(reader.chat("notes", "1", 3).map(item => item.content)).toEqual(["message-16", "message-18", "message-20"]);
});
