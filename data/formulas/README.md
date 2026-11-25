# Formula library

Fifteen fictional, non-sterile formulas (`SHF-001` to `SHF-015`). Every file carries `illustrative: true`.
The formulas are invented for this demo and are not taken from any compendium or vendor.

`illustrative_max` values (on every formula ingredient and in `ingredient_master.yaml`) are **not clinical limits**.
They exist only to exercise rule R2-02 and must never be used for real dosing decisions.

`ingredient_master.yaml` lists every ingredient with aliases, a unit and an illustrative maximum.
`intake.library.load_formulas` validates every `SHF-*.yaml` against the `Formula` model.

## Near-twin pairs (same actives, different base, form or strength)

| Pair | Formulas | Difference |
|---|---|---|
| 1 | SHF-001 / SHF-004 | salicylic acid + urea: cream vs ointment base |
| 2 | SHF-002 / SHF-005 | lidocaine + menthol gel: lidocaine 4% vs 2% |
| 3 | SHF-003 / SHF-006 | famotidine suspension: 8 vs 4 mg/mL |
| 4 | SHF-007 / SHF-008 | baclofen suspension: cherry vs sugar-free vehicle |
| 5 | SHF-009 / SHF-010 | hydrocortisone + clotrimazole cream: hydrocortisone 1% vs 2.5% |

Singles: SHF-011 to SHF-015.
