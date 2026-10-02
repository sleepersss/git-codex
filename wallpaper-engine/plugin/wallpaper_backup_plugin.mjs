import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import {
  applyInventoryToDatabase,
  buildProcessingPlan,
  csvText,
  exists,
  readJson,
  scanWorkshopSource,
  writeJsonAtomic,
} from "./lib/plugin_core.mjs";

const pluginRoot = path.dirname(fileURLToPath(import.meta.url));
const defaultConfigPath = path.join(pluginRoot, "config.json");

function parseArgs(argv) {
  const args = { config: defaultConfigPath, apply: false, skipWait: false, forceRescan: false, planOnly: false };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--config") args.config = path.resolve(argv[++i]);
    else if (argv[i] === "--apply") args.apply = true;
    else if (argv[i] === "--skip-startup-wait") args.skipWait = true;
    else if (argv[i] === "--force-rescan") args.forceRescan = true;
    else if (argv[i] === "--plan-only") args.planOnly = true;
    else if (argv[i] === "--help" || argv[i] === "-h") args.help = true;
    else throw new Error(`Unknown argument: ${argv[i]}`);
  }
  return args;
}

function usage() {
  return `Wallpaper Engine archive startup plugin

Default: dry-run plan only. Real processing requires both config activation_mode=apply and --apply.

  node plugin/wallpaper_backup_plugin.mjs --skip-startup-wait --force-rescan
  node plugin/wallpaper_backup_plugin.mjs --apply
`;
}

function stamp(date = new Date()) {
  const pad = (v) => String(v).padStart(2, "0");
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

function bootEpochMs() {
  return Date.now() - os.uptime() * 1000;
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd,
    encoding: "utf8",
    windowsHide: true,
    maxBuffer: 64 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.status !== 0 && !options.allowFailure) {
    throw new Error(`${path.basename(command)} failed (${result.status}): ${(result.stderr || result.stdout || "").trim()}`);
  }
  return result;
}

function wallpaperProcessRunning(names) {
  const result = run("tasklist.exe", ["/FO", "CSV", "/NH"], { allowFailure: true });
  const text = `${result.stdout}\n${result.stderr}`.toLowerCase();
  return names.some((name) => text.includes(`"${String(name).toLowerCase()}"`));
}

