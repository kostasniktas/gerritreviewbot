#!/bin/bash
#
# gerritreview        Startup script for the gerritreview
#
# chkconfig: - 80 10
# description: THE BEST AWESOMEIST THING EVER!!!
# This is designed for the Gerrit Review Bot instance on SOMESERVER

GERRITREVIEW_DIR=/path/to/gerritreview/repo/here

RETVAL=0

start() {
  echo "Starting gerrit review bot:"
  su -c "$GERRITREVIEW_DIR/daemon_gerritreview.sh 2>&1 > /dev/null" USER
  RETVAL=$?
  echo
  return $RETVAL
}

stop() {
  echo "Stopping gerrit review bot:"
  su -c "$GERRITREVIEW_DIR/daemon_gerritreview.sh kill 2>&1 > /dev/null" USER
  RETVAL=$?
  echo
  return $RETVAL
}

restart() {
  stop
  start
}

case "$1" in
  start)
    start
  ;;
  stop)
    stop
  ;;
  restart)
    restart
  ;;
  *)
    echo "Usage $(basename $0) {start|stop|restart}"
    RETVAL=2
esac

exit $RETVAL
