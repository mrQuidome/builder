#!/usr/bin/env python3
"""
Planner Agent

Reads a technical design markdown file and produces two JSON files:
  - unwalked_build_plan.json   sequential build steps for the orchestrator
  - setup_config.json          all tools, versions, credentials, env vars

Usage:
    python planner.py design.md
    python planner.py design.md --plan my_plan.json --config my_config.json

Requirements:
    claude CLI must be installed and authenticated on this machine.
"""

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_PLAN    = "unwalked_build_plan.json"
DEFAULT_CONFIG  = "setup_config.json"
CLAUDE_TIMEOUT  = 300
LOG_FILE        = "planner.log"

# ---------------------------------------------------------------------------
# Prompts — two separate claude calls to keep output focused
# ---------------------------------------------------------------------------

PLAN_PROMPT = """
You are a Planner Agent. Read the technical design and produce a sequenced
build plan as a single JSON object.

TECHNICAL DESIGN:
{design}

OUTPUT RULES:
- Output ONLY a single valid JSON object. No markdown, no explanation, no code fences.
- If information is missing that would block writing a specific step, do NOT write
  the plan. Output this exact shape instead:
  {{
    "status": "blocked",
    "blockers": [
      {{"id": "B1", "description": "what is missing and why it blocks the plan"}}
    ]
  }}
- If the plan can be written, output this exact shape:
  {{
    "status": "ok",
    "project": "<project name>",
    "steps": [
      {{
        "step": <integer>,
        "title": "<short title>",
        "goal": "<one sentence>",
        "input": "<what must exist before this step>",
        "tasks": ["<task 1>", "<task 2>"],
        "definition_of_done": ["<criterion 1>", "<criterion 2>"]
      }}
    ]
  }}

CHUNKING RULES:
- Data layer first (schemas, migrations, models)
- Then service/business logic layer
- Then API/interface layer
- Then integration and wiring
- Then tests for each layer
- Then configuration, deployment, documentation
- One moving part per step — split if a step touches both schema and API
- Each step must be self-contained and verifiable
- Steps must be ordered so dependencies come before dependents
- Do not include steps for things not in the design
- Do not mix unrelated concerns in one step
""".strip()

