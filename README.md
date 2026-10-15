# ibpme-conf

Personal configs synced across machines. Entry point: `ibpme-conf.py` (Python ≥3.12, stdlib only, run via `uv`).

## Usage

```sh
./ibpme-conf.py check [tmux|zsh|agents]   # report installed tools and versions
./ibpme-conf.py sync [tmux|agents]        # check, then sync
./ibpme-conf.py self info                 # repo path, remote, branch, commit, clean/dirty
./ibpme-conf.py self update               # git pull --ff-only, then sync
```

`sync` runs `check` for each target first. With no target it is best-effort: a target that fails its checks is skipped with a warning. A named target that fails exits 1. Pass `--no-checks` to skip the checks. `self update` takes `--no-checks` too, plus `--no-sync` to only pull.

## Targets

| Target | Requires | Sync method |
|---|---|---|
| `tmux` | tmux, [tpm](https://github.com/tmux-plugins/tpm) | copies `tmux/tmux.conf` to `~/.tmux.conf` |
| `agents` | claude, pi, codex | symlinks `agents/context/GLOBAL.md` to each installed agent's global instructions file |

Existing files are never overwritten: they are renamed aside (`.bak-<timestamp>` for copies, `.pre-ibpme-conf.<timestamp>` for symlinks).

After syncing tmux, reload it and press `prefix + I` to install plugins.

## Layout

```
ibpme-conf.py   entry point
tmux/           tmux.conf (OS differences handled inside via if-shell)
agents/context/ GLOBAL.md shared by all coding agents
nvim/           (empty)
scripts/        standalone helper scripts
```
