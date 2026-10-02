import assert from "node:assert/strict";
import test from "node:test";
import {
  analyzeSceneLoopDependencies,
  buildSceneLoopExportOverrides,
  sceneLoopAnalyzerContract,
  validateSceneLoopAnalysisSource,
} from "../lib/scene_loop_dependency_analyzer.mjs";

function analyze(properties, scene) {
  return analyzeSceneLoopDependencies({
    workshopId: "1234567890",
    project: { title: "fixture", type: "Scene", general: { properties } },
    scene,
  });
}

test("clock script uses the author's bound visibility checkbox", () => {
  const result = analyze(
    { onoff: { type: "bool", text: "On\\Off", value: true } },
    { objects: [{ name: "Clock", text: { script: "export function update(){ const now = new Date(); return now.getHours(); }" }, visible: { user: "onoff", value: true } }] },
  );
  assert.equal(result.decision, "AUTO_SAFE");
  assert.deepEqual(result.override_plan.auto_apply_user_properties, { onoff: false });
});

test("combo selects the author's explicit Off value instead of boolean false", () => {
  const result = analyze(
    { beat: { type: "combo", text: "Audio beat", value: "2", options: [{ label: "关 Off", value: "1" }, { label: "开 On", value: "2" }] } },
    { objects: [{ scale: { script: "const audio = engine.registerAudioBuffers(engine.AUDIO_RESOLUTION_16);", value: 1 }, visible: { user: { name: "beat", condition: "2" }, value: true } }] },
  );
  assert.deepEqual(result.override_plan.auto_apply_user_properties, { beat: "1" });
});

test("group labels are never treated as switches", () => {
  const result = analyze(
    { datetime: { type: "group", text: "Date & Clock", value: "" } },
    { objects: [{ text: { script: "export function update(){ return new Date().toString(); }" }, visible: true }] },
  );
  assert.deepEqual(result.override_plan.auto_apply_user_properties, {});
  assert.equal(result.decision, "REVIEW_REQUIRED");
});

test("slider is not forced outside its declared range", () => {
  const result = analyze(
    { amount: { type: "slider", text: "Audio response", value: 1, min: 0.2, max: 2 } },
    { objects: [{ strength: { script: "const a = engine.registerAudioBuffers(engine.AUDIO_RESOLUTION_16);", user: "amount", value: 1 } }] },
  );
  assert.deepEqual(result.override_plan.auto_apply_user_properties, {});
  assert.equal(result.unresolved.length > 0, true);
});

test("native camera parallax becomes a scene-setting override", () => {
  const result = analyze({}, { general: { cameraparallax: true, cameraparallaxmouseinfluence: 0.5 }, objects: [] });
  assert.deepEqual(result.override_plan.scene_settings, { cameraparallax: false, cameraparallaxmouseinfluence: 0 });
  assert.equal(result.decision, "AUTO_SAFE");
});

test("cursor-named particle layers are detected and use their author checkbox", () => {
  const result = analyze(
    { mouseparticleeffect: { type: "bool", text: "Mouse particle effect", value: true } },
    { objects: [{ name: "cherry blossoms on cursor", particle: "particles/cherry.json", visible: { user: "mouseparticleeffect", value: true } }] },
  );
  assert.equal(result.dependencies.some((item) => item.category === "mouse_input"), true);
  assert.deepEqual(result.override_plan.auto_apply_user_properties, { mouseparticleeffect: false });
});

test("ordinary animation time label is not mistaken for wall clock", () => {
  const result = analyze(
    { animationtime: { type: "slider", text: "Animation time", value: 1, min: 0.1, max: 5 } },
    { objects: [{ name: "Character", visible: true }] },
  );
  assert.equal(result.decision, "NO_EXTERNAL_DEPENDENCY");
  assert.deepEqual(result.override_plan.auto_apply_user_properties, {});
});

test("plugin contract fixes phase order without coupling to a plugin loader order", () => {
  assert.equal(sceneLoopAnalyzerContract.phase, "PRE_EXPORT_NORMALIZATION");
  assert.equal(sceneLoopAnalyzerContract.next_phase, "MPKG_EXPORT");
  assert.ok(sceneLoopAnalyzerContract.prerequisites.includes("SOURCE_HASHED"));
});

test("plugin adapter excludes likely overrides unless permissive mode is explicit", () => {
  const analysis = analyze(
    { enableclock: { type: "bool", text: "Enable clock", value: true } },
    { objects: [{ text: { script: "export function update(){ return new Date().toString(); }" }, visible: true }] },
  );
  assert.deepEqual(buildSceneLoopExportOverrides(analysis).user_properties, {});
  assert.deepEqual(buildSceneLoopExportOverrides(analysis, { includeLikely: true }).user_properties, { enableclock: false });
});

test("plugin rejects an analysis result after either source hash changes", () => {
  const analysis = analyze({}, { objects: [] });
  analysis.source_hashes = { project_json_sha256: "AA", scene_pkg_sha256: "BB" };
  assert.deepEqual(validateSceneLoopAnalysisSource(analysis, { project_json_sha256: "AA", scene_pkg_sha256: "BB" }), { ok: true, reasons: [] });
  const stale = validateSceneLoopAnalysisSource(analysis, { project_json_sha256: "AA", scene_pkg_sha256: "CC" });
  assert.equal(stale.ok, false);
  assert.ok(stale.reasons.includes("STALE_SCENE_PKG_SHA256"));
});
