# Submission notes

- **Solution folder:** `submission/` (`submission/solution.py` defines `build()`).
- **Approach, "what is current" rules, as_of, conflicts, refusals, limitations:** see
  [`submission/NOTES.md`](submission/NOTES.md).
- **API keys:** none. No LLM, no paid API, no network calls. Standard library only.
- **Run:** `python harness/run_eval.py --submission submission --eval eval/public_eval.jsonl`
- **Tests:** `python -m unittest discover -s submission/tests`
