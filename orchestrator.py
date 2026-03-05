#!/usr/bin/env python3
"""
Build Orchestrator

Single entry point that runs the full pipeline:
  1. Planning       — generates .builder/build_plan.json    (planner.py)
  2. Setup Planning — generates .builder/setup_config.json  (setup_planner.py)
  3. Setup          — provisions environment                 (setup.py)
  4. Build Steps    — Dev -> Test -> Refactor -> Security    (existing logic)

Usage:
    python orchestrator.py init my-project                     # scaffold a new project
    python orchestrator.py build /opt/auth-service             # run the full pipeline
    python orchestrator.py build /opt/auth-service --step 7    # run a single step only
    python orchestrator.py build /opt/auth-service --from-step 5  # resume from step 5

The project folder must contain:
    docs/functional_design.md
    docs/technical_design.md

All build artifacts are stored under <project>/.builder/

Requirements:
    claude CLI must be installed and authenticated.
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MAX_DEV_RETRIES = 3
MAX_REF_RETRIES = 2
MAX_SEC_RETRIES = 3
CLAUDE_TIMEOUT  = 1800

# ---------------------------------------------------------------------------
# Agent prompts
# ---------------------------------------------------------------------------

DEV_PROMPT = """
You are a senior developer executing a single build step.

STEP:
{step_json}

PROJECT DIR: {project_dir}

ENVIRONMENT:
{env_summary}

PRODUCTION COMPONENTS ALREADY INSTALLED (do not add to these):
{production_components}

INSTRUCTIONS:
- Implement exactly what the step tasks describe. Nothing more, nothing less.
- Stay inside the project directory.
- Run builds and tests as you go to verify your work.

ALLOWED during this step:
- Adding library dependencies (cargo add, pip install, npm install, etc.)
- Installing dev/build tooling (clippy, rustfmt, cargo-watch, test runners, linters)
- Writing and running tests

NOT ALLOWED during this step:
- Installing or configuring new databases, queues, or caches not already in the
  production components list above
- Adding new external services, APIs, or payment providers not in the design
- Creating new systemd units or system services
- Installing new infrastructure components (reverse proxies, tile servers, etc.)
- Any change that requires production infrastructure not already set up by setup.py

If a step genuinely requires a new production component not in the list above,
do NOT install it. Instead output:
  AGENT_RESULT: FAILED
  REASON: requires production component <name> which is not in setup_config.json

When the Definition of Done is fully met, output:
  AGENT_RESULT: DONE
If you cannot complete the step after your best effort, output:
  AGENT_RESULT: FAILED
  REASON: <brief explanation>
""".strip()

TEST_PROMPT = """
You are a strict QA engineer. Your only job is to verify whether a build step
was completed correctly. You do NOT write or fix code.

STEP:
{step_json}

PROJECT DIR: {project_dir}

INSTRUCTIONS:
- Read the Definition of Done carefully.
- Run builds, tests, and checks to verify each criterion.
- Do not modify any files.
- Output your final verdict as one of:
  AGENT_RESULT: PASS
  AGENT_RESULT: FAIL
  FAILURES: <bullet list of what failed and why>
""".strip()

REFACTOR_PROMPT = """
You are a senior code reviewer. Clean up the code from the previous step
WITHOUT changing any behavior or public interfaces.

STEP:
{step_json}

PROJECT DIR: {project_dir}

INSTRUCTIONS:
- Improve clarity, naming, structure, remove duplication.
- Do NOT add features, change logic, or alter public API contracts.
- Run tests after refactoring to confirm nothing broke.
- Output:
  AGENT_RESULT: DONE
  AGENT_RESULT: FAILED
  REASON: <brief explanation>
""".strip()

SECURITY_PROMPT = """
You are a security engineer reviewing newly written code. You do NOT write features.

STEP:
{step_json}

PROJECT DIR: {project_dir}

PRODUCTION COMPONENTS ALREADY INSTALLED (only these are permitted):
{production_components}

INSTRUCTIONS:
- Review all code added or modified in this step.

