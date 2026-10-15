#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Entry point for syncing configs across machines."""

import argparse
import filecmp
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent

HOME = Path.home()

# tool -> (label, path) of the extras that must be present alongside it
EXTRAS: dict[str, tuple[str, Path]] = {
    "tmux": ("tpm", HOME / ".tmux" / "plugins" / "tpm"),
    "zsh": ("oh-my-zsh", Path(os.environ.get("ZSH", HOME / ".oh-my-zsh"))),
}


AGENTS = ("claude", "pi", "codex")

VERSION_CMDS = {"tmux": ["tmux", "-V"], "zsh": ["zsh", "--version"]}


def run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def report(label: str, found: str | Path | None, version: str = "") -> bool:
    detail = " ".join(x for x in (version, f"({found})" if found else "") if x)
    print(f"{'ok' if found else 'missing':<8} {label}" + (f" {detail}" if detail else ""))
    return found is not None


def check_tool(tool: str) -> bool:
    label, path = EXTRAS[tool]
    installed = report(tool, shutil.which(tool), run(VERSION_CMDS[tool]))
    # tpm and oh-my-zsh are git clones and have no version command
    commit = run(["git", "-C", str(path), "rev-parse", "--short", "HEAD"]) if path.is_dir() else ""
    extra = report(label, path if path.is_dir() else None, f"@{commit}" if commit else "")
    return installed and extra


def check_agents() -> bool:
    results = [
        report(a, shutil.which(a), run([a, "--version"]).splitlines()[0] if shutil.which(a) else "")
        for a in AGENTS
    ]
    return all(results)


def cmd_check(targets: list[str]) -> int:
    results = [check_agents() if t == "agents" else check_tool(t) for t in targets]
    return 0 if all(results) else 1


def copy_config(src: Path, dst: Path) -> None:
    if dst.is_file() and not dst.is_symlink() and filecmp.cmp(src, dst, shallow=False):
        print(f"unchanged {dst}")
        return
    if dst.is_symlink():
        dst.unlink()
    elif dst.exists():
        bak = dst.with_name(f"{dst.name}.bak-{datetime.now():%Y%m%d%H%M%S}")
        dst.rename(bak)
        print(f"backup    {bak}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    print(f"copied    {src} -> {dst}")


def link_one(src: Path, dst: Path) -> None:
    """Symlink dst -> src, renaming anything already at dst aside first."""
    if dst.is_symlink() and dst.readlink() == src:
        print(f"unchanged {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        bak = dst.with_name(f"{dst.name}.pre-ibpme-conf.{datetime.now():%Y%m%dT%H%M%S}")
        dst.rename(bak)
        print(f"backup    {bak}")
    dst.symlink_to(src)
    print(f"linked    {dst} -> {src}")


# agent -> where its global instructions file lives
AGENT_CONTEXT_FILES: dict[str, Path] = {
    "claude": HOME / ".claude" / "CLAUDE.md",
    "codex": HOME / ".codex" / "AGENTS.md",
    "opencode": HOME / ".config" / "opencode" / "AGENTS.md",
    "pi": HOME / ".pi" / "agent" / "AGENTS.md",
}


def sync_tmux() -> None:
    copy_config(REPO / "tmux" / "tmux.conf", HOME / ".tmux.conf")


def sync_agents() -> None:
    src = REPO / "agents" / "context" / "GLOBAL.md"
    for agent, dst in AGENT_CONTEXT_FILES.items():
        if not shutil.which(agent):
            print(f"skip      {agent} (not installed)")
            continue
        link_one(src, dst)


SYNCS = {"tmux": sync_tmux, "agents": sync_agents}


def cmd_sync(targets: list[str], run_checks: bool, explicit: bool) -> int:
    """General sync is best-effort: targets failing their checks only warn.
    An explicitly named target that fails its checks is an error."""
    blocked = 0
    for t in targets:
        if run_checks and cmd_check([t]) != 0:
            print(f"warning: skipping {t}, checks failed (use --no-checks to override)\n", file=sys.stderr)
            blocked += 1
            continue
        SYNCS[t]()
        print()
    return 1 if explicit and blocked else 0


def git(*args: str) -> str:
    return run(["git", "-C", str(REPO), *args])


def cmd_self_info() -> int:
    dirty = git("status", "--porcelain")
    rows = {
        "path": str(REPO),
        "remote": git("remote", "get-url", "origin") or "none",
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "commit": git("log", "-1", "--format=%h %ad %s", "--date=short") or "none",
        "state": "dirty" if dirty else "clean",
    }
    for key, value in rows.items():
        print(f"{key:<8} {value}")
    return 0


def cmd_self_update(run_checks: bool, run_sync: bool) -> int:
    if subprocess.run(["git", "-C", str(REPO), "pull", "--ff-only"]).returncode != 0:
        print("error: git pull failed, not syncing", file=sys.stderr)
        return 1
    if not run_sync:
        return 0
    # re-run as a new process so a freshly pulled version of this script does the sync
    cmd = [sys.executable, str(Path(__file__).resolve()), "sync"] + ([] if run_checks else ["--no-checks"])
    return subprocess.run(cmd).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    check = sub.add_parser("check", help="check required tools are installed")
    targets = [*EXTRAS, "agents"]
    check.add_argument(
        "target", nargs="?", choices=targets, help="limit to one (tmux: +tpm, zsh: +oh-my-zsh, agents: claude/pi/codex)"
    )
    sync = sub.add_parser("sync", help="copy repo configs over the ones on this machine")
    sync.add_argument("target", nargs="?", choices=list(SYNCS), help="limit to one config")
    sync.add_argument("--no-checks", action="store_true", help="skip the pre-sync check")
    self_cmd = sub.add_parser("self", help="utilities and metadata for this repo")
    self_sub = self_cmd.add_subparsers(dest="self_cmd", required=True)
    self_sub.add_parser("info", help="show repo path, remote, branch and commit")
    update = self_sub.add_parser("update", help="git pull this repo, then sync")
    update.add_argument("--no-checks", action="store_true", help="skip the pre-sync check")
    update.add_argument("--no-sync", action="store_true", help="only pull, don't sync")
    args = parser.parse_args()

    match args.cmd:
        case "check":
            return cmd_check([args.target] if args.target else targets)
        case "sync":
            return cmd_sync([args.target] if args.target else list(SYNCS), not args.no_checks, bool(args.target))
        case "self":
            match args.self_cmd:
                case "info":
                    return cmd_self_info()
                case "update":
                    return cmd_self_update(not args.no_checks, not args.no_sync)
    return 0


if __name__ == "__main__":
    sys.exit(main())
