#!/usr/bin/env bash
#
# Why Academy — evolution agent orchestrator
#
# Reads open feedback issues, invokes Claude Code with the EVOLUTION_PROMPT,
# validates the output with sympy/numpy, commits and pushes if it passes,
# closes the addressed issues, and appends to EVOLUTION_LOG.md.
#
# AI proposes, SymPy disposes. Fails closed on validation error.
#
# Usage:
#   ./meta/evolve.sh                  # process all open feedback issues
#   ./meta/evolve.sh --dry-run        # do everything except git commit/push and issue close
#   ./meta/evolve.sh --max-issues N   # only process up to N issues
#
# Exit codes:
#   0  - success (or no issues to process)
#   1  - validation failed (changes reverted)
#   2  - claude invocation failed
#   3  - git operation failed
#   4  - lock held (another run in progress)
#   5  - prerequisite missing (gh, claude, python3, sympy, etc.)

set -uo pipefail

# ── Config ──
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_FILE="${PROJECT_ROOT}/meta/.evolve.lock"
LOG_FILE="${PROJECT_ROOT}/meta/EVOLUTION_LOG.md"
PROMPT_FILE="${PROJECT_ROOT}/meta/EVOLUTION_PROMPT.md"
VALIDATOR="${PROJECT_ROOT}/meta/validate.py"
BRIEF_FILE="${PROJECT_ROOT}/why-academy-brief.md"
FEEDBACK_DUMP="/tmp/why-academy-feedback-issues.json"
REPO="vgainullin/why-academy"
DRY_RUN=0
MAX_ISSUES=50

# ── Args ──
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --max-issues) MAX_ISSUES="$2"; shift 2 ;;
        --help|-h)
            sed -n '3,20p' "${BASH_SOURCE[0]}" | sed 's/^# //; s/^#//'
            exit 0 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

# ── Helpers ──
log() {
    echo "[evolve $(date '+%H:%M:%S')] $*"
}

bail() {
    local code="$1"; shift
    log "ERROR: $*"
    cleanup
    exit "$code"
}

cleanup() {
    rm -f "$LOCK_FILE" "$FEEDBACK_DUMP"
}

trap 'cleanup' EXIT INT TERM

# ── Prerequisite checks ──
log "Checking prerequisites..."

command -v gh >/dev/null 2>&1 || bail 5 "gh CLI not installed"
command -v claude >/dev/null 2>&1 || bail 5 "claude CLI not installed"
command -v python3 >/dev/null 2>&1 || bail 5 "python3 not installed"
command -v git >/dev/null 2>&1 || bail 5 "git not installed"

python3 -c "import sympy" 2>/dev/null || log "WARNING: sympy not installed (derive verification will be soft-warning only)"
python3 -c "import numpy" 2>/dev/null || bail 5 "numpy not installed (required for code block validation)"

[[ -f "$PROMPT_FILE" ]] || bail 5 "missing $PROMPT_FILE"
[[ -f "$VALIDATOR" ]] || bail 5 "missing $VALIDATOR"
[[ -f "$BRIEF_FILE" ]] || log "WARNING: $BRIEF_FILE not found — agent will run without project brief context"

gh auth status >/dev/null 2>&1 || bail 5 "gh CLI not authenticated (run 'gh auth login')"

# ── Lock ──
if [[ -f "$LOCK_FILE" ]]; then
    pid="$(cat "$LOCK_FILE" 2>/dev/null || echo unknown)"
    bail 4 "lock file exists at $LOCK_FILE (pid $pid). Another evolve run is in progress, or a previous run crashed. Delete the lock if you're sure."
fi
echo $$ > "$LOCK_FILE"

# ── Move to project root ──
cd "$PROJECT_ROOT" || bail 3 "cannot cd to $PROJECT_ROOT"

# ── Make sure git is clean ──
if [[ -n "$(git status --porcelain)" ]]; then
    bail 3 "working tree is dirty. Commit or stash before running evolve.sh:
$(git status --short)"
fi

# ── Pull latest ──
log "Pulling latest from origin..."
git pull --ff-only origin main >/dev/null 2>&1 || bail 3 "git pull failed (not fast-forward?)"

# ── Fetch open feedback issues ──
log "Fetching open feedback issues..."
gh issue list \
    --repo "$REPO" \
    --label feedback \
    --state open \
    --limit "$MAX_ISSUES" \
    --json number,title,body,createdAt,labels \
    > "$FEEDBACK_DUMP" 2>/dev/null || bail 3 "failed to fetch issues"

issue_count="$(python3 -c "import json; print(len(json.load(open('$FEEDBACK_DUMP'))))")"

if [[ "$issue_count" -eq 0 ]]; then
    log "No open feedback issues. Nothing to do."
    cleanup
    exit 0
fi

log "Found $issue_count feedback issue(s) to process"

# Extract issue numbers we'll be processing — used later to close them
issue_numbers="$(python3 -c "
import json
issues = json.load(open('$FEEDBACK_DUMP'))
print(' '.join(str(i['number']) for i in issues))
")"
log "Processing issues: $issue_numbers"

# ── Snapshot HEAD so we can revert on validation failure ──
INITIAL_HEAD="$(git rev-parse HEAD)"
log "Initial HEAD: $INITIAL_HEAD"

# ── Build the prompt ──
# We pass a short user message that points Claude at the prompt file and inputs.
# Claude reads everything else with its tools.
USER_MESSAGE="You are running as the Why Academy evolution agent.