Check for security issues:
- Hardcoded secrets, credentials, or API keys in SOURCE CODE files (.rs, .py, .js, etc.)
- SQL injection or unsafe query construction
- Missing authentication or authorisation checks
- Unsafe unwraps on user-controlled input
- Missing or insufficient input validation
- Path traversal vulnerabilities
- Insecure or unpinned dependencies

Check for scope violations:
- Any new production infrastructure introduced (databases, queues, services,
  system daemons, reverse proxies) that is NOT in the production components list
- Any external service dependency not in the original design

ACCEPTABLE PRACTICES — do NOT flag these as issues:
- A .env file in the working directory is standard practice for local configuration.
  As long as .env is listed in .gitignore, this is acceptable. Only flag if .env is
  NOT in .gitignore or if secrets appear in committed source code files.
- Semver ranges in Cargo.toml (e.g. "0.7", "1") are standard Rust practice for
  applications. As long as Cargo.lock is present (pinning exact versions), broad
  ranges in Cargo.toml are acceptable. Only flag if Cargo.lock is missing or gitignored.
- .env.example files with placeholder values are acceptable and expected.
- Auto-generated secrets placed in .env (not in source code) are acceptable.
- Using dotenvy::dotenv().ok() (non-override) to load .env is acceptable.

If you find any issues output:
  AGENT_RESULT: ISSUES_FOUND
  ISSUES:
  1. <issue>
  2. <issue>
If the code is clean and within scope output:
  AGENT_RESULT: PASS
""".strip()

DEV_TEST_FIX_PROMPT = """
You are a senior developer fixing test failures found by the QA engineer.

STEP:
{step_json}

PROJECT DIR: {project_dir}

ENVIRONMENT:
{env_summary}

PRODUCTION COMPONENTS ALREADY INSTALLED (do not add to these):
{production_components}

TEST FAILURES TO FIX:
{test_failures}

INSTRUCTIONS:
- Fix EVERY test failure listed above. Do not skip any.
- The Definition of Done for the step must still be fully met.
- Run builds and tests after your fixes to confirm everything passes.
- Stay inside the project directory.

When all test failures are fixed, output:
  AGENT_RESULT: DONE
If you cannot fix a failure, output:
  AGENT_RESULT: FAILED
  REASON: <brief explanation>
""".strip()

REFACTOR_TEST_FIX_PROMPT = """
You are a senior code reviewer fixing test failures introduced during refactoring.

STEP:
{step_json}

PROJECT DIR: {project_dir}

TEST FAILURES TO FIX:
{test_failures}

INSTRUCTIONS:
- Your previous refactoring broke tests. Fix the issues without reverting to
  pre-refactored code — keep the improved structure where possible.
- Do NOT add features or change logic beyond what is needed to fix the failures.
- Run tests after your fixes to confirm everything passes.

When all test failures are fixed, output:
  AGENT_RESULT: DONE
If you cannot fix the failures, output:
  AGENT_RESULT: FAILED
  REASON: <brief explanation>
""".strip()

SECURITY_FIX_PROMPT = """
You are a security engineer fixing security issues found during a security review.

STEP:
{step_json}

PROJECT DIR: {project_dir}

ENVIRONMENT:
{env_summary}

PRODUCTION COMPONENTS ALREADY INSTALLED (do not add to these):
{production_components}

SECURITY ISSUES TO FIX:
{security_issues}

INSTRUCTIONS:
- Fix EVERY security issue listed above. Do not skip any.
- Do not change functionality or public interfaces — only fix the security problems.
- You may fix issues in both project source code AND system configuration files
  (e.g. /etc/nginx/, /etc/systemd/, service configs) as needed.
- Run builds and tests after your fixes to confirm nothing broke.
- If a fix requires restarting a service (e.g. nginx, martin), do so.

When all security issues are fixed, output:
  AGENT_RESULT: DONE
If you cannot fix an issue, output:
  AGENT_RESULT: FAILED
  REASON: <brief explanation>
""".strip()

SECURITY_FIX_TEST_REPAIR_PROMPT = """
You are a security engineer. A previous security fix broke existing tests.
Your job is to fix ALL the security issues while keeping ALL tests passing.

STEP:
{step_json}

PROJECT DIR: {project_dir}

ENVIRONMENT:
{env_summary}

