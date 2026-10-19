#!/bin/sh
# Migrate, then serve, as an unprivileged user. `set -e` makes a failed migration stop the
# container visibly in OrbStack instead of serving against a half-migrated schema.
set -e

# Started as root (the default): hand /data to the runtime user, then re-run this script
# as that user. Started with `--user` already: skip straight to serving.
if [ "$(id -u)" = 0 ]; then
	# The re-exec below exports this process's pid (exec keeps the pid). Seeing it while still
	# root means dropping privileges did not take, so stop rather than re-execute forever.
	if [ "${AA_ENTRYPOINT_REEXEC:-}" = "$$" ]; then
		echo "entrypoint: still root after switching to ${AA_UID:-1000}:${AA_GID:-1000};" \
			"refusing to re-run" >&2
		exit 1
	fi
	uid="${AA_UID:-1000}"
	gid="${AA_GID:-1000}"
	for id in "$uid" "$gid"; do
		case "$id" in
			'' | *[!0-9]*)
				echo "entrypoint: AA_UID and AA_GID must be numeric ids (got '$uid' / '$gid')" >&2
				exit 1
				;;
		esac
	done
	if [ "$uid" = 0 ]; then
		# AA_UID=0 asks for root: there is no one to drop to (re-running as uid 0 would land
		# back here). Serve as root, and say so. /data needs no chown: root can write it.
		echo "entrypoint: warning: AA_UID=0, so the app is running as root:root" \
			"(AA_GID is ignored; unset AA_UID/AA_GID to run as the unprivileged user 1000:1000)" >&2
	else
		# Volumes created by images that ran as root are root-owned, and anything copied in by
		# a root container (`just db-migrate-to-volume`, a restore) is too. Walk /data only
		# until the first file with the wrong owner, so an already-correct volume costs one
		# short scan. /vault is the user's own Obsidian vault: never chown it.
		if [ -n "$(find /data -xdev \( ! -uid "$uid" -o ! -gid "$gid" \) -print -quit)" ]; then
			echo "entrypoint: giving /data to $uid:$gid"
			chown -R "$uid:$gid" /data
		fi
		if [ -d "$HOME" ] && [ "$(stat -c %u:%g "$HOME")" != "$uid:$gid" ]; then
			chown -R "$uid:$gid" "$HOME"
		fi
		export AA_ENTRYPOINT_REEXEC="$$"
		exec setpriv --reuid="$uid" --regid="$gid" --clear-groups --no-new-privs -- "$0" "$@"
	fi
fi
unset AA_ENTRYPOINT_REEXEC

if [ -d /vault ] && [ ! -w /vault ]; then
	echo "entrypoint: /vault is not writable by uid $(id -u); vault export will fail" \
		"(set AA_UID/AA_GID to the vault owner's ids)" >&2
fi

alembic upgrade head
exec uvicorn adaptive_academy.api.app:app --host 0.0.0.0 --port 8000
