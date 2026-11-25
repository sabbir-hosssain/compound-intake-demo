"""SPEC §4 data models (Pydantic v2). Names and enum values are binding; fields may grow.

Models are structural only: rules, matching and persistence live elsewhere.
"""

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class _Model(BaseModel):
    """Base: unknown fields are rejected, so unexpected LLM keys fail schema validation."""

    model_config = ConfigDict(extra="forbid")


class _FrozenModel(_Model):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Source(StrEnum):
    ERX_FREE_TEXT = "eRx_free_text"
    FAX_OCR = "fax_ocr"
    PARTNER_API = "partner_api"


class Unit(StrEnum):
    MG = "mg"
    MCG = "mcg"
    G = "g"
    PERCENT = "%"
    MG_PER_ML = "mg/mL"
    UNITS = "units"


class Severity(StrEnum):
    BLOCK = "BLOCK"
    REVIEW = "REVIEW"


class ProposalStatus(StrEnum):
    PROPOSED = "PROPOSED"
    NO_MATCH = "NO_MATCH"
    MANUAL = "MANUAL"


class ReviewActionType(StrEnum):
    CONFIRM = "CONFIRM"
    CORRECT = "CORRECT"
    CLARIFY = "CLARIFY"


Score = Annotated[float, Field(ge=0.0, le=1.0)]
FormulaId = Annotated[str, Field(pattern=r"^SHF-\d{3}$")]


class RawPrescription(_Model):
    id: str
    received_at: AwareDatetime
    source: Source
    text: str
    notes: str | None = None


class Ingredient(_Model):
    name: str  # normalised
    strength: float | None = None
    unit: Unit | None = None


class Extraction(_Model):
    """Everything is optional: missing fields are flagged by pass-2 rules, not rejected here."""

    ingredients: list[Ingredient] = Field(default_factory=list)
    dosage_form: str | None = None
    base: str | None = None
    route: str | None = None
    quantity: float | None = None
    quantity_unit: str | None = None
    directions: str | None = None
    prescriber_name: str | None = None
    patient_ref: str | None = None
    species: str | None = None  # veterinary placeholder
    office_stock: bool | None = None  # placeholder
    extraction_notes: str | None = None


class FormulaIngredient(_Model):
    name: str
    strength: float
    unit: Unit
    illustrative_max: float


class Formula(_Model):
    formula_id: FormulaId
    version: str
    name: str
    ingredients: list[FormulaIngredient]
    dosage_form: str
    base: str | None = None
    route: str
    notes: str | None = None
    illustrative: Literal[True]


class Flag(_FrozenModel):
    rule_id: str
    rule_version: str
    severity: Severity
    message: str
    source_pass: Literal[1, 2]


class MatchCandidate(_Model):
    formula_id: FormulaId
    formula_version: str
    score: Score
    component_scores: dict[str, float] = Field(default_factory=dict)


class Proposal(_Model):
    prescription_id: str
    extraction: Extraction | None = None
    candidates: list[MatchCandidate] = Field(default_factory=list, max_length=3)
    confidence: Score
    margin: Score
    status: ProposalStatus
    flags: list[Flag] = Field(default_factory=list)
    reasons: str = ""
    model_id: str
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    rules_version: str
    library_version: str
    created_at: AwareDatetime


class ReviewAction(_Model):
    action: ReviewActionType
    chosen_formula_id: FormulaId | None = None
    corrected_fields: dict[str, Any] = Field(default_factory=dict)
    reason_code: str | None = None
    reviewer: str
    at: AwareDatetime


class AuditRecord(_FrozenModel):
    seq: int = Field(ge=0)
    prev_hash: str
    record_hash: str
    input_hash: str
    proposal: Proposal
    review_action: ReviewAction | None = None
    at: AwareDatetime
