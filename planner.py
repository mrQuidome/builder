#!/usr/bin/env python3
"""
Planner Agent

Reads functional and technical design docs and produces a sequenced build plan.

Usage:
    python planner.py functional_design.md technical_design.md
    python planner.py functional_design.md technical_design.md --plan build_plan.json --log-dir /tmp/logs

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

DEFAULT_PLAN = "build_plan.json"

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
    parser = argparse.ArgumentParser(description="Planner Agent — build plan generator")
    parser.add_argument("design_docs", nargs="+", help="Paths to design markdown files")
    parser.add_argument("--plan", default=DEFAULT_PLAN, help="Build plan output path")
    parser.add_argument("--log-dir", default=None, help="Directory for log files")
    args = parser.parse_args()

    log = setup_logging("planner.log", log_dir=args.log_dir)

    # Read and concatenate all design docs
    design_parts = []
    for doc_path_str in args.design_docs:
        doc_path = Path(doc_path_str)
        if not doc_path.exists():
            log.error(f"Design file not found: {doc_path}")
            sys.exit(1)
        content = doc_path.read_text()
        design_parts.append(f"# --- {doc_path.name} ---\n\n{content}")
        log.info(f"Design  : {doc_path} ({len(content)} chars)")

    design = "\n\n".join(design_parts)
    log.info(f"Plan    : {args.plan}")

    # --- Build plan ---
    raw_plan = call_claude(PLAN_PROMPT.format(design=design), "build_plan", log,
                           log_dir=args.log_dir)
    save_raw(raw_plan, "planner_raw_plan.txt", log, log_dir=args.log_dir)
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
    plan["source_designs"] = args.design_docs

    Path(args.plan).write_text(json.dumps(plan, indent=2))
    log.info(f"\nBuild plan: {len(plan['steps'])} steps")
    for s in plan["steps"]:
        log.info(f"  Step {s['step']:02d}: {s['title']}")

    log.info(f"\nDone. Next: python setup_planner.py {' '.join(args.design_docs)}")


if __name__ == "__main__":
    main()
