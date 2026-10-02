import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { resolveStaticSceneImages } from "../lib/static_scene_archiver.mjs";

test("resolves only visible images referenced by scene model and material", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "wallpaper-static-scene-"));
  try {
    await fs.mkdir(path.join(root, "models"), { recursive: true });
    await fs.mkdir(path.join(root, "materials"), { recursive: true });
    await fs.writeFile(path.join(root, "scene.json"), JSON.stringify({
      objects: [
        { visible: true, image: "models/background.json" },
        { visible: false, image: "models/hidden.json" },
      ],
    }), "utf8");
    await fs.writeFile(path.join(root, "models", "background.json"), JSON.stringify({ material: "materials/background.json" }), "utf8");
    await fs.writeFile(path.join(root, "models", "hidden.json"), JSON.stringify({ material: "materials/hidden.json" }), "utf8");
    await fs.writeFile(path.join(root, "materials", "background.json"), JSON.stringify({ passes: [{ textures: ["background"] }] }), "utf8");
    await fs.writeFile(path.join(root, "materials", "hidden.json"), JSON.stringify({ passes: [{ textures: ["hidden"] }] }), "utf8");
    await fs.writeFile(path.join(root, "materials", "background.png"), "fixture", "utf8");
    await fs.writeFile(path.join(root, "materials", "hidden.png"), "fixture", "utf8");
    const result = await resolveStaticSceneImages(root);
    assert.deepEqual(result, [path.join(root, "materials", "background.png")]);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});
