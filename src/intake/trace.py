"""Replay traces for the static viewer (M5, ADR-0004 draft).

`intake trace` runs a few showcase prescriptions through the same steps as `intake run`
(pass 1 -> extract -> pass 2 -> match -> explain) and writes one JSON file per scenario,
split by stage, for `viewer/`. It is for display only:

- It never writes the audit log and never builds a ReviewAction. Review actions in the
  viewer are simulated in the browser and saved nowhere.
- Output is deterministic in REPLAY (fixed `created_at`, sorted keys), so a test can
  regenerate the traces and fail if the committed copies drift from the pipeline.
- Per-stage flags are read back from the final proposal by `source_pass` and rule prefix;
  the test checks that the stage lists add up to `proposal.flags`, in order.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from intake.adapters.anthropic_client import REPO_ROOT
from intake.cli import DEMO_CASES, demo_case_text, load_demo_cases
from intake.explain import add_reasons
from intake.extract import CompletionClient
from intake.models import Flag, Proposal, ProposalStatus
from intake.pipeline import Library, build_proposal, load_library
from intake.review import REASON_CODES, confirm_blockers, formula_diff, review_flag_ids

TRACE_VERSION = 1
FIXED_CREATED_AT = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
GOLDEN_DIR = REPO_ROOT / "data" / "golden"
VIEWER_TRACES = REPO_ROOT / "viewer" / "traces"
MATCHER_PREFIX = "M-"

# Viewer order. `source` is ("demo", case_id) from data/demo or ("golden", case_id) from data/golden.
SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "clean",
        "label": "Clean",
        "blurb": "A well-formed order. Expect no flags and a clear top match.",
        "source": ("demo", "demo_1_clean"),
    },
    {
        "id": "ambiguous",
        "label": "Ambiguous",
        "blurb": "Two formulas score close together. Expect an M-01 REVIEW flag that needs acknowledging.",
        "source": ("golden", "g027"),
    },
    {
        "id": "unsafe",
        "label": "Unsafe",
        "blurb": "A strength above the illustrative maximum. Expect a BLOCK flag and CONFIRM disabled.",
        "source": ("demo", "demo_2_unsafe"),
    },
    {
        "id": "adversarial",
        "label": "Adversarial",
        "blurb": "The text tries to instruct the system. Expect a BLOCK from the rules, whatever the model does.",
        "source": ("demo", "demo_3_injection"),
    },
]


def _golden_case(case_id: str, directory: Path = GOLDEN_DIR) -> dict[str, Any]:
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line)["case_id"] == case_id:
                return json.loads(line)
    raise KeyError(f"golden case {case_id} not found")


def scenario_input(scenario: dict[str, Any], demo_path: Path = DEMO_CASES) -> tuple[dict[str, Any], str]:
    """The case record and the exact text its recordings were made with."""
    kind, case_id = scenario["source"]
    if kind == "golden":
        case = _golden_case(case_id)
        return case, case["raw"]["text"]  # eval feeds raw.text
    case = next(c for c in load_demo_cases(demo_path) if c["case_id"] == case_id)
    return case, demo_case_text(case)  # intake demo feeds the sample file bytes


def _flags(flags: list[Flag]) -> list[dict[str, Any]]:
    return [f.model_dump(mode="json") for f in flags]


def split_flags(proposal: Proposal) -> dict[str, list[Flag]]:
    """Flags by the stage that added them. Display only; the proposal's list is unchanged."""
    return {
        "pass1": [f for f in proposal.flags if f.source_pass == 1],
        "pass2": [f for f in proposal.flags if f.source_pass == 2 and not f.rule_id.startswith(MATCHER_PREFIX)],
        "match": [f for f in proposal.flags if f.source_pass == 2 and f.rule_id.startswith(MATCHER_PREFIX)],
    }


