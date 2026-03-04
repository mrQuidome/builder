# Manual Happy-Flow Test Plan

**Scope**: Full end-to-end run of the build orchestration system — from `design.md` to a fully built project.
**Precondition**: You have a clean VPS (or will reset state on the current one) with Claude CLI authenticated.

---

## Phase 0 — Reset State

1. Delete any existing state and output files so the run starts clean:
   ```
   rm -f orchestrator_state.json
   rm -f orchestrator.log planner.log setup_planner.log setup.log
   rm -f unwalked_build_plan.json setup_config.json
   rm -f planner_raw_plan.txt planner_raw_config.txt
   rm -rf logs/
   ```
2. Verify `design.md` is present and looks correct — open it and confirm it describes the Unwalked Route Planner.
3. Verify Claude CLI is authenticated: run `claude --version` and confirm it returns a version without errors.

---

## Phase 1 — Generate Build Plan (`planner.py`)

4. Run: `python planner.py design.md`
5. Wait for it to complete (it calls Claude; takes a few minutes).
6. Verify `unwalked_build_plan.json` exists.
7. Open `unwalked_build_plan.json` and spot-check:
   - It contains a list of steps (expect ~44).
   - Each step has a `step_number`, `title`, `tasks`, and `definition_of_done`.
   - Step 1 is about the database schema.
   - Last steps are about deployment/DevOps.
8. Open `planner.log` and confirm the last line says success (no error trace).

---

## Phase 2 — Generate Infrastructure Config (`setup_planner.py`)

9. Run: `python setup_planner.py design.md`
10. Wait for it to complete.
11. Verify `setup_config.json` exists.
12. Open `setup_config.json` and spot-check:
    - `tools` list includes: Rust, Flutter, PostgreSQL-16, PostGIS, pgRouting, Martin, Nginx.
    - `env_vars` section includes: `DATABASE_URL`, `JWT_SECRET`, `GOOGLE_OAUTH_CLIENT_SECRET`, `MOLLIE_API_KEY`.
    - Secrets marked as `external` have placeholder values (not auto-generated).
    - `project_dirs` lists API, client, migrations directories.

---

## Phase 3 — Fill in External Secrets (Manual)

13. Open `setup_config.json` in an editor.
14. Find all secrets where `"source": "external"` and fill in real values:
    - `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` — from Google Cloud Console.
    - `APPLE_OAUTH_CLIENT_SECRET` — from Apple Developer Portal.
    - `MOLLIE_API_KEY` — from Mollie Dashboard.
    - `APPLE_IAP_SHARED_SECRET` — from App Store Connect.
    - `GOOGLE_PLAY_SERVICE_ACCOUNT_JSON` — path to your Google Play service account JSON file.
15. Save the file.
16. Verify no placeholder strings like `"<your-key-here>"` remain in the `env_vars` section.

---

## Phase 4 — Infrastructure Setup (`setup.py`)

17. Run: `python setup.py --config setup_config.json`
18. Watch the terminal output — each tool/service should print a status line.
19. Wait for completion (this is the longest phase — installs Rust, Flutter, PostgreSQL, etc.).
20. Open `setup.log` and verify:
    - Every tool shows `SUCCESS` (Rust, Cargo, Flutter, PostgreSQL-16, PostGIS, pgRouting, osm2pgsql, Martin, Nginx).
    - Every service shows `SUCCESS` (PostgreSQL, Martin, Nginx, unwalked-api).
    - No `FAILED` entries.
21. Spot-check services are actually running:
    - `systemctl is-active postgresql` → should print `active`
    - `systemctl is-active nginx` → should print `active`
22. Verify project directories were created (e.g. the API server dir and Flutter client dir listed in `setup_config.json`).

---

## Phase 5 — Execute Build Steps (`orchestrator.py`)

23. Run: `python orchestrator.py --plan unwalked_build_plan.json --config setup_config.json`
24. Monitor the terminal — you should see step numbers counting up from 1 to 44, with phase labels (Dev, Test, Refactor, Security) printed for each.
25. Let it run to completion (this is the longest phase overall — expect many hours).
26. When it finishes, confirm the terminal shows a completion message (e.g. `ALL 44 STEPS COMPLETE`).
27. Open `orchestrator_state.json` and verify:
    - `completed_steps` contains all 44 step numbers (1–44).
    - `failed_steps` is an empty list `[]`.
28. Open `orchestrator.log` and verify the last entry is a success/completion message, not an exception or error.
29. Run `git log --oneline` in the project directory — verify there are 44 commits (one per step).

---

## Phase 6 — Verify the Built Application

30. Navigate to the API server project directory (as listed in `setup_config.json`).
31. Confirm the Rust source tree is present (`src/main.rs` or similar exists).
32. Run `cargo check` in the API directory — should compile without errors.
33. Confirm the Flutter client directory exists with a valid Flutter project (`pubspec.yaml` present).
34. Run `flutter pub get` in the Flutter directory — should download dependencies without errors.
35. Confirm migration SQL files exist in the migrations directory.
36. Check that the database has the expected schemas: connect with `psql` and run `\dt` — expect tables like `users`, `walks`, `subscriptions`.
37. Start the API server locally and send a health-check HTTP request — expect a `200 OK` response.

---

## Pass Criteria

| Check | Expected Result |
|---|---|
| `unwalked_build_plan.json` created | ~44 steps, well-structured JSON |
| `setup_config.json` created | All tools, services, env vars present |
| `setup.log` | All tools and services: SUCCESS |
| `orchestrator_state.json` | 44 completed steps, 0 failed |
| Git log | 44 commits in project repo |
| `cargo check` on API | No errors |
| DB tables | `users`, `walks`, `subscriptions` present |
| API health check | HTTP 200 |
