#!/bin/sh
# CHOWN is granted only to this one-shot initializer. Never traverse user files.
set -eu
# Preflight before ownership changes: imported private bind directories need the
# operator to prepare UID10001 and traversal permissions explicitly, after backup.
for directory in /data /data/state /data/tmp /data/files /data/logs; do
  if [ -L "$directory" ]; then
    echo "Refusing symbolic data directory: $directory" >&2
    exit 1
  fi
  if [ -e "$directory" ] && [ ! -d "$directory" ]; then
    echo "Expected a data directory: $directory" >&2
    exit 1
  fi
  if [ -d "$directory" ] && [ ! -x "$directory" ]; then
    echo "Data directory is not traversable: $directory. Prepare bind directories for UID10001 with directory mode0755 before starting; existing file ownership is never changed recursively." >&2
    exit 1
  fi
done
# Fresh bind mounts have no image-populated children. Temporarily own only the
# volume root while creating those directories, then give it to the app last.
needs_directories=0
for directory in /data/state /data/tmp /data/files /data/logs; do
  if [ ! -d "$directory" ]; then needs_directories=1; fi
done
if [ "$needs_directories" -eq 1 ]; then
  chown 0:0 /data
  trap 'chown 10001:10001 /data' EXIT HUP INT TERM
fi
for directory in /data/state /data/tmp /data/files /data/logs /data; do
  mkdir -p "$directory"
  if [ "$(stat -c '%u:%g' "$directory")" != '10001:10001' ]; then
    chown 10001:10001 "$directory"
  fi
done
# Existing files keep their ownership and bytes. An incompatible imported bind
# mount must be repaired explicitly by its operator before starting the app.