PRODUCTION COMPONENTS ALREADY INSTALLED (do not add to these):
{production_components}

SECURITY ISSUES TO FIX:
{security_issues}

TEST FAILURES INTRODUCED BY THE PREVIOUS SECURITY FIX:
{test_failures}

INSTRUCTIONS:
- Fix EVERY security issue listed above. Do not skip any.
- Resolve EVERY test failure listed above — tests must pass after your changes.
- Do not change functionality or public interfaces beyond what is needed.
- Run builds and tests after your changes to confirm everything passes.
- If a fix requires restarting a service (e.g. nginx, martin), do so.

When all security issues are fixed and tests pass, output:
  AGENT_RESULT: DONE
If you cannot resolve both the security issues and the test failures, output:
  AGENT_RESULT: FAILED
  REASON: <brief explanation>
""".strip()

# ---------------------------------------------------------------------------
# Logging (configured in main() after parsing args)
# ---------------------------------------------------------------------------

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

PHASE_ORDER = ["dev", "refactor", "security"]

# Set in main() so all functions can access the state file path
_state_file: str = ""


def load_state() -> dict:
    if Path(_state_file).exists():
        with open(_state_file) as f:
            return json.load(f)
    return {"started_at": None, "completed_steps": [], "failed_steps": [],
            "step_phases": {},
            "phase_planning": None, "phase_setup_planning": None,
            "phase_setup": None}


def save_state(state: dict):
    with open(_state_file, "w") as f:
        json.dump(state, f, indent=2)

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return json.load(f)


def get_project_dir(config: dict) -> str:
    """Return the primary project dir from setup config."""
    dirs = config.get("project_dirs", [])
    if dirs:
        return dirs[0]["path"]
    return "/root/unwalked"


def build_env_summary(config: dict) -> str:
    """Build a short non-secret env summary to inject into prompts."""
    lines = []
    for v in config.get("env_vars", []):
        if not v.get("secret"):
            lines.append(f"  {v['name']}={v.get('value', v.get('default', ''))}")
        else:
            lines.append(f"  {v['name']}=<set in environment>")
    return "\n".join(lines) if lines else "  (none)"


def apply_env_to_process(config: dict):
    """Export non-secret env vars into the current process environment."""
    for v in config.get("env_vars", []):
        val = v.get("value", v.get("default", ""))
        if val and "<REPLACE" not in str(val):
            os.environ.setdefault(v["name"], str(val))

# ---------------------------------------------------------------------------
# Claude invocation
# ---------------------------------------------------------------------------

def restore_terminal():
    """Restore terminal to sane state after a subprocess messes it up."""
    try:
        subprocess.run(["stty", "sane"], stdin=open("/dev/tty"), check=False)
    except Exception:
        pass


# Set in main() so run_claude can use it
_agent_log_dir: str = ""


def run_claude(prompt: str, step_num: int, agent: str, project_dir: str) -> str:
    log_dir = Path(_agent_log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    stdout_path = log_dir / f"step_{step_num:02d}_{agent}_{ts}_stdout.log"
    stderr_path = log_dir / f"step_{step_num:02d}_{agent}_{ts}_stderr.log"
    log.info(f"  [{agent}] invoking claude...  stdout -> {stdout_path}")

    with open(stdout_path, "w") as fout, open(stderr_path, "w") as ferr:
        try:
            proc = subprocess.Popen(
                ["claude", "--print", "--dangerously-skip-permissions"],
                stdin=subprocess.PIPE,
                stdout=fout,
                stderr=ferr,
                cwd=project_dir,
            )
            proc.stdin.write(prompt.encode())
            proc.stdin.close()
            proc.wait(timeout=CLAUDE_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            restore_terminal()
            log.error(f"  [{agent}] timed out after {CLAUDE_TIMEOUT}s")
            return "AGENT_RESULT: FAILED\nREASON: timeout"
        except FileNotFoundError:
            log.error("claude CLI not found — is it installed and on PATH?")
            sys.exit(1)

    if proc.returncode != 0:
        restore_terminal()
        stderr_content = Path(stderr_path).read_text().strip()
        log.error(f"  [{agent}] claude exited {proc.returncode}: {stderr_content}")
        return f"AGENT_RESULT: FAILED\nREASON: claude exited {proc.returncode}"

    output = Path(stdout_path).read_text().strip()
    return output


def parse_result(output: str) -> str:
    for line in reversed(output.splitlines()):
        line = line.strip()
        if line.startswith("AGENT_RESULT:"):
            return line.split(":", 1)[1].strip()
    return "UNKNOWN"

# ---------------------------------------------------------------------------
# Agent runners
# ---------------------------------------------------------------------------

def run_dev(step: dict, project_dir: str, env_summary: str, production_components: str) -> tuple[bool, str]:
    prompt = DEV_PROMPT.format(
        step_json=json.dumps(step, indent=2),
        project_dir=project_dir,
        env_summary=env_summary,
        production_components=production_components,
    )
    output = run_claude(prompt, step["step"], "dev", project_dir)
    result = parse_result(output)
    log.info(f"  [dev] -> {result}")
    return result == "DONE", output


def run_dev_test_fix(step: dict, project_dir: str, env_summary: str,
                     production_components: str, test_failures: str) -> tuple[bool, str]:
    prompt = DEV_TEST_FIX_PROMPT.format(
        step_json=json.dumps(step, indent=2),
        project_dir=project_dir,
        env_summary=env_summary,
        production_components=production_components,
        test_failures=test_failures,
    )
    output = run_claude(prompt, step["step"], "dev", project_dir)
    result = parse_result(output)
    log.info(f"  [dev/test-fix] -> {result}")
    return result == "DONE", output


def run_security_fix(step: dict, project_dir: str, env_summary: str,
                     production_components: str, security_issues: str) -> tuple[bool, str]:
    prompt = SECURITY_FIX_PROMPT.format(
        step_json=json.dumps(step, indent=2),
        project_dir=project_dir,
        env_summary=env_summary,
        production_components=production_components,
        security_issues=security_issues,
    )
    output = run_claude(prompt, step["step"], "security-fix", project_dir)
    result = parse_result(output)
    log.info(f"  [security-fix] -> {result}")
    return result == "DONE", output


def run_security_fix_test_repair(step: dict, project_dir: str, env_summary: str,
                                 production_components: str, security_issues: str,
                                 test_failures: str) -> tuple[bool, str]:
    prompt = SECURITY_FIX_TEST_REPAIR_PROMPT.format(
        step_json=json.dumps(step, indent=2),
        project_dir=project_dir,
        env_summary=env_summary,
        production_components=production_components,
        security_issues=security_issues,
        test_failures=test_failures,
    )
    output = run_claude(prompt, step["step"], "security-fix", project_dir)
    result = parse_result(output)
    log.info(f"  [security-fix/repair] -> {result}")
    return result == "DONE", output


def run_refactor_test_fix(step: dict, project_dir: str,
                          test_failures: str) -> tuple[bool, str]:
    prompt = REFACTOR_TEST_FIX_PROMPT.format(
        step_json=json.dumps(step, indent=2),
        project_dir=project_dir,
        test_failures=test_failures,
    )
    output = run_claude(prompt, step["step"], "refactor", project_dir)
    result = parse_result(output)
    log.info(f"  [refactor/test-fix] -> {result}")
    return result == "DONE", output


def run_test(step: dict, project_dir: str) -> tuple[bool, str]:
    prompt = TEST_PROMPT.format(
        step_json=json.dumps(step, indent=2),
        project_dir=project_dir,
    )
    output = run_claude(prompt, step["step"], "test", project_dir)
    result = parse_result(output)
    log.info(f"  [test] -> {result}")
    return result == "PASS", output


def run_refactor(step: dict, project_dir: str) -> tuple[bool, str]:
    prompt = REFACTOR_PROMPT.format(
        step_json=json.dumps(step, indent=2),
        project_dir=project_dir,
    )
    output = run_claude(prompt, step["step"], "refactor", project_dir)
    result = parse_result(output)
    log.info(f"  [refactor] -> {result}")
    return result == "DONE", output


def run_security(step: dict, project_dir: str, production_components: str) -> tuple[bool, str]:
    prompt = SECURITY_PROMPT.format(
        step_json=json.dumps(step, indent=2),
        project_dir=project_dir,
        production_components=production_components,
    )
    output = run_claude(prompt, step["step"], "security", project_dir)
    result = parse_result(output)
    log.info(f"  [security] -> {result}")
    return result == "PASS", output

# ---------------------------------------------------------------------------
# Step pipeline
# ---------------------------------------------------------------------------

def build_production_components(config: dict) -> str:
    """Build a readable list of production components from setup config."""
    lines = []
    for svc in config.get("services", []):
        lines.append(f"  - {svc['name']} (service)")
    for tool in config.get("tools", []):
        lines.append(f"  - {tool['name']} {tool['version']} (tool)")
    return "\n".join(lines) if lines else "  (none listed)"


def _ensure_git_repo(project_dir: str, git_cfg: dict):
    """Initialise a git repo in project_dir if one doesn't exist yet."""
    git_dir = os.path.join(project_dir, ".git")
    if os.path.isdir(git_dir):
        return
    user_name = git_cfg.get("user_name", "builder")
    user_email = git_cfg.get("user_email", "builder@localhost")
    log.info(f"  [commit] no .git found – running git init in {project_dir}")
    subprocess.run(["git", "init"], cwd=project_dir, check=True,
                   capture_output=True, timeout=30)
    subprocess.run(["git", "config", "user.name", user_name],
                   cwd=project_dir, check=True, capture_output=True, timeout=10)
    subprocess.run(["git", "config", "user.email", user_email],
                   cwd=project_dir, check=True, capture_output=True, timeout=10)


