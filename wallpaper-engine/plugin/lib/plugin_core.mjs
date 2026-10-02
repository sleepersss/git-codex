import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";

export const PLUGIN_SCHEMA_VERSION = 1;

export function normalizeType(value) {
  const type = String(value ?? "").toLowerCase();
  if (type === "video") return "video";
  if (type === "scene") return "Scene";
  if (type === "web") return "web";
  return "UNKNOWN";
}

export function safeArray(value) {
  if (Array.isArray(value)) return value.map((item) => String(item)).filter((item) => item.trim());
  if (value == null || String(value).trim() === "") return [];
  return [String(value)];
}

export function workshopUrl(id) {
  return `https://steamcommunity.com/sharedfiles/filedetails/?id=${id}`;
}

export async function exists(file) {
  try { await fs.access(file); return true; } catch { return false; }
}

export async function readJson(file) {
  return JSON.parse((await fs.readFile(file, "utf8")).replace(/^\uFEFF/, ""));
}

export async function sha256File(file) {
  const hash = crypto.createHash("sha256");
  const handle = await fs.open(file, "r");
  try {
    for await (const chunk of handle.createReadStream()) hash.update(chunk);
  } finally {
    await handle.close();
  }
  return hash.digest("hex");
}

export async function writeJsonAtomic(file, value) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const temporary = `${file}.${process.pid}.tmp`;
  await fs.writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  JSON.parse(await fs.readFile(temporary, "utf8"));
  await fs.rename(temporary, file);
}

function payloadCandidates(type, project, workshopDir) {
  if (type === "Scene") return [path.join(workshopDir, "scene.pkg")];
  const declared = String(project?.file ?? "").trim();
  if (declared) return [path.resolve(workshopDir, declared)];
  return [];
}

async function payloadManifest(type, project, workshopDir) {
  const output = [];
  for (const candidate of payloadCandidates(type, project, workshopDir)) {
    if (!(await exists(candidate))) continue;
    const stat = await fs.stat(candidate);
    if (!stat.isFile()) continue;
    output.push({
      relative_path: path.relative(workshopDir, candidate).split(path.sep).join("/"),
      size: stat.size,
      mtime_ms: Math.trunc(stat.mtimeMs),
    });
  }
  return output;
}

export async function scanWorkshopSource(sourceRoot) {
  const resolvedRoot = path.resolve(sourceRoot);
  if (path.basename(resolvedRoot) !== "431960") throw new Error(`Source boundary must end at 431960: ${resolvedRoot}`);
  const entries = [];
  const warnings = [];
  for (const dirent of (await fs.readdir(resolvedRoot, { withFileTypes: true }))) {
    if (!dirent.isDirectory() || !/^\d+$/.test(dirent.name)) continue;
    const id = dirent.name;
    const workshopDir = path.join(resolvedRoot, id);
    const projectPath = path.join(workshopDir, "project.json");
    if (!(await exists(projectPath))) {
      warnings.push({ workshopid: id, code: "PROJECT_JSON_MISSING" });
      continue;
    }
    try {
      const project = await readJson(projectPath);
      const type = normalizeType(project.type);
      entries.push({
        id,
        workshop_dir: workshopDir,
        type,
        original_type: String(project.type ?? ""),
        project,
        project_path: projectPath,
        project_hash: await sha256File(projectPath),
        payload_manifest: await payloadManifest(type, project, workshopDir),
      });
    } catch (error) {
      warnings.push({ workshopid: id, code: "PROJECT_JSON_INVALID", message: error.message });
    }
  }
  entries.sort((a, b) => a.id.localeCompare(b.id));
  return { source_root: resolvedRoot, entries, warnings };
}

function manifestsEqual(left, right) {
  return JSON.stringify(left ?? []) === JSON.stringify(right ?? []);
}

export function buildProcessingPlan(inventory, database, config) {
  const records = database?.wallpapers ?? {};
  const currentIds = new Set(inventory.entries.map((entry) => entry.id));
  const plan = {
    new: [],
    updated: [],
    pending_existing: [],
    unchanged: [],
    skipped_web: [],
    unknown: [],
    missing_from_source: Object.keys(records).filter((id) => !currentIds.has(id)).sort(),
  };

  for (const entry of inventory.entries) {
    const record = records[entry.id];
    if (!record) {
      plan.new.push(entry.id);
      if (entry.type === "web") plan.skipped_web.push(entry.id);
      if (entry.type === "UNKNOWN") plan.unknown.push(entry.id);
      continue;
    }
    const projectChanged = Boolean(entry.project_hash && record.project_json_hash && String(entry.project_hash).toLowerCase() !== String(record.project_json_hash).toLowerCase());
    const payloadChanged = Array.isArray(record.plugin_source_manifest) && !manifestsEqual(entry.payload_manifest, record.plugin_source_manifest);
    if (projectChanged || payloadChanged) {
      plan.updated.push(entry.id);
      continue;
    }
    const status = String(record.processing_status ?? "");
    const retryError = Boolean(config?.processing?.retry_error_records) && status === "ERROR";
    const pendingStage = status.startsWith("PENDING_");
    if (["DISCOVERED", "UPDATE_PENDING", "PROCESSING"].includes(status) || pendingStage || retryError) plan.pending_existing.push(entry.id);
    else plan.unchanged.push(entry.id);
  }

  const actionable = [...new Set([...plan.new, ...plan.updated, ...plan.pending_existing])];
  plan.video = actionable.filter((id) => inventory.entries.find((entry) => entry.id === id)?.type === "video");
  plan.scene = actionable.filter((id) => inventory.entries.find((entry) => entry.id === id)?.type === "Scene");
  plan.web = actionable.filter((id) => inventory.entries.find((entry) => entry.id === id)?.type === "web");
  plan.unsupported = actionable.filter((id) => inventory.entries.find((entry) => entry.id === id)?.type === "UNKNOWN");
  return plan;
}

