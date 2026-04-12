#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
PYTHON=$(which python3 || which python)
if [ ! -d "venv" ]; then
    $PYTHON -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt -q
echo "Starting AVA Server on port 8765..."
python server.py