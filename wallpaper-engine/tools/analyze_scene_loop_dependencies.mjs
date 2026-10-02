import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { analyzeSceneLoopDependencies, sceneLoopAnalyzerContract } from "./lib/scene_loop_dependency_analyzer.mjs";

const DEFAULT_SOURCE_ROOT = String.raw`E:\1_Game\steam\steamapps\workshop\content\431960`;
const DEFAULT_REPKG = String.raw`D:\0_Vital document\tools\RePKG-GUI_v1.0.1\RePKG.exe`;

function parseArgs(argv) {
  const options = {
    ids: [],
    all: false,
    sourceRoot: DEFAULT_SOURCE_ROOT,
    extractRoot: path.resolve("temp", "extracted", "scene_loop_analysis"),
    sceneRoot: "",
    output: path.resolve("temp", "extracted", "scene_loop_analysis.json"),
    repkg: DEFAULT_REPKG,
    noExtract: false,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = () => {
      if (i + 1 >= argv.length) throw new Error(`Missing value after ${arg}`);
      i += 1;
      return argv[i];
    };
    if (arg === "--workshop-id" || arg === "-i") options.ids.push(...next().split(",").map((item) => item.trim()).filter(Boolean));
    else if (arg === "--all-scenes") options.all = true;
    else if (arg === "--source-root") options.sourceRoot = next();
    else if (arg === "--extract-root") options.extractRoot = path.resolve(next());
    else if (arg === "--scene-root") options.sceneRoot = path.resolve(next());
    else if (arg === "--output" || arg === "-o") options.output = path.resolve(next());
    else if (arg === "--repkg") options.repkg = next();
    else if (arg === "--no-extract") options.noExtract = true;
    else if (arg === "--help" || arg === "-h") options.help = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }
  return options;
}

function usage() {
  return `Scene loop dependency analyzer

Usage:
  node tools/analyze_scene_loop_dependencies.mjs --workshop-id 2733091473
  node tools/analyze_scene_loop_dependencies.mjs --all-scenes

Options:
  -i, --workshop-id <id[,id]>  Analyze one or more numeric Workshop IDs
      --all-scenes              Analyze every current Scene under source root
      --source-root <path>      Must be the Wallpaper Engine 431960 directory
      --scene-root <path>       Reuse extracted <id>/scene.json directories
      --extract-root <path>     Temporary RePKG extraction root
      --repkg <path>            RePKG executable path
      --no-extract              Report missing scene.json instead of extracting
  -o, --output <path>           Versioned batch JSON output
`;
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8").replace(/^\uFEFF/, ""));
}

function sha256(file) {
  const hash = crypto.createHash("sha256");
  hash.update(fs.readFileSync(file));
  return hash.digest("hex").toUpperCase();
}

function findSceneJson(root) {
  if (!fs.existsSync(root)) return "";
  const queue = [root];
  const candidates = [];
  while (queue.length) {
    const current = queue.shift();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) queue.push(full);
      else if (/^(?:scene|gifscene)\.json$/i.test(entry.name)) candidates.push(full);
    }
  }
  return candidates.sort((a, b) => a.length - b.length)[0] ?? "";
}

function assertSourceBoundary(sourceRoot) {
  const resolved = path.resolve(sourceRoot);
  if (path.basename(resolved) !== "431960") throw new Error(`Source root must end at appid 431960: ${resolved}`);
  return resolved;
}

function directWorkshopDir(sourceRoot, id) {
  if (!/^\d+$/.test(id)) throw new Error(`Workshop ID must be numeric: ${id}`);
  const candidate = path.resolve(sourceRoot, id);
  if (path.dirname(candidate).toLowerCase() !== sourceRoot.toLowerCase()) throw new Error(`Workshop path escaped source boundary: ${candidate}`);
  return candidate;
}

