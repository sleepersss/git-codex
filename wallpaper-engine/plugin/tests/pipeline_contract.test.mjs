import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

async function text(relative) {
  return fs.readFile(path.join(projectRoot, relative), "utf8");
}

test("loop analysis path is forwarded through every MPKG export layer", async () => {
  for (const file of [
    "tools/export_mpkg_then_extract_mp4.ps1",
    "tools/test_saveas_all_wallpaperui.ps1",
    "tools/export_wallpaper_mpkg.ps1",
  ]) {
    const source = await text(file);
    assert.match(source, /LoopAnalysisPath/);
    assert.match(source, /IncludeLikelyLoopOverrides/);
  }
});

test("export gate verifies schema, phase and both source hashes", async () => {
  const source = await text("tools/export_wallpaper_mpkg.ps1");
  assert.match(source, /schema_version/);
  assert.match(source, /PRE_EXPORT_NORMALIZATION/);
  assert.match(source, /project_json_sha256/);
  assert.match(source, /scene_pkg_sha256/);
});

test("startup plugin requires dual apply gate and uses exact Workshop root", async () => {
  const source = await text("plugin/wallpaper_backup_plugin.mjs");
  assert.match(source, /args\.apply && config\.activation_mode === "apply"/);
  assert.match(source, /E:\\1_Game\\steam\\steamapps\\workshop\\content\\431960/);
  assert.match(source, /metadata\.file/);
  assert.match(source, /boundedRoot/);
});
