"""S1.1: SPEC §4 data models import with binding names/enum values and round-trip through JSON."""

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ValidationError

from intake.models import (
    AuditRecord,
    Extraction,
    Flag,
    Formula,
    FormulaIngredient,
    Ingredient,
    MatchCandidate,
    Proposal,
    ProposalStatus,
    RawPrescription,
    ReviewAction,
    ReviewActionType,
    Severity,
    Source,
    Unit,
)

AT = datetime(2026, 11, 24, 9, 30, tzinfo=UTC)


def _ingredient() -> Ingredient:
    return Ingredient(name="examplol", strength=2.0, unit=Unit.PERCENT)


def _raw() -> RawPrescription:
    return RawPrescription(
        id="rx-0001",
        received_at=AT,
        source=Source.ERX_FREE_TEXT,
        text="Examplol 2% cream, 30 g, apply BID. Dr Placeholder.",
        notes="synthetic",
    )


def _extraction() -> Extraction:
    return Extraction(
        ingredients=[_ingredient(), Ingredient(name="samplex", strength=None, unit=None)],
        dosage_form="cream",
        base="emollient base",
        route="topical",
        quantity=30.0,
        quantity_unit="g",
        directions="apply twice daily",
        prescriber_name="Dr Placeholder",
        patient_ref="PT-0001",
        extraction_notes="strength of samplex not stated",
    )


def _formula() -> Formula:
    return Formula(
        formula_id="SHF-001",
        version="1",
        name="Examplol 2% cream (illustrative)",
        ingredients=[FormulaIngredient(name="examplol", strength=2.0, unit=Unit.PERCENT, illustrative_max=5.0)],
        dosage_form="cream",
        base="emollient base",
        route="topical",
        notes="fictional",
        illustrative=True,
    )


def _flag() -> Flag:
    return Flag(rule_id="R1-01", rule_version="0.1.0", severity=Severity.REVIEW, message="empty", source_pass=1)


def _candidate() -> MatchCandidate:
    return MatchCandidate(
        formula_id="SHF-001",
        formula_version="1",
        score=0.92,
        component_scores={"ingredients": 1.0, "strength": 0.8, "dosage_form": 1.0, "base": 1.0, "route": 1.0},
    )


def _proposal() -> Proposal:
    return Proposal(
        prescription_id="rx-0001",
        extraction=_extraction(),
        candidates=[_candidate()],
        confidence=0.92,
        margin=0.3,
        status=ProposalStatus.PROPOSED,
        flags=[
            _flag(),
            Flag(rule_id="R2-01", rule_version="0.1.0", severity=Severity.BLOCK, message="x", source_pass=2),
        ],
        reasons="Ingredient set and strength match SHF-001.",
        model_id="claude-sonnet-5-5",
        prompt_versions={"extract_v1": "a" * 64, "explain_v1": "b" * 64},
        rules_version="0.1.0",
        library_version="0.1.0",
        created_at=AT,
    )


def _review() -> ReviewAction:
    return ReviewAction(
        action=ReviewActionType.CORRECT,
        chosen_formula_id="SHF-001",
        corrected_fields={"quantity": 60.0, "directions": "apply once daily"},
        reason_code="QTY_CORRECTED",
        reviewer="pharmacist-demo",
        at=AT,
    )


def _audit() -> AuditRecord:
    return AuditRecord(
        seq=1,
        prev_hash="0" * 64,
        record_hash="c" * 64,
        input_hash="d" * 64,
        proposal=_proposal(),
        review_action=_review(),
        at=AT,
    )


ALL_MODELS = [
    _raw,
    _ingredient,
    _extraction,
    _formula,
    _flag,
    _candidate,
    _proposal,
    _review,
    _audit,
    lambda: Extraction(),
    lambda: AuditRecord(
        seq=0, prev_hash="", record_hash="e" * 64, input_hash="f" * 64, proposal=_proposal(), review_action=None, at=AT
    ),
]


@pytest.mark.parametrize("factory", ALL_MODELS)
def test_json_round_trip(factory) -> None:
    original: BaseModel = factory()
    restored = type(original).model_validate_json(original.model_dump_json())
    assert restored == original


def test_enum_values_match_spec() -> None:
    assert {s.value for s in Source} == {"eRx_free_text", "fax_ocr", "partner_api"}
    assert {u.value for u in Unit} == {"mg", "mcg", "g", "%", "mg/mL", "units"}
    assert {s.value for s in Severity} == {"BLOCK", "REVIEW"}
    assert {s.value for s in ProposalStatus} == {"PROPOSED", "NO_MATCH", "MANUAL"}
    assert {a.value for a in ReviewActionType} == {"CONFIRM", "CORRECT", "CLARIFY"}


def test_enums_serialise_as_spec_strings() -> None:
    data = _flag().model_dump(mode="json")
    assert data["severity"] == "REVIEW"
    assert Ingredient(name="x", strength=1.0, unit="mg/mL").unit is Unit.MG_PER_ML


def test_placeholder_fields_default_to_none() -> None:
    extraction = Extraction()
    assert extraction.species is None
    assert extraction.office_stock is None
    assert extraction.ingredients == []


@pytest.mark.parametrize("bad_id", ["SHF-1", "SHF-0001", "XYZ-001", "shf-001"])
def test_formula_id_pattern(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        Formula.model_validate(_formula().model_dump() | {"formula_id": bad_id})


def test_formula_must_be_illustrative() -> None:
    with pytest.raises(ValidationError):
        Formula.model_validate(_formula().model_dump() | {"illustrative": False})
    with pytest.raises(ValidationError):
        Formula.model_validate({k: v for k, v in _formula().model_dump().items() if k != "illustrative"})


def test_proposal_has_at_most_three_candidates() -> None:
    data = _proposal().model_dump()
    data["candidates"] = [_candidate().model_dump()] * 4
    with pytest.raises(ValidationError):
        Proposal.model_validate(data)


@pytest.mark.parametrize("score", [-0.01, 1.01])
def test_candidate_score_bounded(score: float) -> None:
    with pytest.raises(ValidationError):
        MatchCandidate(formula_id="SHF-001", formula_version="1", score=score, component_scores={})


@pytest.mark.parametrize("source_pass", [0, 3])
def test_flag_source_pass_is_1_or_2(source_pass: int) -> None:
    with pytest.raises(ValidationError):
        Flag(rule_id="R1-01", rule_version="0.1.0", severity="REVIEW", message="m", source_pass=source_pass)


def test_unknown_enum_value_rejected() -> None:
    with pytest.raises(ValidationError):
        Flag(rule_id="R1-01", rule_version="0.1.0", severity="WARN", message="m", source_pass=1)
    with pytest.raises(ValidationError):
        Ingredient(name="x", strength=1.0, unit="ml")


def test_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate({"dosage_form": "cream", "auto_confirm": True})


def test_flag_and_audit_record_are_immutable() -> None:
    flag = _flag()
    with pytest.raises(ValidationError):
        flag.severity = Severity.REVIEW
    record = _audit()
    with pytest.raises(ValidationError):
        record.record_hash = "tampered"


def test_timestamps_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        RawPrescription(id="rx", received_at=datetime(2026, 11, 24, 9, 30), source="fax_ocr", text="t")
