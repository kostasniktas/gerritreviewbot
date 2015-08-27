#!/bin/sh
# Start the gerrit review bot infinite loop and run as daemon
# Also allows for killing the group
# This is designed for the Gerrit Review Bot instance on SOMESERVER

CONFIGFILE=$(dirname $0)/prodconfig/CONFIGFILE.config.json

if [ $# -gt 0 ]; then
  if [ "$1" = "kill" ]; then
    if [ -f $(dirname $0)/gerrit_review.pid ]; then
      PROCESS_GROUP=$(cat $(dirname $0)/gerrit_review.pid)
      echo "Killing process group $PROCESS_GROUP"
      rm $(dirname $0)/gerrit_review.pid
      kill -- -$PROCESS_GROUP
    fi
    exit 0
  fi
fi


if [ -f $(dirname $0)/gerrit_review.pid ]; then
  echo "File gerrit_review.pid exists.  Please kill the currently running bot first."
  exit 1
fi


mkdir -p stdoutlogs
test -f gerrit_review.out && mv gerrit_review.out stdoutlogs/gerrit_review.out.`date -r gerrit_review.out +%Y-%m-%dT%H:%M:%S`
if [ -z "$PYTHON_EXEC" ]; then
  setsid nohup $(dirname $0)/gerrit_review.sh $CONFIGFILE > gerrit_review.out 2>&1 &
else
  PYTHON_EXEC=$PYTHON_EXEC setsid nohup $(dirname $0)/gerrit_review.sh $CONFIGFILE > gerrit_review.out 2>&1 &
fi

pid=$!
echo pid = $pid
echo $pid > gerrit_review.pid
sleep 2
kill -0 $pid || tail gerrit_review.out
