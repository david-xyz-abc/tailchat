#!/usr/bin/env bash
set -e

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

trap 'printf "\nTailChat could not start. Read the error above and README.md.\n" >&2' ERR

printf '\n  TailChat - your team\047s private space\n'
printf '  -----------------------------------\n'

if ! command -v python3 >/dev/null 2>&1 ||
    ! python3 -c 'import sys; assert sys.version_info >= (3, 10)' >/dev/null 2>&1; then
    printf 'Python 3.10 or newer is required. Install it, then run ./start.sh again.\n' >&2
    exit 1
fi

if [ ! -x .venv/bin/python ]; then
    printf 'Creating the local Python environment...\n'
    if ! python3 -m venv .venv; then
        printf 'Could not create .venv. Check that Python venv support is installed.\n' >&2
        printf 'On Ubuntu/Debian, install it with: sudo apt install python3-venv\n' >&2
        exit 1
    fi
fi

printf 'Checking dependencies. Internet is needed the first time.\n'
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt

printf '\nLocal URL: http://localhost:5000\n'
printf 'On the host, run: tailscale ip -4\n'
printf 'Give your team: http://YOUR_TAILSCALE_IP:5000\n'
printf 'Keep this window open. Press Ctrl+C to stop the server.\n\n'
exec .venv/bin/python app.py
