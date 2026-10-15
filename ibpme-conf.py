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

# __file__ is undefined when piped via stdin (curl ... | uv run -); only `self install` works then
SCRIPT = Path(__file__).resolve() if "__file__" in globals() else Path.cwd() / "ibpme-conf.py"
REPO = SCRIPT.parent
REPO_URL = "https://github.com/ibpme/ibpme-conf.git"

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


def restore_backup(dst: Path, pattern: str) -> None:
    # timestamp suffixes sort chronologically, so the last match is the newest
    backups = sorted(dst.parent.glob(pattern))
    if backups:
        backups[-1].rename(dst)
        print(f"restored  {backups[-1]} -> {dst}")


def unlink_one(dst: Path, src: Path) -> None:
    """Remove dst only if it is a symlink to src, then restore the newest backup."""
    if not dst.is_symlink() or dst.readlink() != src:
        print(f"skip      {dst} (not our link)" if dst.exists() or dst.is_symlink() else f"absent    {dst}")
        return
    dst.unlink()
    print(f"removed   {dst}")
    restore_backup(dst, f"{dst.name}.pre-ibpme-conf.*")


def unsync_tmux() -> None:
    src, dst = REPO / "tmux" / "tmux.conf", HOME / ".tmux.conf"
    if not dst.is_file() or dst.is_symlink():
        print(f"absent    {dst}" if not dst.exists() else f"skip      {dst} (not our copy)")
    elif not filecmp.cmp(src, dst, shallow=False):
        print(f"skip      {dst} (differs from the repo copy, not removing local edits)")
    else:
        dst.unlink()
        print(f"removed   {dst}")
        restore_backup(dst, f"{dst.name}.bak-*")


def unsync_agents() -> None:
    src = REPO / "agents" / "context" / "GLOBAL.md"
    for dst in AGENT_CONTEXT_FILES.values():
        unlink_one(dst, src)


UNSYNCS = {"tmux": unsync_tmux, "agents": unsync_agents}


def cmd_unsync(targets: list[str]) -> int:
    for t in targets:
        UNSYNCS[t]()
        print()
    return 0


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


def cmd_self_sync() -> int:
    script = SCRIPT
    script.chmod(script.stat().st_mode | 0o111)
    bin_dir = HOME / ".local" / "bin"
    link_one(script, bin_dir / "ibpme-conf")
    if str(bin_dir) not in os.environ.get("PATH", "").split(os.pathsep):
        print(f"warning: {bin_dir} is not on PATH", file=sys.stderr)
    return 0


def ask(question: str) -> str:
    """Prompt on the terminal even when stdin is a pipe (curl ... | uv run -)."""
    try:
        with open("/dev/tty", "r+") as tty:
            tty.write(question)
            tty.flush()
            return tty.readline()
    except OSError:
        return ""


def cmd_self_install(parent: Path | None) -> int:
    if parent is None:
        parent = Path.cwd()
        answer = ask(f"Clone ibpme-conf into {parent / 'ibpme-conf'}? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("aborted")
            return 1
    dest = parent.expanduser().resolve() / "ibpme-conf"
    if dest.exists():
        print(f"error: {dest} already exists", file=sys.stderr)
        return 1
    if subprocess.run(["git", "clone", REPO_URL, str(dest)]).returncode != 0:
        return 1
    return subprocess.run([sys.executable, str(dest / "ibpme-conf.py"), "self", "update"]).returncode


def cmd_self_uninstall(remove_repo: bool, yes: bool) -> int:
    if remove_repo:
        if not (SCRIPT.is_file() and (REPO / ".git").is_dir()):
            print("error: not running from a cloned repo, refusing to use -a", file=sys.stderr)
            return 1
        dirty = " (has uncommitted changes!)" if git("status", "--porcelain") else ""
        if not yes and ask(f"Delete {REPO}{dirty}? [y/N] ").strip().lower() not in ("y", "yes"):
            print("aborted")
            return 1
    cmd_unsync(list(UNSYNCS))
    unlink_one(HOME / ".local" / "bin" / "ibpme-conf", SCRIPT)
    if remove_repo:
        shutil.rmtree(REPO)
        print(f"removed   {REPO}")
    return 0


def cmd_self_update(run_checks: bool, run_sync: bool) -> int:
    if subprocess.run(["git", "-C", str(REPO), "pull", "--ff-only"]).returncode != 0:
        print("error: git pull failed, not syncing", file=sys.stderr)
        return 1
    # re-run as new processes so a freshly pulled version of this script does the work
    script = [sys.executable, str(SCRIPT)]
    if subprocess.run([*script, "self", "sync"]).returncode != 0:
        return 1
    if not run_sync:
        return 0
    return subprocess.run([*script, "sync", *([] if run_checks else ["--no-checks"])]).returncode


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
    unsync = sub.add_parser("unsync", help="undo sync: remove what it created and restore backups")
    unsync.add_argument("target", nargs="?", choices=list(UNSYNCS), help="limit to one config")
    self_cmd = sub.add_parser("self", help="utilities and metadata for this repo")
    self_sub = self_cmd.add_subparsers(dest="self_cmd", required=True)
    self_sub.add_parser("info", help="show repo path, remote, branch and commit")
    self_sub.add_parser("sync", help="symlink this script into ~/.local/bin")
    uninstall = self_sub.add_parser("uninstall", help="unsync everything and remove the ~/.local/bin link")
    uninstall.add_argument("-a", "--all", action="store_true", help="also delete this cloned repo (asks first)")
    uninstall.add_argument("-y", "--yes", action="store_true", help="don't ask before deleting with -a")
    install = self_sub.add_parser("install", help="clone this repo, then self update (install + sync)")
    install.add_argument("--dir", type=Path, help="parent directory to clone into (skips the prompt)")
    update = self_sub.add_parser("update", help="git pull this repo, install it to ~/.local/bin, then sync")
    update.add_argument("--no-checks", action="store_true", help="skip the pre-sync check")
    update.add_argument("--no-sync", action="store_true", help="only pull, don't sync")
    args = parser.parse_args()

    match args.cmd:
        case "check":
            return cmd_check([args.target] if args.target else targets)
        case "sync":
            return cmd_sync([args.target] if args.target else list(SYNCS), not args.no_checks, bool(args.target))
        case "unsync":
            return cmd_unsync([args.target] if args.target else list(UNSYNCS))
        case "self":
            match args.self_cmd:
                case "info":
                    return cmd_self_info()
                case "sync":
                    return cmd_self_sync()
                case "install":
                    return cmd_self_install(args.dir)
                case "uninstall":
                    return cmd_self_uninstall(args.all, args.yes)
                case "update":
                    return cmd_self_update(not args.no_checks, not args.no_sync)
    return 0


if __name__ == "__main__":
    sys.exit(main())
