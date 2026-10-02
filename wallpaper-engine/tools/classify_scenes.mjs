import fs from "node:fs";
import path from "node:path";

function walk(dir, acc = []) {
  if (!fs.existsSync(dir)) return acc;
  for (const name of fs.readdirSync(dir)) {
    const full = path.join(dir, name);
    const st = fs.statSync(full);
    if (st.isDirectory()) walk(full, acc);
    else acc.push(full);
  }
  return acc;
}

function truthy(value) {
  if (value == null) return false;
  if (typeof value === "boolean") return value;
  if (typeof value === "object" && "value" in value) return truthy(value.value);
  return Boolean(value);
}

function collectKeys(obj, keys = new Set(), depth = 0) {
  if (!obj || typeof obj !== "object" || depth > 8) return keys;
  if (Array.isArray(obj)) {
    for (const item of obj) collectKeys(item, keys, depth + 1);
    return keys;
  }
  for (const [key, value] of Object.entries(obj)) {
    keys.add(key.toLowerCase());
    collectKeys(value, keys, depth + 1);
  }
  return keys;
}

const cli = process.argv.slice(2);
const requestedIds = [];
let outputPath = "temp/extracted/scene_classification.json";
for (let i = 0; i < cli.length; i += 1) {
  if (cli[i] === "--workshop-id") requestedIds.push(...String(cli[++i] ?? "").split(",").map((item) => item.trim()).filter(Boolean));
  else if (cli[i] === "--output") outputPath = path.resolve(cli[++i]);
  else throw new Error(`Unknown argument: ${cli[i]}`);
}
const db = JSON.parse(fs.readFileSync("database/wallpapers.json", "utf8").replace(/^\uFEFF/, ""));
const sourceRoot = String.raw`E:\1_Game\steam\steamapps\workshop\content\431960`;
const recordsById = new Map(Object.values(db.wallpapers).map((record) => [String(record.workshopid), record]));
for (const id of requestedIds) {
  if (recordsById.has(id)) continue;
  const projectPath = path.join(sourceRoot, id, "project.json");
  if (!fs.existsSync(projectPath)) continue;
  try {
    const project = JSON.parse(fs.readFileSync(projectPath, "utf8").replace(/^\uFEFF/, ""));
    recordsById.set(id, { workshopid: id, title: project.title ?? id, type: String(project.type).toLowerCase() === "scene" ? "Scene" : project.type, primary_tag: Array.isArray(project.tags) ? project.tags[0] : "_NoTag", raw_project_metadata: project });
  } catch {}
}
const scenes = [...recordsById.values()].filter((record) =>
  record.type === "Scene" && (!requestedIds.length || requestedIds.includes(String(record.workshopid)))
);
const results = [];

