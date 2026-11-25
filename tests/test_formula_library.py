"""Data checks for the fictional formula library (data/formulas/)."""

import yaml

from intake.library import DEFAULT_FORMULA_DIR, load_alias_map, load_formulas

TWIN_PAIRS = [
    ("SHF-001", "SHF-004"),
    ("SHF-002", "SHF-005"),
    ("SHF-003", "SHF-006"),
    ("SHF-007", "SHF-008"),
    ("SHF-009", "SHF-010"),
]


def _master() -> dict[str, dict]:
    data = yaml.safe_load((DEFAULT_FORMULA_DIR / "ingredient_master.yaml").read_text())
    return {e["name"]: e for e in data["ingredients"]}


def test_loads_fifteen_unique_formulas() -> None:
    formulas = load_formulas()
    assert [f.formula_id for f in formulas] == [f"SHF-{i:03d}" for i in range(1, 16)]
    assert all(f.illustrative for f in formulas)


def test_every_ingredient_in_master_with_consistent_unit_and_max() -> None:
    master = _master()
    for formula in load_formulas():
        for ing in formula.ingredients:
            entry = master[ing.name]
            assert entry["unit"] == ing.unit
            assert entry["illustrative_max"] == ing.illustrative_max
            assert 0 < ing.strength <= ing.illustrative_max
    assert set(load_alias_map()) >= set(master)


def test_files_marked_illustrative_and_labelled() -> None:
    for path in DEFAULT_FORMULA_DIR.glob("SHF-*.yaml"):
        data = yaml.safe_load(path.read_text())
        assert data["illustrative"] is True
        assert "not clinical limits" in data["notes"]


def test_near_twin_pairs_share_actives_but_differ() -> None:
    by_id = {f.formula_id: f for f in load_formulas()}
    for a, b in TWIN_PAIRS:
        fa, fb = by_id[a], by_id[b]
        assert {i.name for i in fa.ingredients} == {i.name for i in fb.ingredients}
        strengths_a = [(i.name, i.strength) for i in fa.ingredients]
        strengths_b = [(i.name, i.strength) for i in fb.ingredients]
        assert strengths_a != strengths_b or fa.base != fb.base


def test_readme_lists_every_twin_pair() -> None:
    readme = (DEFAULT_FORMULA_DIR / "README.md").read_text()
    for a, b in TWIN_PAIRS:
        assert f"{a} / {b}" in readme
