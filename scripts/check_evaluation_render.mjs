// Render actual evaluation cards without launching a browser or sending input.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(root, "frontend/package.json"));
const { build } = await import(pathToFileURL(require.resolve("vite")).href);
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const argument = process.argv.indexOf("--python");
const python = argument >= 0 ? process.argv[argument + 1] : process.env.LOOTWEAVE_PYTHON || "python";
const pythonCode = "import copy, json\nfrom pathlib import Path\nfrom contracts import digest\nfrom services.evaluation.domain import evaluate\nroot = Path.cwd()\nrows = []\nfor version in (\"0.1.0\", \"0.1.1\", \"0.1.2\", \"0.1.3\"):\n    archive = json.loads((root / f\"fixtures/evaluation-{version}.json\").read_text(encoding=\"utf-8\"))\n    for case in archive[\"cases\"]:\n        inputs = case[\"inputs\"]\n        old = {\"evaluation_id\": case[\"evaluation_id\"],\n               **evaluate(inputs[\"profile\"], inputs[\"knowledge\"], inputs[\"intent\"], evaluator_version=version)}\n        assert digest(old) == case[\"result_hash\"], \"historical_result_changed\"\n        rows.append({\"kind\": \"historical\", \"id\": case[\"evaluation_id\"], \"result\": old})\n        if version == \"0.1.3\":\n            # Current fictional checks explicitly confirm empty held inventory; archives stay unchanged.\n            current_inputs = copy.deepcopy(inputs)\n            current_facts = current_inputs[\"profile\"][\"facts\"]\n            current_facts[\"inventory_items\"] = []\n            # Current-engine fictional owners are explicit; the archived inputs remain untouched.\n            actor_sources = [entry for group in (\"skills\", \"talents\", \"paragon\", \"runes\", \"temporary_effects\")\n                             for entry in current_facts[group]]\n            actor_sources.extend(entry for item in [*current_facts[\"equipped_items\"].values(), current_facts[\"candidate_item\"]]\n                                 for entry in item[\"embedded_items\"])\n            companion_sources = [entry for entry in actor_sources if entry.get(\"actor\") == \"companion\"]\n            if companion_sources:\n                owner = {\"id\": \"renderer-companion\", \"actor\": \"companion\", \"effects\": [],\n                         \"evidence_ids\": current_facts[\"evidence_ids\"]}\n                current_facts[\"companions\"].append(owner)\n                for entry in companion_sources:\n                    entry[\"companion_id\"] = owner[\"id\"]\n            current_inputs[\"profile\"][\"facts_hash\"] = digest(current_facts)\n            current = {\"evaluation_id\": \"current-\" + case[\"evaluation_id\"],\n                       **evaluate(current_inputs[\"profile\"], current_inputs[\"knowledge\"], current_inputs[\"intent\"])}\n            expected = case[\"expected_current_result\"]\n            assert current[\"retention\"] == expected[\"retention\"], \"current_retention_mismatch\"\n            assert {key: current[\"comparison\"].get(key) for key in expected[\"comparison\"]} == expected[\"comparison\"], \"current_states_mismatch\"\n            rows.append({\"kind\": \"current\", \"id\": \"current-\" + case[\"evaluation_id\"], \"result\": current})\nprint(json.dumps(rows))\n";
const produced = spawnSync(python, ["-c", pythonCode], {
  cwd: root, windowsHide: true, timeout: 10000, encoding: "utf8",
});
assert.equal(produced.status, 0, "locked_evaluation_results_failed: " + produced.stderr);
const cases = JSON.parse(produced.stdout);
assert.equal(cases.length, 32);
const componentPath = path.join(root, "frontend/src/entities/evaluation/index.tsx");
const source = await readFile(componentPath, "utf8");
const bundled = await build({
  root: path.join(root, "frontend"), configFile: false, logLevel: "silent",
  build: { ssr: componentPath, write: false, minify: false,
    rolldownOptions: { output: { format: "cjs" } } },
});
const chunks = (Array.isArray(bundled) ? bundled : [bundled])
  .flatMap(result => result.output).filter(item => item.type === "chunk");
assert.equal(chunks.length, 1, "unexpected_server_render_bundle");
assert.equal(await readFile(componentPath, "utf8"), source, "component_changed_during_compile");
const module = { exports: {} };
new Function("require", "module", "exports", chunks[0].code)(require, module, module.exports);
const { EvaluationCard } = module.exports;
assert.equal(typeof EvaluationCard, "function");
const output = path.join(root, ".local/evaluation-render", randomUUID());
await mkdir(output, { recursive: true });
const labels = { mana_loop: "法力循环" };
const actors = { hero: "角色", companion: "仆从" };
const states = { active: "已确认生效", inactive: "已确认未生效", unknown: "未知 · 待确认" };
let current = 0, historical = 0, uncertain = 0;
for (const item of cases) {
  const html = renderToStaticMarkup(React.createElement(EvaluationCard, {
    result: item.result, onReplay() {}, replaying: false, replayed: false,
  }));
  const plain = html.replace(/<[^>]*>/g, "");
  assert.ok(plain.includes("评估器 " + item.result.pin.evaluator_version), "rendered_pin_changed");
  const pending = item.result.comparison.uncertain_mechanisms || [];
  assert.equal(plain.includes("机制状态待确认"), pending.length > 0, "unknown_section_mismatch");
  for (const row of pending) {
    const actor = actors[row.actor], capability = labels[row.capability] || row.capability;
    assert.ok(plain.includes(actor + " · " + capability + "：替换前 " + states[row.before] +
      " → 替换后 " + states[row.after]), "uncertain_owner_or_states_missing");
  }
  if (item.id === "current-legacy-active-to-unknown") {
    const loss = html.match(/<div><h3>换装失去<\/h3>(.*?)<\/div>/s)?.[1];
    assert.ok(loss && !loss.includes("法力循环"), "unknown_state_rendered_as_definite_loss");
    assert.ok(!plain.includes("未满足所需机制："), "unknown_requirement_rendered_as_missing");
  }
  if (item.id === "current-legacy-unknown-to-active") {
    const gain = html.match(/<div><h3>换装获得<\/h3>(.*?)<\/div>/s)?.[1];
    assert.ok(gain && !gain.includes("法力循环"), "unknown_prior_state_rendered_as_definite_gain");
  }
  if (item.kind === "historical") {
    historical++;
    assert.ok(!Object.hasOwn(item.result.comparison, "uncertain_mechanisms"));
    if (item.id === "legacy-active-to-unknown")
      assert.ok(plain.includes("未满足所需机制：角色 · 法力循环"), "historical_result_reinterpreted");
  } else {
    current++;
    if (pending.length) uncertain++;
  }
  await writeFile(path.join(output, item.kind + "-" + item.id + ".html"), html, { flag: "wx" });
}
const report = { passed: true, render_cases: cases.length, current_cases: current,
  historical_cases: historical, current_cases_with_uncertainty: uncertain,
  source_sha256: createHash("sha256").update(source).digest("hex"),
  limitations: ["Server-rendered presentation only; no browser interaction, native IPC, game or release acceptance."],
};
await writeFile(path.join(output, "report.json"), JSON.stringify(report, null, 2) + "\n", { flag: "wx" });
console.log(JSON.stringify({ ...report, evidence: path.relative(root, output) }));
