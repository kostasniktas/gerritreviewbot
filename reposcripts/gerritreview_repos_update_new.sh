#!/bin/bash

MY_HOME=/path/to/reposcripts/location
BASE_DIR=/path/to/all/git/repos

if [ -z "$GIT_REPOS_LIST" ]; then
  echo "GIT_REPOS_LIST must be set to a file name"
  exit 1
fi

if [ ! -f $GIT_REPOS_LIST ]; then
  echo "GIT_REPOS_LIST must be a file"
  exit 1
fi

date
for i in $(cat $GIT_REPOS_LIST); do
  REPO_DIR=$($MY_HOME/gerritreview_repos_format.sh $i)
  echo $i $REPO_DIR
  cd $BASE_DIR
  if [ ! -d $REPO_DIR ]; then
    echo "Repo directory $REPO_DIR for repo $i does not exist. Clone"
    git clone GERRITUSER@gerrit.example.local:$i $REPO_DIR
  fi
done
