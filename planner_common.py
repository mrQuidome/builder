"""
Shared utilities for planner.py and setup_planner.py.

Provides: call_claude, extract_json, save_raw, setup_logging
"""

import json
import logging
import re
import subprocess
import sys
from pathlib import Path

CLAUDE_TIMEOUT = 600


def setup_logging(log_file: str, log_dir: str | None = None) -> logging.Logger:
    """Configure and return a logger that writes to both file and stdout.

    If log_dir is provided, the log file is placed inside that directory.
    """
    if log_dir:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        log_file = str(Path(log_dir) / log_file)
    logger = logging.getLogger(log_file)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s")
        fh = logging.FileHandler(log_file)
        fh.setFormatter(fmt)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger


def restore_terminal():
    """Restore terminal to sane state after a subprocess messes it up."""
    try:
        subprocess.run(["stty", "sane"], stdin=open("/dev/tty"), check=False)
    except Exception:
        pass


def call_claude(prompt: str, label: str, log: logging.Logger,
                log_dir: str | None = None) -> str:
    """Send a prompt to the claude CLI and return its stdout."""
    slug = label.replace(" ", "_")
    if log_dir:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        stdout_path = str(Path(log_dir) / f"claude_{slug}_stdout.log")
        stderr_path = str(Path(log_dir) / f"claude_{slug}_stderr.log")
    else:
        stdout_path = f"claude_{slug}_stdout.log"
        stderr_path = f"claude_{slug}_stderr.log"
    log.info(f"Calling claude [{label}]  stdout -> {stdout_path}  stderr -> {stderr_path}")

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
            log.error(f"Claude timed out after {CLAUDE_TIMEOUT}s — check {stdout_path} and {stderr_path} for partial output")
            sys.exit(1)
        except FileNotFoundError:
            log.error("claude CLI not found — is it installed and on PATH?")
            sys.exit(1)

    if proc.returncode != 0:
        restore_terminal()
        stderr_content = Path(stderr_path).read_text().strip()
        log.warning(f"claude exited {proc.returncode}: {stderr_content}")

    output = Path(stdout_path).read_text().strip()
    return output


def extract_json(raw: str, log: logging.Logger) -> dict:
    """Extract and parse a JSON object from claude's output, handling code fences."""
    # Try matched opening + closing fences first
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
    if match:
        text = match.group(1).strip()
    else:
        # Handle opening fence with no closing fence
        match_open = re.search(r"```(?:json)?\s*\n", raw)
        text = raw[match_open.end():].strip() if match_open else raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse JSON: {e}")
        log.error(f"Raw output:\n{raw[:500]}")
        sys.exit(1)


def save_raw(raw: str, filename: str, log: logging.Logger,
             log_dir: str | None = None):
    """Save raw claude output to a file for debugging."""
    if log_dir:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        filepath = Path(log_dir) / filename
    else:
        filepath = Path(filename)
    filepath.write_text(raw)
    log.info(f"Raw output saved to {filepath}")