Read these files in this order, then act:
  1. \`meta/EVOLUTION_PROMPT.md\` — your full instructions and constraints
  2. \`why-academy-brief.md\` — the project vision (gitignored, server-local)
  3. \`lessons/*.json\` — every existing lesson
  4. \`meta/EVOLUTION_LOG.md\` — your past actions
  5. \`$FEEDBACK_DUMP\` — the open student feedback issues you must respond to

Then:
  - Decide: patch existing lesson(s), add a new block, or generate a new lesson
  - Make the changes by editing or creating files in \`lessons/\`
  - Run \`python3 meta/validate.py\` and iterate until it passes
  - Append a short entry to \`meta/EVOLUTION_LOG.md\` describing what you did

Do not commit or push. Do not modify files outside \`lessons/\` and \`meta/EVOLUTION_LOG.md\`.

The orchestrator will validate, commit, and push after you finish.
Begin."

# ── Invoke Claude Code ──
log "Invoking Claude Code (this may take a few minutes)..."
log "  Allowed tools: Read, Edit, Write, Glob, Grep, Bash"
log "  Max turns: 60"

CLAUDE_OUTPUT_LOG="${PROJECT_ROOT}/meta/.evolve-last-run.log"

if ! claude \
    -p "$USER_MESSAGE" \
    --allowedTools "Read,Edit,Write,Glob,Grep,Bash" \
    --max-turns 60 \
    > "$CLAUDE_OUTPUT_LOG" 2>&1
then
    log "Claude invocation failed. See $CLAUDE_OUTPUT_LOG"
    tail -30 "$CLAUDE_OUTPUT_LOG" >&2
    git reset --hard "$INITIAL_HEAD" >/dev/null 2>&1
    bail 2 "claude failed"
fi

log "Claude finished. Output saved to $CLAUDE_OUTPUT_LOG"

# ── Detect what changed ──
changed_files="$(git diff --name-only HEAD)"
new_files="$(git ls-files --others --exclude-standard)"

if [[ -z "$changed_files" && -z "$new_files" ]]; then
    log "Claude made no file changes. Treating as no-op success."
    log "Last 20 lines of Claude output:"
    tail -20 "$CLAUDE_OUTPUT_LOG"
    cleanup
    exit 0
fi

log "Changed files:"
[[ -n "$changed_files" ]] && echo "$changed_files" | sed 's/^/  M /'
[[ -n "$new_files" ]] && echo "$new_files" | sed 's/^/  A /'

# ── Sanity check: only allowed paths touched ──
all_changed="$(echo -e "$changed_files\n$new_files" | grep -v '^$' || true)"
disallowed="$(echo "$all_changed" | grep -vE '^(lessons/|meta/EVOLUTION_LOG\.md$)' || true)"

if [[ -n "$disallowed" ]]; then
    log "ERROR: Claude touched files outside lessons/ and meta/EVOLUTION_LOG.md:"
    echo "$disallowed" | sed 's/^/    /'
    git reset --hard "$INITIAL_HEAD" >/dev/null 2>&1
    bail 1 "out-of-scope file changes — reverted"
fi

# ── Validate ──
log "Running validator..."
if ! python3 "$VALIDATOR" 2>&1 | tee /tmp/why-academy-validate.log; then
    log "Validation FAILED. Reverting changes."
    git reset --hard "$INITIAL_HEAD" >/dev/null 2>&1
    git clean -fd lessons/ meta/ >/dev/null 2>&1

    # Comment on the issues so the next run knows
    for n in $issue_numbers; do
        gh issue comment "$n" --repo "$REPO" --body "The evolution agent attempted to address this issue but the generated content failed validation. Run output:

\`\`\`
$(tail -30 /tmp/why-academy-validate.log)
\`\`\`

The changes have been reverted. The issue remains open." >/dev/null 2>&1 || true
    done
    bail 1 "validation failed — changes reverted"
fi

log "Validator passed."

# ── Commit ──
COMMIT_TITLE="Evolution agent: address $issue_count feedback issue(s)"
COMMIT_BODY="$(cat <<EOF
Issues addressed: $(echo "$issue_numbers" | tr ' ' ',')

Files changed:
$(echo "$all_changed" | sed 's/^/  /')

Generated by meta/evolve.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
)"

if [[ "$DRY_RUN" -eq 1 ]]; then
    log "DRY RUN — would commit and push but stopping here."
    log "Commit message:"
    echo "$COMMIT_TITLE"
    echo
    echo "$COMMIT_BODY"
    log "Run without --dry-run to actually commit."
    cleanup
    exit 0
fi

log "Committing..."
git add lessons/ meta/EVOLUTION_LOG.md 2>/dev/null
git commit -m "$COMMIT_TITLE" -m "$COMMIT_BODY" >/dev/null || bail 3 "git commit failed"

NEW_HEAD="$(git rev-parse HEAD)"
log "Committed: $NEW_HEAD"

log "Pushing..."
if ! git push origin main >/dev/null 2>&1; then
    log "git push failed. Resetting to initial HEAD."
    git reset --hard "$INITIAL_HEAD" >/dev/null 2>&1
    bail 3 "git push failed — reverted"
fi
log "Pushed to origin."

# ── Close addressed issues ──
log "Closing addressed issues..."
for n in $issue_numbers; do
    gh issue close "$n" --repo "$REPO" >/dev/null 2>&1 \
        && log "  closed #$n" \
        || log "  WARN: failed to close #$n (may need manual close)"

    # Comment with link to the commit
    gh issue comment "$n" --repo "$REPO" --body "Addressed by evolution agent in commit $NEW_HEAD." >/dev/null 2>&1 || true
done

# ── Done ──
log "DONE. Evolved $issue_count issue(s) into commit $NEW_HEAD"
cleanup
exit 0
