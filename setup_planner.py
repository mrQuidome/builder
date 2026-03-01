#!/usr/bin/env python3
"""
Setup Planner Agent

Reads a technical design markdown file and produces the setup configuration:
  - setup_config.json   all tools, versions, credentials, env vars

Usage:
    python setup_planner.py design.md
    python setup_planner.py design.md --config my_config.json

Requirements:
    claude CLI must be installed and authenticated on this machine.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from planner_common import call_claude, extract_json, save_raw, setup_logging

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = "setup_config.json"

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SETUP_PROMPT = """
You are a Setup Config Extractor. Read the technical design and extract all
information needed to set up the build environment and external services.

TECHNICAL DESIGN:
{design}

OUTPUT RULES:
- Output ONLY a single valid JSON object. No markdown, no explanation, no code fences.
- Extract every tool, version, credential placeholder, environment variable,
  and configuration choice mentioned in the design.
- For each secret, classify its source:
  - "generate" — the setup agent can create this itself (database passwords,
    JWT signing keys, database connection strings, any secret that does not
    come from an external provider). Use value "<AUTO_GENERATE>".
  - "external" — requires credentials from a third-party service that the
    human operator must supply (OAuth client secrets, payment API keys,
    App Store / Play Store credentials, etc.). Use value "<REPLACE_WITH_...>".
- Non-secret env vars keep their concrete default values as usual.
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
        "source": "<generate|external|static>",
        "default": "<default value or null>",
        "value": "<AUTO_GENERATE | <REPLACE_WITH_...> | concrete value>"
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
# Main
# ---------------------------------------------------------------------------

def main():
    log = setup_logging("setup_planner.log")

    parser = argparse.ArgumentParser(description="Setup Planner Agent — setup config generator")
    parser.add_argument("design", help="Path to technical design markdown file")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="Setup config output path")
    args = parser.parse_args()

    design_path = Path(args.design)
    if not design_path.exists():
        log.error(f"Design file not found: {design_path}")
        sys.exit(1)

    design = design_path.read_text()
    log.info(f"Design  : {design_path} ({len(design)} chars)")
    log.info(f"Config  : {args.config}")

    # --- Setup config ---
    raw_config = call_claude(SETUP_PROMPT.format(design=design), "setup_config", log)
    save_raw(raw_config, "planner_raw_config.txt", log)
    config = extract_json(raw_config, log)

    if config.get("status") != "ok":
        log.error(f"Unexpected config status: {config.get('status')}")
        sys.exit(1)

    config["generated_at"] = datetime.now().isoformat()
    config["source_design"] = str(design_path)
    config["install_results"] = []   # setup.py will populate this

    Path(args.config).write_text(json.dumps(config, indent=2))
    log.info(f"\nSetup config: {len(config['tools'])} tools, "
             f"{len(config['services'])} services, "
             f"{len(config['env_vars'])} env vars")

    # Count auto-generate vs external secrets
    auto = [v for v in config["env_vars"] if v.get("source") == "generate"]
    external = [v for v in config["env_vars"] if v.get("source") == "external"]

    if auto:
        log.info(f"\n  {len(auto)} secret(s) will be auto-generated by setup.py:")
        for s in auto:
            log.info(f"    {s['name']}: {s['description']}")

    if external:
        log.warning(f"\n  {len(external)} secret(s) require external credentials:")
        for s in external:
            log.warning(f"    {s['name']}: {s['description']}")
        log.warning(f"  Edit {args.config} and fill in these values first.\n")

    log.info(f"\nDone. Next:")
    if external:
        log.info(f"  1. Fill in external secrets in {args.config}")
        log.info(f"  2. python setup.py --config {args.config}")
    else:
        log.info(f"  python setup.py --config {args.config}")


if __name__ == "__main__":
    main()