def commit_step(step: dict, project_dir: str, git_cfg: dict):
    """Git add + commit all changes for the completed step."""
    n = step["step"]
    title = step.get("title", "untitled")
    msg = f"Step {n:02d}: {title}"
    log.info("")
    log.info(f"  [commit] {msg}")
    try:
        _ensure_git_repo(project_dir, git_cfg)
        subprocess.run(["git", "add", "-A"], cwd=project_dir, check=True,
                       capture_output=True, timeout=60)
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=project_dir, capture_output=True, timeout=60,
        )
        if result.returncode == 0:
            log.info(f"  [commit] nothing to commit")
            return
        subprocess.run(["git", "commit", "-m", msg], cwd=project_dir, check=True,
                       capture_output=True, timeout=60)
        log.info(f"  [commit] done")
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode(errors="replace").strip()
        log.warning(f"  [commit] failed: {e}")
        if stderr:
            log.warning(f"  [commit] stderr: {stderr}")
    except Exception as e:
        log.warning(f"  [commit] error: {e}")


def _save_phase(state: dict, step_num: int, phase: str):
    """Record that a phase completed for a step (persisted immediately)."""
    state.setdefault("step_phases", {})[str(step_num)] = phase
    save_state(state)


def _completed_phases(state: dict, step_num: int) -> set[str]:
    """Return the set of phases already done for a step."""
    last = state.get("step_phases", {}).get(str(step_num))
    if not last or last not in PHASE_ORDER:
        return set()
    idx = PHASE_ORDER.index(last)
    return set(PHASE_ORDER[: idx + 1])


