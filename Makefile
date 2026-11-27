demo:   ; uv sync && INTAKE_MODE=replay uv run intake demo
test:   ; uv run pytest -q
eval:   ; uv run python -m eval.run_eval --mode replay
review: ; uv run streamlit run app/review.py
traces: ; INTAKE_MODE=replay uv run intake trace
viewer: ; INTAKE_MODE=replay uv run intake trace && uv run python -m http.server 8000 -d viewer
