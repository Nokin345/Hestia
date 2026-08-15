#!/bin/bash
set -e

# Replicate the upstream entrypoint's cgroup v2 setup (required by Isolate),
# then start the API in the background, ensure the Hestia runtimes are
# installed (idempotent — skips what's already in /piston/packages), and stay
# alive as the API's parent process.

CGROUP_FS="/sys/fs/cgroup"
if [ ! -e "$CGROUP_FS" ]; then
  echo "Cannot find $CGROUP_FS. Please make sure your system is using cgroup v2"
  exit 1
fi
if [ -e "$CGROUP_FS/unified" ]; then
  echo "Combined cgroup v1+v2 mode is not supported. Please make sure your system is using pure cgroup v2"
  exit 1
fi
if [ ! -e "$CGROUP_FS/cgroup.subtree_control" ]; then
  echo "Cgroup v2 not found. Please make sure cgroup v2 is enabled on your system"
  exit 1
fi

cd /sys/fs/cgroup
mkdir -p isolate
echo 1 > isolate/cgroup.procs
echo '+cpuset +cpu +io +memory +pids' > cgroup.subtree_control
cd isolate
mkdir -p init
echo 1 > init/cgroup.procs
echo '+cpuset +memory' > cgroup.subtree_control
echo "Initialized cgroup"
chown piston:piston /piston/packages 2>/dev/null || true

# Start the Piston API as the piston user, same as the upstream entrypoint.
su -- piston -c 'ulimit -n 65536 && node /piston_api/src' &
API_PID=$!

# Ensure the runtimes Hestia needs are installed (skips already-installed ones).
node /piston/init.js

# Keep the container alive for the API process.
wait $API_PID
