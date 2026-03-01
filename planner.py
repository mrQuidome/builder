#!/usr/bin/env python3
"""
Planner Agent

Reads a technical design markdown file and produces a sequenced build plan:
  - unwalked_build_plan.json   sequential build steps for the orchestrator

Usage:
    python planner.py design.md
    python planner.py design.md --plan my_plan.json

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

DEFAULT_PLAN = "unwalked_build_plan.json"

# ---------------------------------------------------------------------------
# Prompt
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

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log = setup_logging("planner.log")

    parser = argparse.ArgumentParser(description="Planner Agent — build plan generator")
    parser.add_argument("design", help="Path to technical design markdown file")
    parser.add_argument("--plan", default=DEFAULT_PLAN, help="Build plan output path")
    args = parser.parse_args()

    design_path = Path(args.design)
    if not design_path.exists():
        log.error(f"Design file not found: {design_path}")
        sys.exit(1)

    design = design_path.read_text()
    log.info(f"Design  : {design_path} ({len(design)} chars)")
    log.info(f"Plan    : {args.plan}")

    # --- Build plan ---
    raw_plan = call_claude(PLAN_PROMPT.format(design=design), "build_plan", log)
    save_raw(raw_plan, "planner_raw_plan.txt", log)
    plan = extract_json(raw_plan, log)

    if plan.get("status") == "blocked":
        log.error("\nPlanner found blockers — cannot produce a build plan.")
        log.error("Resolve the following before re-running:\n")
        for b in plan.get("blockers", []):
            log.error(f"  [{b['id']}] {b['description']}")
        sys.exit(1)

    if plan.get("status") != "ok":
        log.error(f"Unexpected plan status: {plan.get('status')}")
        sys.exit(1)

    plan["generated_at"] = datetime.now().isoformat()
    plan["source_design"] = str(design_path)

    Path(args.plan).write_text(json.dumps(plan, indent=2))
    log.info(f"\nBuild plan: {len(plan['steps'])} steps")
    for s in plan["steps"]:
        log.info(f"  Step {s['step']:02d}: {s['title']}")

    log.info(f"\nDone. Next: python setup_planner.py {args.design}")


if __name__ == "__main__":
    main()
