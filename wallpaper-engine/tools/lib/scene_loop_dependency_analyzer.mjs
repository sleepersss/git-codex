const ANALYZER_VERSION = "1.0.0";
const RESULT_SCHEMA_VERSION = 1;

const OFF_WORDS = [
  "off", "none", "disabled", "disable", "no", "关闭", "关", "无", "禁用", "停用",
];

const SEMANTIC_PATTERNS = {
  audio_input: [
    /(?:audio|sound|音频|聲音).*(?:visual|react|response|responsive|beat|spectrum|bars?|bounce|可视化|响应|反应|跳动|律动)/i,
    /(?:visual|react|response|responsive|beat|spectrum|bars?|bounce|可视化|响应|反应|跳动|律动).*(?:audio|sound|音频|聲音)/i,
    /(?:media|music)\s*player|音乐播放器|媒體播放器|媒体播放器/i,
  ],
  mouse_input: [
    /(?:mouse|cursor|鼠标|滑鼠).*(?:particle|trail|ripple|effect|interactive|parallax|粒子|拖尾|波纹|互动|交互|视差)/i,
    /(?:particle|trail|ripple|effect|interactive|parallax|粒子|拖尾|波纹|互动|交互|视差).*(?:mouse|cursor|鼠标|滑鼠)/i,
  ],
  wall_clock: [
    /(?:show|enable|display|显示|启用|开启).*(?:clock|date|time|时钟|日期|时间)/i,
    /(?:clock|date|时钟|日期)(?!.*(?:format|color|size|position|格式|颜色|大小|位置))/i,
  ],
  camera_parallax: [
    /camera\s*parallax|mouse\s*parallax|镜头视差|鼠标视差/i,
  ],
  camera_shake: [
    /camera\s*shake|镜头震动|镜头抖动/i,
  ],
};

