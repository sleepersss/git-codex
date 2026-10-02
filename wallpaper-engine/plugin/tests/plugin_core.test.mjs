import assert from "node:assert/strict";
import test from "node:test";
import { applyInventoryToDatabase, buildProcessingPlan, makeDatabaseRecord, normalizeType } from "../lib/plugin_core.mjs";

const config = { processing: { retry_error_records: false } };

function entry(id, type = "video", hash = "aa", manifest = [{ relative_path: "a.mp4", size: 10, mtime_ms: 1 }]) {
  return { id, type, original_type: type, workshop_dir: `E:\\root\\${id}`, project_hash: hash, payload_manifest: manifest, project: { type, title: id, tags: ["Anime"] } };
}

test("normalizes supported types without guessing unknown types", () => {
  assert.equal(normalizeType("scene"), "Scene");
  assert.equal(normalizeType("VIDEO"), "video");
  assert.equal(normalizeType("web"), "web");
  assert.equal(normalizeType("application"), "UNKNOWN");
});

test("plan never deletes database records missing from the current source", () => {
  const inventory = { entries: [entry("2")] };
  const database = { wallpapers: { "1": { workshopid: "1", processing_status: "PROCESSED" } } };
  const plan = buildProcessingPlan(inventory, database, config);
  assert.deepEqual(plan.missing_from_source, ["1"]);
  assert.deepEqual(plan.new, ["2"]);
  assert.ok(database.wallpapers["1"]);
});

test("existing discovered records are included in the next actionable batch", () => {
  const item = entry("1");
  const database = { wallpapers: { "1": { workshopid: "1", processing_status: "DISCOVERED", project_json_hash: "aa", plugin_source_manifest: item.payload_manifest } } };
  const plan = buildProcessingPlan({ entries: [item] }, database, config);
  assert.deepEqual(plan.pending_existing, ["1"]);
  assert.deepEqual(plan.video, ["1"]);
});

test("classified Scene stages are retried on the next boot", () => {
  for (const status of ["PENDING_SCENE_EXPORT", "PENDING_STATIC_ARCHIVE"]) {
    const item = entry("200", "Scene");
    const inventory = { entries: [item] };
    const database = { wallpapers: { "200": { workshopid: "200", type: "Scene", processing_status: status, project_json_hash: item.project_hash, plugin_source_manifest: item.payload_manifest } } };
    const plan = buildProcessingPlan(inventory, database, { processing: { retry_error_records: false } });
    assert.deepEqual(plan.pending_existing, ["200"]);
    assert.deepEqual(plan.scene, ["200"]);
  }
});

test("payload manifest changes produce UPDATE_PENDING while preserving the old archive fields", () => {
  const old = { workshopid: "1", processing_status: "PROCESSED", project_json_hash: "aa", plugin_source_manifest: [{ relative_path: "a.mp4", size: 10, mtime_ms: 1 }], relative_path: "wallpaper/video/Anime/old.mp4", output_hash: "oldhash", warnings: [] };
  const item = entry("1", "video", "aa", [{ relative_path: "a.mp4", size: 11, mtime_ms: 2 }]);
  const database = { schema_version: 1, wallpapers: { "1": old } };
  const history = { schema_version: 1, events: [] };
  const plan = buildProcessingPlan({ entries: [item] }, database, config);
  const applied = applyInventoryToDatabase(database, history, { entries: [item] }, plan, "2026-10-02T00:00:00.000Z");
  assert.equal(applied.database.wallpapers["1"].processing_status, "UPDATE_PENDING");
  assert.equal(applied.database.wallpapers["1"].relative_path, "wallpaper/video/Anime/old.mp4");
  assert.equal(applied.database.wallpapers["1"].output_hash, "oldhash");
});

test("web records are retained as SKIPPED_WEB", () => {
  const record = makeDatabaseRecord(entry("9", "web"), "2026-10-02T00:00:00.000Z");
  assert.equal(record.processing_status, "SKIPPED_WEB");
  assert.equal(record.conversion_status, "SKIPPED_WEB");
});
