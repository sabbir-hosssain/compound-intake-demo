"""S2.8 threshold tuning: grid search over T_match and T_margin on the dev split only (REPLAY)."""

import hashlib
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:  # `eval/` is a top-level package next to `src/`, run with `python -m`
    sys.path.insert(0, str(REPO))

from eval import run_eval, tune
from intake import pipeline
from intake.adapters import anthropic_client
from intake.adapters.anthropic_client import Mode, ModelClient
from intake.pipeline import load_library

GOLDEN = REPO / "data" / "golden" / "golden_cases.jsonl"
THRESHOLDS = REPO / "eval" / "thresholds.yaml"
PROPOSED = REPO / "eval" / "thresholds.proposed.yaml"


@pytest.fixture(autouse=True)
def _replay_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test runs in REPLAY, and constructing a live client is a failure."""
    monkeypatch.setenv(anthropic_client.MODE_ENV, "replay")

    def _boom() -> Any:
        raise AssertionError("a live client was constructed in REPLAY")

    monkeypatch.setattr(anthropic_client, "_make_live_client", _boom)


@pytest.fixture(autouse=True)
def _no_audit_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_: Any, **__: Any) -> Any:
        raise AssertionError("tuning touched the audit log")

    monkeypatch.setattr(pipeline.audit, "connect", _boom)
    monkeypatch.setattr(pipeline, "log_pending", _boom)


class SpyClient:
    """A REPLAY client that remembers every input it was asked to complete."""

    def __init__(self) -> None:
        self.inner = ModelClient(mode=Mode.REPLAY)
        self.config = self.inner.config
        self.mode = Mode.REPLAY
        self.inputs: list[str] = []

    def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.inputs.append(kwargs["user_input"])
        return self.inner.complete(**kwargs)


@pytest.fixture(scope="module")
def library() -> pipeline.Library:
    return load_library()


@pytest.fixture(scope="module")
def prepared(library: pipeline.Library) -> list[tune.Prepared]:
    cases = tune.dev_only(run_eval.load_cases(GOLDEN))
    return tune.prepare(cases, client=ModelClient(mode=Mode.REPLAY), library=library)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FullRun(BaseModel):
    out: Path
    exit_code: int
    inputs: list[str]
    thresholds_before: str
    thresholds_after: str


@pytest.fixture(scope="module")
def full_run(tmp_path_factory: pytest.TempPathFactory) -> FullRun:
    """One full `python -m eval.tune` run (REPLAY, spy client), shared by the tests that need it."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv(anthropic_client.MODE_ENV, "replay")
        mp.setattr(anthropic_client, "_make_live_client", lambda: pytest.fail("live client in REPLAY"))
        before = _sha(THRESHOLDS)
        out = tmp_path_factory.mktemp("tune") / "proposed.yaml"
        spy = SpyClient()
        code = tune.main(["--out", str(out)], client=spy)
        return FullRun(
            out=out, exit_code=code, inputs=spy.inputs, thresholds_before=before, thresholds_after=_sha(THRESHOLDS)
        )


# --- AC 1: dev split only ----------------------------------------------------------------------


def test_dev_only_keeps_only_dev_cases() -> None:
    cases = run_eval.load_cases(GOLDEN)
    dev = tune.dev_only(cases)
    assert dev and {c.split for c in dev} == {"dev"}
    assert len(dev) == sum(c.split == "dev" for c in cases)
    assert any(c.split == "test" for c in cases)  # the filter has something to exclude


def test_prepare_refuses_a_non_dev_case(library: pipeline.Library) -> None:
    test_case = next(c for c in run_eval.load_cases(GOLDEN) if c.split == "test")
    with pytest.raises(ValueError, match="dev"):
        tune.prepare([test_case], client=SpyClient(), library=library)


