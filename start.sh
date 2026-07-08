#!/usr/bin/env bash
# Start the assistant monitor TUI (activates the venv first).
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

if [[ ! -f .venv/bin/activate ]]; then
    echo "start.sh: .venv not found — run ./install.sh or 'python -m venv .venv' first" >&2
    exit 1
fi

source .venv/bin/activate

# Reap an orphaned daemon from a prior run (e.g. a TUI that was killed before it
# could stop its child). Left alive, it would listen and speak alongside the new
# one — two mics, two voices. Newer daemons die with the TUI (PR_SET_PDEATHSIG),
# so this only ever catches stragglers from before that landed.
pkill -TERM -f "python -m assistant.app" 2>/dev/null || true

exec python -m tui "$@"
