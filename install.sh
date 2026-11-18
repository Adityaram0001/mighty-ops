#!/usr/bin/env bash
# Install the mighty-ops-system-manager skill for the current user by linking
# this clone's skill/ directory into ~/.claude/skills/. A `git pull` in the
# clone then updates the installed skill.
#
#   ./install.sh               install (or repair) the link
#   ./install.sh --uninstall   remove the link (only if it is a link)
#
# CLAUDE_SKILLS_DIR overrides the target directory (default ~/.claude/skills).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="mighty-ops-system-manager"
SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
DEST="$SKILLS_DIR/$NAME"

case "${1:-}" in
  "") ;;
  --uninstall)
    if [ -L "$DEST" ]; then
      rm "$DEST"
      echo "removed $DEST"
    else
      echo "nothing to remove: $DEST is not a symlink"
    fi
    exit 0
    ;;
  -h|--help)
    sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  *)
    echo "error: unknown option: $1 (try --help)" >&2
    exit 2
    ;;
esac

command -v python3 >/dev/null 2>&1 || { echo "error: python3 not found on PATH" >&2; exit 1; }
command -v git >/dev/null 2>&1 || echo "warning: git not found on PATH; catch-up needs git"

mkdir -p "$SKILLS_DIR"
if [ -e "$DEST" ] && [ ! -L "$DEST" ]; then
  echo "error: $DEST already exists and is not a symlink (an earlier copy?)." >&2
  echo "       Remove it, then run ./install.sh again." >&2
  exit 1
fi

ln -sfn "$HERE/skill" "$DEST"
echo "installed: $DEST -> $HERE/skill"
echo "Open a new Claude Code session, then run /$NAME init at a project root."
