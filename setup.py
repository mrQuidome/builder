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
    Fill in all <REPLACE_ME> secrets in setup_config.json before running.
"""

import argparse
import json
import logging
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
- Apply all config_files changes described in the spec.
- Enable and start the systemd unit if specified.
- Run the validate_cmd and confirm output contains validate_expect.
- When done output one of these exact lines:
  AGENT_RESULT: DONE
  AGENT_RESULT: FAILED
  REASON: <what went wrong>
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
    bad = [
        v["name"] for v in config.get("env_vars", [])
        if "<REPLACE" in str(v.get("value", ""))
    ]
    if bad:
        log.error("The following secrets have not been filled in:")
        for name in bad:
            log.error(f"  {name}")
        log.error(f"Edit {DEFAULT_CONFIG} and replace all <REPLACE_*> placeholders.")
        return False
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
# Phase runners
# ---------------------------------------------------------------------------

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

    # Guard: refuse to run with unfilled secrets
    if not check_secrets(config):
        sys.exit(1)

    failed = []

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
