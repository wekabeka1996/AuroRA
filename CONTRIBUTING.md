# Contributing

Thanks for contributing! This repo follows a strict SSOT workflow:

- All work items are defined in `Copilot_Master_Roadmap.md` (SSOT). Follow the order strictly.
- Commit message style: `type(scope): message [TASK_ID]`
- Open PRs with the same title style and a concise description.
- Do not add interim reports; update SSOT status after merges only.

## Development
- Python 3.11+
- Install: `pip install -r requirements.txt -r requirements-dev.txt`
- Tests: `pytest -q`

## Code Style
- EditorConfig enforced; LF line endings.
- Prefer small, idempotent changes; feature-flags where needed.

## Safety
- Never commit secrets. `.env` is ignored. Use `.env.example` for samples.
- Logs and artifacts are ignored except `.keep` placeholders.
