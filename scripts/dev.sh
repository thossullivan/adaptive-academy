#!/usr/bin/env sh
# Run the API and the frontend dev server together in one terminal (`just dev`).
#
# Each server's output is prefixed with [api] or [web]. Ctrl-C (or SIGTERM/SIGHUP) stops
# both, and if either server exits on its own the other is stopped too, so no uvicorn or
# vite process is left behind.
#
# Environment:
#   AA_API_PORT      API port (default 8000)
#   AA_WEB_PORT      frontend port (default 5173)
#   AA_API_URL       where Vite proxies /api (default http://127.0.0.1:$AA_API_PORT)
#   AA_DEV_API_CMD   override the API command (used by the tests)
#   AA_DEV_WEB_CMD   override the frontend command (used by the tests)
#
# POSIX sh on purpose (dash on Linux, bash-as-sh on macOS): no job control, no `wait -n`.
set -u

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/.." && pwd)"
cd "$repo" || exit 1

api_port="${AA_API_PORT:-8000}"
web_port="${AA_WEB_PORT:-5173}"
AA_API_URL="${AA_API_URL:-http://127.0.0.1:$api_port}"
export AA_API_URL
# Python block-buffers stdout into a pipe; keep uvicorn's log lines live.
PYTHONUNBUFFERED=1
export PYTHONUNBUFFERED

api_cmd="${AA_DEV_API_CMD:-exec uv run uvicorn adaptive_academy.api.app:app --reload --port $api_port}"
web_cmd="${AA_DEV_WEB_CMD:-cd frontend && exec npm run dev -- --port $web_port --strictPort}"

say() { printf '[dev] %s\n' "$*"; }

if [ -z "${AA_DEV_API_CMD:-}" ] && [ ! -d .venv ]; then
	say "no .venv here yet; run \`just setup\` first." >&2
	exit 1
fi
if [ -z "${AA_DEV_WEB_CMD:-}" ] && [ ! -d frontend/node_modules ]; then
	say "frontend/node_modules is missing; run \`just setup\` first." >&2
	exit 1
fi

tmp="$(mktemp -d "${TMPDIR:-/tmp}/aa-dev.XXXXXX")"
api_pid=""
web_pid=""
api_seen=""
web_seen=""
sed_pids=""
sleep_pid=""

# Every descendant of a pid (uv -> python reloader -> worker; npm -> sh -> node). sh has no
# local variables, so print each child before recursing, which reuses $child.
descendants() {
	for child in $(pgrep -P "$1" 2>/dev/null); do
		echo "$child"
		descendants "$child"
	done
}

# Wait up to $1 tenths of a second for the remaining pids to exit, then SIGKILL the rest.
reap_or_kill() {
	tenths=$1
	shift
	i=0
	while [ "$i" -lt "$tenths" ]; do
		alive=""
		for p in "$@"; do
			kill -0 "$p" 2>/dev/null && alive="$alive $p"
		done
		[ -n "$alive" ] || return 0
		sleep 0.1
		i=$((i + 1))
	done
	# shellcheck disable=SC2086
	kill -KILL $alive 2>/dev/null
	return 0
}

# A server's descendants now, plus those seen earlier that are still alive. Once a parent
# dies its children are re-parented and can't be found from the root any more (a SIGKILLed
# uvicorn reloader leaves its worker serving), so the poll loop keeps this list current.
remember() { # remember ROOT PREVIOUS
	{
		for p in $2; do
			kill -0 "$p" 2>/dev/null && echo "$p"
		done
		descendants "$1"
	} | sort -u
}

# Signal a whole process tree at once, from a fresh snapshot plus the remembered one.
# (Without pgrep only the top pid is signalled; uv and npm forward SIGTERM to their children.)
stop_tree() { # stop_tree ROOT REMEMBERED
	[ -n "$1" ] || return 0
	pids="$(descendants "$1") $2 $1"
	# shellcheck disable=SC2086
	kill -TERM $pids 2>/dev/null
	# shellcheck disable=SC2086
	reap_or_kill 50 $pids
}

stopping=""
cleanup() {
	[ -n "$stopping" ] && return
	stopping=1
	trap '' INT TERM HUP
	[ -n "$sleep_pid" ] && kill "$sleep_pid" 2>/dev/null
	stop_tree "$api_pid" "$api_seen"
	stop_tree "$web_pid" "$web_seen"
	# The prefixers end at EOF; don't hang on one if something else still holds its FIFO.
	# shellcheck disable=SC2086
	reap_or_kill 20 $sed_pids
	wait 2>/dev/null
	rm -rf "$tmp"
}

# shellcheck disable=SC2329 # invoked from the traps below
on_signal() {
	say "stopping api and web..."
	cleanup
	exit "$1"
}
trap 'on_signal 130' INT
trap 'on_signal 143' TERM
trap 'on_signal 129' HUP
trap 'cleanup' EXIT

# One prefixer per server, reading a FIFO. The prefixers ignore SIGINT so a Ctrl-C (sent to
# the whole foreground process group) doesn't cut off the servers' shutdown lines; they
# exit on their own at EOF once the server is gone.
start() { # start NAME CMD  -> sets $started_pid to the server's pid
	mkfifo "$tmp/$1"
	(trap '' INT; exec sed "s/^/[$1] /" <"$tmp/$1") &
	sed_pids="$sed_pids $!"
	sh -c "$2" >"$tmp/$1" 2>&1 </dev/null &
	started_pid=$!
}

say "api on http://127.0.0.1:$api_port, web on http://localhost:$web_port (Ctrl-C stops both)"
start api "$api_cmd"
api_pid=$started_pid
start web "$web_cmd"
web_pid=$started_pid

# Poll instead of `wait -n` (not POSIX). Waiting on a short sleep, rather than running it in
# the foreground, lets a signal trap fire at once, and reaps exited servers so `kill -0`
# stops seeing them.
while :; do
	if ! kill -0 "$api_pid" 2>/dev/null; then
		wait "$api_pid"
		status=$?
		say "api exited (status $status); stopping web."
		break
	fi
	if ! kill -0 "$web_pid" 2>/dev/null; then
		wait "$web_pid"
		status=$?
		say "web exited (status $status); stopping api."
		break
	fi
	api_seen="$(remember "$api_pid" "$api_seen")"
	web_seen="$(remember "$web_pid" "$web_seen")"
	sleep 1 &
	sleep_pid=$!
	wait "$sleep_pid"
done
cleanup
[ "$status" -eq 0 ] && exit 1 # a dev server stopping by itself is still a failure to report
exit "$status"
