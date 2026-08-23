#!/bin/bash
#
# Copy what the speaker has learned off the Pi, and keep it.  --help
#
# Everything happens in backup.py. It prefers the project's virtualenv,
# because uploading needs huggingface_hub.

set -euo pipefail
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then
    exec .venv/bin/python backup.py "$@"
fi
exec python3 backup.py "$@"