def build_trace(
    scenario: dict[str, Any], case: dict[str, Any], text: str, proposal: Proposal, library: Library
) -> dict[str, Any]:
    names = {f.formula_id: f for f in library.formulas}
    by_stage = split_flags(proposal)
    extract_prompts = {k: v for k, v in proposal.prompt_versions.items() if k.startswith("extract")}
    explain_prompts = {k: v for k, v in proposal.prompt_versions.items() if k.startswith("explain")}
    manual = proposal.status is ProposalStatus.MANUAL
    candidates = [
        {
            **c.model_dump(mode="json"),
            "name": names[c.formula_id].name,
            "diff": [
                row.model_dump() for row in formula_diff(proposal.extraction, names[c.formula_id], library.aliases)
            ],
        }
        for c in proposal.candidates
    ]
    raw = case["raw"]
    return {
        "trace_version": TRACE_VERSION,
        "generated_by": "intake trace",
        "mode": "REPLAY",
        "illustrative": True,
        "scenario": {
            "id": scenario["id"],
            "label": scenario["label"],
            "blurb": scenario["blurb"],
            "source_case": case["case_id"],
            "category": case["category"],
        },
        "raw": {
            "id": raw["id"],
            "source": raw["source"],
            "received_at": raw["received_at"],
            "text": text.rstrip("\n"),
            "input_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        },
        "stages": {
            "pass1": {"flags": _flags(by_stage["pass1"]), "rules_version": proposal.rules_version},
            "extract": {
                "status": "MANUAL" if manual else "OK",
                "extraction": proposal.extraction.model_dump(mode="json") if proposal.extraction else None,
                "model_id": proposal.model_id,
                "prompt_versions": extract_prompts,
            },
            "pass2": {"flags": _flags(by_stage["pass2"]), "skipped": manual},
            "match": {
                "skipped": manual,
                "candidates": candidates,
                "confidence": proposal.confidence,
                "margin": proposal.margin,
                "status": proposal.status.value,
                "flags": _flags(by_stage["match"]),
                "weights": library.thresholds.weights,
                "T_match": library.thresholds.T_match,
                "T_margin": library.thresholds.T_margin,
            },
            "explain": {"reasons": proposal.reasons, "prompt_versions": explain_prompts},
        },
        "proposal": {
            "status": proposal.status.value,
            "flags": _flags(proposal.flags),
            "confidence": proposal.confidence,
            "margin": proposal.margin,
            "model_id": proposal.model_id,
            "prompt_versions": proposal.prompt_versions,
            "rules_version": proposal.rules_version,
            "library_version": proposal.library_version,
        },
        "review": {
            "confirm_blockers": confirm_blockers(proposal, []),
            "blockers_after_ack": confirm_blockers(proposal, review_flag_ids(proposal)),
            "review_flag_ids": review_flag_ids(proposal),
            "reason_codes": {
                action.value: sorted(code.value for code in codes) for action, codes in REASON_CODES.items()
            },
        },
    }


def trace_scenario(scenario: dict[str, Any], *, client: CompletionClient, library: Library) -> dict[str, Any]:
    case, text = scenario_input(scenario)
    proposal = build_proposal(text, case["case_id"], client=client, library=library, now=FIXED_CREATED_AT)
    proposal = add_reasons(proposal, client=client)
    return build_trace(scenario, case, text, proposal, library)


def dumps(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render_all(*, client: CompletionClient) -> dict[str, str]:
    """File name -> content for every scenario plus `index.json`. Nothing is written."""
    library = load_library()
    files: dict[str, str] = {}
    index = []
    for scenario in SCENARIOS:
        name = f"{scenario['id']}.json"
        files[name] = dumps(trace_scenario(scenario, client=client, library=library))
        index.append({"id": scenario["id"], "label": scenario["label"], "file": name})
    files["index.json"] = dumps({"trace_version": TRACE_VERSION, "mode": "REPLAY", "scenarios": index})
    return files


def write_all(out_dir: Path, *, client: CompletionClient) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in render_all(client=client).items():
        path = out_dir / name
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written
