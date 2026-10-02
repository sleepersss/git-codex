import path from "node:path";
import { fileURLToPath } from "node:url";
import { archiveStaticScenes } from "./lib/static_scene_archiver.mjs";

const args = process.argv.slice(2);
const ids = [];
let extractedRoot = path.resolve("temp", "extracted", "scene_json");
for (let i = 0; i < args.length; i += 1) {
  if (args[i] === "--workshop-id") ids.push(...String(args[++i] ?? "").split(",").map((item) => item.trim()).filter(Boolean));
  else if (args[i] === "--extracted-root") extractedRoot = path.resolve(args[++i]);
  else throw new Error(`Unknown argument: ${args[i]}`);
}
if (!ids.length || ids.some((id) => !/^\d+$/.test(id))) throw new Error("Pass numeric --workshop-id values.");
const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const result = await archiveStaticScenes({ projectRoot, workshopIds: [...new Set(ids)], extractedRoot });
console.log(JSON.stringify({ archived: result }, null, 2));