def run_step(step: dict, project_dir: str, env_summary: str,
             production_components: str, state: dict, git_cfg: dict) -> bool:
    n = step["step"]
    done = _completed_phases(state, n)
    log.info("")
    log.info(f"{'='*60}")
    log.info(f"STEP {n:02d}: {step['title']}")
    if done:
        log.info(f"  Resuming — phases already done: {', '.join(sorted(done))}")
    log.info(f"{'='*60}")

    # --- Dev + Test loop ---
    if "dev" in done:
        log.info(f"  [dev loop] skipping (already completed)")
    else:
        log.info("")
        log.info(f"  [dev loop]")
        dev_passed = False
        last_test_output = ""
        for attempt in range(1, MAX_DEV_RETRIES + 1):
            log.info(f"  attempt {attempt}/{MAX_DEV_RETRIES}")
            if attempt == 1:
                dev_ok, _ = run_dev(step, project_dir, env_summary, production_components)
            else:
                dev_ok, _ = run_dev_test_fix(step, project_dir, env_summary,
                                             production_components, last_test_output)
            if not dev_ok:
                log.warning(f"  [dev] FAILED on attempt {attempt}")
            else:
                test_ok, last_test_output = run_test(step, project_dir)
                if test_ok:
                    log.info(f"  [test] PASS — dev loop done")
                    dev_passed = True
                    break
                else:
                    log.warning(f"  [test] FAIL — retrying dev with failure details")
            if attempt == MAX_DEV_RETRIES:
                log.error(f"  [dev loop] exhausted {MAX_DEV_RETRIES} attempts — STEP FAILED")
                return False
            time.sleep(3)

        if not dev_passed:
            return False

        _save_phase(state, n, "dev")

    # --- Refactor + Test loop ---
    if "refactor" in done:
        log.info(f"  [refactor loop] skipping (already completed)")
    else:
        log.info("")
        log.info(f"  [refactor loop]")
        for attempt in range(1, MAX_REF_RETRIES + 1):
            ref_ok, _ = run_refactor(step, project_dir)
            if not ref_ok:
                log.warning(f"  [refactor] FAILED attempt {attempt} — skipping refactor")
                break
            test_ok, test_output = run_test(step, project_dir)
            if test_ok:
                log.info(f"  [test] PASS after refactor")
                break
            else:
                log.warning(f"  [test] FAIL after refactor attempt {attempt}")
                if attempt == MAX_REF_RETRIES:
                    log.error(f"  [refactor] broke tests — STEP FAILED")
                    return False
                fix_ok, _ = run_refactor_test_fix(step, project_dir, test_output)
                if not fix_ok:
                    log.error(f"  [refactor/test-fix] could not fix — STEP FAILED")
                    return False
                time.sleep(3)

        _save_phase(state, n, "refactor")

    # --- Security + Fix loop ---
    if "security" in done:
        log.info(f"  [security loop] skipping (already completed)")
    else:
        log.info("")
        log.info(f"  [security loop]")
        sec_ok, sec_output = run_security(step, project_dir, production_components)
        for sec_attempt in range(1, MAX_SEC_RETRIES + 1):
            if sec_ok:
                break

            log.warning(f"  [security] issues found — fix attempt {sec_attempt}/{MAX_SEC_RETRIES}")
            fix_ok, _ = run_security_fix(step, project_dir, env_summary,
                                         production_components, sec_output)
            if not fix_ok:
                log.error(f"  [security-fix] could not fix issues — STEP FAILED")
                return False

            test_ok, test_output = run_test(step, project_dir)
            if not test_ok:
                log.warning(f"  [security fix] broke tests — attempting repair")
                repair_ok, _ = run_security_fix_test_repair(
                    step, project_dir, env_summary, production_components,
                    sec_output, test_output)
                if not repair_ok:
                    log.error(f"  [security fix] repair agent failed — STEP FAILED")
                    return False
                test_ok, _ = run_test(step, project_dir)
                if not test_ok:
                    log.error(f"  [security fix] tests still failing after repair — STEP FAILED")
                    return False

            sec_ok, sec_output = run_security(step, project_dir, production_components)
            time.sleep(3)

        if not sec_ok:
            log.error(f"  [security] unresolved issues after {MAX_SEC_RETRIES} fix attempts — STEP FAILED")
            return False

        _save_phase(state, n, "security")

    # --- Commit ---
    commit_step(step, project_dir, git_cfg)

    # Step complete — clean up phase tracking
    state.get("step_phases", {}).pop(str(n), None)

    log.info("")
    log.info(f"  STEP {n:02d} COMPLETE")
    return True

