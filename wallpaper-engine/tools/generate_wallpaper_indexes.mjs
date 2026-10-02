import fs from "node:fs/promises";
import fsSync from "node:fs";
import path from "node:path";

const projectRoot = "D:\\7_Video\\20_Wallpaper Engine";
const databasePath = path.join(projectRoot, "database", "wallpapers.json");
const wallpaperRoot = path.join(projectRoot, "wallpaper");
const logDir = path.join(projectRoot, "database", "logs");
const runStamp = formatLocalStamp(new Date());
const runIso = new Date().toISOString();
const logPath = path.join(logDir, `generate_indexes_${runStamp}.log`);
const summaryPath = path.join(logDir, `generate_indexes_summary_${runStamp}.json`);
const previewWidth = 240;
const previewHeight = 135;

function formatLocalStamp(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

async function exists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function log(message) {
  const line = `[${new Date().toISOString()}] ${message}`;
  console.log(line);
  await fs.appendFile(logPath, `${line}\n`, "utf8");
}

function readJsonText(text) {
  return JSON.parse(text.replace(/^\uFEFF/, ""));
}

function sanitizeName(value, fallback) {
  let safe = String(value ?? "").trim() || fallback;
  safe = safe.replace(/[\\/:*?"<>|]/g, "_").replace(/[\u0000-\u001f]/g, "");
  safe = safe.trim().replace(/[. ]+$/g, "");
  return safe || fallback;
}

function relativeLink(fromDir, targetPath) {
  return path.relative(fromDir, targetPath)
    .split(path.sep)
    .map((segment) => segment
      .replace(/%/g, "%25")
      .replace(/#/g, "%23")
      .replace(/\?/g, "%3F"))
    .join("/");
}

function escapeMarkdown(value) {
  return String(value ?? "").replace(/\\/g, "\\\\").replace(/\|/g, "\\|").replace(/\r?\n/g, " ");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/\r?\n/g, "<br>");
}

function titleSort(a, b) {
  return String(a.title ?? "").localeCompare(String(b.title ?? ""), "zh-Hans", { sensitivity: "base" }) ||
    String(a.workshopid).localeCompare(String(b.workshopid));
}

function recordHasOutput(record) {
  return record.relative_path && record.processing_status === "PROCESSED";
}

function previewCell(record, indexDir) {
  if (!record.preview_path) return "无预览";
  const previewPath = path.join(projectRoot, record.preview_path);
  if (!existsSync(previewPath)) return "无预览";
  const link = relativeLink(indexDir, previewPath);
  const label = escapeHtml(`${record.title}_preview`);
  const safeLink = escapeHtml(link);
  return `<a href="${safeLink}"><img src="${safeLink}" alt="${label}" width="${previewWidth}" height="${previewHeight}" style="width:${previewWidth}px;height:${previewHeight}px;object-fit:cover;display:block;" /></a>`;
}

function videoCell(record, indexDir) {
  if (!recordHasOutput(record)) return "无归档文件";
  const videoPath = path.join(projectRoot, record.relative_path);
  if (!existsSync(videoPath)) return "无归档文件";
  const link = relativeLink(indexDir, videoPath);
  return `<a href="${escapeHtml(link)}">打开视频</a>`;
}

function steamCell(record) {
  const url = `steam://url/CommunityFilePage/${record.workshopid}`;
  return `<a href="${escapeHtml(url)}">打开 Wallpaper</a>`;
}

function existsSync(filePath) {
  try {
    fsSync.accessSync(filePath);
    return true;
  } catch {
    return false;
  }
}

function renderIndex({ title, rows, indexDir }) {
  const lines = [
    `<style>
table.wallpaper-index { width: 100%; table-layout: fixed; }
table.wallpaper-index th:nth-child(1), table.wallpaper-index td:nth-child(1) { width: 320px; min-width: 320px; }
table.wallpaper-index th:nth-child(2), table.wallpaper-index td:nth-child(2) { width: 260px; min-width: 260px; }
table.wallpaper-index th:nth-child(3), table.wallpaper-index td:nth-child(3) { width: 120px; min-width: 120px; }
table.wallpaper-index th:nth-child(4), table.wallpaper-index td:nth-child(4) { width: 150px; min-width: 150px; }
table.wallpaper-index td { vertical-align: middle; }
.wallpaper-title { display: block; width: 300px; max-width: 300px; white-space: normal; overflow-wrap: anywhere; word-break: break-word; }
</style>`,
    "",
    `# ${escapeHtml(title)}`,
    "",
    `生成时间：${runIso}`,
    "",
    `<table class="wallpaper-index">`,
    "<thead><tr><th>标题</th><th>预览</th><th>视频</th><th>Wallpaper</th></tr></thead>",
    "<tbody>",
  ];
  for (const record of [...rows].sort(titleSort)) {
    const titleCell = `<span class="wallpaper-title">${escapeHtml(record.title)}</span>`;
    lines.push(`<tr><td>${titleCell}</td><td>${previewCell(record, indexDir)}</td><td>${videoCell(record, indexDir)}</td><td>${steamCell(record)}</td></tr>`);
  }
  if (!rows.length) {
    lines.push("<tr><td colspan=\"4\">暂无记录</td></tr>");
  }
  lines.push("</tbody></table>", "");
  return lines.join("\n");
}

async function writeIndex(indexDir, title, rows) {
  await fs.mkdir(indexDir, { recursive: true });
  const filePath = path.join(indexDir, "index.md");
  const text = renderIndex({ title, rows, indexDir });
  await fs.writeFile(filePath, text, "utf8");
  return filePath;
}

async function main() {
  await fs.mkdir(logDir, { recursive: true });
  await fs.writeFile(logPath, "", "utf8");

  const db = readJsonText(await fs.readFile(databasePath, "utf8"));
  if (db.source_root !== "E:\\1_Game\\steam\\steamapps\\workshop\\content\\431960") {
    throw new Error(`Unexpected source_root: ${db.source_root}`);
  }
  const records = Object.values(db.wallpapers).sort(titleSort);
  const videoRecords = records.filter((record) => record.type === "video");
  const sceneStatic = records.filter((record) => record.type === "Scene" && record.scene_class === "Scene_Static");
  const sceneDynamic = records.filter((record) => record.type === "Scene" && record.scene_class === "Scene_Dynamic");
  const unknown = records.filter((record) => record.type === "UNKNOWN" || (record.type === "Scene" && !["Scene_Static", "Scene_Dynamic"].includes(record.scene_class)));
  const outputs = [];
  const warnings = [];

  outputs.push(await writeIndex(path.join(wallpaperRoot, "data"), "Wallpaper Engine 壁纸总索引", records));
  outputs.push(await writeIndex(path.join(wallpaperRoot, "video", "data"), "video", videoRecords));
  outputs.push(await writeIndex(path.join(wallpaperRoot, "Scene_Static", "data"), "Scene_Static", sceneStatic));
  outputs.push(await writeIndex(path.join(wallpaperRoot, "Scene_Dynamic", "data"), "Scene_Dynamic", sceneDynamic));
  outputs.push(await writeIndex(path.join(wallpaperRoot, "UNKNOWN", "data"), "UNKNOWN", unknown));

  async function writeTagIndexes(typeDir, recordsForType) {
    const tags = new Map();
    for (const record of recordsForType) {
      if (!record.relative_path) continue;
      const tag = sanitizeName(record.primary_tag, "_NoTag");
      if (!tags.has(tag)) tags.set(tag, []);
      tags.get(tag).push(record);
    }
    for (const [tag, rows] of tags.entries()) {
      outputs.push(await writeIndex(path.join(wallpaperRoot, typeDir, tag, "data"), tag, rows));
    }
  }

  await writeTagIndexes("video", videoRecords);
  await writeTagIndexes("Scene_Static", sceneStatic);
  await writeTagIndexes("Scene_Dynamic", sceneDynamic);

  for (const record of records) {
    if (record.preview_path && !existsSync(path.join(projectRoot, record.preview_path))) {
      warnings.push(`PREVIEW_MISSING ${record.workshopid} ${record.preview_path}`);
    }
    if (record.relative_path && !existsSync(path.join(projectRoot, record.relative_path))) {
      warnings.push(`OUTPUT_MISSING ${record.workshopid} ${record.relative_path}`);
    }
    const expectedUrl = `https://steamcommunity.com/sharedfiles/filedetails/?id=${record.workshopid}`;
    if (record.workshopurl && !String(record.workshopurl).includes(`id=${record.workshopid}`)) {
      warnings.push(`WORKSHOP_URL_MISMATCH ${record.workshopid} ${record.workshopurl}`);
    }
  }

  const summary = {
    timestamp: runIso,
    index_files: outputs.map((filePath) => path.relative(projectRoot, filePath).split(path.sep).join("\\")),
    record_count: records.length,
    video_record_count: videoRecords.length,
    warnings,
  };
  await fs.writeFile(summaryPath, JSON.stringify(summary, null, 2), "utf8");
  await log(`SUMMARY indexes=${outputs.length} records=${records.length} warnings=${warnings.length}`);
}

main().catch(async (error) => {
  await log(`ERROR ${error.stack ?? error.message}`);
  process.exit(1);
});
