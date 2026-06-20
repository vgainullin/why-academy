#!/usr/bin/env bash
# Worktree-isolated epoch runner.
#
# Each autonomous-epoch workflow executes in its own git worktree on a
# dedicated branch, so multiple experiments can run concurrently and be
# compared before one is merged. Runtime artifacts (logs, reports,
# _evolutions/, _epoch_state.json) are gitignored and therefore fully
# isolated per worktree; only committed code/test_corpus changes travel
# when an experiment branch is merged.
#
# Usage:
#   scripts/worktree_epoch.sh launch [--base <branch>] [--queue <file>] [--reset] [--name <id>]
#   scripts/worktree_epoch.sh list
#   scripts/worktree_epoch.sh merge <name> [--base <branch>]
#   scripts/worktree_epoch.sh clean <name> | --all
#
# Naming: experiment/<config>_<timestamp>  (e.g. experiment/v5_20260620_093756)
#   <config> is the config_version from the base branch's derivations/state.json.
#   Override with --name.
#
# The shared uv venv from the launching repo is reused via DERIVATION_PYTHON,
# so worktrees don't need their own venv install.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKTREES_ROOT="${WHY_ACADEMY_WORKTREES_DIR:-$ROOT/../why-academy-worktrees}"
VENV_PY="$ROOT/derivations/.venv/bin/python"

die() {
	echo "[worktree] $*" >&2
	exit 1
}

config_version_of_base() {
	local base="$1"
	git -C "$ROOT" show "$base:derivations/state.json" 2>/dev/null |
		"$VENV_PY" -c 'import json,sys; print(json.load(sys.stdin).get("config_version","v1"))' 2>/dev/null ||
		echo "v1"
}

timestamp() { date +%Y%m%d_%H%M%S; }

worktree_path() { echo "$WORKTREES_ROOT/$1"; }

ensure_worktrees_root() {
	mkdir -p "$WORKTREES_ROOT"
}

branch_for() { echo "experiment/$1"; }

# ── launch ───────────────────────────────────────────────────────────────
cmd_launch() {
	local base="" queue="" reset=0 name_override="" dry=0
	while [[ $# -gt 0 ]]; do
		case "$1" in
		--base)
			base="$2"
			shift 2
			;;
		--queue)
			queue="$2"
			shift 2
			;;
		--reset)
			reset=1
			shift
			;;
		--name)
			name_override="$2"
			shift 2
			;;
		--dry-run)
			dry=1
			shift
			;;
		*) die "launch: unknown arg: $1" ;;
		esac
	done

	[[ -x "$VENV_PY" ]] || die "shared venv not found at $VENV_PY. Run: uv venv derivations/.venv && uv pip install -r derivations/requirements.txt --python derivations/.venv/bin/python"

	# Default base: main if it exists, else current HEAD.
	if [[ -z "$base" ]]; then
		if git -C "$ROOT" show-ref --verify --quiet refs/heads/main; then
			base="main"
		elif git -C "$ROOT" show-ref --verify --quiet refs/remotes/origin/main; then
			base="origin/main"
		else
			base="HEAD"
		fi
	fi
	git -C "$ROOT" rev-parse --verify "$base" >/dev/null 2>&1 || die "base branch '$base' does not exist"

	local cfg name
	cfg="$(config_version_of_base "$base")"
	name="${name_override:-${cfg}_$(timestamp)}"
	local branch wt
	branch="$(branch_for "$name")"
	wt="$(worktree_path "$name")"

	[[ -e "$wt" ]] && die "worktree path already exists: $wt"
	git -C "$ROOT" show-ref --verify --quiet "refs/heads/$branch" &&
		die "branch $branch already exists"

	ensure_worktrees_root
	echo "[worktree] creating worktree: $wt (branch $branch from $base)"
	git -C "$ROOT" worktree add -b "$branch" "$wt" "$base"

	# Commit any uncommitted tracked changes carried from the base working tree
	# into the experiment branch so the worktree starts clean. (git worktree add
	# from a branch ref doesn't copy uncommitted changes, so this is usually a
	# no-op; included for safety.)
	if ! git -C "$wt" diff --quiet || ! git -C "$wt" diff --cached --quiet; then
		git -C "$wt" add -A
		git -C "$wt" commit -m "experiment $name: carry base working-tree changes" >/dev/null
	fi

	# Hand off to the real epoch runner inside the worktree. DERIVATION_PYTHON
	# points at the shared venv so the worktree doesn't need its own install.
	local epoch_args=()
	[[ $reset -eq 1 ]] && epoch_args+=(--reset)
	[[ -n "$queue" ]] && epoch_args+=(--queue "$queue")

	echo "[worktree] launching epoch in $wt"
	echo "[worktree]   base=$base  branch=$branch  config=$cfg"
	echo "[worktree]   args: ${epoch_args[*]:-(resume)}"

	if [[ $dry -eq 1 ]]; then
		echo "[worktree] --dry-run: worktree created, skipping epoch"
		echo "[worktree] worktree: $wt"
		echo "[worktree] branch:   $branch"
		echo "[worktree] resume:   scripts/worktree_epoch.sh launch --name $name"
		return 0
	fi

	# Run the epoch. We don't `exec` so a failure still leaves the worktree in
	# place for inspection; the user can resume by re-running launch --name.
	local rc=0
	(cd "$wt" && DERIVATION_PYTHON="$VENV_PY" bash scripts/autonomous_epoch.sh "${epoch_args[@]}") || rc=$?

	echo "[worktree] epoch exited rc=$rc"
	echo "[worktree] worktree: $wt"
	echo "[worktree] branch:   $branch"
	echo "[worktree] resume:   scripts/worktree_epoch.sh launch --name $name"
	return "$rc"
}