function cleanText(value) {
  return String(value ?? "")
    .replace(/<[^>]*>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function jsonPath(parts) {
  let out = "$";
  for (const part of parts) {
    if (typeof part === "number" || /^\d+$/.test(String(part))) out += `[${part}]`;
    else if (/^[A-Za-z_$][\w$]*$/.test(String(part))) out += `.${part}`;
    else out += `[${JSON.stringify(String(part))}]`;
  }
  return out;
}

function primitiveValue(value) {
  if (value && typeof value === "object" && Object.prototype.hasOwnProperty.call(value, "value")) {
    return primitiveValue(value.value);
  }
  return value;
}

function isTruthy(value) {
  const current = primitiveValue(value);
  if (typeof current === "string") return !/^(?:0|false|off|no|none)?$/i.test(current.trim());
  return Boolean(current);
}

function walk(value, visitor, path = [], ancestors = []) {
  visitor(value, path, ancestors);
  if (!value || typeof value !== "object") return;
  if (Array.isArray(value)) {
    value.forEach((item, index) => walk(item, visitor, [...path, index], [...ancestors, value]));
    return;
  }
  for (const [key, child] of Object.entries(value)) {
    walk(child, visitor, [...path, key], [...ancestors, value]);
  }
}

function projectProperties(project) {
  const props = project?.general?.properties;
  if (!props || typeof props !== "object" || Array.isArray(props)) return {};
  return props;
}

function describeProperty(key, descriptor) {
  return {
    key,
    type: String(descriptor?.type ?? "unknown"),
    text: cleanText(descriptor?.text ?? descriptor?.label ?? descriptor?.name ?? ""),
    value: descriptor?.value ?? null,
    min: descriptor?.min ?? null,
    max: descriptor?.max ?? null,
    options: Array.isArray(descriptor?.options)
      ? descriptor.options.map((option) => ({
          label: cleanText(option?.label ?? ""),
          value: option?.value ?? null,
        }))
      : [],
  };
}

function bindingName(user) {
  if (typeof user === "string") return user;
  if (user && typeof user === "object") return String(user.name ?? user.key ?? "");
  return "";
}

function objectIndexFromPath(path) {
  const index = path.indexOf("objects");
  if (index < 0 || index + 1 >= path.length) return null;
  const candidate = Number(path[index + 1]);
  return Number.isInteger(candidate) ? candidate : null;
}

function collectBindings(scene) {
  const bindings = [];
  walk(scene, (value, path) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return;
    if (!Object.prototype.hasOwnProperty.call(value, "user")) return;
    const key = bindingName(value.user);
    if (!key) return;
    const controlledProperty = String(path[path.length - 1] ?? "");
    bindings.push({
      key,
      condition: typeof value.user === "object" ? String(value.user.condition ?? "") : "",
      controlled_property: controlledProperty,
      path: jsonPath(path),
      object_index: objectIndexFromPath(path),
      current_value: value.value ?? null,
    });
  });
  return bindings;
}

function scriptSignals(script) {
  const signals = [];
  const add = (category, signal, confidence = "high") => signals.push({ category, signal, confidence });
  if (/engine\s*\.\s*registerAudioBuffers\s*\(|AUDIO_RESOLUTION_(?:16|32|64)/i.test(script)) {
    add("audio_input", "SCENESCRIPT_AUDIO_BUFFER");
  }
  if (/engine\s*\.\s*timeOfDay\b|\bnew\s+Date\s*\(|\bDate\s*\.\s*now\s*\(/i.test(script)) {
    add("wall_clock", "SCENESCRIPT_REAL_TIME");
  }
  if (/engine\s*\.\s*runtime\b/i.test(script)) add("runtime_state", "SCENESCRIPT_RUNTIME");
  if (/\bMath\s*\.\s*random\s*\(|\brandom\s*\(/i.test(script)) add("random_state", "SCENESCRIPT_RANDOM", "medium");
  if (/export\s+function\s+cursor(?:Enter|Leave|Move|Down|Up|Click)\s*\(|(?:input|engine)\s*\.\s*cursor/i.test(script)) {
    add("mouse_input", "SCENESCRIPT_CURSOR_EVENT");
  }
  return signals;
}

function collectScriptDependencies(scene) {
  const dependencies = [];
  walk(scene, (value, path) => {
    if (typeof value !== "string" || String(path[path.length - 1]) !== "script") return;
    const signals = scriptSignals(value);
    for (const signal of signals) {
      dependencies.push({
        ...signal,
        source: "scene_script",
        path: jsonPath(path),
        object_index: objectIndexFromPath(path),
        excerpt: value.match(/.{0,45}(?:registerAudioBuffers|timeOfDay|new\s+Date|Date\.now|engine\.runtime|Math\.random|cursor(?:Enter|Leave|Move|Down|Up|Click)).{0,80}/is)?.[0]?.replace(/\s+/g, " ").slice(0, 180) ?? "",
      });
    }
  });
  return dependencies;
}

function collectConfiguredDependencies(scene, project) {
  const dependencies = [];
  const general = scene?.general ?? {};
  if (isTruthy(general.cameraparallax) && Number(primitiveValue(general.cameraparallaxmouseinfluence) ?? 1) !== 0) {
    dependencies.push({
      category: "camera_parallax",
      signal: "CAMERA_PARALLAX_MOUSE_INFLUENCE",
      confidence: "high",
      source: "scene_config",
      path: "$.general.cameraparallax",
      object_index: null,
    });
  }
  if (isTruthy(general.camerashake)) {
    dependencies.push({
      category: "camera_shake",
      signal: "CAMERA_SHAKE_ENABLED",
      confidence: "high",
      source: "scene_config",
      path: "$.general.camerashake",
      object_index: null,
    });
  }

  const supportsAudio = isTruthy(project?.general?.supportsaudioprocessing);
  walk(scene?.objects ?? [], (value, path) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return;
    const descriptor = cleanText(`${value.name ?? ""} ${value.file ?? ""} ${value.effect ?? ""}`);
    if (!descriptor) return;
    if (supportsAudio && /audio|spectrum|visuali[sz]er|音频|可视化/i.test(descriptor)) {
      dependencies.push({
        category: "audio_input",
        signal: "AUDIO_EFFECT_OR_LAYER",
        confidence: "medium",
        source: "scene_structure",
        path: jsonPath(["objects", ...path]),
        object_index: objectIndexFromPath(["objects", ...path]),
        label: descriptor.slice(0, 180),
      });
    }
    const cursorNamedParticle = Boolean(value.particle || value.particles) && /mouse|cursor|鼠标|滑鼠/i.test(descriptor);
    if (cursorNamedParticle || /cursor\s*ripple|mouse\s*particle|cursor\s*particle|x[- ]?ray|鼠标粒子|鼠标拖尾/i.test(descriptor)) {
      dependencies.push({
        category: "mouse_input",
        signal: "INTERACTIVE_EFFECT_OR_LAYER",
        confidence: "medium",
        source: "scene_structure",
        path: jsonPath(["objects", ...path]),
        object_index: objectIndexFromPath(["objects", ...path]),
        label: descriptor.slice(0, 180),
      });
    }
  });
  return dependencies;
}

function offOption(descriptor) {
  const options = Array.isArray(descriptor?.options) ? descriptor.options : [];
  const scored = options.map((option) => {
    const label = cleanText(option?.label).toLowerCase();
    let score = 0;
    if (OFF_WORDS.includes(label)) score = 100;
    else if (OFF_WORDS.some((word) => label === `${word}.` || label.startsWith(`${word} `) || label.endsWith(` ${word}`))) score = 80;
    else if (/关闭|禁用|停用|\boff\b|\bnone\b|\bdisabled?\b/i.test(label)) score = 60;
    return { option, score };
  }).filter((item) => item.score > 0).sort((a, b) => b.score - a.score);
  return scored[0]?.option ?? null;
}

function semanticCategories(key, descriptor) {
  const text = cleanText(`${key} ${descriptor?.text ?? descriptor?.label ?? ""}`);
  const categories = [];
  for (const [category, patterns] of Object.entries(SEMANTIC_PATTERNS)) {
    if (patterns.some((pattern) => pattern.test(text))) categories.push(category);
  }
  return categories;
}

function overrideForDescriptor(key, descriptor, reason, confidence, controlledProperty = "") {
  const type = String(descriptor?.type ?? "").toLowerCase();
  if (type === "bool") {
    return { key, value: false, value_type: "bool", confidence, reason, controlled_property: controlledProperty };
  }
  if (type === "combo") {
    const option = offOption(descriptor);
    if (option) {
      return {
        key,
        value: option.value,
        value_type: "combo",
        confidence,
        reason,
        controlled_property: controlledProperty,
        selected_label: cleanText(option.label),
      };
    }
    return null;
  }
  if (type === "slider" && ["volume", "count", "strength", "amount", "influence", "rate"].includes(controlledProperty.toLowerCase())) {
    const min = Number(descriptor?.min ?? 0);
    const max = Number(descriptor?.max ?? 0);
    if (Number.isFinite(min) && Number.isFinite(max) && min <= 0 && max >= 0) {
      return { key, value: 0, value_type: "slider", confidence, reason, controlled_property: controlledProperty };
    }
  }
  return null;
}

function mergeOverrides(overrides) {
  const byKey = new Map();
  const conflicts = [];
  for (const override of overrides) {
    const previous = byKey.get(override.key);
    if (!previous) {
      byKey.set(override.key, { ...override, reasons: [override.reason] });
      continue;
    }
    if (JSON.stringify(previous.value) !== JSON.stringify(override.value)) {
      conflicts.push({ key: override.key, values: [previous.value, override.value], reasons: [...previous.reasons, override.reason] });
      byKey.delete(override.key);
      continue;
    }
    previous.reasons.push(override.reason);
    if (previous.confidence === "medium" && override.confidence === "high") previous.confidence = "high";
  }
  return { overrides: [...byKey.values()].map(({ reason, ...item }) => item), conflicts };
}

function dependencyKey(item) {
  return `${item.category}|${item.signal}|${item.path}|${item.object_index ?? ""}`;
}

function dedupeDependencies(items) {
  const seen = new Set();
  return items.filter((item) => {
    const key = dependencyKey(item);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function analyzeSceneLoopDependencies({ workshopId, project, scene, sourceHashes = {} }) {
  if (!project || typeof project !== "object") throw new TypeError("project must be an object");
  if (!scene || typeof scene !== "object") throw new TypeError("scene must be an object");

  const descriptors = projectProperties(project);
  const bindings = collectBindings(scene);
  const dependencies = dedupeDependencies([
    ...collectScriptDependencies(scene),
    ...collectConfiguredDependencies(scene, project),
  ]);
  const proposed = [];
  const dependencyControls = [];

  for (const dependency of dependencies) {
    const localBindings = bindings.filter((binding) =>
      binding.object_index === dependency.object_index &&
      ["visible", "enabled", "active", "volume", "count", "strength", "amount", "influence", "rate"].includes(binding.controlled_property.toLowerCase())
    );
    const controls = [];
    for (const binding of localBindings) {
      const descriptor = descriptors[binding.key];
      if (!descriptor) continue;
      const candidate = overrideForDescriptor(
        binding.key,
        descriptor,
        `${dependency.signal} controlled by ${binding.path}`,
        "high",
        binding.controlled_property,
      );
      if (candidate) {
        proposed.push(candidate);
        controls.push(candidate.key);
      }
    }
    dependencyControls.push({ dependency: dependencyKey(dependency), controls });
  }

  for (const [key, descriptor] of Object.entries(descriptors)) {
    const categories = semanticCategories(key, descriptor);
    if (!categories.length) continue;
    const relevant = categories.some((category) => dependencies.some((dependency) => dependency.category === category));
    if (!relevant) continue;
    const candidate = overrideForDescriptor(key, descriptor, `semantic author option for ${categories.join(",")}`, "medium");
    if (candidate) proposed.push(candidate);
  }

  const { overrides, conflicts } = mergeOverrides(proposed);
  const safeOverrides = overrides.filter((item) => item.confidence === "high");
  const suggestedOverrides = overrides.filter((item) => item.confidence !== "high");
  const sceneOverrides = {};
  if (dependencies.some((item) => item.category === "camera_parallax")) {
    sceneOverrides.cameraparallax = false;
    sceneOverrides.cameraparallaxmouseinfluence = 0;
  }
  if (dependencies.some((item) => item.category === "camera_shake")) sceneOverrides.camerashake = false;

  const coveredDependencyKeys = new Set();
  const categoryWideControls = new Set();
  for (const control of dependencyControls) {
    if (!control.controls.length) continue;
    coveredDependencyKeys.add(control.dependency);
  }
  if (Object.prototype.hasOwnProperty.call(sceneOverrides, "cameraparallax")) categoryWideControls.add("camera_parallax");
  if (Object.prototype.hasOwnProperty.call(sceneOverrides, "camerashake")) categoryWideControls.add("camera_shake");
  for (const override of suggestedOverrides) {
    for (const category of semanticCategories(override.key, descriptors[override.key])) categoryWideControls.add(category);
  }

  const unresolved = dependencies.filter((dependency) =>
    !coveredDependencyKeys.has(dependencyKey(dependency)) && !categoryWideControls.has(dependency.category)
  ).map((dependency) => ({
    category: dependency.category,
    signal: dependency.signal,
    path: dependency.path,
    reason: "No safe author control or supported scene override was found.",
  }));

  let decision = "NO_EXTERNAL_DEPENDENCY";
  if (dependencies.length && unresolved.length === 0 && suggestedOverrides.length === 0 && conflicts.length === 0) decision = "AUTO_SAFE";
  else if (dependencies.length && unresolved.length === 0 && conflicts.length === 0) decision = "AUTO_WITH_LIKELY_OVERRIDES";
  else if (dependencies.length) decision = "REVIEW_REQUIRED";

  return {
    schema_version: RESULT_SCHEMA_VERSION,
    analyzer_version: ANALYZER_VERSION,
    workshopid: String(workshopId ?? ""),
    title: String(project.title ?? ""),
    type: String(project.type ?? ""),
    source_hashes: sourceHashes,
    decision,
    plugin_phase: "PRE_EXPORT_NORMALIZATION",
    dependencies,
    bindings,
    override_plan: {
      auto_apply_user_properties: Object.fromEntries(safeOverrides.map((item) => [item.key, item.value])),
      likely_user_properties: Object.fromEntries(suggestedOverrides.map((item) => [item.key, item.value])),
      scene_settings: sceneOverrides,
      details: overrides,
      conflicts,
    },
    unresolved,
    statistics: {
      dependencies: dependencies.length,
      user_properties: Object.keys(descriptors).length,
      bindings: bindings.length,
      safe_overrides: safeOverrides.length,
      likely_overrides: suggestedOverrides.length,
      unresolved: unresolved.length,
    },
  };
}

export const sceneLoopAnalyzerContract = Object.freeze({
  analyzer_version: ANALYZER_VERSION,
  schema_version: RESULT_SCHEMA_VERSION,
  phase: "PRE_EXPORT_NORMALIZATION",
  prerequisites: ["SCENE_CLASSIFIED_DYNAMIC", "SOURCE_HASHED", "SCENE_JSON_AVAILABLE"],
  next_phase: "MPKG_EXPORT",
});

export function buildSceneLoopExportOverrides(analysis, { includeLikely = false } = {}) {
  if (!analysis || analysis.schema_version !== RESULT_SCHEMA_VERSION) {
    throw new Error(`Unsupported scene loop analysis schema: ${analysis?.schema_version ?? "missing"}`);
  }
  const plan = analysis.override_plan ?? {};
  return {
    user_properties: {
      ...(plan.auto_apply_user_properties ?? {}),
      ...(includeLikely ? (plan.likely_user_properties ?? {}) : {}),
    },
    scene_settings: { ...(plan.scene_settings ?? {}) },
    residual_review_required: analysis.decision === "REVIEW_REQUIRED" || (analysis.unresolved?.length ?? 0) > 0,
  };
}

export function validateSceneLoopAnalysisSource(analysis, currentHashes) {
  const reasons = [];
  if (!analysis || analysis.schema_version !== RESULT_SCHEMA_VERSION) reasons.push("UNSUPPORTED_SCHEMA");
  if (analysis?.plugin_phase !== sceneLoopAnalyzerContract.phase) reasons.push("WRONG_PLUGIN_PHASE");
  for (const key of ["project_json_sha256", "scene_pkg_sha256"]) {
    const expected = String(analysis?.source_hashes?.[key] ?? "").toUpperCase();
    const current = String(currentHashes?.[key] ?? "").toUpperCase();
    if (!expected || !current) reasons.push(`MISSING_${key.toUpperCase()}`);
    else if (expected !== current) reasons.push(`STALE_${key.toUpperCase()}`);
  }
  return { ok: reasons.length === 0, reasons };
}