def test_tuning_never_reads_a_test_split_case(full_run: FullRun) -> None:
    """The full tuning run requests every dev case's text and no test case's text from the model client."""
    cases = run_eval.load_cases(GOLDEN)
    assert full_run.exit_code == 0
    requested = "\n".join(full_run.inputs)
    for case in cases:
        text = run_eval.case_text(case)
        if case.split == "dev":
            assert text in requested, case.case_id
        else:
            assert text not in requested, f"test-split case {case.case_id} was sent to the model client"


def test_proposal_reports_no_test_split_metrics(full_run: FullRun) -> None:
    text = full_run.out.read_text(encoding="utf-8")
    assert "split:test" not in text
    doc = yaml.safe_load(text)
    assert doc["cases"]["split"] == "dev"
    test_ids = {c.case_id for c in run_eval.load_cases(GOLDEN) if c.split == "test"}
    assert not test_ids & set(doc["cases"]["ids"])


# --- AC 2: writes the proposal, never thresholds.yaml ------------------------------------------


def test_main_writes_proposal_and_leaves_thresholds_yaml_unchanged(full_run: FullRun) -> None:
    assert full_run.exit_code == 0
    assert full_run.out.exists()
    assert full_run.thresholds_after == full_run.thresholds_before


def test_writer_refuses_thresholds_yaml() -> None:
    before = _sha(THRESHOLDS)
    with pytest.raises(ValueError, match="thresholds.yaml"):
        tune.write_proposal({"x": 1}, THRESHOLDS)
    assert _sha(THRESHOLDS) == before


def test_main_refuses_thresholds_yaml_as_output() -> None:
    before = _sha(THRESHOLDS)
    assert tune.main(["--out", str(THRESHOLDS)], client=SpyClient()) == 1
    assert _sha(THRESHOLDS) == before


def test_committed_proposal_is_reproduced(full_run: FullRun) -> None:
    """eval/thresholds.proposed.yaml is exactly what `python -m eval.tune` generates from the recordings."""
    assert full_run.out.read_text(encoding="utf-8") == PROPOSED.read_text(encoding="utf-8")


def test_committed_proposal_contents() -> None:
    doc = yaml.safe_load(PROPOSED.read_text(encoding="utf-8"))
    current = yaml.safe_load(THRESHOLDS.read_text(encoding="utf-8"))
    assert doc["current"] == {"T_match": current["T_match"], "T_margin": current["T_margin"]}
    assert set(doc["proposed"]) == {"T_match", "T_margin"}
    for point in ("current", "proposed"):
        metrics = doc["dev_metrics"][point]
        assert all(g["passed"] for g in metrics["hard_gates"].values())
        assert {"system", "baseline"} <= set(metrics)
    assert doc["objective"] and doc["selection"] and doc["grid"]


# --- the search only varies T_match and T_margin -----------------------------------------------


@pytest.mark.parametrize(("t_match", "t_margin"), [(0.60, 0.10), (0.50, 0.05), (0.75, 0.20), (0.30, 0.0)])
def test_grid_point_equals_the_pipeline_at_those_thresholds(
    prepared: list[tune.Prepared], library: pipeline.Library, t_match: float, t_margin: float
) -> None:
    """Re-matching the recorded extraction gives exactly what `build_proposal` gives at those thresholds."""
    at = tune.library_at(library, t_match, t_margin)
    assert at.thresholds.weights == library.thresholds.weights
    assert at.thresholds.strength_tolerance == library.thresholds.strength_tolerance
    client = ModelClient(mode=Mode.REPLAY)
    for prep in prepared:
        expected = run_eval.run_case(prep.case, client=client, library=at).outcome()
        assert tune.result_at(prep, at).outcome() == expected, prep.case.case_id


def test_flags_are_only_added(prepared: list[tune.Prepared], library: pipeline.Library) -> None:
    for prep in prepared:
        base = prep.base.flag_ids
        got = tune.result_at(prep, tune.library_at(library, 0.6, 0.3)).flag_ids
        assert got[: len(base)] == base


def test_every_dev_case_has_a_recording(prepared: list[tune.Prepared]) -> None:
    assert prepared and all(not p.base.missing_recording for p in prepared)


