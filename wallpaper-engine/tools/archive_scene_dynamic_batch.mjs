import fs from "node:fs/promises";
import fssync from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { spawnSync } from "node:child_process";

let SpreadsheetFile = null;
let Workbook = null;
try {
  const artifact = await import("@oai/artifact-tool");
  SpreadsheetFile = artifact.SpreadsheetFile;
  Workbook = artifact.Workbook;
} catch {
  SpreadsheetFile = null;
  Workbook = null;
}

const projectRoot = "D:\\7_Video\\20_Wallpaper Engine";
const sourceRoot = "E:\\1_Game\\steam\\steamapps\\workshop\\content\\431960";
const databaseDir = path.join(projectRoot, "database");
const wallpaperDir = path.join(projectRoot, "wallpaper");
const convertedDirDefault = path.join(projectRoot, "temp", "converted");
const mpkgDirDefault = path.join(projectRoot, "temp", "mpkg");
const lockPath = path.join(databaseDir, ".lock");
const runStamp = formatLocalStamp(new Date());
const runIso = new Date().toISOString();
const logDir = path.join(databaseDir, "logs");
const logPath = path.join(logDir, `archive_scene_dynamic_${runStamp}.log`);
const backupDir = path.join(databaseDir, "backups", runStamp);

const cliArgs = process.argv.slice(2);
let convertedDir = convertedDirDefault;
let mpkgDir = mpkgDirDefault;
let replaceExisting = false;
let removeTempInputs = false;
const workshopIds = [];
for (let i = 0; i < cliArgs.length; i++) {
  if (cliArgs[i] === "--converted-dir" || cliArgs[i] === "--mpkg-dir") {
    const value = cliArgs[++i];
    if (!value) throw new Error(`Missing value for ${cliArgs[i - 1]}`);
    const resolved = path.resolve(value);
    if (cliArgs[i - 1] === "--converted-dir") convertedDir = resolved;
    else mpkgDir = resolved;
  } else if (cliArgs[i] === "--replace-existing") {
    replaceExisting = true;
  } else if (cliArgs[i] === "--remove-temp-inputs") {
    removeTempInputs = true;
  } else {
    workshopIds.push(cliArgs[i]);
  }
}
if (!workshopIds.length) {
  throw new Error("Pass workshop IDs as arguments.");
}

const fields = [
  "title", "type", "scene_class", "tags", "primary_tag", "workshopid", "workshopurl",
  "contentrating", "relative_path", "filename", "resolution", "file_size", "duration",
  "fps", "codec", "bitrate", "file_created_time", "file_modified_time", "source_hash",
  "output_hash", "archive_state", "processing_status", "archive_location", "preview_path",
  "preview_type", "preview_width", "preview_height", "preview_size", "preview_hash",
];

const zh = {
  title: "标题", type: "类型", scene_class: "Scene类型", tags: "标签", primary_tag: "主标签",
  workshopid: "Workshop ID", workshopurl: "Workshop网址", contentrating: "内容评级",
  relative_path: "相对路径", filename: "文件名", resolution: "分辨率", file_size: "文件大小",
  duration: "时长", fps: "FPS", codec: "编码格式", bitrate: "码率",
  file_created_time: "文件创建时间", file_modified_time: "文件修改时间",
  source_hash: "源文件哈希", output_hash: "输出文件哈希", archive_state: "归档状态",
  processing_status: "处理状态", archive_location: "归档位置", preview_path: "预览图路径",
  preview_type: "预览图类型", preview_width: "预览图宽度", preview_height: "预览图高度",
  preview_size: "预览图大小", preview_hash: "预览图哈希",
};

const longWrapFields = new Set(["title", "tags", "workshopurl", "relative_path", "filename", "source_hash", "output_hash", "preview_path"]);

