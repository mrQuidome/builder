#!/usr/bin/env python3
"""
Setup Agent

Reads setup_config.json produced by planner.py, calls claude to install
and configure all tools and services, validates each one, and writes
results back to setup_config.json.

Usage:
    python setup.py
    python setup.py --config setup_config.json

Requirements:
    claude CLI must be installed and authenticated on this machine.
    Must be run as root or sudo on the target VPS.
    Fill in external secrets (source=external) in setup_config.json before running.
    Secrets with source=generate will be auto-generated.
"""

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG  = "setup_config.json"
CLAUDE_TIMEOUT  = 600   # installs can be slow
LOG_FILE        = "setup.log"

# ---------------------------------------------------------------------------
# Agent prompts
# ---------------------------------------------------------------------------

INSTALL_TOOL_PROMPT = """
You are a system setup agent running on {os} as {run_as}.

Install and configure the following tool exactly as specified.

TOOL:
{tool_json}

ENV VARS AVAILABLE:
{env_json}

INSTRUCTIONS:
- Follow the install_method and install_notes exactly.
- After installing, run the validate_cmd and confirm the output contains validate_expect.
- Do not install anything not listed in the tool spec.
- When done output one of these exact lines:
  AGENT_RESULT: DONE
  AGENT_RESULT: FAILED
  REASON: <what went wrong>
""".strip()

CONFIGURE_SERVICE_PROMPT = """
You are a system setup agent running on {os} as {run_as}.

Configure and start the following service exactly as specified.

SERVICE:
{service_json}

ENV VARS AVAILABLE:
{env_json}

INSTRUCTIONS:
- For database services (e.g. postgresql): create the database user and database
  using the credentials from the env vars. Extract the username, password, and
  database name from DATABASE_URL. Enable required extensions (e.g. PostGIS,
  pgRouting) inside the database.
- Apply all config_files changes described in the spec.
- Enable and start the systemd unit if specified.
- Run the validate_cmd and confirm output contains validate_expect.
- When done output one of these exact lines:
  AGENT_RESULT: DONE
  AGENT_RESULT: FAILED
  REASON: <what went wrong>
""".strip()

GENERATE_SECRETS_PROMPT = """
You are a system setup agent running on {os} as {run_as}.

Generate secure values for the following secrets. Each one has source "generate",
meaning it should be created locally — not obtained from any external service.

SECRETS TO GENERATE:
{secrets_json}

INSTRUCTIONS:
- For database passwords: generate a random 32-character alphanumeric password.
- For JWT secrets: generate a random 64-character hex string.
- For connection strings (like DATABASE_URL): construct the full connection string
  using the generated password. Use the template in the current value if available.
- For any other generate-type secret: produce an appropriate secure random value.
- Output ONLY a single valid JSON object mapping each variable name to its
  generated value. No markdown, no explanation, no code fences.
- Example output:
  {{"JWT_SECRET": "a1b2c3...", "DATABASE_URL": "postgres://user:pass@host/db"}}
""".strip()

SETUP_ENV_PROMPT = """
You are a system setup agent running on {os} as {run_as}.

Write the following environment variables to /etc/environment so they are
available system-wide. Do not overwrite any existing variables not in this list.

ENV VARS:
{env_json}

PROJECT DIRS — create these directories if they don't exist:
{dirs_json}

INSTRUCTIONS:
- Append or update each variable in /etc/environment.
- Create all project directories with appropriate permissions.
- When done output one of these exact lines:
  AGENT_RESULT: DONE
  AGENT_RESULT: FAILED
  REASON: <what went wrong>
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
# Helpers
# ---------------------------------------------------------------------------

def restore_terminal():
    """Restore terminal to sane state after a subprocess messes it up."""
    try:
        subprocess.run(["stty", "sane"], stdin=open("/dev/tty"), check=False)
    except Exception:
        pass


def call_claude(prompt: str, label: str) -> str:
    slug = label.replace(" ", "_").replace("/", "_")
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    stdout_path = log_dir / f"setup_{slug}_{ts}_stdout.log"
    stderr_path = log_dir / f"setup_{slug}_{ts}_stderr.log"
    log.info(f"  [claude] {label}  stdout -> {stdout_path}")

    with open(stdout_path, "w") as fout, open(stderr_path, "w") as ferr:
        try:
            proc = subprocess.Popen(
                ["claude", "--print", "--dangerously-skip-permissions"],
                stdin=subprocess.PIPE,
                stdout=fout,
                stderr=ferr,
            )
            proc.stdin.write(prompt.encode())
            proc.stdin.close()
            proc.wait(timeout=CLAUDE_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            restore_terminal()
            log.error(f"  [claude] timed out after {CLAUDE_TIMEOUT}s")
            return "AGENT_RESULT: FAILED\nREASON: timeout"
        except FileNotFoundError:
            log.error("claude CLI not found — is it installed and on PATH?")
            sys.exit(1)

    if proc.returncode != 0:
        restore_terminal()
        stderr_content = Path(stderr_path).read_text().strip()
        log.error(f"  [claude] exited {proc.returncode}: {stderr_content}")
        return f"AGENT_RESULT: FAILED\nREASON: claude exited {proc.returncode}"

    output = Path(stdout_path).read_text().strip()
    return output


def parse_result(output: str) -> str:
    for line in reversed(output.splitlines()):
        line = line.strip()
        if line.startswith("AGENT_RESULT:"):
            return line.split(":", 1)[1].strip()
    return "UNKNOWN"


def check_secrets(config: dict) -> bool:
    """Warn about external secrets that still have <REPLACE_*> placeholders but don't block."""
    bad = [
        v["name"] for v in config.get("env_vars", [])
        if v.get("source") == "external" and "<REPLACE" in str(v.get("value", ""))
    ]
    if bad:
        log.warning("The following external secrets have not been filled in (skipping for now):")
        for name in bad:
            log.warning(f"  {name}")
        log.warning("You can fill them in later by editing the config and re-running setup.")
    return True