async function waitForWallpaper(config, log) {
  if (!config.startup.wait_for_wallpaper_process) return;
  const deadline = Date.now() + Number(config.startup.wait_timeout_seconds ?? 300) * 1000;
  while (Date.now() < deadline) {
    if (wallpaperProcessRunning(config.startup.wallpaper_process_names ?? ["wallpaper32.exe", "wallpaper64.exe"])) {
      await log("Wallpaper Engine renderer detected.");
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error("Wallpaper Engine renderer was not detected before timeout.");
}

async function sourceSnapshot(sourceRoot) {
  const rows = [];
  for (const entry of await fs.readdir(sourceRoot, { withFileTypes: true })) {
    if (!entry.isDirectory() || !/^\d+$/.test(entry.name)) continue;
    const itemRoot = path.join(sourceRoot, entry.name);
    const itemStat = await fs.stat(itemRoot);
    rows.push(`${entry.name}|DIR|${Math.trunc(itemStat.mtimeMs)}`);
    const project = path.join(itemRoot, "project.json");
    const files = [project, path.join(itemRoot, "scene.pkg")];
    if (await exists(project)) {
      try {
        const metadata = await readJson(project);
        if (typeof metadata.file === "string" && metadata.file.trim()) {
          const payload = path.resolve(itemRoot, metadata.file.replace(/\//g, path.sep));
          const boundedRoot = `${path.resolve(itemRoot).toLowerCase()}${path.sep}`;
          if (payload.toLowerCase().startsWith(boundedRoot)) files.push(payload);
        }
      } catch {
        // The project file itself remains in the snapshot and will be retried until stable.
      }
    }
    for (const file of [...new Set(files)]) {
      if (!(await exists(file))) continue;
      const stat = await fs.stat(file);
      rows.push(`${entry.name}|${path.relative(itemRoot, file)}|${stat.size}|${Math.trunc(stat.mtimeMs)}`);
    }
  }
  return rows.sort().join("\n");
}

async function waitForStableSource(sourceRoot, seconds, log) {
  if (seconds <= 0) return;
  let previous = await sourceSnapshot(sourceRoot);
  let stableSince = Date.now();
  const deadline = Date.now() + Math.max(60, seconds * 6) * 1000;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    const current = await sourceSnapshot(sourceRoot);
    if (current === previous) {
      if (Date.now() - stableSince >= seconds * 1000) {
        await log(`Workshop source stable for ${seconds}s.`);
        return;
      }
    } else {
      previous = current;
      stableSince = Date.now();
    }
  }
  throw new Error("Workshop source did not stabilize before timeout.");
}

async function copyIfExists(source, destination) {
  if (await exists(source)) await fs.copyFile(source, destination);
}

async function databaseTransaction(projectRoot, inventory, plan, runIso, log) {
  const databaseDir = path.join(projectRoot, "database");
  const lock = path.join(databaseDir, ".lock");
  if (await exists(lock)) throw new Error(`Database lock exists: ${lock}`);
  await fs.writeFile(lock, `wallpaper_backup_plugin ${runIso}`, "utf8");
  try {
    const dbPath = path.join(databaseDir, "wallpapers.json");
    const csvPath = path.join(databaseDir, "wallpapers.csv");
    const historyPath = path.join(databaseDir, "history.json");
    const db = await readJson(dbPath);
    const history = await readJson(historyPath);
    const backup = path.join(databaseDir, "backups", stamp(), "plugin_scan");
    await fs.mkdir(backup, { recursive: true });
    await copyIfExists(dbPath, path.join(backup, "wallpapers.json"));
    await copyIfExists(csvPath, path.join(backup, "wallpapers.csv"));
    await copyIfExists(historyPath, path.join(backup, "history.json"));
    const applied = applyInventoryToDatabase(db, history, inventory, plan, runIso);
    await writeJsonAtomic(dbPath, applied.database);
    await fs.writeFile(`${csvPath}.${process.pid}.tmp`, csvText(Object.values(applied.database.wallpapers)), "utf8");
    await fs.rename(`${csvPath}.${process.pid}.tmp`, csvPath);
    await writeJsonAtomic(historyPath, applied.history);
    await log(`Database scan committed after backup: ${backup}`);
    return { backup, database: applied.database };
  } finally {
    if (await exists(lock)) await fs.unlink(lock);
  }
}

async function setSceneClassification(projectRoot, idsToClasses, runIso) {
  const databaseDir = path.join(projectRoot, "database");
  const lock = path.join(databaseDir, ".lock");
  if (await exists(lock)) throw new Error(`Database lock exists: ${lock}`);
  await fs.writeFile(lock, `wallpaper_backup_plugin_classify ${runIso}`, "utf8");
  try {
    const dbPath = path.join(databaseDir, "wallpapers.json");
    const csvPath = path.join(databaseDir, "wallpapers.csv");
    const historyPath = path.join(databaseDir, "history.json");
    const db = await readJson(dbPath);
    const history = await readJson(historyPath);
    const backup = path.join(databaseDir, "backups", stamp(), "plugin_scene_classification");
    await fs.mkdir(backup, { recursive: true });
    await copyIfExists(dbPath, path.join(backup, "wallpapers.json"));
    await copyIfExists(csvPath, path.join(backup, "wallpapers.csv"));
    await copyIfExists(historyPath, path.join(backup, "history.json"));
    for (const [id, sceneClass] of Object.entries(idsToClasses)) {
      const record = db.wallpapers[id];
      if (!record) throw new Error(`Cannot classify missing database record: ${id}`);
      const old = record.scene_class;
      record.scene_class = sceneClass;
      record.processing_status = sceneClass === "Scene_Static" ? "PENDING_STATIC_ARCHIVE" : sceneClass === "Scene_Dynamic" ? "PENDING_SCENE_EXPORT" : "SCENE_REVIEW_REQUIRED";
      history.events.push({ timestamp: runIso, workshopid: id, event: "SCENE_CLASSIFIED", old_state: old, new_state: sceneClass, details: "Classified by startup plugin using the existing scene classifier." });
    }
    db.updated_at = runIso;
    history.updated_at = runIso;
    await writeJsonAtomic(dbPath, db);
    await fs.writeFile(`${csvPath}.${process.pid}.tmp`, csvText(Object.values(db.wallpapers)), "utf8");
    await fs.rename(`${csvPath}.${process.pid}.tmp`, csvPath);
    await writeJsonAtomic(historyPath, history);
  } finally {
    if (await exists(lock)) await fs.unlink(lock);
  }
}

const args = parseArgs(process.argv.slice(2));
if (args.help) { console.log(usage()); process.exit(0); }
const config = await readJson(args.config);
const projectRoot = path.resolve(config.project_root);
const sourceRoot = path.resolve(config.source_root);
if (projectRoot !== path.resolve(String.raw`D:\7_Video\20_Wallpaper Engine`)) throw new Error(`Unexpected project_root: ${projectRoot}`);
if (sourceRoot !== path.resolve(String.raw`E:\1_Game\steam\steamapps\workshop\content\431960`)) throw new Error(`Unexpected source_root: ${sourceRoot}`);
const apply = args.apply && config.activation_mode === "apply" && !args.planOnly;
if (args.apply && config.activation_mode !== "apply") throw new Error("--apply was requested, but config activation_mode is not apply.");

const runStamp = stamp();
const runIso = new Date().toISOString();
const runtimeRoot = path.join(projectRoot, "runtime", "plugin");
const runDir = path.join(runtimeRoot, "runs", runStamp);
const statePath = path.join(runtimeRoot, "state.json");
const pluginLock = path.join(runtimeRoot, "plugin.lock");
await fs.mkdir(runDir, { recursive: true });
const logPath = path.join(runDir, "plugin.log");
const log = async (message) => {
  const line = `[${new Date().toISOString()}] ${message}`;
  console.log(line);
  await fs.appendFile(logPath, `${line}\n`, "utf8");
};

if (await exists(pluginLock)) throw new Error(`Plugin lock exists: ${pluginLock}`);
await fs.writeFile(pluginLock, `${process.pid} ${runIso}`, "utf8");
const itemResults = [];
try {
  const currentBootEpoch = bootEpochMs();
  const state = (await exists(statePath)) ? await readJson(statePath) : {};
  const sameBoot = Number.isFinite(state.boot_epoch_ms) && Math.abs(Number(state.boot_epoch_ms) - currentBootEpoch) < 120000;
  if (config.startup.once_per_boot && sameBoot && state.completed && !args.forceRescan) {
    await log("Already completed during this Windows boot; exiting without scanning.");
    process.exitCode = 0;
  } else {
    if (!args.skipWait) {
      await waitForWallpaper(config, log);
      await waitForStableSource(sourceRoot, Number(config.startup.source_stable_seconds ?? 15), log);
    }
    const database = await readJson(path.join(projectRoot, "database", "wallpapers.json"));
    if (path.resolve(database.source_root) !== sourceRoot) throw new Error(`Database source_root mismatch: ${database.source_root}`);
    const inventory = await scanWorkshopSource(sourceRoot);
    const plan = buildProcessingPlan(inventory, database, config);
    const planPayload = {
      schema_version: 1,
      generated_at: runIso,
      mode: apply ? "apply" : "dry_run",
      source_root: sourceRoot,
      summary: {
        scanned: inventory.entries.length,
        new: plan.new.length,
        updated: plan.updated.length,
        pending_existing: plan.pending_existing.length,
        video: plan.video.length,
        scene: plan.scene.length,
        web: plan.web.length,
        unsupported: plan.unsupported.length,
        missing_from_source: plan.missing_from_source.length,
      },
      plan,
      warnings: inventory.warnings,
    };
    await writeJsonAtomic(path.join(runDir, "plan.json"), planPayload);
    await log(`Plan: ${JSON.stringify(planPayload.summary)}`);

    if (apply) {
      await databaseTransaction(projectRoot, inventory, plan, runIso, log);

      if (config.processing.videos && plan.video.length) {
        const video = run(config.tools.powershell, ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path.join(projectRoot, "tools", "process_wallpaper_videos.ps1"), "-WorkshopId", plan.video.join(",")], { cwd: projectRoot, allowFailure: true });
        itemResults.push({ stage: "VIDEO", ids: plan.video, ok: video.status === 0, stdout: video.stdout, stderr: video.stderr });
        if (video.status !== 0 && !config.processing.continue_after_item_error) throw new Error("Video processing failed.");
      }

      if (config.processing.scenes && plan.scene.length) {
        const loopAnalysisPath = path.join(runDir, "scene_loop_analysis.json");
        const analyzerArgs = [path.join(projectRoot, "tools", "analyze_scene_loop_dependencies.mjs"), "--workshop-id", plan.scene.join(","), "--extract-root", path.join(projectRoot, "temp", "extracted", "scene_json"), "--output", loopAnalysisPath, "--repkg", config.tools.repkg];
        const analyzed = run(config.tools.node, analyzerArgs, { cwd: projectRoot, allowFailure: true });
        itemResults.push({ stage: "SCENE_ANALYSIS", ids: plan.scene, ok: analyzed.status === 0, stdout: analyzed.stdout, stderr: analyzed.stderr });
        if (analyzed.status !== 0) throw new Error("Scene loop dependency analysis failed.");

        const classificationPath = path.join(runDir, "scene_classification.json");
        const classified = run(config.tools.node, [path.join(projectRoot, "tools", "classify_scenes.mjs"), "--workshop-id", plan.scene.join(","), "--output", classificationPath], { cwd: projectRoot, allowFailure: true });
        if (classified.status !== 0) throw new Error(`Scene classification failed: ${classified.stderr}`);
        const classification = await readJson(classificationPath);
        const classMap = {};
        for (const id of plan.scene) classMap[id] = classification.results.find((item) => String(item.id) === id)?.scene_class ?? "UNKNOWN";
        await setSceneClassification(projectRoot, classMap, runIso);

        const staticIds = plan.scene.filter((id) => classMap[id] === "Scene_Static");
        if (staticIds.length) {
          const staticArchive = run(config.tools.node, [path.join(pluginRoot, "archive_scene_static.mjs"), "--workshop-id", staticIds.join(","), "--extracted-root", path.join(projectRoot, "temp", "extracted", "scene_json")], { cwd: projectRoot, allowFailure: true });
          itemResults.push({ stage: "SCENE_STATIC_ARCHIVE", ids: staticIds, ok: staticArchive.status === 0, stdout: staticArchive.stdout, stderr: staticArchive.stderr });
          if (staticArchive.status !== 0 && !config.processing.continue_after_item_error) throw new Error("Static Scene archive failed.");
        }

        for (const id of plan.scene) {
          const sceneClass = classMap[id];
          if (sceneClass !== "Scene_Dynamic") {
            if (sceneClass !== "Scene_Static") itemResults.push({ stage: "SCENE_ROUTE", ids: [id], ok: false, status: "SCENE_REVIEW_REQUIRED" });
            continue;
          }
          const analysis = await readJson(loopAnalysisPath);
          const itemAnalysis = analysis.results.find((item) => String(item.workshopid) === id);
          if (!itemAnalysis) throw new Error(`Loop analysis missing for ${id}`);
          if (itemAnalysis.decision === "REVIEW_REQUIRED" && config.processing.review_scene_policy === "stop") {
            itemResults.push({ stage: "SCENE_EXPORT", ids: [id], ok: false, status: "REVIEW_REQUIRED" });
            continue;
          }
          const exportArgs = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path.join(projectRoot, "tools", "export_mpkg_then_extract_mp4.ps1"), "-WorkshopId", id, "-LoopAnalysisPath", loopAnalysisPath];
          if (config.processing.include_likely_loop_overrides) exportArgs.push("-IncludeLikelyLoopOverrides");
          const exported = run(config.tools.powershell, exportArgs, { cwd: projectRoot, allowFailure: true });
          if (exported.status !== 0) {
            run(config.tools.powershell, ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path.join(projectRoot, "tools", "repair_wallpaper_engine_mpkg.ps1")], { cwd: projectRoot, allowFailure: true });
            itemResults.push({ stage: "SCENE_EXPORT", ids: [id], ok: false, stdout: exported.stdout, stderr: exported.stderr });
            if (!config.processing.continue_after_item_error) throw new Error(`Scene export failed for ${id}`);
            continue;
          }
          const archiveArgs = [path.join(projectRoot, "tools", "archive_scene_dynamic_batch.mjs"), id];
          if (config.processing.remove_verified_temp_inputs) archiveArgs.push("--remove-temp-inputs");
          const archived = run(config.tools.node, archiveArgs, { cwd: projectRoot, allowFailure: true });
          itemResults.push({ stage: "SCENE_ARCHIVE", ids: [id], ok: archived.status === 0, stdout: archived.stdout, stderr: archived.stderr });
          if (archived.status !== 0 && !config.processing.continue_after_item_error) throw new Error(`Scene archive failed for ${id}`);
        }
      }

      const index = run(config.tools.node, [path.join(projectRoot, "tools", "generate_wallpaper_indexes.mjs")], { cwd: projectRoot, allowFailure: true });
      itemResults.push({ stage: "INDEX", ok: index.status === 0, stdout: index.stdout, stderr: index.stderr });
      await writeJsonAtomic(path.join(runDir, "results.json"), { generated_at: new Date().toISOString(), item_results: itemResults });
      await writeJsonAtomic(statePath, { schema_version: 1, boot_epoch_ms: currentBootEpoch, completed: true, completed_at: new Date().toISOString(), last_run_dir: runDir });
      await log("Plugin apply run finished.");
    } else {
      await log("Dry-run complete; database, Workshop source, formal archive and startup state were not modified.");
    }
  }
} finally {
  if (await exists(pluginLock)) await fs.unlink(pluginLock);
}
