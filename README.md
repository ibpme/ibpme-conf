# ibpme-conf

Personal configs synced across machines. Entry point: `ibpme-conf.py` (Python ≥3.12, stdlib only, run via `uv`).

## Quick install

Requires [`uv`](https://docs.astral.sh/uv/) and `git`. Clones into `./ibpme-conf` (asks first), installs `ibpme-conf` to `~/.local/bin`, then syncs:

```sh
curl -fsSL https://raw.githubusercontent.com/ibpme/ibpme-conf/main/ibpme-conf.py | uv run --script - self install
```

Add `--dir ~/src` to clone into `~/src/ibpme-conf` without the prompt.

## Usage

```sh
./ibpme-conf.py check [tmux|zsh|agents]   # report installed tools and versions
./ibpme-conf.py sync [tmux|agents]        # check, then sync
./ibpme-conf.py unsync [tmux|agents]      # undo sync, restoring backups
./ibpme-conf.py self info                 # repo path, remote, branch, commit, clean/dirty
./ibpme-conf.py self sync                 # symlink the script to ~/.local/bin/ibpme-conf
./ibpme-conf.py self install [--dir DIR]  # clone, then self update
./ibpme-conf.py self uninstall [-a]      # unsync all, remove the bin link; -a also deletes this clone
./ibpme-conf.py self update               # git pull --ff-only, self sync, then sync
```

`sync` runs `check` for each target first. With no target it is best-effort: a target that fails its checks is skipped with a warning. A named target that fails exits 1. Pass `--no-checks` to skip the checks. `self update` takes `--no-checks` too, plus `--no-sync` to skip the config sync (the install still runs).

`unsync` only removes what `sync` created (links to this repo, or a `~/.tmux.conf` identical to the repo copy) and restores the newest backup. `self uninstall -a` asks before deleting the clone (`-y` skips the prompt).

## Targets

| Target | Requires | Sync method |
|---|---|---|
| `tmux` | tmux, [tpm](https://github.com/tmux-plugins/tpm) | copies `tmux/tmux.conf` to `~/.tmux.conf` |
| `agents` | claude, pi, codex, jq | symlinks `agents/context/GLOBAL.md` to each installed agent's global instructions file; for claude, also symlinks `agents/claude/statusline.sh` to `~/.claude/statusline-command.sh` (`settings.json` is never modified; sync warns if its `statusLine` doesn't reference `statusline-command.sh`) |

Existing files are never overwritten: they are renamed aside (`.bak-<timestamp>` for copies, `.pre-ibpme-conf.<timestamp>` for symlinks).

After syncing tmux, reload it and press `prefix + I` to install plugins.

## Layout

```
ibpme-conf.py   entry point
tmux/           tmux.conf (OS differences handled inside via if-shell)
agents/context/ GLOBAL.md shared by all coding agents
agents/claude/  statusline.sh, the Claude Code status line (macOS and Linux)
nvim/           (empty)
scripts/        standalone helper scripts
```