for (const record of scenes) {
  const extractRoot = path.join("temp/extracted/scene_json", record.workshopid);
  const files = walk(extractRoot).map((file) => path.relative(extractRoot, file).split(path.sep).join("/"));
  const sceneFile =
    files.find((file) => /(?:^|\/)(?:scene|gifscene)\.json$/i.test(file)) ||
    files.find((file) => /scene\.json$/i.test(file));
  const reasons = [];
  let scene = null;
  if (sceneFile) {
    try {
      scene = JSON.parse(fs.readFileSync(path.join(extractRoot, sceneFile), "utf8"));
    } catch (error) {
      reasons.push(`SCENE_JSON_PARSE_FAIL ${error.message}`);
    }
  } else {
    reasons.push("SCENE_JSON_MISSING");
  }

  const fileField = String(record.raw_project_metadata?.file || "");
  const objects = Array.isArray(scene?.objects) ? scene.objects : [];
  const visibleObjects = objects.filter((object) => object.visible === undefined || truthy(object.visible));
  const hiddenObjects = objects.filter((object) => object.visible !== undefined && !truthy(object.visible));
  const effectNames = [];
  let visibleEffects = 0;
  let hiddenEffects = 0;
  for (const object of objects) {
    const objectVisible = object.visible === undefined || truthy(object.visible);
    for (const effect of object.effects || []) {
      const effectVisible = effect.visible === undefined || truthy(effect.visible);
      const name = effect.name || effect.file || "effect";
      if (effectVisible && objectVisible) {
        visibleEffects += 1;
        effectNames.push(name);
      } else {
        hiddenEffects += 1;
      }
    }
  }

  const particleObjects = objects.filter((object) =>
    object.particle ||
    object.particles ||
    String(object.name || "").toLowerCase().includes("particle") ||
    String(object.image || "").includes("particle")
  );
  const animationObjects = objects.filter((object) => object.animation || object.animations || object.puppet);
  const videoLike = objects.filter((object) => /\.(mp4|webm|mov)$/i.test(String(object.image || "")) || object.video);
  const imageObjects = visibleObjects.filter((object) =>
    object.image &&
    !String(object.image).includes("composelayer") &&
    !String(object.image).includes("util/")
  );
  const composeLayers = visibleObjects.filter((object) =>
    String(object.image || "").includes("composelayer") ||
    String(object.name || "").includes("组合层")
  );
  const parallaxDepths = [...new Set(visibleObjects.map((object) => String(object.parallaxDepth || "")).filter(Boolean))];
  const general = scene?.general || {};
  const cameraParallax = truthy(general.cameraparallax);
  const cameraShake = truthy(general.camerashake);
  const bloom = truthy(general.bloom);
  const materialText = walk(extractRoot)
    .filter((file) =>
      file.split(path.sep).includes("materials") &&
      /\.json$/i.test(file) &&
      fs.statSync(file).size <= 1024 * 1024
    )
    .slice(0, 256)
    .map((file) => fs.readFileSync(file, "utf8"))
    .join("\n");
  const spritesheet = /spritesheet/i.test(materialText);
  const gifFile = /gifscene/i.test(fileField) || files.some((file) => /gifscene/i.test(file));
  const hasParticlesDir = files.some((file) => file.split("/").includes("particles"));
  const hasEmbeddedVideoAsset = files.some((file) => /\.(mp4|webm|mov)$/i.test(file));
  const extractedAssetRoot = path.join("temp/extracted/static_assets", record.workshopid);
  const hasConvertedVideoTexture = fs.existsSync(extractedAssetRoot) && walk(extractedAssetRoot)
    .some((file) => /\.(mp4|webm|mov)$/i.test(file));
  const interesting = [...collectKeys(objects)].filter((key) =>
    /particle|animat|script|video|sound|audio|puppet|instance|timeline|sequence|emitter/.test(key)
  );

  if (gifFile) reasons.push("GIF_SCENE");
  if (spritesheet) reasons.push("SPRITESHEET_MATERIAL");
  if (visibleEffects > 0) reasons.push(`VISIBLE_EFFECTS:${visibleEffects}`);
  if (particleObjects.length) reasons.push(`PARTICLE_OBJECTS:${particleObjects.length}`);
  if (animationObjects.length) reasons.push(`MODEL_OR_ANIM:${animationObjects.length}`);
  if (videoLike.length) reasons.push(`VIDEO_OBJECTS:${videoLike.length}`);
  if (hasParticlesDir) reasons.push("PARTICLES_DIR");
  if (hasEmbeddedVideoAsset) reasons.push("EMBEDDED_VIDEO_ASSET");
  if (hasConvertedVideoTexture) reasons.push("CONVERTED_VIDEO_TEXTURE");
  if (composeLayers.length) reasons.push(`COMPOSE_LAYERS:${composeLayers.length}`);
  if (imageObjects.length > 1) reasons.push(`MULTI_VISIBLE_IMAGES:${imageObjects.length}`);
  if (interesting.length) reasons.push(`OBJECT_KEYS:${interesting.join(",")}`);
  if (parallaxDepths.length > 1) reasons.push("MULTI_PARALLAX_DEPTH");
  if (cameraParallax) reasons.push("CAMERA_PARALLAX_RUNTIME");
  if (cameraShake) reasons.push("CAMERA_SHAKE_RUNTIME");

  let sceneClass = "UNKNOWN";
  if (
    gifFile ||
    spritesheet ||
    hasEmbeddedVideoAsset ||
    hasConvertedVideoTexture ||
    visibleEffects > 0 ||
    particleObjects.length > 0 ||
    videoLike.length > 0 ||
    hasParticlesDir ||
    composeLayers.length > 0 ||
    cameraParallax ||
    cameraShake
  ) {
    sceneClass = "Scene_Dynamic";
  } else if (imageObjects.length >= 1 && visibleEffects === 0 && !gifFile && !spritesheet && !hasParticlesDir) {
    sceneClass = "Scene_Static";
    if (imageObjects.length > 1) reasons.push("STATIC_LAYERED_IMAGES");
    if (cameraParallax) reasons.push("CAMERA_PARALLAX_CONFIG_ONLY");
    if (cameraShake) reasons.push("CAMERA_SHAKE_CONFIG_ONLY");
  } else {
    reasons.push("NO_CLEAR_STATIC_OR_DYNAMIC_SIGNAL");
  }

  results.push({
    id: record.workshopid,
    title: record.title,
    primary_tag: record.primary_tag,
    file: fileField,
    scene_class: sceneClass,
    objects: objects.length,
    visible: visibleObjects.length,
    hidden: hiddenObjects.length,
    imageObjects: imageObjects.length,
    visibleEffects,
    hiddenEffects,
    effectNames: effectNames.slice(0, 6),
    cameraParallax,
    cameraShake,
    bloom,
    files: files.length,
    reasons,
  });
}

const groups = {};
for (const result of results) {
  groups[result.scene_class] = (groups[result.scene_class] || 0) + 1;
}

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, JSON.stringify({ groups, results }, null, 2), "utf8");
console.log(JSON.stringify(groups, null, 2));
console.log("static:");
for (const result of results.filter((item) => item.scene_class === "Scene_Static")) {
  console.log(`  ${result.id}  ${result.title}  images=${result.imageObjects}  ${result.reasons.join("|")}`);
}
console.log("unknown:");
for (const result of results.filter((item) => item.scene_class === "UNKNOWN")) {
  console.log(`  ${result.id}  ${result.title}  ${result.reasons.join("|")}`);
}
console.log(`wrote ${outputPath}`);