export function makeDatabaseRecord(entry, nowIso) {
  const project = entry.project ?? {};
  const tags = safeArray(project.tags);
  const type = entry.type;
  const statManifest = entry.payload_manifest?.[0] ?? null;
  const status = type === "web" ? "SKIPPED_WEB" : type === "UNKNOWN" ? "UNKNOWN" : "DISCOVERED";
  return {
    workshopid: entry.id,
    title: project.title ?? entry.id,
    type,
    original_type: entry.original_type ?? String(project.type ?? ""),
    scene_class: type === "Scene" ? "UNKNOWN" : null,
    tags: tags.join(";"),
    primary_tag: tags[0] ?? "_NoTag",
    workshopurl: workshopUrl(entry.id),
    project_workshopurl: project.workshopurl ?? null,
    source_workshop_path: entry.workshop_dir,
    source_hash: entry.project_hash,
    source_hash_scope: "project.json",
    project_json_hash: entry.project_hash,
    plugin_source_manifest: entry.payload_manifest,
    archive_state: "LOCAL",
    processing_status: status,
    first_seen: nowIso,
    last_seen: nowIso,
    last_processed: null,
    relative_path: null,
    filename: null,
    file_size: statManifest?.size ?? null,
    file_created_time: null,
    file_modified_time: statManifest ? new Date(statManifest.mtime_ms).toISOString() : null,
    width: null,
    height: null,
    resolution: null,
    duration: null,
    fps: null,
    codec: null,
    bitrate: null,
    output_hash: null,
    conversion_status: type === "web" ? "SKIPPED_WEB" : "NOT_PROCESSED",
    conversion_time: null,
    archive_location: null,
    artifacts: [],
    warnings: entry.project_error ? [entry.project_error] : [],
    raw_project_metadata: project,
    contentrating: project.contentrating ?? null,
    preview_path: null,
    preview_type: null,
    preview_width: null,
    preview_height: null,
    preview_size: null,
    preview_hash: null,
  };
}

export function applyInventoryToDatabase(database, history, inventory, plan, nowIso) {
  const db = JSON.parse(JSON.stringify(database));
  const hist = JSON.parse(JSON.stringify(history));
  if (!db.wallpapers || !hist.events) throw new Error("Database or history schema is invalid.");
  const newSet = new Set(plan.new);
  const updatedSet = new Set(plan.updated);
  for (const entry of inventory.entries) {
    if (newSet.has(entry.id)) {
      db.wallpapers[entry.id] = makeDatabaseRecord(entry, nowIso);
      hist.events.push({ timestamp: nowIso, workshopid: entry.id, event: "DISCOVERED", old_state: null, new_state: db.wallpapers[entry.id].processing_status, details: "Discovered by startup plugin from the bounded 431960 source." });
      continue;
    }
    const record = db.wallpapers[entry.id];
    if (!record) continue;
    record.last_seen = nowIso;
    record.plugin_source_manifest = entry.payload_manifest;
    if (entry.project_hash) record.project_json_hash = entry.project_hash;
    if (updatedSet.has(entry.id)) {
      const old = record.processing_status;
      record.processing_status = "UPDATE_PENDING";
      record.conversion_status = "UPDATE_PENDING";
      record.raw_project_metadata = entry.project ?? record.raw_project_metadata;
      record.title = entry.project?.title ?? record.title;
      const tags = safeArray(entry.project?.tags);
      record.tags = tags.join(";");
      record.primary_tag = tags[0] ?? "_NoTag";
      record.warnings = [...new Set([...(record.warnings ?? []), "WORKSHOP_CONTENT_CHANGED"])]
      hist.events.push({ timestamp: nowIso, workshopid: entry.id, event: "UPDATED", old_state: old, new_state: "UPDATE_PENDING", details: "Project metadata or primary payload manifest changed; previous archive was preserved." });
    }
  }
  db.updated_at = nowIso;
  hist.updated_at = nowIso;
  return { database: db, history: hist };
}

export function csvText(records) {
  const fields = [
    "title", "type", "scene_class", "tags", "primary_tag", "workshopid", "workshopurl",
    "contentrating", "relative_path", "filename", "width", "height", "resolution",
    "file_size", "duration", "fps", "codec", "bitrate", "file_created_time",
    "file_modified_time", "source_hash", "output_hash", "archive_state",
    "processing_status", "archive_location",
  ];
  const escape = (value) => {
    const text = Array.isArray(value) ? value.join(";") : String(value ?? "");
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const rows = [fields, ...records.map((record) => fields.map((field) => record[field] ?? ""))];
  return `\uFEFF${rows.map((row) => row.map(escape).join(",")).join("\r\n")}\r\n`;
}
