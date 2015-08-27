#!/bin/sh
# Start gerrit review bot in an infinite while loop

if [ -z "$PYTHON_EXEC" ]; then
  PYTHON_EXEC=python2.6
fi

echo "Running bot with python executable $PYTHON_EXEC"

while [ true ]; do
  $PYTHON_EXEC gerrit2.py $1
  echo "Gerrit Review Bot ended with exit code [$?], waiting 2 seconds and restarting"
  sleep 2
done
