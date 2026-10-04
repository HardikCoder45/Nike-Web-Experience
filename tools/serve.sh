#!/bin/zsh
cd "$(dirname "$0")/.."
exec python3 -m http.server 4321 --bind 127.0.0.1
