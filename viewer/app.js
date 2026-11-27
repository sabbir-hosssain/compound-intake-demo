// compound-intake-demo replay viewer.
// Plays back traces exported by `intake trace` (REPLAY recordings). Nothing here calls a model
// or a server, and review actions are simulated in this browser tab only: nothing is saved.
"use strict";

const STAGES = [
  { name: "Intake", kind: "INPUT", file: "RawPrescription" },
  { name: "Rules pass 1", kind: "CODE", file: "rules.py · raw text" },
  { name: "LLM extract", kind: "LLM", file: "extract.py" },
  { name: "Schema validation", kind: "CODE", file: "Extraction (Pydantic)" },
  { name: "Rules pass 2", kind: "CODE", file: "rules.py · fields" },
  { name: "Matcher", kind: "CODE", file: "match.py" },
  { name: "LLM explain", kind: "LLM", file: "explain.py" },
  { name: "Proposal", kind: "CODE", file: "Proposal" },
  { name: "Pharmacist review", kind: "HUMAN", file: "ReviewAction" },
];
const LAST = STAGES.length - 1;
const FLAG_STAGE = { pass1: 1, pass2: 4, match: 5 };
const SKIPPED_ON_MANUAL = new Set([4, 5, 6]);
const GENESIS = "0".repeat(64);
const REVIEWER = "demo-pharmacist";

const state = {
  traces: {}, order: [], sc: null,
  step: -1, view: -1, playing: false, fast: false, timer: null,
  picked: 0, ack: false, action: "", reason: "", done: false,
  chain: [],
  seen: new Set(), lastView: null, // animate only what is new since the last render
};

const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const num = (v, d = 2) => (typeof v === "number" ? v.toFixed(d) : "—");
const short = (h, n = 12) => (h ? `${h.slice(0, n)}…` : "—");
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
const t = () => state.traces[state.sc];
const isManual = () => t().stages.extract.status === "MANUAL";

// --- derived -------------------------------------------------------------------------------------

function flagsWithStage(trace) {
  const out = [];
  for (const [key, at] of Object.entries(FLAG_STAGE)) {
    for (const f of trace.stages[key].flags) out.push({ ...f, at });
  }
  return out;
}
const hasSeverity = (trace, sev) => trace.proposal.flags.some((f) => f.severity === sev);

function visibleFlags() {
  return flagsWithStage(t())
    .filter((f) => f.at <= state.step)
    .sort((a, b) => (a.severity === "BLOCK" ? 0 : 1) - (b.severity === "BLOCK" ? 0 : 1));
}

function isNew(key) {
  if (state.seen.has(key)) return false;
  state.seen.add(key);
  return true;
}

function blockersNow() {
  const r = t().review;
  return state.ack ? r.blockers_after_ack : r.confirm_blockers;
}

// --- playback ------------------------------------------------------------------------------------

function schedule() {
  clearTimeout(state.timer);
  state.timer = setTimeout(tick, state.fast ? 650 : 1300);
}
function tick() {
  if (!state.playing || state.step >= LAST) { state.playing = false; render(); return; }
  state.step += 1;
  state.view = state.step;
  state.playing = state.step < LAST;
  render();
  if (state.playing) schedule();
}
function resetReview() {
  Object.assign(state, { picked: 0, ack: false, action: "", reason: "", done: false, lastView: null });
  for (const key of [...state.seen]) if (key.startsWith("flag:")) state.seen.delete(key);
}
function run() {
  clearTimeout(state.timer);
  resetReview();
  Object.assign(state, { step: 0, view: 0, playing: true });
  render();
  schedule();
}
function selectScenario(id) {
  clearTimeout(state.timer);
  resetReview();
  Object.assign(state, { sc: id, step: -1, view: -1, playing: false });
  history.replaceState(null, "", `#${id}`);
  render();
}

