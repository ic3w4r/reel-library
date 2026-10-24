# Contributing to Reel Library

Thanks for helping out. Bug reports, ideas, docs fixes and code are all welcome.

## Ways to contribute

- **Report a bug**: open an issue with the bug template. Include your AI engine, OS, how you run it
  (Docker / local) and the relevant lines from `docker logs instamcp`.
- **Suggest an idea**: start a thread in Discussions, or open a feature request if it's concrete.
- **Send code**: look for issues labelled `good first issue` or `help wanted`, or open an issue first
  for anything big so we can agree on the approach before you spend time on it.

## Run it locally

Requires [uv](https://docs.astral.sh/uv/), ffmpeg and Node 20+.

```bash
uv sync --extra decisions          # drop --extra decisions to skip Laya / PyTorch
(cd web && npm install && npm run build)
uv run instamcp web                # UI + API + MCP on http://127.0.0.1:8080
```

For UI work, also run `cd web && npm run dev` (Vite on :5173, proxied to :8080).

Or with Docker: `docker compose up -d --build`, then open http://localhost:8090.

Use a throwaway data folder while developing so you don't touch your real library:
`INSTAMCP_DATA_DIR=/tmp/reel-dev uv run instamcp web`.

## Making changes

1. Fork the repo and create a branch: `git checkout -b fix/short-description`.
2. Keep changes focused: one fix or feature per pull request.
3. Match the surrounding code: type hints, short docstrings that say *why*, no new dependency without
   a good reason (say why in the PR).
4. Check that it still builds:
   ```bash
   uv run python -m compileall -q src
   (cd web && npm run build)
   docker build -t instamcp:dev .
   ```
5. Open a pull request describing what changed and how you tested it. Screenshots help for UI changes.

## Releasing (maintainers)

1. Bump `version` in `pyproject.toml` and `__version__` in `src/instamcp/__init__.py`, and commit.
2. Tag and push: `git tag v0.2.0 && git push origin v0.2.0`.

The Release workflow then publishes `ghcr.io/ic3w4r/reel-library:<version>` and `:latest` for
Intel/AMD and Apple Silicon, and creates the GitHub release with generated notes and the Windows zip.

## Ground rules

- **Never commit personal data**: Instagram exports, cookies, `settings.json`, databases, API keys.
  `.gitignore` covers the usual files; double-check `git status` before committing.
- Respect Instagram creators: features should help people organize what *they* saved, not scrape or
  republish other people's content.
- Be kind and constructive in issues and reviews.

## License

By contributing, you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE), the same license as the project.
