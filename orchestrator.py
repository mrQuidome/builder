#!/usr/bin/env python3
"""
Build Orchestrator

Reads unwalked_build_plan.json and setup_config.json, then runs each build
step through four agents in sequence: Dev -> Test -> Refactor -> Security.

Usage:
    python orchestrator.py
    python orchestrator.py --plan unwalked_build_plan.json --config setup_config.json
    python orchestrator.py --step 7          # run a single step only
    python orchestrator.py --from-step 5     # resume from step 5

Requirements:
    claude CLI must be installed and authenticated.
    setup.py must have completed successfully.
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

DEFAULT_PLAN    = "unwalked_build_plan.json"
DEFAULT_CONFIG  = "setup_config.json"
STATE_FILE      = "orchestrator_state.json"
LOG_FILE        = "orchestrator.log"
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

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

PHASE_ORDER = ["dev", "refactor", "security"]


def load_state() -> dict:
    if Path(STATE_FILE).exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"started_at": None, "completed_steps": [], "failed_steps": [],
            "step_phases": {}}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
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


def run_claude(prompt: str, step_num: int, agent: str, project_dir: str) -> str:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
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


def commit_step(step: dict, project_dir: str):
    """Git add + commit all changes for the completed step."""
    n = step["step"]
    title = step.get("title", "untitled")
    msg = f"Step {n:02d}: {title}"
    log.info("")
    log.info(f"  [commit] {msg}")
    try:
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
        log.warning(f"  [commit] failed: {e}")
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
             production_components: str, state: dict) -> bool:
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

            test_ok, _ = run_test(step, project_dir)
            if not test_ok:
                log.error(f"  [security fix] broke tests — STEP FAILED")
                return False

            sec_ok, sec_output = run_security(step, project_dir, production_components)
            time.sleep(3)

        if not sec_ok:
            log.error(f"  [security] unresolved issues after {MAX_SEC_RETRIES} fix attempts — STEP FAILED")
            return False

        _save_phase(state, n, "security")

    # --- Commit ---
    commit_step(step, project_dir)

    # Step complete — clean up phase tracking
    state.get("step_phases", {}).pop(str(n), None)

    log.info("")
    log.info(f"  STEP {n:02d} COMPLETE")
    return True

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Build Orchestrator")
    parser.add_argument("--plan",      default=DEFAULT_PLAN,   help="Build plan JSON")
    parser.add_argument("--config",    default=DEFAULT_CONFIG, help="Setup config JSON")
    parser.add_argument("--step",      type=int, help="Run only this step number")
    parser.add_argument("--from-step", type=int, help="Start from this step number")
    args = parser.parse_args()

    # Load plan
    if not Path(args.plan).exists():
        log.error(f"Plan not found: {args.plan} — run planner.py first")
        sys.exit(1)
    with open(args.plan) as f:
        plan = json.load(f)

    # Load config
    if not Path(args.config).exists():
        log.error(f"Config not found: {args.config} — run planner.py and setup.py first")
        sys.exit(1)
    config = load_config(args.config)
    apply_env_to_process(config)
    project_dir = get_project_dir(config)
    env_summary = build_env_summary(config)
    production_components = build_production_components(config)

    steps = plan["steps"]
    if args.step:
        steps = [s for s in steps if s["step"] == args.step]
        if not steps:
            log.error(f"Step {args.step} not found in plan")
            sys.exit(1)
    elif args.from_step:
        steps = [s for s in steps if s["step"] >= args.from_step]

    state = load_state()
    if not state["started_at"]:
        state["started_at"] = datetime.now().isoformat()
        save_state(state)

    log.info(f"Build Orchestrator")
    log.info(f"Plan       : {args.plan}")
    log.info(f"Config     : {args.config}")
    log.info(f"Project dir: {project_dir}")
    log.info(f"Steps      : {len(steps)}")

    for step in steps:
        n = step["step"]

        if n in state["completed_steps"]:
            log.info(f"Skipping step {n:02d} (already completed)")
            continue

        success = run_step(step, project_dir, env_summary, production_components, state)

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
            log.error(f"  python orchestrator.py --from-step {n} --config {args.config}")
            sys.exit(1)

        save_state(state)

    log.info("")
    log.info(f"{'='*60}")
    log.info(f"ALL {len(steps)} STEPS COMPLETE")
    log.info(f"{'='*60}")


if __name__ == "__main__":
    main()