SETUP_PROMPT = """
You are a Setup Config Extractor. Read the technical design and extract all
information needed to set up the build environment and external services.

TECHNICAL DESIGN:
{design}

OUTPUT RULES:
- Output ONLY a single valid JSON object. No markdown, no explanation, no code fences.
- Extract every tool, version, credential placeholder, environment variable,
  and configuration choice mentioned in the design.
- For secrets and passwords use placeholder strings like "<REPLACE_WITH_DB_PASSWORD>"
  so the operator knows they must fill these in before running setup.
- Output this exact shape:
  {{
    "status": "ok",
    "project": "<project name>",
    "system": {{
      "os": "<target OS>",
      "run_as": "<user, e.g. root>"
    }},
    "tools": [
      {{
        "name": "<tool name>",
        "version": "<pinned version or 'latest stable'>",
        "install_method": "<apt | cargo | wget | build_from_source | pip | npm>",
        "install_notes": "<any special steps from the design>",
        "validate_cmd": "<command to confirm install succeeded>",
        "validate_expect": "<expected output or substring>"
      }}
    ],
    "services": [
      {{
        "name": "<service name e.g. postgresql>",
        "config_files": [
          {{
            "path": "<absolute path>",
            "notes": "<what to configure and why>"
          }}
        ],
        "systemd_unit": "<unit name or null>",
        "validate_cmd": "<command to confirm service is healthy>",
        "validate_expect": "<expected output or substring>"
      }}
    ],
    "env_vars": [
      {{
        "name": "<VAR_NAME>",
        "description": "<what it is used for>",
        "secret": <true|false>,
        "default": "<default value or null>",
        "value": "<actual value or placeholder like <REPLACE_ME>>"
      }}
    ],
    "project_dirs": [
      {{
        "name": "<logical name e.g. api_server>",
        "path": "<absolute path on VPS>",
        "notes": "<what lives here>"
      }}
    ]
  }}
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

def call_claude(prompt: str, label: str) -> str:
    log.info(f"Calling claude [{label}]...")
    try:
        result = subprocess.run(
            ["claude", "--print", "--dangerously-skip-permissions", prompt],
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log.error(f"Claude timed out after {CLAUDE_TIMEOUT}s")
        sys.exit(1)
    except FileNotFoundError:
        log.error("claude CLI not found — is it installed and on PATH?")
        sys.exit(1)

    if result.returncode != 0:
        log.warning(f"claude exited {result.returncode}: {result.stderr.strip()}")

    return result.stdout.strip()


def extract_json(raw: str) -> dict:
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
    text = match.group(1).strip() if match else raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse JSON: {e}")
        log.error(f"Raw output:\n{raw[:500]}")
        sys.exit(1)


def save_raw(raw: str, filename: str):
    Path(filename).write_text(raw)
    log.info(f"Raw output saved to {filename}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Planner Agent")
    parser.add_argument("design",    help="Path to technical design markdown file")
    parser.add_argument("--plan",    default=DEFAULT_PLAN,   help="Build plan output path")
    parser.add_argument("--config",  default=DEFAULT_CONFIG, help="Setup config output path")
    args = parser.parse_args()

    design_path = Path(args.design)
    if not design_path.exists():
        log.error(f"Design file not found: {design_path}")
        sys.exit(1)

    design = design_path.read_text()
    log.info(f"Design  : {design_path} ({len(design)} chars)")
    log.info(f"Plan    : {args.plan}")
    log.info(f"Config  : {args.config}")

    # --- Build plan ---
    raw_plan = call_claude(PLAN_PROMPT.format(design=design), "build plan")
    save_raw(raw_plan, "planner_raw_plan.txt")
    plan = extract_json(raw_plan)

    if plan.get("status") == "blocked":
        log.error("\nPlanner found blockers — cannot produce a build plan.")
        log.error("Resolve the following before re-running:\n")
        for b in plan.get("blockers", []):
            log.error(f"  [{b['id']}] {b['description']}")
        sys.exit(1)

    if plan.get("status") != "ok":
        log.error(f"Unexpected plan status: {plan.get('status')}")
        sys.exit(1)

    plan["generated_at"]  = datetime.now().isoformat()
    plan["source_design"] = str(design_path)

    Path(args.plan).write_text(json.dumps(plan, indent=2))
    log.info(f"\nBuild plan: {len(plan['steps'])} steps")
    for s in plan["steps"]:
        log.info(f"  Step {s['step']:02d}: {s['title']}")

    # --- Setup config ---
    raw_config = call_claude(SETUP_PROMPT.format(design=design), "setup config")
    save_raw(raw_config, "planner_raw_config.txt")
    config = extract_json(raw_config)

    if config.get("status") != "ok":
        log.error(f"Unexpected config status: {config.get('status')}")
        sys.exit(1)

    config["generated_at"]  = datetime.now().isoformat()
    config["source_design"] = str(design_path)
    config["install_results"] = []   # setup.py will populate this

    Path(args.config).write_text(json.dumps(config, indent=2))
    log.info(f"\nSetup config: {len(config['tools'])} tools, "
             f"{len(config['services'])} services, "
             f"{len(config['env_vars'])} env vars")

    # Warn about secrets that need filling in
    secrets = [v for v in config["env_vars"] if v["secret"] and "<REPLACE" in str(v.get("value", ""))]
    if secrets:
        log.warning(f"\n  {len(secrets)} secret(s) need values before running setup.py:")
        for s in secrets:
            log.warning(f"    {s['name']}: {s['description']}")
        log.warning(f"  Edit {args.config} and fill in these values first.\n")

    log.info(f"\nNext steps:")
    log.info(f"  1. Fill in secrets in {args.config}")
    log.info(f"  2. python setup.py --config {args.config}")
    log.info(f"  3. python orchestrator.py --plan {args.plan} --config {args.config}")


if __name__ == "__main__":
    main()