function extractScenePkg(repkg, pkg, output) {
  if (!fs.existsSync(repkg)) throw new Error(`RePKG not found: ${repkg}`);
  fs.mkdirSync(output, { recursive: true });
  const result = spawnSync(repkg, ["extract", pkg, "-o", output, "--overwrite"], {
    encoding: "utf8",
    windowsHide: true,
    maxBuffer: 32 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`RePKG failed (${result.status}): ${(result.stderr || result.stdout || "").trim()}`);
}

function listSceneIds(sourceRoot) {
  return fs.readdirSync(sourceRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && /^\d+$/.test(entry.name))
    .map((entry) => entry.name)
    .filter((id) => {
      const projectPath = path.join(sourceRoot, id, "project.json");
      if (!fs.existsSync(projectPath)) return false;
      try { return String(readJson(projectPath).type).toLowerCase() === "scene"; }
      catch { return false; }
    })
    .sort((a, b) => Number(a) - Number(b));
}

const options = parseArgs(process.argv.slice(2));
if (options.help) {
  console.log(usage());
  process.exit(0);
}

const sourceRoot = assertSourceBoundary(options.sourceRoot);
const ids = [...new Set(options.all ? [...listSceneIds(sourceRoot), ...options.ids] : options.ids)];
if (!ids.length) throw new Error("Specify --workshop-id or --all-scenes.");

const results = [];
const errors = [];
for (const id of ids) {
  try {
    const workshopDir = directWorkshopDir(sourceRoot, id);
    const projectPath = path.join(workshopDir, "project.json");
    const scenePkgPath = path.join(workshopDir, "scene.pkg");
    if (!fs.existsSync(projectPath)) throw new Error(`project.json missing: ${projectPath}`);
    if (!fs.existsSync(scenePkgPath)) throw new Error(`scene.pkg missing: ${scenePkgPath}`);
    const project = readJson(projectPath);
    if (String(project.type).toLowerCase() !== "scene") throw new Error(`Workshop ${id} is not a Scene.`);

    const projectHash = sha256(projectPath);
    const scenePkgHash = sha256(scenePkgPath);
    const hashedExtractRoot = path.join(options.extractRoot, id, scenePkgHash.slice(0, 16));
    let sceneJson = options.sceneRoot ? findSceneJson(path.join(options.sceneRoot, id)) : findSceneJson(hashedExtractRoot);
    if (!sceneJson && !options.noExtract) {
      extractScenePkg(options.repkg, scenePkgPath, hashedExtractRoot);
      sceneJson = findSceneJson(hashedExtractRoot);
    }
    if (!sceneJson) throw new Error(`scene.json unavailable for ${id}`);

    const result = analyzeSceneLoopDependencies({
      workshopId: id,
      project,
      scene: readJson(sceneJson),
      sourceHashes: {
        project_json_sha256: projectHash,
        scene_pkg_sha256: scenePkgHash,
      },
    });
    result.source_paths = {
      project_json: projectPath,
      scene_pkg: scenePkgPath,
      analyzed_scene_json: sceneJson,
    };
    results.push(result);
  } catch (error) {
    errors.push({ workshopid: id, error: error.message });
  }
}

const decisions = {};
for (const result of results) decisions[result.decision] = (decisions[result.decision] ?? 0) + 1;
const payload = {
  schema_version: 1,
  generated_at: new Date().toISOString(),
  source_root: sourceRoot,
  contract: sceneLoopAnalyzerContract,
  summary: { requested: ids.length, analyzed: results.length, errors: errors.length, decisions },
  results,
  errors,
};

fs.mkdirSync(path.dirname(options.output), { recursive: true });
const tempOutput = `${options.output}.${process.pid}.tmp`;
fs.writeFileSync(tempOutput, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
JSON.parse(fs.readFileSync(tempOutput, "utf8"));
fs.renameSync(tempOutput, options.output);

console.log(JSON.stringify({ output: options.output, ...payload.summary }, null, 2));
if (errors.length) process.exitCode = 2;