function formatLocalStamp(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

async function log(message) {
  const line = `[${new Date().toISOString()}] ${message}`;
  console.log(line);
  await fs.appendFile(logPath, `${line}\n`, "utf8");
}

async function exists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

function sanitizeName(value, fallback) {
  let safe = String(value ?? "").trim() || fallback;
  safe = safe.replace(/[\\/:*?"<>|]/g, "_").replace(/[\u0000-\u001f]/g, "");
  safe = safe.trim().replace(/[. ]+$/g, "");
  if (!safe) safe = fallback;
  if (safe.length > 160) safe = safe.slice(0, 160).trim().replace(/[. ]+$/g, "");
  return safe || fallback;
}

function relFromProject(fullPath) {
  const relative = path.relative(projectRoot, fullPath);
  if (relative.startsWith("..")) throw new Error(`Path outside project root: ${fullPath}`);
  return relative;
}

function toDisplayTags(value) {
  if (Array.isArray(value)) return value.join(";");
  if (value == null) return "";
  return String(value);
}

function normalizeCell(value) {
  if (value == null) return "";
  if (Array.isArray(value)) return value.join(";");
  return String(value);
}

function csvEscape(value) {
  const text = normalizeCell(value);
  if (/[",\r\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

async function writeCsv(filePath, rows) {
  const matrix = [
    fields,
    fields.map((field) => zh[field]),
    ...rows.map((record) => fields.map((field) => record[field] ?? "")),
  ];
  const text = matrix.map((row) => row.map(csvEscape).join(",")).join("\r\n") + "\r\n";
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, "\ufeff" + text, "utf8");
}

function columnName(index) {
  let n = index + 1;
  let name = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    name = String.fromCharCode(65 + rem) + name;
    n = Math.floor((n - 1) / 26);
  }
  return name;
}

function widthForField(field, values) {
  const maxContent = Math.max(field.length, zh[field].length, ...values.map((value) => normalizeCell(value).length));
  const caps = { title: 40, tags: 45, workshopurl: 60, relative_path: 60, filename: 60, source_hash: 70, output_hash: 70, preview_path: 60, preview_hash: 70 };
  const minimums = { title: 18, tags: 24, workshopurl: 32, relative_path: 36, filename: 28, resolution: 14, file_size: 14, duration: 12, fps: 10, codec: 12, bitrate: 14, preview_type: 12 };
  return Math.max(minimums[field] ?? 12, Math.min(caps[field] ?? 30, maxContent + 2));
}

async function writeXlsx(filePath, rows) {
  if (!Workbook || !SpreadsheetFile) {
    return;
  }
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add("metadata");
  sheet.showGridLines = false;
  const matrix = [
    fields,
    fields.map((field) => zh[field]),
    ...rows.map((record) => fields.map((field) => normalizeCell(record[field]))),
  ];
  const lastCol = columnName(fields.length - 1);
  const lastRow = matrix.length;
  sheet.getRange(`A1:${lastCol}${lastRow}`).values = matrix;
  sheet.freezePanes.freezeRows(2);
  const allRange = sheet.getRange(`A1:${lastCol}${lastRow}`);
  allRange.format.font = { name: "Arial", size: 10, color: "#111827" };
  allRange.format.verticalAlignment = "center";
  allRange.format.borders = { preset: "all", style: "thin", color: "#E5E7EB" };
  sheet.getRange(`A1:${lastCol}1`).format = { fill: "#1F4E78", font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" } };
  sheet.getRange(`A2:${lastCol}2`).format = { fill: "#EAF2F8", font: { name: "Arial", size: 10, bold: true, color: "#111827" } };
  sheet.getRange(`A1:${lastCol}2`).format.verticalAlignment = "center";
  sheet.getRange(`A2:${lastCol}2`).format.rowHeight = 28;
  for (let i = 0; i < fields.length; i++) {
    const field = fields[i];
    const col = columnName(i);
    const range = sheet.getRange(`${col}1:${col}${lastRow}`);
    range.format.columnWidth = widthForField(field, rows.map((record) => record[field]));
    if (longWrapFields.has(field)) range.format.wrapText = true;
  }
  if (lastRow >= 3) {
    const table = sheet.tables.add(`A1:${lastCol}${lastRow}`, true, `Metadata_${crypto.randomBytes(4).toString("hex")}`);
    table.showFilterButton = true;
    table.style = "TableStyleMedium2";
  }
  workbook.recalculate();
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  const xlsx = await SpreadsheetFile.exportXlsx(workbook);
  await xlsx.save(filePath);
}

async function writeMetadataPair(dir, rows) {
  const dataDir = path.join(dir, "data");
  await fs.mkdir(dataDir, { recursive: true });
  await writeCsv(path.join(dataDir, "metadata.csv"), rows);
  if (Workbook && SpreadsheetFile) {
    await writeXlsx(path.join(dataDir, "metadata.xlsx"), rows);
  }
}

async function sha256(filePath) {
  const hash = crypto.createHash("sha256");
  const handle = await fs.open(filePath, "r");
  try {
    for await (const chunk of handle.createReadStream()) hash.update(chunk);
  } finally {
    await handle.close();
  }
  return hash.digest("hex");
}

async function imageDimensions(filePath) {
  const buffer = await fs.readFile(filePath);
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".gif" && buffer.length >= 10 && buffer.toString("ascii", 0, 3) === "GIF") {
    return { width: buffer.readUInt16LE(6), height: buffer.readUInt16LE(8) };
  }
  if ((ext === ".jpg" || ext === ".jpeg") && buffer.length > 4 && buffer[0] === 0xff && buffer[1] === 0xd8) {
    let offset = 2;
    while (offset < buffer.length) {
      if (buffer[offset] !== 0xff) break;
      const marker = buffer[offset + 1];
      const length = buffer.readUInt16BE(offset + 2);
      if ([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf].includes(marker)) {
        return { height: buffer.readUInt16BE(offset + 5), width: buffer.readUInt16BE(offset + 7) };
      }
      offset += 2 + length;
    }
  }
  if (ext === ".png" && buffer.length >= 24 && buffer.toString("ascii", 1, 4) === "PNG") {
    return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
  }
  return { width: null, height: null };
}

function probeVideo(filePath) {
  const ffprobe = "C:\\Program Files\\ffmpeg\\bin\\ffprobe.exe";
  const result = spawnSync(ffprobe, [
    "-v", "error", "-select_streams", "v:0",
    "-show_entries", "stream=codec_name,width,height,avg_frame_rate,r_frame_rate,bit_rate",
    "-show_entries", "format=duration,bit_rate,size",
    "-of", "json", "--", filePath,
  ], { encoding: "utf8", windowsHide: true });
  if (result.status !== 0) throw new Error(`ffprobe failed for ${filePath}: ${result.stderr}`);
  const json = JSON.parse(result.stdout);
  const stream = json.streams?.[0] || {};
  const format = json.format || {};
  const rate = String(stream.avg_frame_rate || stream.r_frame_rate || "");
  let fps = null;
  if (/^\d+\/\d+$/.test(rate)) {
    const [n, d] = rate.split("/").map(Number);
    if (d) fps = Math.round((n / d) * 1000) / 1000;
  }
  const width = stream.width ? Number(stream.width) : null;
  const height = stream.height ? Number(stream.height) : null;
  return {
    width,
    height,
    resolution: width && height ? `${width}x${height}` : null,
    duration: format.duration ? Math.round(Number(format.duration) * 1000) / 1000 : null,
    fps,
    codec: stream.codec_name || null,
    bitrate: format.bit_rate ? Number(format.bit_rate) : (stream.bit_rate ? Number(stream.bit_rate) : null),
  };
}

function rowFromRecord(record) {
  const row = {};
  for (const field of fields) row[field] = record[field] ?? "";
  row.tags = toDisplayTags(record.tags);
  return row;
}

function latestRepkgResult(id) {
  const root = path.join(projectRoot, "temp", "repkg");
  if (!fssync.existsSync(root)) return null;
  const matches = [];
  function visit(directory) {
    for (const entry of fssync.readdirSync(directory, { withFileTypes: true })) {
      const fullPath = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        visit(fullPath);
      } else if (entry.isFile() && entry.name.toLowerCase() === "result.json") {
        try {
          const result = JSON.parse(fssync.readFileSync(fullPath, "utf8").replace(/^\uFEFF/, ""));
          if (path.basename(String(result.source_mpkg ?? "")).toLowerCase() === `${id}.mpkg`.toLowerCase()) {
            matches.push({ file: fullPath, result, mtime: fssync.statSync(fullPath).mtimeMs });
          }
        } catch {
          // Ignore unrelated or incomplete temporary result files.
        }
      }
    }
  }
  visit(root);
  matches.sort((a, b) => b.mtime - a.mtime);
  return matches[0]?.result ?? null;
}

function convertedPathFor(id) {
  const flat = path.join(convertedDir, `${id}.mp4`);
  if (fssync.existsSync(flat)) return flat;
  return path.join(convertedDir, id, `${id}.mp4`);
}

async function writeJsonAtomic(filePath, value) {
  const tmp = `${filePath}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(value, null, 2), "utf8");
  JSON.parse(await fs.readFile(tmp, "utf8"));
  await fs.rename(tmp, filePath);
}

async function backupArchiveMetadata(destinationRoot) {
  if (!(await exists(wallpaperDir))) return 0;
  let copied = 0;
  async function visit(dir) {
    for (const entry of await fs.readdir(dir, { withFileTypes: true })) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        await visit(fullPath);
      } else if (entry.isFile() && /^metadata\.(csv|xlsx)$/i.test(entry.name)) {
        const relative = path.relative(wallpaperDir, fullPath);
        const destination = path.join(destinationRoot, relative);
        await fs.mkdir(path.dirname(destination), { recursive: true });
        await fs.copyFile(fullPath, destination);
        copied++;
      }
    }
  }
  await visit(wallpaperDir);
  return copied;
}

async function main() {
  await fs.mkdir(logDir, { recursive: true });
  await fs.writeFile(logPath, "", "utf8");
  if (await exists(lockPath)) throw new Error(`Database lock exists: ${lockPath}`);
  await fs.writeFile(lockPath, `archive_scene_dynamic_batch ${runIso}`, "utf8");

  try {
    const dbPath = path.join(databaseDir, "wallpapers.json");
    const csvPath = path.join(databaseDir, "wallpapers.csv");
    const historyPath = path.join(databaseDir, "history.json");
    const db = JSON.parse((await fs.readFile(dbPath, "utf8")).replace(/^\uFEFF/, ""));
    const history = JSON.parse((await fs.readFile(historyPath, "utf8")).replace(/^\uFEFF/, ""));
    if (db.source_root !== sourceRoot) throw new Error(`Unexpected source_root: ${db.source_root}`);
    if (removeTempInputs) {
      const tempRoot = path.resolve(projectRoot, "temp");
      for (const candidate of [convertedDir, mpkgDir]) {
        const relative = path.relative(tempRoot, candidate);
        if (relative.startsWith("..") || path.isAbsolute(relative)) {
          throw new Error(`Refusing cleanup outside project temp directory: ${candidate}`);
        }
      }
    }

    // Validate every input before creating a backup or touching the archive.
    for (const id of workshopIds) {
      const record = db.wallpapers[id];
      if (!record) throw new Error(`Missing database record ${id}`);
      const sourceMp4 = convertedPathFor(id);
      const sourceMpkg = path.join(mpkgDir, `${id}.mpkg`);
      if (!(await exists(sourceMp4))) throw new Error(`Converted MP4 missing: ${sourceMp4}`);
      if (!(await exists(sourceMpkg))) throw new Error(`MPKG missing: ${sourceMpkg}`);
      const outputHash = await sha256(sourceMp4);
      const mpkgHash = await sha256(sourceMpkg);
      const repkg = latestRepkgResult(id);
      if (!repkg || String(repkg.status).toUpperCase() !== "SUCCESS") {
        throw new Error(`RePKG result missing or not SUCCESS for ${id}`);
      }
      if (String(repkg.source_sha256 ?? "").toLowerCase() !== mpkgHash.toLowerCase()) {
        throw new Error(`RePKG source hash does not match selected MPKG for ${id}`);
      }
      if (String(repkg.output_sha256 ?? "").toLowerCase() !== outputHash.toLowerCase()) {
        throw new Error(`RePKG output hash does not match selected MP4 for ${id}`);
      }
      const probe = probeVideo(sourceMp4);
      if (!probe.codec || !probe.width || !probe.height || !probe.duration || !probe.fps) {
        throw new Error(`ffprobe invalid for ${id}`);
      }
    }
    await log(`Preflight passed ids=${workshopIds.join(",")}`);

    await fs.mkdir(backupDir, { recursive: true });
    await fs.copyFile(dbPath, path.join(backupDir, "wallpapers.json"));
    if (await exists(csvPath)) await fs.copyFile(csvPath, path.join(backupDir, "wallpapers.csv"));
    await fs.copyFile(historyPath, path.join(backupDir, "history.json"));
    const metadataBackupCount = await backupArchiveMetadata(path.join(backupDir, "wallpaper_metadata"));
    await log(`Backup ${backupDir}; metadata_files=${metadataBackupCount}`);

    const usedNames = new Map();
    const archived = [];
    const hashes = new Map();

    for (const id of workshopIds) {
      const record = db.wallpapers[id];
      if (!record) throw new Error(`Missing database record ${id}`);
      const sourceMp4 = convertedPathFor(id);
      const sourceMpkg = path.join(mpkgDir, `${id}.mpkg`);
      const probe = probeVideo(sourceMp4);
      const outputHash = await sha256(sourceMp4);
      const mpkgHash = await sha256(sourceMpkg);
      const repkg = latestRepkgResult(id);
      if (!repkg || String(repkg.status).toUpperCase() !== "SUCCESS") {
        throw new Error(`RePKG result missing or not SUCCESS for ${id}`);
      }
      if (String(repkg.source_sha256 ?? "").toLowerCase() !== mpkgHash.toLowerCase()) {
        throw new Error(`RePKG source hash does not match selected MPKG for ${id}`);
      }
      if (String(repkg.output_sha256 ?? "").toLowerCase() !== outputHash.toLowerCase()) {
        throw new Error(`RePKG output hash does not match selected MP4 for ${id}`);
      }

      const tag = sanitizeName(record.primary_tag, "_NoTag");
      const title = sanitizeName(record.title, id);
      const targetDir = path.join(wallpaperDir, "Scene_Dynamic", tag);
      await fs.mkdir(targetDir, { recursive: true });
      let filename = `${title}.mp4`;
      let targetPath = path.join(targetDir, filename);
      if (replaceExisting && record.relative_path) {
        const recordedPath = path.resolve(projectRoot, record.relative_path);
        const relativeToWallpaper = path.relative(wallpaperDir, recordedPath);
        if (relativeToWallpaper.startsWith("..") || path.isAbsolute(relativeToWallpaper)) {
          throw new Error(`Recorded archive path escapes wallpaper root for ${id}: ${record.relative_path}`);
        }
        if (await exists(recordedPath)) {
          targetPath = recordedPath;
          filename = path.basename(recordedPath);
        }
      }
      let existingHash = await exists(targetPath) ? await sha256(targetPath) : null;
      const key = targetPath.toLowerCase();
      if ((usedNames.has(key) && usedNames.get(key) !== id) ||
          (existingHash && existingHash.toLowerCase() !== outputHash.toLowerCase())) {
        if (!(replaceExisting && record.relative_path && targetPath === path.resolve(projectRoot, record.relative_path))) {
          filename = `${title} [${id}].mp4`;
          targetPath = path.join(targetDir, filename);
          existingHash = await exists(targetPath) ? await sha256(targetPath) : null;
        }
      }
      const replacingDifferentContent = existingHash &&
        existingHash.toLowerCase() !== outputHash.toLowerCase() &&
        replaceExisting &&
        record.relative_path &&
        targetPath === path.resolve(projectRoot, record.relative_path);
      if (existingHash && existingHash.toLowerCase() !== outputHash.toLowerCase() && !replacingDifferentContent) {
        throw new Error(`Refusing to overwrite a different archive file: ${targetPath}`);
      }
      usedNames.set(targetPath.toLowerCase(), id);
      if (replacingDifferentContent) {
        const oldArchiveBackup = path.join(backupDir, "replaced_archive", path.relative(projectRoot, targetPath));
        await fs.mkdir(path.dirname(oldArchiveBackup), { recursive: true });
        await fs.copyFile(targetPath, oldArchiveBackup, fssync.constants.COPYFILE_EXCL);
        if ((await sha256(oldArchiveBackup)).toLowerCase() !== existingHash.toLowerCase()) {
          throw new Error(`Existing archive backup verification failed for ${id}: ${oldArchiveBackup}`);
        }
        const stagedTarget = `${targetPath}.${id}.${runStamp}.tmp`;
        await fs.copyFile(sourceMp4, stagedTarget, fssync.constants.COPYFILE_EXCL);
        if ((await sha256(stagedTarget)).toLowerCase() !== outputHash.toLowerCase()) {
          await fs.unlink(stagedTarget).catch(() => {});
          throw new Error(`Staged replacement verification failed for ${id}: ${stagedTarget}`);
        }
        await fs.rename(stagedTarget, targetPath);
      } else if (!existingHash) {
        await fs.copyFile(sourceMp4, targetPath);
      }
      const targetStat = await fs.stat(targetPath);
      const sourceStat = await fs.stat(sourceMp4);
      if (targetStat.size <= 0 || targetStat.size !== sourceStat.size ||
          (await sha256(targetPath)).toLowerCase() !== outputHash.toLowerCase()) {
        throw new Error(`Archive copy verification failed for ${id}`);
      }

      const dataDir = path.join(targetDir, "data");
      await fs.mkdir(dataDir, { recursive: true });
      const previewRef = record.raw_project_metadata?.preview;
      const previewCandidates = [];
      for (const name of ["preview.jpg", "preview.gif", previewRef].filter(Boolean)) {
        const candidate = path.join(record.source_workshop_path, name);
        if (await exists(candidate)) previewCandidates.push(candidate);
      }
      if (previewCandidates.length) {
        const sourcePreview = previewCandidates[0];
        const ext = path.extname(sourcePreview).toLowerCase() || ".jpg";
        const previewType = ext === ".gif" ? "gif" : "jpg";
        let previewName = `${title}_preview.${previewType}`;
        let previewPath = path.join(dataDir, previewName);
        const previewHash = await sha256(sourcePreview);
        if (await exists(previewPath) &&
            (await sha256(previewPath)).toLowerCase() !== previewHash.toLowerCase()) {
          previewName = `${title} [${id}]_preview.${previewType}`;
          previewPath = path.join(dataDir, previewName);
        }
        if (await exists(previewPath)) {
          if ((await sha256(previewPath)).toLowerCase() !== previewHash.toLowerCase()) {
            throw new Error(`Refusing to overwrite a different preview: ${previewPath}`);
          }
        } else {
          await fs.copyFile(sourcePreview, previewPath);
        }
        const previewStat = await fs.stat(previewPath);
        const dims = await imageDimensions(previewPath);
        record.preview_path = relFromProject(previewPath);
        record.preview_type = previewType;
        record.preview_width = dims.width;
        record.preview_height = dims.height;
        record.preview_size = previewStat.size;
        record.preview_hash = await sha256(previewPath);
      }

      const relativePath = relFromProject(targetPath);
      const oldStatus = record.processing_status;
      record.scene_class = "Scene_Dynamic";
      record.relative_path = relativePath;
      record.filename = filename;
      record.file_size = targetStat.size;
      record.file_created_time = (targetStat.birthtime || targetStat.ctime).toISOString();
      record.file_modified_time = targetStat.mtime.toISOString();
      record.width = probe.width;
      record.height = probe.height;
      record.resolution = probe.resolution;
      record.duration = probe.duration;
      record.fps = probe.fps;
      record.codec = probe.codec;
      record.bitrate = probe.bitrate;
      record.output_hash = outputHash;
      record.archive_state = "LOCAL";
      record.processing_status = "PROCESSED";
      record.conversion_status = "MPKG_TO_MP4";
      record.conversion_time = runIso;
      record.last_processed = runIso;
      record.last_seen = runIso;
      record.contentrating = record.raw_project_metadata?.contentrating ?? record.contentrating ?? null;
      record.artifacts = [
        {
          kind: "video",
          relative_path: relativePath,
          filename,
          width: probe.width,
          height: probe.height,
          resolution: probe.resolution,
          duration: probe.duration,
          fps: probe.fps,
          codec: probe.codec,
          bitrate: probe.bitrate,
          file_size: targetStat.size,
          output_hash: outputHash,
        },
      ];
      record.mpkg_temp_path = removeTempInputs ? null : relFromProject(sourceMpkg);
      record.mpkg_hash = mpkgHash;
      record.mpkg_size = (await fs.stat(sourceMpkg)).size;
      if (removeTempInputs) {
        record.mpkg_cleanup_status = "PENDING_VERIFIED_ARCHIVE_CLEANUP";
        record.mpkg_cleanup_time = null;
      }
      history.events.push({
        timestamp: runIso,
        workshopid: id,
        event: "CONVERTED",
        old_state: oldStatus,
        new_state: "PROCESSED",
        details: `Scene_Dynamic archived to ${relativePath}; mpkg_sha256=${mpkgHash}; mp4_sha256=${outputHash}`,
      });
      history.events.push({
        timestamp: runIso,
        workshopid: id,
        event: "VERIFIED",
        old_state: "PROCESSING",
        new_state: "PROCESSED",
        details: `ffprobe codec=${probe.codec} resolution=${probe.resolution} fps=${probe.fps} duration=${probe.duration}`,
      });

      if (hashes.has(outputHash)) {
        history.events.push({
          timestamp: runIso,
          workshopid: id,
          event: "DUPLICATE_FOUND",
          old_state: "PROCESSED",
          new_state: "PROCESSED",
          details: `Duplicate output hash with ${hashes.get(outputHash)}`,
        });
        await log(`DUPLICATE ${id} matches ${hashes.get(outputHash)}`);
      } else {
        hashes.set(outputHash, id);
      }

      archived.push({
        workshopid: id,
        title: record.title,
        primary_tag: record.primary_tag,
        relative_path: relativePath,
        file_size: targetStat.size,
        resolution: probe.resolution,
        fps: probe.fps,
        duration: probe.duration,
        codec: probe.codec,
        output_hash: outputHash,
        mpkg_hash: mpkgHash,
      });
      await log(`ARCHIVED ${id} -> ${relativePath}`);
    }

    const records = Object.values(db.wallpapers);
    const allRows = records.map(rowFromRecord);
    const processedVideos = records.filter((record) => record.type === "video" && record.processing_status === "PROCESSED").map(rowFromRecord);
    const sceneStatic = records.filter((record) => record.type === "Scene" && record.scene_class === "Scene_Static" && record.processing_status === "PROCESSED").map(rowFromRecord);
    const sceneDynamic = records.filter((record) => record.type === "Scene" && record.scene_class === "Scene_Dynamic" && record.processing_status === "PROCESSED").map(rowFromRecord);
    const wallpaperRows = [...processedVideos, ...sceneStatic, ...sceneDynamic];

    db.updated_at = runIso;
    history.updated_at = runIso;
    await writeJsonAtomic(dbPath, db);
    await writeCsv(csvPath, allRows);
    await writeJsonAtomic(historyPath, history);

    await writeMetadataPair(wallpaperDir, wallpaperRows);
    await writeMetadataPair(path.join(wallpaperDir, "video"), processedVideos);
    await writeMetadataPair(path.join(wallpaperDir, "Scene_Static"), sceneStatic);
    await writeMetadataPair(path.join(wallpaperDir, "Scene_Dynamic"), sceneDynamic);

    const tagGroups = new Map();
    for (const record of records.filter((item) => item.type === "Scene" && item.scene_class === "Scene_Dynamic" && item.processing_status === "PROCESSED")) {
      const tag = sanitizeName(record.primary_tag, "_NoTag");
      if (!tagGroups.has(tag)) tagGroups.set(tag, []);
      tagGroups.get(tag).push(rowFromRecord(record));
    }
    for (const [tag, rows] of tagGroups.entries()) {
      await writeMetadataPair(path.join(wallpaperDir, "Scene_Dynamic", tag), rows);
    }

    const indexResult = spawnSync(process.execPath, [path.join(projectRoot, "tools", "generate_wallpaper_indexes.mjs")], {
      cwd: projectRoot,
      encoding: "utf8",
      windowsHide: true,
    });
    if (indexResult.status !== 0) {
      throw new Error(`Index generation failed: ${indexResult.stderr || indexResult.stdout}`);
    }
    await log((indexResult.stdout || "").trim());

    if (removeTempInputs) {
      for (const id of workshopIds) {
        const record = db.wallpapers[id];
        const sourceMpkg = path.join(mpkgDir, `${id}.mpkg`);
        const sourceMp4 = convertedPathFor(id);
        const repkg = latestRepkgResult(id);
        const tempPkg = repkg?.temp_pkg ? path.resolve(repkg.temp_pkg) : null;
        const expectedMpkgHash = String(record.mpkg_hash ?? "").toLowerCase();
        const expectedMp4Hash = String(record.output_hash ?? "").toLowerCase();

        if (!(await exists(sourceMpkg)) || (await sha256(sourceMpkg)).toLowerCase() !== expectedMpkgHash) {
          throw new Error(`Refusing to remove unverified MPKG input for ${id}`);
        }
        if (!(await exists(sourceMp4)) || (await sha256(sourceMp4)).toLowerCase() !== expectedMp4Hash) {
          throw new Error(`Refusing to remove unverified temporary MP4 for ${id}`);
        }
        if (!tempPkg || !tempPkg.toLowerCase().endsWith(".pkg")) {
          throw new Error(`Refusing cleanup because temporary .pkg path is invalid for ${id}`);
        }
        const tempRoot = path.resolve(projectRoot, "temp");
        for (const candidate of [sourceMpkg, sourceMp4, tempPkg]) {
          const relative = path.relative(tempRoot, candidate);
          if (relative.startsWith("..") || path.isAbsolute(relative)) {
            throw new Error(`Refusing cleanup outside project temp directory: ${candidate}`);
          }
        }
        if (await exists(tempPkg)) {
          if ((await sha256(tempPkg)).toLowerCase() !== expectedMpkgHash) {
            throw new Error(`Refusing to remove .pkg with mismatched hash for ${id}`);
          }
          await fs.unlink(tempPkg);
        }
        await fs.unlink(sourceMpkg);
        await fs.unlink(sourceMp4);
        record.mpkg_cleanup_status = "REMOVED_AFTER_VERIFIED_ARCHIVE";
        record.mpkg_cleanup_time = runIso;
        history.events.push({
          timestamp: runIso,
          workshopid: id,
          event: "CLEANED_TEMP",
          old_state: "VERIFIED_TEMP_INPUTS",
          new_state: "REMOVED_AFTER_VERIFIED_ARCHIVE",
          details: `Removed temporary MPKG, .pkg, and staged MP4 after archive verification; mpkg_sha256=${expectedMpkgHash}; mp4_sha256=${expectedMp4Hash}`,
        });
        await log(`CLEANED_TEMP ${id}`);
      }
      db.updated_at = runIso;
      history.updated_at = runIso;
      await writeJsonAtomic(dbPath, db);
      await writeCsv(csvPath, Object.values(db.wallpapers).map(rowFromRecord));
      await writeJsonAtomic(historyPath, history);
    }

    const summary = {
      timestamp: runIso,
      backup_dir: backupDir,
      archived,
    };
    await fs.writeFile(path.join(logDir, `archive_scene_dynamic_summary_${runStamp}.json`), JSON.stringify(summary, null, 2), "utf8");
    await log(`SUMMARY archived=${archived.length}`);
    console.log(JSON.stringify(summary, null, 2));
  } finally {
    if (await exists(lockPath)) await fs.unlink(lockPath);
  }
}

main().catch(async (error) => {
  console.error(error);
  try { await log(`ERROR ${error.stack ?? error.message}`); } catch {}
  try { if (fssync.existsSync(lockPath)) fssync.unlinkSync(lockPath); } catch {}
  process.exit(1);
});
