#!/bin/sh
set -eu
if [ "$#" -lt 1 ]; then
  echo "Usage: ./run.sh /path/to/CoverLetters"
  exit 1
fi
python3 main.py "$1"
