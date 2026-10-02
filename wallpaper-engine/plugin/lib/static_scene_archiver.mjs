import fs from "node:fs/promises";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { csvText, exists, readJson, sha256File, writeJsonAtomic } from "./plugin_core.mjs";

function visible(value) {
  if (value == null) return true;
  if (typeof value === "object" && Object.prototype.hasOwnProperty.call(value, "value")) return visible(value.value);
  if (typeof value === "string") return !/^(?:0|false|off)$/i.test(value.trim());
  return Boolean(value);
}

function sanitize(value, fallback) {
  let safe = String(value ?? "").trim() || fallback;
  safe = safe.replace(/[\\/:*?"<>|]/g, "_").replace(/[\u0000-\u001f]/g, "").trim().replace(/[. ]+$/g, "");
  return (safe || fallback).slice(0, 150).trim().replace(/[. ]+$/g, "") || fallback;
}

async function walk(root) {
  const files = [];
  if (!(await exists(root))) return files;
  for (const entry of await fs.readdir(root, { withFileTypes: true })) {
    const full = path.join(root, entry.name);
    if (entry.isDirectory()) files.push(...await walk(full));
    else files.push(full);
  }
  return files;
}

export async function findSceneJson(extractedIdRoot) {
  const candidates = (await walk(extractedIdRoot)).filter((file) => /(?:^|[\\/])(?:scene|gifscene)\.json$/i.test(file));
  return candidates.sort((a, b) => a.length - b.length)[0] ?? "";
}

function textureTokens(material) {
  const tokens = [];
  const visit = (value) => {
    if (typeof value === "string") return;
    if (!value || typeof value !== "object") return;
    if (Array.isArray(value)) { value.forEach(visit); return; }
    for (const [key, child] of Object.entries(value)) {
      if (key.toLowerCase() === "textures" && Array.isArray(child)) {
        for (const token of child) if (typeof token === "string") tokens.push(token);
      } else visit(child);
    }
  };
  visit(material);
  return tokens;
}

async function resolveTexture(sceneRoot, materialPath, token) {
  const extensions = [".png", ".webp", ".jpg", ".jpeg"];
  const normalized = token.replace(/\//g, path.sep);
  const candidates = [];
  if (/\.(?:png|webp|jpe?g)$/i.test(normalized)) {
    candidates.push(path.resolve(sceneRoot, normalized), path.resolve(path.dirname(materialPath), normalized));
  } else {
    for (const ext of extensions) {
      candidates.push(path.resolve(sceneRoot, "materials", `${normalized}${ext}`));
      candidates.push(path.resolve(path.dirname(materialPath), `${normalized}${ext}`));
      candidates.push(path.resolve(sceneRoot, `${normalized}${ext}`));
    }
  }
  const boundedRoot = path.resolve(sceneRoot).toLowerCase();
  for (const candidate of candidates) {
    const resolved = path.resolve(candidate);
    if (!resolved.toLowerCase().startsWith(`${boundedRoot}${path.sep}`)) continue;
    if (await exists(resolved)) return resolved;
  }
  return "";
}

export async function resolveStaticSceneImages(extractedIdRoot) {
  const sceneJson = await findSceneJson(extractedIdRoot);
  if (!sceneJson) throw new Error(`scene.json missing under ${extractedIdRoot}`);
  const sceneRoot = path.dirname(sceneJson);
  const scene = await readJson(sceneJson);
  const images = [];
  for (const object of (Array.isArray(scene.objects) ? scene.objects : [])) {
    if (!visible(object.visible) || !object.image || !/\.json$/i.test(String(object.image))) continue;
    const modelPath = path.resolve(sceneRoot, String(object.image).replace(/\//g, path.sep));
    if (!(await exists(modelPath))) continue;
    const model = await readJson(modelPath);
    const materialRef = String(model.material ?? "");
    if (!materialRef) continue;
    const materialPath = path.resolve(sceneRoot, materialRef.replace(/\//g, path.sep));
    if (!(await exists(materialPath))) continue;
    const material = await readJson(materialPath);
    for (const token of textureTokens(material)) {
      const image = await resolveTexture(sceneRoot, materialPath, token);
      if (image) images.push(image);
    }
  }
  return [...new Set(images.map((file) => path.resolve(file)))];
}

function probeImage(file) {
  const result = spawnSync("ffprobe.exe", ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,codec_name", "-of", "json", file], { encoding: "utf8", windowsHide: true });
  if (result.status !== 0) return { width: null, height: null, codec: null };
  try {
    const stream = JSON.parse(result.stdout).streams?.[0] ?? {};
    return { width: Number(stream.width) || null, height: Number(stream.height) || null, codec: stream.codec_name ?? null };
  } catch { return { width: null, height: null, codec: null }; }
}

async function backupDatabase(projectRoot, label) {
  const databaseDir = path.join(projectRoot, "database");
  const stamp = new Date().toISOString().replace(/[-:TZ.]/g, "").slice(0, 14);
  const backup = path.join(databaseDir, "backups", stamp, label);
  await fs.mkdir(backup, { recursive: true });
  for (const name of ["wallpapers.json", "wallpapers.csv", "history.json"]) {
    const source = path.join(databaseDir, name);
    if (await exists(source)) await fs.copyFile(source, path.join(backup, name));
  }
  return backup;
}

export async function archiveStaticScenes({ projectRoot, workshopIds, extractedRoot }) {
  const databaseDir = path.join(projectRoot, "database");
  const lock = path.join(databaseDir, ".lock");
  if (await exists(lock)) throw new Error(`Database lock exists: ${lock}`);
  const dbPath = path.join(databaseDir, "wallpapers.json");
  const csvPath = path.join(databaseDir, "wallpapers.csv");
  const historyPath = path.join(databaseDir, "history.json");
  const db = await readJson(dbPath);
  const history = await readJson(historyPath);
  const prepared = [];
  for (const id of workshopIds) {
    const record = db.wallpapers[id];
    if (!record || record.type !== "Scene" || record.scene_class !== "Scene_Static") throw new Error(`Record is not classified Scene_Static: ${id}`);
    const sources = await resolveStaticSceneImages(path.join(extractedRoot, id));
    if (!sources.length) throw new Error(`No referenced original static image found for ${id}`);
    prepared.push({ id, record, sources });
  }
  await fs.writeFile(lock, `archive_static_scene ${new Date().toISOString()}`, "utf8");
  try {
    const backup = await backupDatabase(projectRoot, "plugin_static_scene");
    const archived = [];
    for (const item of prepared) {
      const { id, record, sources } = item;
      const tag = sanitize(record.primary_tag, "_NoTag");
      const title = sanitize(record.title, id);
      const targetDir = path.join(projectRoot, "wallpaper", "Scene_Static", tag);
      await fs.mkdir(targetDir, { recursive: true });
      const artifacts = [];
      for (let index = 0; index < sources.length; index += 1) {
        const source = sources[index];
        const ext = path.extname(source).toLowerCase();
        const suffix = sources.length === 1 ? "" : ` [${index + 1}]`;
        let filename = `${title}${suffix}${ext}`;
        let target = path.join(targetDir, filename);
        if (await exists(target)) {
          filename = `${title}${suffix} [${id}]${ext}`;
          target = path.join(targetDir, filename);
        }
        await fs.copyFile(source, target);
        const sourceHash = await sha256File(source);
        const outputHash = await sha256File(target);
        if (sourceHash !== outputHash) throw new Error(`Static copy hash mismatch for ${id}: ${filename}`);
        const stat = await fs.stat(target);
        const probe = probeImage(target);
        artifacts.push({ kind: "image", relative_path: path.relative(projectRoot, target), filename, width: probe.width, height: probe.height, resolution: probe.width && probe.height ? `${probe.width}x${probe.height}` : null, file_size: stat.size, output_hash: outputHash });
      }
      const oldStatus = record.processing_status;
      record.artifacts = artifacts;
      record.relative_path = artifacts[0].relative_path;
      record.filename = artifacts[0].filename;
      record.output_hash = artifacts[0].output_hash;
      record.file_size = artifacts.reduce((sum, artifact) => sum + artifact.file_size, 0);
      record.width = artifacts[0].width;
      record.height = artifacts[0].height;
      record.resolution = artifacts[0].resolution;
      record.archive_state = "LOCAL";
      record.processing_status = "PROCESSED";
      record.conversion_status = "NOT_NEEDED_STATIC_EXTRACTION";
      record.conversion_time = new Date().toISOString();
      record.last_processed = record.conversion_time;
      history.events.push({ timestamp: record.conversion_time, workshopid: id, event: "STATIC_SCENE_ARCHIVED", old_state: oldStatus, new_state: "PROCESSED", details: `Extracted ${artifacts.length} referenced original static image(s); backup=${backup}` });
      archived.push({ workshopid: id, artifacts });
    }
    db.updated_at = new Date().toISOString();
    history.updated_at = db.updated_at;
    await writeJsonAtomic(dbPath, db);
    await fs.writeFile(`${csvPath}.${process.pid}.tmp`, csvText(Object.values(db.wallpapers)), "utf8");
    await fs.rename(`${csvPath}.${process.pid}.tmp`, csvPath);
    await writeJsonAtomic(historyPath, history);
    return archived;
  } finally {
    if (await exists(lock)) await fs.unlink(lock);
  }
}

