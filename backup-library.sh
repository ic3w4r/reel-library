#!/bin/sh
# Back up the Reel Library (database, settings, thumbnails, Instagram login) to instamcp-library.tgz,
# to restore on another machine with windows\restore-library.bat.
# Downloaded models and temporary media are left out; the other machine downloads them again.
# The backup holds your API keys and Instagram login: keep it private.
set -e
cd "$(dirname "$0")"
docker run --rm -v instamcp_instamcp-data:/data:ro -v "$PWD":/backup alpine \
  tar czf /backup/instamcp-library.tgz -C /data --exclude=./models --exclude=./media --exclude=./queue.json .
echo "Saved $(du -h instamcp-library.tgz | cut -f1) to $PWD/instamcp-library.tgz"
