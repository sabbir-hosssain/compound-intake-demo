"""Record explain_v1 replies for a case set (S3.3). Never run in CI.

    INTAKE_MODE is ignored: extraction always REPLAYs its existing recordings, and only the explain
    call goes to the model (RECORD). Cases whose explain recording already exists are skipped, so a
    re-run spends calls only on what is missing.

    python -m eval.record_explanations [--cases FILE] [--limit N] [--max-calls N]

The SDK client is built with `max_retries=0` and every attempt goes through `CountingClient`, so the
printed call count is exact.
"""

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from eval.run_eval import GOLDEN_CASES, case_text, load_cases
from eval.variance import CountingClient
from intake.adapters.anthropic_client import Mode, ModelClient
from intake.adapters.cassette import recording_key
from intake.explain import ExplainSource, explain, explain_input, load_prompt
from intake.pipeline import build_proposal, load_library

NOW = datetime(2026, 11, 26, tzinfo=UTC)  # not part of the explain input; fixed for reproducibility


def _record_client() -> ModelClient:
    import anthropic

    client = ModelClient(mode=Mode.RECORD)
    client._live = anthropic.Anthropic(max_retries=0)  # same reach as eval.variance.live_model_client
    return client


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.record_explanations")
    parser.add_argument("--cases", type=Path, default=GOLDEN_CASES)
    parser.add_argument("--limit", type=int, default=None, help="Only the first N cases.")
    parser.add_argument("--max-calls", type=int, default=80)
    args = parser.parse_args(argv)

    replay = ModelClient(mode=Mode.REPLAY)
    recorder = _record_client()
    counted = CountingClient(recorder, retry_budget=3, max_calls=args.max_calls)
    library = load_library()
    prompt = load_prompt()
    fallbacks = 0
    for case in load_cases(args.cases)[: args.limit]:
        proposal = build_proposal(case_text(case), case.case_id, client=replay, library=library, now=NOW)
        key = recording_key(recorder.config.model_id, prompt.sha256, explain_input(proposal))
        if recorder.cassette.path_for(key).is_file():
            print(f"skip   {case.case_id} (recorded)")
            continue
        result = explain(proposal, client=counted, prompt=prompt)
        fallbacks += result.source is ExplainSource.FALLBACK
        print(f"record {case.case_id} {result.source.value} missing={result.missing}")
    print(f"live calls: {counted.count.calls} (transient retries: {counted.count.retries}); fallbacks: {fallbacks}")
    return 1 if fallbacks else 0


if __name__ == "__main__":
    sys.exit(main())