# ---------------------------------------------------------------------------
# Pre-build phases
# ---------------------------------------------------------------------------

def run_phase(phase_name: str, cmd: list[str], state: dict, state_key: str) -> bool:
    """Run a pre-build phase via subprocess. Returns True on success."""
    if state.get(state_key) == "done":
        log.info(f"  [{phase_name}] skipping (already done)")
        return True

    log.info(f"  [{phase_name}] running: {' '.join(cmd)}")
    result = subprocess.run(cmd, timeout=CLAUDE_TIMEOUT)
    if result.returncode != 0:
        log.error(f"  [{phase_name}] FAILED (exit code {result.returncode})")
        return False

    state[state_key] = "done"
    save_state(state)
    log.info(f"  [{phase_name}] done")
    return True


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

FUNCTIONAL_DESIGN_TEMPLATE = """\
# Functional Design — {name}

## 1. Overview
<!-- What is this project? One paragraph summary. -->

## 2. Goals
<!-- What should the finished product achieve? Bullet list. -->

## 3. User Roles
<!-- Who uses the system? (e.g. admin, end-user, API consumer) -->

## 4. Features
<!-- Describe each feature. For each one:
     - What it does
     - Inputs / outputs
     - Acceptance criteria
-->

### 4.1 Feature A
### 4.2 Feature B

## 5. Constraints & Assumptions
<!-- Anything the builder should know: rate limits, compliance, SLAs, etc. -->
"""