# ── list ─────────────────────────────────────────────────────────────────
cmd_list() {
	ensure_worktrees_root
	printf '%-28s %-10s %-14s %-8s %s\n' "NAME" "PHASE" "EPOCH" "VDONE" "PATH"
	local found=0
	while IFS= read -r line; do
		# git worktree list --porcelain: lines like "worktree /path"
		[[ "$line" == worktree\ * ]] || continue
		local wt="${line#worktree }"
		[[ "$wt" == "$ROOT" ]] && continue
		local branch
		branch="$(git -C "$wt" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")"
		[[ "$branch" == experiment/* ]] || continue
		local name="${branch#experiment/}"
		local phase="?" epoch="?" vdone="?"
		local es="$wt/derivations/_epoch_state.json"
		if [[ -f "$es" ]]; then
			phase="$("$VENV_PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("phase","?"))' "$es" 2>/dev/null || echo "?")"
		fi
		local st="$wt/derivations/state.json"
		if [[ -f "$st" ]]; then
			epoch="$("$VENV_PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("epoch","?"))' "$st" 2>/dev/null || echo "?")"
			vdone="$("$VENV_PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("validator_version","?"))' "$st" 2>/dev/null || echo "?")"
		fi
		printf '%-28s %-10s %-14s %-8s %s\n' "$name" "$phase" "epoch=$epoch" "v=$vdone" "$wt"
		found=1
	done < <(git -C "$ROOT" worktree list --porcelain)
	[[ $found -eq 0 ]] && echo "(no experiment worktrees)"
}

# ── merge ────────────────────────────────────────────────────────────────
cmd_merge() {
	local name="" base=""
	while [[ $# -gt 0 ]]; do
		case "$1" in
		--base)
			base="$2"
			shift 2
			;;
		--base=*)
			base="${1#--base=}"
			shift
			;;
		*) [[ -z "$name" ]] && name="$1" && shift || die "merge: unexpected arg: $1" ;;
		esac
	done
	[[ -n "$name" ]] || die "merge: name required (e.g. v5_20260620_093756)"
	local branch="experiment/$name"
	local wt
	wt="$(worktree_path "$name")"
	git -C "$ROOT" show-ref --verify --quiet "refs/heads/$branch" ||
		die "branch $branch does not exist"

	# Commit any uncommitted tracked changes in the worktree so they travel
	# with the merge. Runtime artifacts are gitignored and won't be included.
	if [[ -d "$wt" ]]; then
		if ! git -C "$wt" diff --quiet || ! git -C "$wt" diff --cached --quiet; then
			echo "[worktree] committing pending changes in $name"
			git -C "$wt" add -A
			git -C "$wt" commit -m "experiment $name: epoch results (auto-commit on merge)" >/dev/null
		fi
	fi

	# Determine the merge target. Default: the base the experiment branched
	# from is recorded via the branch's merge-base; we merge into the current
	# branch of the main repo unless --base is given.
	local target
	if [[ -n "$base" ]]; then
		target="$base"
	else
		target="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
	fi
	echo "[worktree] merging $branch into $target (in $ROOT)"

	# If a target branch was specified and it's not the current checkout,
	# check it out in the main worktree first.
	if [[ -n "$base" && "$base" != "$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)" ]]; then
		git -C "$ROOT" checkout "$base"
	fi

	git -C "$ROOT" merge --no-ff "$branch" -m "Merge experiment $name into $target"
	echo "[worktree] merged. run 'scripts/worktree_epoch.sh clean $name' to remove the worktree."
}

# ── clean ────────────────────────────────────────────────────────────────
cmd_clean() {
	local target="${1:-}"
	[[ -z "$target" ]] && die "clean: name or --all required"
	if [[ "$target" == "--all" ]]; then
		while IFS= read -r line; do
			[[ "$line" == worktree\ * ]] || continue
			local wt="${line#worktree }"
			[[ "$wt" == "$ROOT" ]] && continue
			local branch
			branch="$(git -C "$wt" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")"
			[[ "$branch" == experiment/* ]] || continue
			local name="${branch#experiment/}"
			echo "[worktree] removing $name ($wt)"
			git -C "$ROOT" worktree remove --force "$wt" 2>/dev/null || rm -rf "$wt"
			git -C "$ROOT" branch -D "$branch" 2>/dev/null || true
		done < <(git -C "$ROOT" worktree list --porcelain)
		return
	fi
	local name="$target"
	local branch="experiment/$name"
	local wt
	wt="$(worktree_path "$name")"
	if [[ -d "$wt" ]]; then
		echo "[worktree] removing worktree $name ($wt)"
		git -C "$ROOT" worktree remove --force "$wt" 2>/dev/null || rm -rf "$wt"
	fi
	if git -C "$ROOT" show-ref --verify --quiet "refs/heads/$branch"; then
		git -C "$ROOT" branch -D "$branch"
	fi
	echo "[worktree] cleaned $name"
}

# ── main ─────────────────────────────────────────────────────────────────
[[ $# -eq 0 ]] && die "usage: $0 {launch|list|merge|clean} ..."
sub="$1"
shift
case "$sub" in
launch) cmd_launch "$@" ;;
list) cmd_list "$@" ;;
merge) cmd_merge "$@" ;;
clean) cmd_clean "$@" ;;
*) die "unknown subcommand: $sub (expected launch|list|merge|clean)" ;;
esac
