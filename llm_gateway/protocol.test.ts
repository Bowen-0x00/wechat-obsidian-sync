import { expect, test } from "bun:test";
import { parseJsonObject } from "./protocol";

test("structured replies tolerate commentary and JSON fences without losing quoted braces", () => {
  expect(parseJsonObject('历史对照完成。\n```json\n{"score":82,"reason":"literal } and \\\"quoted\\\" {", "nested":{"items":[1,2]}}\n```')).toEqual({ score: 82, reason: 'literal } and "quoted" {', nested: { items: [1, 2] } });
  expect(parseJsonObject('Evidence checked. {"has_valuable_insight":false,"insights":[]}')).toEqual({ has_valuable_insight: false, insights: [] });
});

test("invalid, incomplete, and ambiguous responses cannot become successful analyses", () => {
  expect(() => parseJsonObject('No analysis available')).toThrow();
  expect(() => parseJsonObject('{"score":82')).toThrow("incomplete");
  expect(() => parseJsonObject('{"score":}')).toThrow();
  expect(() => parseJsonObject('{"score":1} {"score":2}')).toThrow("more than one");
});