TECHNICAL_DESIGN_TEMPLATE = """\
# Technical Design — {name}

## 1. Tech Stack
<!-- Languages, frameworks, and versions. Be specific.
     e.g. Rust 1.78, Actix-web 4, PostgreSQL 16, Node 20 -->

## 2. Architecture
<!-- High-level components and how they connect.
     e.g. REST API server + PostgreSQL + Redis cache -->

## 3. Data Models
<!-- Database tables / schemas. Include columns, types, relations. -->

## 4. API Specification
<!-- Endpoints, methods, request/response formats. -->

## 5. Services & Infrastructure
<!-- Databases, caches, reverse proxies, queues, etc.
     Include systemd units and config file paths if relevant. -->

## 6. Environment Variables
<!-- List every env var the app needs.
     Mark each as: static value | auto-generated secret | external credential -->

## 7. Directory Structure
<!-- Where does the source code live? e.g. /opt/my-project -->

## 8. Testing Strategy
<!-- How to run tests, what coverage is expected. -->

## 9. Security Considerations
<!-- Auth method, input validation, secrets handling, TLS, etc. -->
"""


def cmd_init(args):
    """Create project folder with docs/ skeleton."""
    project_dir = Path(args.project_dir).resolve()

    if project_dir.exists():
        print(f"Error: {project_dir} already exists")
        sys.exit(1)

    docs_dir = project_dir / "docs"
    docs_dir.mkdir(parents=True)

    name = project_dir.name

    func_path = docs_dir / "functional_design.md"
    tech_path = docs_dir / "technical_design.md"

    func_path.write_text(FUNCTIONAL_DESIGN_TEMPLATE.format(name=name))
    tech_path.write_text(TECHNICAL_DESIGN_TEMPLATE.format(name=name))

    print(f"Project initialised: {project_dir}")
    print(f"  {docs_dir / 'functional_design.md'}")
    print(f"  {docs_dir / 'technical_design.md'}")
    print()
    print("Next steps:")
    print("  1. Fill in the design documents")
    print(f"  2. python orchestrator.py build {project_dir}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global _state_file, _agent_log_dir

    parser = argparse.ArgumentParser(description="Build Orchestrator")
    sub = parser.add_subparsers(dest="command")

    # --- init ---
    p_init = sub.add_parser("init", help="Scaffold a new project folder")
    p_init.add_argument("project_dir", help="Name or path for the new project")

    # --- build (default) ---
    p_build = sub.add_parser("build", help="Run the build pipeline")
    p_build.add_argument("project_dir",               help="Path to project folder")
    p_build.add_argument("--step",      type=int,     help="Run only this step number")
    p_build.add_argument("--from-step", type=int,     help="Start from this step number")

    args = parser.parse_args()

    # Backwards compat: bare path without subcommand
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "init":
        cmd_init(args)
        return

    project_dir = Path(args.project_dir).resolve()

    # Derive all paths from project_dir
    docs_dir     = project_dir / "docs"
    builder_dir  = project_dir / ".builder"
    log_dir      = builder_dir / "logs"
    plan_path    = builder_dir / "build_plan.json"
    config_path  = builder_dir / "setup_config.json"
    state_path   = builder_dir / "state.json"
    orch_log     = log_dir / "orchestrator.log"

    func_design  = docs_dir / "functional_design.md"
    tech_design  = docs_dir / "technical_design.md"

    # Create .builder/ directory structure
    builder_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    # Set module-level paths
    _state_file = str(state_path)
    _agent_log_dir = str(log_dir)

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        handlers=[
            logging.FileHandler(str(orch_log)),
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Validate design docs exist
    design_docs = []
    for doc in [func_design, tech_design]:
        if not doc.exists():
            log.error(f"Design file not found: {doc}")
            sys.exit(1)
        design_docs.append(str(doc))

    state = load_state()
    if not state["started_at"]:
        state["started_at"] = datetime.now().isoformat()
        save_state(state)

    script_dir = Path(__file__).resolve().parent

    log.info(f"Build Orchestrator")
    log.info(f"Project    : {project_dir}")
    log.info(f"Design docs: {', '.join(d.name for d in [func_design, tech_design])}")

    # --- Phase 1: Planning ---
    skip_planning = (state.get("phase_planning") == "done"
                     and plan_path.exists())
    if skip_planning:
        log.info(f"  [planning] skipping (already done)")
    else:
        if not run_phase("planning",
                         ["python3", str(script_dir / "planner.py"),
                          *design_docs,
                          "--plan", str(plan_path),
                          "--log-dir", str(log_dir)],
                         state, "phase_planning"):
            sys.exit(1)

    # --- Phase 2: Setup Planning ---
    skip_setup_planning = (state.get("phase_setup_planning") == "done"
                           and config_path.exists())
    if skip_setup_planning:
        log.info(f"  [setup-planning] skipping (already done)")
    else:
        if not run_phase("setup-planning",
                         ["python3", str(script_dir / "setup_planner.py"),
                          *design_docs,
                          "--config", str(config_path),
                          "--log-dir", str(log_dir)],
                         state, "phase_setup_planning"):
            sys.exit(1)

    # --- Phase 3: Setup ---
    if not run_phase("setup",
                     ["python3", str(script_dir / "setup.py"),
                      "--config", str(config_path),
                      "--log-dir", str(log_dir)],
                     state, "phase_setup"):
        sys.exit(1)

    # --- Phase 4: Build Steps ---
    # Load plan
    if not plan_path.exists():
        log.error(f"Plan not found: {plan_path}")
        sys.exit(1)
    with open(plan_path) as f:
        plan = json.load(f)

    # Load config
    if not config_path.exists():
        log.error(f"Config not found: {config_path}")
        sys.exit(1)
    config = load_config(str(config_path))
    apply_env_to_process(config)
    build_project_dir = get_project_dir(config)
    env_summary = build_env_summary(config)
    production_components = build_production_components(config)
    git_cfg = config.get("git", {})

    log.info(f"Plan       : {plan_path}")
    log.info(f"Config     : {config_path}")
    log.info(f"Project dir: {build_project_dir}")

    steps = plan["steps"]
    if args.step:
        steps = [s for s in steps if s["step"] == args.step]
        if not steps:
            log.error(f"Step {args.step} not found in plan")
            sys.exit(1)
    elif args.from_step:
        steps = [s for s in steps if s["step"] >= args.from_step]

    log.info(f"Steps      : {len(steps)}")

    for step in steps:
        n = step["step"]

        if n in state["completed_steps"]:
            log.info(f"Skipping step {n:02d} (already completed)")
            continue

        success = run_step(step, build_project_dir, env_summary, production_components, state, git_cfg)

        if success:
            state["completed_steps"].append(n)
            if n in state.get("failed_steps", []):
                state["failed_steps"].remove(n)
        else:
            state.setdefault("failed_steps", [])
            if n not in state["failed_steps"]:
                state["failed_steps"].append(n)
            save_state(state)
            log.error("")
            log.error(f"Step {n:02d} FAILED. Orchestrator stopped.")
            log.error(f"Fix the issue then resume with:")
            log.error(f"  python orchestrator.py {project_dir} --from-step {n}")
            sys.exit(1)

        save_state(state)

    log.info("")
    log.info(f"{'='*60}")
    log.info(f"ALL {len(steps)} STEPS COMPLETE")
    log.info(f"{'='*60}")


if __name__ == "__main__":
    main()