// --- simulated audit -----------------------------------------------------------------------------

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}
async function sha256(text) {
  if (!window.crypto || !crypto.subtle) return null;
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
async function record() {
  const trace = t();
  const cand = trace.stages.match.candidates[state.picked];
  const prev = state.chain.length ? state.chain[state.chain.length - 1].hash : GENESIS;
  const rec = {
    seq: state.chain.length + 1,
    prescription_id: trace.scenario.source_case,
    input_hash: trace.raw.input_hash,
    action: state.action,
    chosen_formula_id: state.action === "CLARIFY" ? null : cand ? cand.formula_id : null,
    reason_code: state.reason,
    reviewer: REVIEWER,
    acknowledged_flags: state.action === "CONFIRM" ? trace.review.review_flag_ids : [],
    at: new Date().toISOString(),
  };
  const hash = (await sha256(prev + canonical(rec))) || "unavailable (needs https or localhost)";
  state.chain.push({ ...rec, prev_hash: prev, hash });
  state.done = true;
  render();
}

// --- stage details -------------------------------------------------------------------------------

function kv(rows) {
  return `<div class="kv">${rows.map(([k, v, opts = {}]) => {
    const bar = opts.bar != null ? `<span class="bar" aria-hidden="true"><i data-w="${esc(opts.bar)}"></i></span>` : "";
    return `<div><span class="k">${esc(k)}</span><span class="v">${bar}<span class="${opts.mono === false ? "" : "mono"}" style="font-size:13px">${esc(v)}</span></span></div>`;
  }).join("")}</div>`;
}
const flagIds = (flags) => (flags.length ? flags.map((f) => `${f.rule_id} (${f.severity})`).join(", ") : "none");
const strength = (i) => (i.strength == null ? "no strength" : `${i.strength}${i.unit ? ` ${i.unit}` : " (no unit)"}`);

function stageDetail(i) {
  const tr = t();
  const s = tr.stages;
  const manual = isManual();
  if (manual && SKIPPED_ON_MANUAL.has(i)) {
    return { title: `${STAGES[i].name} skipped`, summary: "Extraction failed schema validation, so the proposal is MANUAL. There are no candidates; the pharmacist works it by hand.", body: "" };
  }
  switch (i) {
    case 0:
      return {
        title: "Prescription received",
        summary: "Free text arrives in the intake queue. Nothing has been interpreted yet.",
        body: `<pre class="rx">${esc(tr.raw.text)}</pre>${kv([["Source", tr.raw.source], ["Received", tr.raw.received_at], ["Input hash (sha256)", short(tr.raw.input_hash, 16)]])}`,
      };
    case 1:
      return {
        title: "Rules pass 1 on the raw text",
        summary: s.pass1.flags.length ? `Deterministic rules fired before the model saw anything: ${flagIds(s.pass1.flags)}.` : "No pass-1 rule fired.",
        body: kv([["Rules checked", "R1-01 … R1-05"], ["Flags added", String(s.pass1.flags.length)], ["Rules version", s.pass1.rules_version]]),
        note: "Runs on the raw text, so an instruction hidden in the prescription is flagged whatever the model later does.",
      };
    case 2: {
      const e = s.extract.extraction || {};
      const rows = (e.ingredients || []).map((ing, n) => [`Ingredient ${n + 1}`, `${ing.name} · ${strength(ing)}`]);
      rows.push(
        ["Dosage form", e.dosage_form ?? "—"], ["Base", e.base ?? "—"], ["Route", e.route ?? "—"],
        ["Quantity", e.quantity == null ? "—" : `${e.quantity} ${e.quantity_unit ?? ""}`.trim()],
        ["Directions", e.directions ?? "—", { mono: false }],
        ["Prescriber / patient", `${e.prescriber_name ?? "—"} / ${e.patient_ref ?? "—"}`],
      );
      if (e.extraction_notes) rows.push(["Model notes", e.extraction_notes, { mono: false }]);
      const prompts = Object.entries(s.extract.prompt_versions).map(([k, v]) => `${k} ${short(v, 8)}`).join(" · ");
      rows.push(["Model · prompt", `${s.extract.model_id} · ${prompts}`]);
      return {
        title: "The model extracts fields to a schema",
        summary: "The LLM reads the prescription as data (wrapped and escaped, never as instructions) and fills the Extraction schema through a strict tool call.",
        body: kv(rows),
        note: "extract.py cannot import the audit module or any commit function. An architecture test enforces this.",
      };
    }
    case 3:
      return {
        title: "Schema validation",
        summary: "The extraction is validated against the Pydantic model. If it fails twice, the proposal is MANUAL with no candidates.",
        body: kv([["Schema", "Extraction"], ["Result", manual ? "invalid → MANUAL" : "valid"]]),
      };
    case 4:
      return {
        title: "Rules pass 2 on the extracted fields",
        summary: s.pass2.flags.length ? `Fields checked against the ingredient master and library: ${flagIds(s.pass2.flags)}.` : "No pass-2 rule fired.",
        body: kv([["Rules checked", "R2-01 … R2-07"], ["Flags added", String(s.pass2.flags.length)], ["Flags so far", String(s.pass1.flags.length + s.pass2.flags.length)]]),
        note: "Flags are a union of pass 1 and pass 2. The model may add a flag but can never clear one.",
      };
    case 5: {
      const m = s.match;
      const w = m.weights;
      const rows = m.candidates.map((c) => [c.formula_id, num(c.score, 3), { bar: Math.round(c.score * 100) }]);
      rows.push(
        ["Status", m.status],
        ["Confidence", num(m.confidence, 3)],
        ["Margin", `${num(m.margin, 3)} (T_margin ${num(m.T_margin)})`],
        ["T_match", num(m.T_match)],
      );
      return {
        title: "Code scores every formula",
        summary: `Weighted score: ${num(w.ingredients)} ingredients · ${num(w.strength)} strength · ${num(w.dosage_form)} form · ${num(w.base)} base · ${num(w.route)} route.${m.flags.length ? ` Matcher flag: ${flagIds(m.flags)}.` : ""}`,
        body: kv(rows),
        note: "Weights and thresholds live in eval/thresholds.yaml, tuned on the dev split and frozen at Gate 2.",
      };
    }
    case 6:
      return {
        title: "The model explains the ranking",
        summary: "Explanation only: written after scoring, from the scores and flags.",
        body: `<div class="reasons">${esc(s.explain.reasons || "(no explanation recorded)")}</div>${kv([["Prompt", Object.keys(s.explain.prompt_versions).join(", ") || "—"], ["Can change scores or flags?", "No"]])}`,
      };
    case 7: {
      const p = tr.proposal;
      const blocks = p.flags.filter((f) => f.severity === "BLOCK").length;
      const top = s.match.candidates[0];
      return {
        title: "Proposal assembled",
        summary: "Everything the pharmacist needs, stamped with the versions that produced it.",
        body: kv([
          ["Status", p.status],
          ["Top candidate", top ? `${top.formula_id} · ${num(top.score, 3)}` : "—"],
          ["Flags", `${p.flags.length}${blocks ? ` (${blocks} BLOCK)` : ""}`],
          ["Versions", `rules ${p.rules_version} · library ${p.library_version}`],
        ]),
        note: "There is no code path from this object to a committed record.",
      };
    }
    default:
      return {
        title: "Waiting for the pharmacist",
        summary: "The pipeline stops here. Only a human action creates an audit record.",
        body: kv([["Bulk or auto-confirm", "Not available"]]),
      };
  }
}

// --- rendering -----------------------------------------------------------------------------------

function renderScenarios() {
  $("scenarios").innerHTML = state.order
    .map((id) => `<button type="button" class="pill" data-sc="${esc(id)}" aria-pressed="${id === state.sc}">${esc(state.traces[id].scenario.label)}</button>`)
    .join("");
}

function renderControls() {
  const running = state.step >= 0;
  $("run-label").textContent = running ? "Run again" : "Run";
  $("pause").disabled = !running || state.step >= LAST;
  $("pause").textContent = state.playing || !running || state.step >= LAST ? "Pause" : "Resume";
  $("step").disabled = state.step >= LAST;
  $("speed").textContent = state.fast ? "2×" : "1×";
  $("progress").textContent = `${state.step + 1} / ${STAGES.length}`;
}

function renderTimeline() {
  const added = {};
  for (const f of flagsWithStage(t())) (added[f.at] ||= []).push(f);
  $("timeline").innerHTML = STAGES.map((st, i) => {
    const locked = i > state.step;
    const active = i === state.step && state.playing;
    const flags = added[i] || [];
    let status = "Done";
    let dot = "done";
    if (locked) { status = "Pending"; dot = ""; }
    else if (active) { status = "Running…"; dot = "active"; }
    else if (i === LAST) { status = state.done ? "Action recorded (simulated)" : "Awaiting action"; dot = state.done ? "done" : "active"; }
    else if (isManual() && SKIPPED_ON_MANUAL.has(i)) status = "Skipped (MANUAL)";
    else if (flags.length) {
      status = `+${plural(flags.length, "flag")}`;
      dot = flags.some((f) => f.severity === "BLOCK") ? "block" : "review";
    }
    return `<li><button type="button" class="stage${i === state.view ? " viewing" : ""}" data-stage="${i}" ${locked ? "disabled" : ""} aria-current="${i === state.view ? "step" : "false"}">
      <span class="dot ${dot}" aria-hidden="true"></span>
      <span class="label"><span class="name">${esc(st.name)}</span><span class="status">${esc(status)}</span></span>
      <span class="kind ${st.kind}">${st.kind}</span></button></li>`;
  }).join("");
}

function renderFlags() {
  const flags = visibleFlags();
  $("flag-count").textContent = plural(flags.length, "flag");
  $("flags").innerHTML = flags.length
    ? flags.map((f) => `<div class="flag ${esc(f.severity)}${isNew(`flag:${state.sc}:${f.rule_id}:${f.at}:${f.message}`) ? " rise" : ""}"><div class="head"><span class="mono" style="font-size:12px;font-weight:500">${esc(f.rule_id)}</span><span class="sev ${esc(f.severity)}">${esc(f.severity)}</span></div>
        <div style="font-size:13px">${esc(f.message)}</div><div style="font-size:11px;opacity:.85">Added by ${esc(STAGES[f.at].name.toLowerCase())}</div></div>`).join("")
    : `<div class="empty">No flags yet</div>`;
}

function renderStage() {
  const panel = $("stage-panel");
  const tr = t();
  if (state.step < 0) {
    panel.innerHTML = `<div class="mono muted" style="font-size:12px">Inbound prescription · ${esc(tr.raw.source)} · case ${esc(tr.scenario.source_case)}</div>
      <pre class="rx">${esc(tr.raw.text)}</pre>
      <p class="muted" style="max-width:600px">${esc(tr.scenario.blurb)}</p>
      <div><button type="button" class="btn primary" data-action="run">Run intake</button></div>`;
    return;
  }
  const i = state.view;
  const d = stageDetail(i);
  panel.innerHTML = `<div style="display:flex;flex-wrap:wrap;justify-content:space-between;gap:10px;align-items:center">
      <span style="display:flex;gap:10px;align-items:center"><span class="mono muted" style="font-size:12px">Stage ${i + 1} of ${STAGES.length}</span><span class="kind ${STAGES[i].kind}">${STAGES[i].kind}</span></span>
      <span class="mono muted" style="font-size:12px">${esc(STAGES[i].file)}</span></div>
    <h2 class="${i !== state.lastView ? "rise" : ""}">${esc(d.title)}</h2>
    <p style="color:var(--ink-2);max-width:760px">${esc(d.summary)}</p>
    ${d.body}
    ${d.note ? `<div class="note">${esc(d.note)}</div>` : ""}`;
  state.lastView = i;
  requestAnimationFrame(() => panel.querySelectorAll(".bar > i").forEach((el) => { el.style.width = `${el.dataset.w}%`; }));
}

function reviewHint(confirmOk, candidates) {
  if (state.done) return "Recorded below (simulated). Run again or pick another scenario to try a different path.";
  if (!state.action) return "Choose an action, then a reason code.";
  if (state.action === "CONFIRM" && !confirmOk) return blockersNow().join(" ") || "CONFIRM accepts the top candidate only; use CORRECT to choose another.";
  if (state.action === "CORRECT" && !candidates.length) return "No candidate to choose.";
  if (!state.reason) return "A reason code is required.";
  return state.action === "CLARIFY" ? "CLARIFY sends it back to the prescriber; no formula is chosen." : `Records ${state.action} on ${candidates[state.picked].formula_id}.`;
}

function renderReview() {
  const panel = $("review-panel");
  panel.hidden = state.step < LAST;
  if (panel.hidden) return;
  const tr = t();
  const cands = tr.stages.match.candidates;
  const block = hasSeverity(tr, "BLOCK");
  const review = tr.review.review_flag_ids.length > 0;
  const confirmOk = blockersNow().length === 0 && state.picked === 0 && cands.length > 0;
  const statusTag = block ? "BLOCK" : review ? "REVIEW" : "";
  const statusText = `${tr.proposal.status}${block ? " · BLOCKED" : review ? " · NEEDS REVIEW" : ""}`;
  const codes = state.action ? tr.review.reason_codes[state.action] : [];
  const valid = state.action && state.reason && !state.done &&
    (state.action !== "CONFIRM" || confirmOk) && (state.action !== "CORRECT" || cands.length > 0);
  const chosen = cands[state.picked];

  panel.innerHTML = `<div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:10px">
      <h2>Pharmacist review</h2><span class="status-tag ${statusTag}">${esc(statusText)}</span></div>
    ${block ? `<div class="banner BLOCK">${esc(tr.review.confirm_blockers[0])}</div>` : ""}
    <div style="display:flex;flex-direction:column;gap:8px">
      <h3 class="eyebrow">Candidates</h3>
      ${cands.length ? `<div class="cands">${cands.map((c, n) => `<button type="button" class="cand" data-pick="${n}" aria-pressed="${n === state.picked}" ${state.done ? "disabled" : ""}>
        <span class="top"><span class="mono muted" style="font-size:12px">${n + 1}. ${esc(c.formula_id)}</span><span class="mono" style="font-size:15px;font-weight:500">${num(c.score, 3)}</span></span>
        <span style="font-weight:600">${esc(c.name)}</span>
        <span class="comp">ing ${num(c.component_scores.ingredients)} · str ${num(c.component_scores.strength)} · form ${num(c.component_scores.dosage_form)} · base ${num(c.component_scores.base)} · route ${num(c.component_scores.route)}</span></button>`).join("")}</div>`
      : `<div class="empty">No candidates (status ${esc(tr.proposal.status)}).</div>`}
    </div>
    ${chosen ? `<div style="display:flex;flex-direction:column;gap:8px"><h3 class="eyebrow">Prescription vs. ${esc(chosen.formula_id)}</h3>
      <div class="table-wrap"><table><thead><tr><th scope="col">Field</th><th scope="col">Extracted from Rx</th><th scope="col">Formula</th><th scope="col">Match</th></tr></thead><tbody>
      ${chosen.diff.map((r) => `<tr><td style="font-weight:600">${esc(r.field.replace("_", " "))}</td><td class="mono" style="font-size:12px">${esc(r.prescribed)}</td><td class="mono" style="font-size:12px">${esc(r.formula)}</td><td class="${r.same ? "same" : "diff"}">${r.same ? "Match" : "Differs"}</td></tr>`).join("")}
      </tbody></table></div></div>` : ""}
    <div class="reasons"><strong>Reasons (LLM, explanation only): </strong>${esc(tr.stages.explain.reasons || "(none recorded)")}</div>
    ${review && !block ? `<label class="ack"><input type="checkbox" id="ack" ${state.ack ? "checked" : ""} ${state.done ? "disabled" : ""}><span>I have reviewed the REVIEW flag${tr.review.review_flag_ids.length > 1 ? "s" : ""}: ${esc(tr.review.review_flag_ids.join(", "))}</span></label>` : ""}
    <div class="actions">
      <fieldset><legend>Action</legend>
        ${["CONFIRM", "CORRECT", "CLARIFY"].map((a) => {
          const off = state.done || (a === "CONFIRM" && !confirmOk) || (a === "CORRECT" && !cands.length);
          return `<label class="seg"><input type="radio" name="action" value="${a}" ${state.action === a ? "checked" : ""} ${off ? "disabled" : ""}><span>${a[0]}${a.slice(1).toLowerCase()}</span></label>`;
        }).join("")}
      </fieldset>
      <label class="field">Reason code
        <select id="reason" ${!state.action || state.done ? "disabled" : ""}>
          <option value="">Select a reason…</option>
          ${codes.map((c) => `<option value="${esc(c)}" ${state.reason === c ? "selected" : ""}>${esc(c)}</option>`).join("")}
        </select></label>
      <button type="button" class="btn go" id="record" ${valid ? "" : "disabled"}>Record (simulated)</button>
    </div>
    <div class="hint" id="review-hint">${esc(reviewHint(confirmOk, cands))}</div>`;
}

function renderChain() {
  const panel = $("chain-panel");
  panel.hidden = state.chain.length === 0;
  if (panel.hidden) return;
  panel.innerHTML = `<div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:8px">
      <h2 class="eyebrow">Audit chain (simulated in this tab)</h2><span class="small">Nothing is saved · reload clears it</span></div>
    ${state.chain.slice().reverse().map((b) => `<div class="block-rec${isNew(`block:${b.seq}`) ? " rise" : ""}"><div class="seq">#${b.seq}</div><div style="display:flex;flex-direction:column;gap:4px;min-width:0">
      <div style="color:#fff;font-weight:500">${esc(b.action)}${b.chosen_formula_id ? ` · ${esc(b.chosen_formula_id)}` : ""} · ${esc(b.reason_code)} · ${esc(b.prescription_id)} · ${esc(b.reviewer)}</div>
      <div class="h">prev_hash ${esc(b.prev_hash)}</div><div class="h">record_hash ${esc(b.hash)}</div></div></div>`).join("")}
    <div class="small">record_hash = sha256(prev_hash + canonical JSON of the record), computed in your browser. The real app appends the same kind of record to an append-only SQLite table, and <code>intake audit verify</code> recomputes the chain.</div>`;
}

function render() {
  const focusId = document.activeElement && document.activeElement.id;
  const focusKey = document.activeElement && (document.activeElement.dataset.pick ?? document.activeElement.value);
  renderScenarios();
  renderControls();
  renderTimeline();
  renderFlags();
  renderStage();
  renderReview();
  renderChain();
  if (focusId && $(focusId)) $(focusId).focus();
  else if (focusKey != null) {
    const el = document.querySelector(`[data-pick="${focusKey}"], input[name="action"][value="${focusKey}"]`);
    if (el) el.focus();
  }
}

// --- events --------------------------------------------------------------------------------------

function bind() {
  $("run").addEventListener("click", run);
  $("pause").addEventListener("click", () => {
    state.playing = !state.playing;
    if (state.playing) schedule(); else clearTimeout(state.timer);
    render();
  });
  $("step").addEventListener("click", () => {
    clearTimeout(state.timer);
    state.step = Math.min(LAST, state.step + 1);
    state.view = state.step;
    state.playing = false;
    render();
  });
  $("speed").addEventListener("click", () => { state.fast = !state.fast; render(); });
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-sc],[data-stage],[data-pick],[data-action],#record");
    if (!el || el.disabled) return;
    if (el.dataset.sc) selectScenario(el.dataset.sc);
    else if (el.dataset.stage != null) { state.view = Number(el.dataset.stage); render(); }
    else if (el.dataset.pick != null) {
      state.picked = Number(el.dataset.pick);
      if (state.action === "CONFIRM" && state.picked !== 0) { state.action = ""; state.reason = ""; }
      render();
    } else if (el.dataset.action === "run") run();
    else if (el.id === "record") record();
  });
  document.addEventListener("change", (e) => {
    if (e.target.id === "ack") { state.ack = e.target.checked; if (!state.ack && state.action === "CONFIRM") { state.action = ""; state.reason = ""; } }
    else if (e.target.name === "action") { state.action = e.target.value; state.reason = ""; }
    else if (e.target.id === "reason") state.reason = e.target.value;
    else return;
    render();
  });
}

async function load() {
  try {
    const index = await (await fetch("traces/index.json")).json();
    for (const s of index.scenarios) {
      state.traces[s.id] = await (await fetch(`traces/${s.file}`)).json();
      state.order.push(s.id);
    }
  } catch (err) {
    $("stage-panel").innerHTML = `<h2>Couldn't load the traces</h2><p class="muted">Opened from a file? Browsers block local fetches. Run <code>make viewer</code> and open the printed localhost address.</p>`;
    return;
  }
  const wanted = location.hash.slice(1);
  state.sc = state.order.includes(wanted) ? wanted : state.order[0];
  bind();
  render();
}

load();
