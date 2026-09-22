# SentinelX — project conventions

Standing rules every change in this repo follows. When a prompt and this file disagree, the prompt wins for that change and this file gets updated to match.

## Branching and commits

- **All commits go on `ansh-dev`. Never commit directly to `main`, and do not create throwaway feature branches** — `ansh-dev` is the integration branch and the user merges it into `main` themselves.
- Small commits with clear messages; never push unless asked.
- Never discard, stash, or rewrite changes you did not make.

## Gates before every commit

- Backend: `cd backend && ../.venv/Scripts/python -m pytest`
- Frontend: `npx tsc -b`, `npm run lint`, `npm run build`
- If migrations changed: `alembic upgrade head` from an empty database, from a populated one, and `downgrade -1` must all work; exactly one Alembic head.

## Migrations

- Never edit an old migration. New schema changes get one new, hand-written migration (no `--autogenerate` against shared history).
- Preserve names the older migrations' downgrades reference (constraints, FKs, indexes) when recreating structures.

## Configuration and URLs

- No hardcoded URLs in app code. Emailed links are built from `settings.frontend_url` **at send time** (see `app/invite_service.build_invite_link`), never a baked-in constant.
- CORS allow-list is explicit. A share session adds exactly its own origin via `DEV_SHARE_ORIGINS`; wildcards are rejected by the parser and forbidden.
- Frontend code takes its API base from `src/lib/apiBase.ts` (page origin in share mode, `http://localhost:8000` otherwise) — do not inline backend URLs elsewhere.

## Dev launcher and sharing

- Plain `npm run dev` must behave exactly as before any launcher change; new behavior goes behind flags.
- Sharing the dev environment is **opt-in only** (`npm run dev:share` / `--lan` / `--tunnel`) and lasts one run: it sets `FRONTEND_URL` + `DEV_SHARE_ORIGINS` for that session and nothing persists.
- The launcher never installs anything outside the repo's declared dependencies (cloudflared, ngrok, etc. are external CLIs — print the install command instead).

## Dependencies

- Ask before adding any npm or Python dependency. Verify a library is already used in the project before employing it.

## Docs

- Behavior changes update the relevant docs in the same change: `API_CONTRACT.md`, `DECISIONS.md` (one entry per decision, with the why), `architecture.md`, and `README.md` when dev workflow changes. Reports go in `docs/reports/`.
