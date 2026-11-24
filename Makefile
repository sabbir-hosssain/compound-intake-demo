demo:   ; uv sync && INTAKE_MODE=replay uv run intake demo
test:   ; uv run pytest -q
eval:   ; uv run python -m eval.run_eval --mode replay
review: ; uv run streamlit run app/review.py