def record_result(config: dict, item_type: str, name: str, status: str, notes: str = ""):
    config.setdefault("install_results", []).append({
        "type": item_type,
        "name": name,
        "status": status,
        "notes": notes,
        "timestamp": datetime.now().isoformat(),
    })


def save_config(config: dict, path: str):
    Path(path).write_text(json.dumps(config, indent=2))


# ---------------------------------------------------------------------------
# Preflight permission checks
# ---------------------------------------------------------------------------

def preflight_checks(config: dict) -> bool:
    """Check all required permissions and tools before running any phases.

    Returns True if all checks pass, False otherwise.
    """
    log.info(f"\n{'='*60}")
    log.info("PREFLIGHT: Checking permissions and prerequisites")
    log.info(f"{'='*60}")

    errors = []

    # 1. claude CLI must be on PATH
    if not shutil.which("claude"):
        errors.append("claude CLI not found on PATH")
    else:
        log.info("  [ok] claude CLI found")

    # 2. Root or passwordless sudo required
    is_root = os.geteuid() == 0
    has_sudo = False
    if not is_root:
        ret = subprocess.run(
            ["sudo", "-n", "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        has_sudo = ret.returncode == 0

    if is_root:
        log.info("  [ok] Running as root")
    elif has_sudo:
        log.info("  [ok] Passwordless sudo available")
    else:
        errors.append(
            "Not root and no passwordless sudo. "
            "Fix: echo 'builder ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/builder"
        )

    # 3. systemctl must be available (needed for services)
    if config.get("services"):
        if not shutil.which("systemctl"):
            errors.append("systemctl not found — required for service management")
        else:
            log.info("  [ok] systemctl found")

    # 4. Can write to /etc/environment (env setup phase)
    if is_root or has_sudo:
        ret = subprocess.run(
            ["sudo", "-n", "test", "-w", "/etc/environment"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ) if not is_root else subprocess.run(
            ["test", "-w", "/etc/environment"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if ret.returncode == 0:
            log.info("  [ok] /etc/environment is writable")
        else:
            errors.append("/etc/environment is not writable")

    # 5. Collect all system paths and verify top-level roots are accessible.
    #    Nested dirs (e.g. /etc/postgresql/16/main) are created by package
    #    installs or earlier phases, so we only check that the filesystem
    #    roots (/opt, /etc, etc.) exist and are writable with our privileges.
    needed_dirs = set()
    for d in config.get("project_dirs", []):
        needed_dirs.add(d["path"])
    for svc in config.get("services", []):
        for cf in svc.get("config_files", []):
            needed_dirs.add(str(Path(cf["path"]).parent))

    # Extract top-level root dirs (e.g. /opt, /etc)
    root_dirs = set()
    for dirpath in needed_dirs:
        parts = Path(dirpath).parts  # ('/', 'opt', 'unwalked', 'api')
        if len(parts) >= 2:
            root_dirs.add("/" + parts[1])  # e.g. /opt, /etc

    test_cmd_prefix = ["sudo", "-n"] if has_sudo and not is_root else []
    for root_dir in sorted(root_dirs):
        ret = subprocess.run(
            test_cmd_prefix + ["test", "-w", root_dir],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if ret.returncode == 0:
            dirs_under = sorted(d for d in needed_dirs if d.startswith(root_dir))
            log.info(f"  [ok] {root_dir} is writable ({len(dirs_under)} paths needed under it)")
        else:
            errors.append(f"{root_dir} is not writable — needed for: "
                          + ", ".join(sorted(d for d in needed_dirs if d.startswith(root_dir))))

    # 6. apt-get available (needed for apt install_method tools)
    apt_tools = [t for t in config.get("tools", []) if t.get("install_method") == "apt"]
    if apt_tools:
        if not shutil.which("apt-get"):
            errors.append("apt-get not found — required for tool installation")
        else:
            log.info(f"  [ok] apt-get found ({len(apt_tools)} tools need it)")

    # 7. cargo available or installable (needed for cargo install_method tools)
    cargo_tools = [t for t in config.get("tools", []) if t.get("install_method") == "cargo"]
    if cargo_tools:
        if shutil.which("cargo"):
            log.info(f"  [ok] cargo found ({len(cargo_tools)} tools need it)")
        else:
            log.info(f"  [--] cargo not yet installed ({len(cargo_tools)} tools need it — will be installed in tool phase)")

    # Report results
    if errors:
        log.error(f"\n  PREFLIGHT FAILED — {len(errors)} problem(s):")
        for i, err in enumerate(errors, 1):
            log.error(f"    {i}. {err}")
        log.error("  Fix the above issues and re-run setup.")
        return False

    log.info("  All preflight checks passed.")
    return True


# ---------------------------------------------------------------------------
# Phase runners
# ---------------------------------------------------------------------------

def run_generate_secrets(config: dict) -> bool:
    """Phase 0: auto-generate secrets marked with source=generate."""
    gen_vars = [v for v in config["env_vars"] if v.get("source") == "generate"]
    if not gen_vars:
        log.info("  No secrets to auto-generate.")
        return True

    log.info(f"\n{'='*60}")
    log.info(f"PHASE: Auto-generate secrets ({len(gen_vars)} secrets)")
    log.info(f"{'='*60}")

    prompt = GENERATE_SECRETS_PROMPT.format(
        os=config["system"]["os"],
        run_as=config["system"]["run_as"],
        secrets_json=json.dumps(gen_vars, indent=2),
    )

    output = call_claude(prompt, "generate_secrets")

    # Parse the JSON mapping from the output
    try:
        # Try to extract JSON from the output (may be wrapped in fences)
        match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", output)
        if match:
            text = match.group(1).strip()
        else:
            match_open = re.search(r"```(?:json)?\s*\n", output)
            text = output[match_open.end():].strip() if match_open else output.strip()
        generated = json.loads(text)
    except (json.JSONDecodeError, AttributeError) as e:
        log.error(f"  Failed to parse generated secrets: {e}")
        log.error(f"  Raw output:\n{output[:500]}")
        record_result(config, "secrets", "generate", "failed", str(e))
        return False

    # Write generated values back into the config
    updated = 0
    for var in config["env_vars"]:
        if var["name"] in generated:
            var["value"] = generated[var["name"]]
            updated += 1
            log.info(f"  Generated: {var['name']}")

    if updated < len(gen_vars):
        missing = [v["name"] for v in gen_vars if v["name"] not in generated]
        log.warning(f"  Missing generated values for: {', '.join(missing)}")

    record_result(config, "secrets", "generate", "ok", f"{updated} secrets generated")
    return True


def run_env_setup(config: dict) -> bool:
    log.info(f"\n{'='*60}")
    log.info(f"PHASE: Environment variables and project directories")
    log.info(f"{'='*60}")

    prompt = SETUP_ENV_PROMPT.format(
        os=config["system"]["os"],
        run_as=config["system"]["run_as"],
        env_json=json.dumps(config["env_vars"], indent=2),
        dirs_json=json.dumps(config.get("project_dirs", []), indent=2),
    )

    output = call_claude(prompt, "env_setup")
    result = parse_result(output)
    log.info(f"  [env setup] -> {result}")

    if result == "DONE":
        record_result(config, "env", "environment", "ok")
        return True
    else:
        record_result(config, "env", "environment", "failed", output[-300:])
        return False


def run_tool_install(tool: dict, config: dict) -> bool:
    name = tool["name"]
    log.info(f"\n  Installing tool: {name} ({tool['version']})")

    prompt = INSTALL_TOOL_PROMPT.format(
        os=config["system"]["os"],
        run_as=config["system"]["run_as"],
        tool_json=json.dumps(tool, indent=2),
        env_json=json.dumps(config["env_vars"], indent=2),
    )

    for attempt in range(1, 3):  # retry once
        output = call_claude(prompt, f"tool_{name}_attempt{attempt}")
        result = parse_result(output)
        log.info(f"  [{name}] attempt {attempt} -> {result}")

        if result == "DONE":
            record_result(config, "tool", name, "ok", tool["version"])
            return True

        if attempt < 2:
            log.warning(f"  [{name}] failed, retrying once...")

    record_result(config, "tool", name, "failed", output[-300:])
    return False


def run_service_configure(service: dict, config: dict) -> bool:
    name = service["name"]
    log.info(f"\n  Configuring service: {name}")

    prompt = CONFIGURE_SERVICE_PROMPT.format(
        os=config["system"]["os"],
        run_as=config["system"]["run_as"],
        service_json=json.dumps(service, indent=2),
        env_json=json.dumps(config["env_vars"], indent=2),
    )

    for attempt in range(1, 3):  # retry once
        output = call_claude(prompt, f"service_{name}_attempt{attempt}")
        result = parse_result(output)
        log.info(f"  [{name}] attempt {attempt} -> {result}")

        if result == "DONE":
            record_result(config, "service", name, "ok")
            return True

        if attempt < 2:
            log.warning(f"  [{name}] failed, retrying once...")

    record_result(config, "service", name, "failed", output[-300:])
    return False

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Setup Agent")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="Setup config JSON file")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        log.error(f"Config file not found: {config_path}")
        log.error("Run planner.py first to generate it.")
        sys.exit(1)

    with open(config_path) as f:
        config = json.load(f)

    log.info(f"Setup Agent")
    log.info(f"Config  : {config_path}")
    log.info(f"Project : {config.get('project')}")
    log.info(f"OS      : {config['system']['os']}")
    log.info(f"Tools   : {len(config['tools'])}")
    log.info(f"Services: {len(config['services'])}")

    # Guard: refuse to run with unfilled external secrets
    if not check_secrets(config):
        sys.exit(1)

    # Preflight: check all permissions before doing any work
    if not preflight_checks(config):
        sys.exit(1)

    # Update run_as to reflect actual privilege level
    if os.geteuid() != 0:
        config["system"]["run_as"] = f"user {os.getenv('USER', 'builder')} with sudo"

    # Clear stale install_results from previous failed runs
    config["install_results"] = []

    failed = []

    # --- Phase 0: auto-generate secrets ---
    if not run_generate_secrets(config):
        log.error("Secret generation failed — cannot continue.")
        save_config(config, args.config)
        sys.exit(1)
    save_config(config, args.config)

    # --- Phase 1: env vars and directories ---
    if not run_env_setup(config):
        log.error("Environment setup failed — cannot continue.")
        save_config(config, args.config)
        sys.exit(1)
    save_config(config, args.config)

    # --- Phase 2: tools ---
    log.info(f"\n{'='*60}")
    log.info(f"PHASE: Tool installation ({len(config['tools'])} tools)")
    log.info(f"{'='*60}")

    for tool in config["tools"]:
        ok = run_tool_install(tool, config)
        save_config(config, args.config)  # save after every tool
        if not ok:
            failed.append(f"tool:{tool['name']}")
            log.error(f"  Tool {tool['name']} failed after retry — stopping.")
            log.error(f"  Results saved to {config_path}")
            log.error(f"  Fix the issue and re-run: python setup.py --config {config_path}")
            sys.exit(1)

    # --- Phase 3: services ---
    log.info(f"\n{'='*60}")
    log.info(f"PHASE: Service configuration ({len(config['services'])} services)")
    log.info(f"{'='*60}")

    for service in config["services"]:
        ok = run_service_configure(service, config)
        save_config(config, args.config)  # save after every service
        if not ok:
            failed.append(f"service:{service['name']}")
            log.error(f"  Service {service['name']} failed after retry — stopping.")
            log.error(f"  Results saved to {config_path}")
            log.error(f"  Fix the issue and re-run: python setup.py --config {config_path}")
            sys.exit(1)

    # --- Summary ---
    log.info(f"\n{'='*60}")
    log.info(f"SETUP COMPLETE")
    log.info(f"  Tools    : {len(config['tools'])} installed")
    log.info(f"  Services : {len(config['services'])} configured")
    log.info(f"  Results  : {config_path}")
    log.info(f"{'='*60}")
    log.info(f"\nNext step:")
    log.info(f"  python orchestrator.py --config {config_path}")


if __name__ == "__main__":
    main()