# --- objective and selection -------------------------------------------------------------------


def _score(i: int, j: int, key: tuple[int, int, float], gates: bool = True) -> tune.PointScore:
    return tune.PointScore(
        i=i,
        j=j,
        T_match=tune.T_MATCH_GRID[i],
        T_margin=tune.T_MARGIN_GRID[j],
        gates_passed=gates,
        robust_correct=key[0],
        correct=key[0],
        wrong_proposals=-key[1],
        m01_tp=0,
        m01_pos=0,
        m01_fp=0,
        m01_neg=0,
        j_stat=key[2],
    )


def _scores(best: set[tuple[int, int]], gated_out: set[tuple[int, int]] = frozenset()) -> list[tune.PointScore]:
    return [
        _score(i, j, (2, 0, 0.0) if (i, j) in best else (1, 0, 0.0), gates=(i, j) not in gated_out)
        for i in range(len(tune.T_MATCH_GRID))
        for j in range(len(tune.T_MARGIN_GRID))
    ]


def test_select_picks_the_centre_of_the_optimal_plateau() -> None:
    best = {(i, j) for i in range(10, 21) for j in range(2, 9)}  # 11 x 7 block
    chosen = tune.select(_scores(best), current=(0.60, 0.10))
    assert (chosen.i, chosen.j) == (15, 5)


def test_select_prefers_a_wide_plateau_over_a_sharp_one() -> None:
    best = {(3, 3)} | {(i, j) for i in range(30, 37) for j in range(10, 17)}
    chosen = tune.select(_scores(best), current=(tune.T_MATCH_GRID[3], tune.T_MARGIN_GRID[3]))
    assert (chosen.i, chosen.j) == (33, 13)


def test_select_breaks_ties_towards_current_values() -> None:
    best = {(5, 5), (40, 5)}  # two single points, equally sharp
    chosen = tune.select(_scores(best), current=(tune.T_MATCH_GRID[38], tune.T_MARGIN_GRID[5]))
    assert (chosen.i, chosen.j) == (40, 5)


def test_select_never_picks_a_point_that_fails_a_hard_gate() -> None:
    best = {(i, j) for i in range(10, 21) for j in range(2, 9)}
    chosen = tune.select(_scores(best, gated_out=best), current=(0.60, 0.10))
    assert (chosen.i, chosen.j) not in best
    assert chosen.gates_passed


def test_select_needs_a_feasible_point() -> None:
    every = {(i, j) for i in range(len(tune.T_MATCH_GRID)) for j in range(len(tune.T_MARGIN_GRID))}
    with pytest.raises(ValueError, match="hard gate"):
        tune.select(_scores(set(), gated_out=every), current=(0.60, 0.10))


def test_objective_orders_robust_correct_then_wrong_proposals_then_m01() -> None:
    a = _score(0, 0, (30, -2, 0.1))
    b = _score(0, 0, (30, -3, 0.9))
    c = _score(0, 0, (31, -9, -1.0))
    assert c.key > a.key > b.key


def test_tie_at_the_top_is_not_a_robust_decision(prepared: list[tune.Prepared], library: pipeline.Library) -> None:
    """A PROPOSED top-1 that ties with the runner-up is decided by formula_id order, so it never counts."""
    at = tune.library_at(library, 0.30, 0.10)
    tied = [p for p in prepared if tune.top_tied(tune.result_at(p, at))]
    assert tied  # the dev set has near-twin ties
    score = tune.score_point(prepared, at, 0, 0)
    assert score.robust_correct <= score.correct - sum(
        tune.result_at(p, at).top1_ok for p in tied if p.case.gold_formula != run_eval.NO_MATCH
    )


def test_grids_cover_the_spec_start_values() -> None:
    assert 0.60 in tune.T_MATCH_GRID and 0.10 in tune.T_MARGIN_GRID
    assert tune.T_MATCH_GRID == sorted(tune.T_MATCH_GRID)
    assert tune.T_MARGIN_GRID[0] == 0.0
