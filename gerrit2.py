#!/usr/bin/env python

# Gerrit Review Bot
#  author: kniktas

# Watches the Gerrit Event Stream and adds reviewers
#  based on the commit message and files touched


try:
  from collections import OrderedDict
except ImportError:
  from ordereddict import OrderedDict
from Queue import Queue, Empty
from threading import Thread, Timer
import collections
import components
import getpass
import git
import json
import logging
import logging.handlers
import os
import paramiko
import platform
import re
import sendMail
import signal
import sys
import thread
import time

import gerrit_stream_events

# Load Options
options = None
if len(sys.argv) < 2:
    print "Please pass in a config json file as the first argument."
    print ""
    print "Usage %s CONFIGFILE.json" % sys.argv[0]
    sys.exit(1)
options_file = sys.argv[1]
if not os.path.isfile(options_file):
  print "%s options file not found." % sys.argv[1]
  sys.exit(1)
with open(options_file, "r") as f:
  options = json.load(f)
GITREPOS = options["gitrepos"]
GITREMOTE = str(options["gitremote"])
USERNAME = str(options["username"])
KEYFILE = str(options["keyfile"])
GERRIT_HOST = str(options["hostname"])
ADD_REVIEWERS = options["addreviewers"]
ADD_COMMENT = options["addcomment"]
SEND_EMAILS = options["sendemails"]
MERGE_REVIEWERS = options["mergereviewers"]
SMTP_SERVER = options["smtpserver"]
EMAIL_FROM = options["emailfrom"]
IGNORED_COMPONENTS = options["ignoredcomponents"]
USERS_EMAIL_DOMAIN = options["usersemaildomain"]

# Constants
REQUEST_CR = "CRR: "
OPTIN = "AUTOREVIEW"
EMAIL_OPTIN = "EMAILREVIEW"
NOSUBMIT = "NOSUBMIT"
CHANGE_REF = "GERRIT_MONITOR"
CONNECTION_CHECK_INTERVAL = 60 #seconds
QUEUE_TIMEOUT = 5 # seconds
AUTHOR_NO_ONE = "noone"
AUTHOR_IGNORED = "ignored"
INVALID_USERS = "error: could not add (.*): (.*) does not identify a registered user or group"
MULTIPLE_CHANGES = "matches multiple changes"

# Debug-based settings
CONNECTION_DOT = False

# Set up Logger
logger = logging.getLogger('gerrit_reviewer')
logger.setLevel(logging.DEBUG)
fh = logging.handlers.RotatingFileHandler('gerrit_reviewer.log', maxBytes=100 * 1024**2)
fh.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
if options["debuglogging"]:
  ch.setLevel(logging.DEBUG)
else:
  ch.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(threadName)s - %(message)s')
fh.setFormatter(formatter)
ch.setFormatter(formatter)
logger.addHandler(fh)
logger.addHandler(ch)

exit_code = 0

logger.info("----------------- %s started -------------------", sys.argv[0])


#
# Thread Functions
#

def check_connection(sshclient):
  global exit_code
  logger.info("Entering connection check loop")
  while True:
    if not sshclient.get_transport().is_active():
      logger.critical("SSH Connection is down. Ending " + sys.argv[0])
      clean_up()
      exit_code = 1
      thread.interrupt_main()
    else:
      if CONNECTION_DOT:
        sys.stdout.write(".")
        sys.stdout.flush()
    time.sleep(CONNECTION_CHECK_INTERVAL)

def store_event_stream(out, queue):
  logger.info("Event stream ready and waiting")
  try:
    for line in iter(out.readline, b''):
      queue.put(line)
  except Exception, e:
    logger.error("Error in event stream thread: %s", e)


#
# Helper Functions
#
def get_components_for_repo_and_branch(git_command, branch_packages, branch_regex):
  """
  Create a components dict from the specified branch
  """
  try:
    if branch_packages.startswith("refs/sandbox/"):
      branch_packages = branch_packages[len("refs/"):]
    else:
      branch_packages = GITREMOTE + "/" + branch_packages

    component_text = None
    component_regex_text = None

    try:
      component_text = git_command.show(branch_packages + \
        ":components-packages.txt")
    except Exception, e:
      pass
    component_dict = components.parse_component_text(component_text)
    for i in component_dict.keys():
      if i in IGNORED_COMPONENTS:
        del component_dict[i]

    try:
      component_regex_text = git_command.show("origin/%s:components-regex.txt" % branch_regex)
    except Exception, e:
      pass
    component_regex_dict = components.parse_component_text(component_regex_text, starting_dict = OrderedDict())
    component_regex_high_dict = components.get_high_priority_components(component_regex_dict)
    component_regex_normal_dict = components.get_normal_priority_components(component_regex_dict)
    return {"packages": component_dict, "regexhigh": component_regex_high_dict, "regexnormal": component_regex_normal_dict}
  except Exception, e:
    logger.error("Couldn't retrieve components file: %s", e)
    return {}

def pick_owner(component, author):
  """From a component, pick the owner.  We don't consider the author of the commit for ownership."""
  for consider in component.owners:
    if author != consider:
      return consider
  return AUTHOR_NO_ONE

def pick_owner_all(component, author):
  """From a component, pick all the owners.  We don't consider the author of the commit for ownership."""
  considering = []
  for consider in component.owners:
    if author != consider:
      considering.append(consider)
  if len(considering) > 0:
    return considering
  else:
    return [AUTHOR_NO_ONE]

def add_reviewer_reason(reviewers, reviewer, reason):
  """Add a tuple to the list of reasons to add a certain reviewer"""
  # Format of reviewers dict:
  #   reviewer => [(reason, notes), ... ]
  #   ex:  kniktas : [ ("/path/to/file", str(component.name)), ("requested", ""), ...]
  if reviewer not in reviewers:
    reviewers[reviewer] = []
  reviewers[reviewer].append(reason)

def add_multiple_reviewer_reasons(reviewers, reviewer, reason):
  if not isinstance(reviewer, list):
    reviewer = [reviewer]
  for i in reviewer:
    add_reviewer_reason(reviewers, i, reason)

def is_already_matched(reviewers, item):
  for reviewer in reviewers.keys():
    for reason in reviewers[reviewer]:
      if item == reason[0]:
        return True
  return False

def process_touched_files(comment, all_components, starting_reviewers = {}):
  """Perform the actual processing of touched files and look for component owners."""
  reviewers = starting_reviewers
  for i in comment_added.touched_files:
    if is_already_matched (reviewers, i):
      continue
    (match, component) = components.find_component_re(all_components["regexnormal"], i)
    if component is not None:
      logger.debug("file change \"%s\" matched on %s", i, component)
      if component.all_owners_component:
        add_multiple_reviewer_reasons(reviewers, pick_owner_all(component, comment_added.author), \
                              (i, "Matched on: " + match))
      else:
        add_reviewer_reason(reviewers, pick_owner(component, comment_added.author), \
                              (i, "Matched on: " + match))
    else:
      logger.warning("file change \"%s\" was not matched", i)
      add_reviewer_reason(reviewers, AUTHOR_NO_ONE, (i, "No matches"))
  return reviewers

def get_review_string(reviewer, reasons, change_url, change_patchset_number, is_main_reviewer = False, is_unmatched = False):
  """Construct the reviewer's portion of the comment added after the reviewers are added"""
  value = []
  if not is_unmatched:
    value.append(" " + reviewer)
  if is_main_reviewer:
    value.append( "You are the main reviewer because you have " + str(len(reasons)) + " item(s) to review.")
  for i in reasons:
    if i[0] == "requested":
      value.append("- Requested in the Commit Message")
    elif i[0] == "mergecommit":
      value.append("- This is a merge commit")
    else:
      value.append("- " + change_url + "/" + change_patchset_number + "/" + i[0].replace(" ","+") + ",unified")
  return "\n".join(value)

def clean_up():
  if ssh_stream is not None:
    logger.info("Closing event stream")
    ssh_stream.close()
  if ssh_commands is not None:
    logger.info("Closing command connection")
    ssh_commands.close()

def send_gerrit_command(ssh_client, command, expect_output = False):
  result = None
  try:
    ssh_client = connect_ssh_commands()
    if "\n" in command:
      logger.info("Sending command: %s", command.split("\n"))
    else:
      logger.info("Sending command: %s", command)
    stdin, stdout, stderr = ssh_client.exec_command(command)
    stdin.close()
    outlines = stdout.readlines()
    errlines = stderr.readlines()
    result = (outlines, errlines)
    if not expect_output:
      if len(outlines) > 0:
        logger.info("Result of command (out): %s", outlines)
    if len(errlines) > 0:
      logger.error("Result of command (err): %s", errlines)
    ssh_client.close()
  except Exception, e:
    logger.error("Error sending gerrit command: %s", e)
  finally:
    return result

def connect_ssh_commands():
  ssh_client = paramiko.SSHClient()
  ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
  ssh_client.connect(GERRIT_HOST, username=USERNAME, key_filename=KEYFILE)
  return ssh_client


def scan_for_invalid_users (ssh_errs):
  invalid_users = []
  p = re.compile(INVALID_USERS)
  for err in ssh_errs:
    m = p.match(err)
    if m:
      invalid_users.append(m.group(1)[:-len(USERS_EMAIL_DOMAIN)])
  return invalid_users


def contains_multiple_matches (ssh_errs):
  for err in ssh_errs:
    if MULTIPLE_CHANGES in err:
      return True
  return False

#
# Git Repo Commands
#
class GitTimeoutException(Exception):
  pass

def git_timeout_handler(signum, frame):
  raise GitTimeoutException()

def git_timeout(timeout):
  """Function decorator to timeout git commands"""
  def wrap(func):
    def wrapped_func(*args):
      old_handler = signal.signal(signal.SIGALRM, git_timeout_handler)
      signal.alarm(timeout)
      try:
        value = func(*args)
      except GitTimeoutException:
        return None
      except Exception, e:
        signal.alarm(0)
        raise e
      finally:
        signal.signal(signal.SIGALRM, old_handler)
      signal.alarm(0)
      return value
    return wrapped_func
  return wrap

TIMEOUT_FETCH = int(options.get("timeoutfetch",120))
TIMEOUT_TOUCHED_FILES = 15
TIMEOUT_COMMIT_MESSAGE = 15

@git_timeout(TIMEOUT_FETCH)
def git_repo_fetch(g, ref):
  return g.fetch(GITREMOTE , "+" + ref + ":" + CHANGE_REF)

@git_timeout(TIMEOUT_TOUCHED_FILES)
def git_repo_show_touched_files(g):
  return g.log("-M", "--name-status", "-1", "--pretty=oneline", CHANGE_REF)

@git_timeout(TIMEOUT_COMMIT_MESSAGE)
def git_repo_commit_message(g):
  return g.log("-1", "--format=%s%n%n%b", CHANGE_REF)

#
#
#

# Git objects for viewing commits and files
#   Handle filling in defaults if not there
git_commands = {}
git_repos = {}
for repo in GITREPOS.keys():
  git_commands[repo] = git.Git(GITREPOS[repo]["path"])
  git_repos[repo] = git.Repo(GITREPOS[repo]["path"])
  if "regexbranch" not in GITREPOS[repo]:
    GITREPOS[repo]["regexbranch"] = "master"
  logger.debug("Set up git repo object at %s for project %s. (AUTOREVIEW using %s)", GITREPOS[repo]["path"], repo, GITREPOS[repo]["regexbranch"])
watched_projects = git_repos.keys()


# Queue, SSH Connection, and Thread for the event stream
event_queue = Queue()
ssh_stream = paramiko.SSHClient()
ssh_stream.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_stream.connect(GERRIT_HOST, username=USERNAME, key_filename=KEYFILE)
ssh_stream.get_transport().set_keepalive(30)
stdin, stdout, stderr = ssh_stream.exec_command('gerrit stream-events')
thread_stream = Thread(name="event_stream", target=store_event_stream, args=(stdout, event_queue))
thread_stream.daemon = True
thread_stream.start()


# Thread to check for active connection to stream
thread_connection = Thread(name='connection_check', target=check_connection, args = [ssh_stream])
thread_connection.daemon = True
thread_connection.start()


# SSH Connection for the commands
ssh_commands = None

"""
NOTES:

Must Haves

Nice Haves

Things to consider
-Should we remove existing reviewers if a new patchset is added? (would require new gerrit stream class and logic)
  -> since we want to be state-less, we could add a carefully formatted comment of the previous reviewers in case
      the owner added one manually
-Optional not adding reviewers. For stuff like testing out, stress testing, etc. it's necessary

"""


logger.info("Entering event queue loop.")

while True:
  try:
    line = event_queue.get(True, timeout=QUEUE_TIMEOUT)
  except Empty:
    pass
  except KeyboardInterrupt:
    logger.info("KeyboardInterrupt caught, closing ssh connections and exiting")
    clean_up()
    sys.exit(exit_code)
  else:
    event_json = json.loads(str(line))
    if event_json["type"] == "comment-added" and \
       event_json["change"]["project"] in watched_projects:
      current_project = event_json["change"]["project"]
      git_command = git_commands[current_project]
      git_repo = git_repos[current_project]
      git_settings = GITREPOS[current_project]

      gerrit_comment = [] # No double-quotes please
      comment_added = gerrit_stream_events.CommentAddedEvent(event_json)

      if comment_added.verified == "1":
        logger.debug("Considering %s change %s/%s : %s : %s", current_project, comment_added.number, comment_added.patch_number, comment_added.author, comment_added.subject)

        # Get JSON info from gerrit
        json_change = None
        gerrit_return = send_gerrit_command (ssh_commands, 'gerrit query --current-patch-set --format json project:' + current_project + ' ' + \
                          comment_added.number + '', expect_output = True)
        if gerrit_return is not None:
          gerrit_out, gerrit_err = gerrit_return
          if len(gerrit_err) == 0:
            json_change = json.loads(gerrit_out[0])

        if json_change is not None and json_change["currentPatchSet"]["number"] != comment_added.patch_number:
          logger.debug("Change %s/%s is not the current patch set [%s].", comment_added.number, comment_added.patch_number, json_change["currentPatchSet"]["number"])
          continue

        reviewers = {}
        reviewers_email = {}
        author_opt_in = False
        email_opt_in = False
        high_priority_matches = False
        merge_commit = False

        try:
          gitout = git_repo_fetch(git_command, comment_added.ref)
          if gitout is None:
            logger.error("Fetch failed (timeout) for %s/%s. Trying again.", comment_added.number, comment_added.patch_number)
            gitout = git_repo_fetch(git_command, comment_added.ref)
            if gitout is None:
              raise GitTimeoutException()
        except (git.errors.GitCommandError, GitTimeoutException), e:
          # Failed Fetch
          if isinstance(e, git.errors.GitCommandError):
            logger.error("Git fetch failed: %s. stderr output: %s", e, str(e.stderr.split()))
          else:
            logger.error("Git fetch command timed out in %d seconds", TIMEOUT_FETCH)
          # We can't exactly add a comment to the commit since we don't know if they want it reviewed
          continue

        # Get commit's information
        parents = git.commit.Commit(git_repo, CHANGE_REF).parents
        if len(parents) > 1 and (MERGE_REVIEWERS is not None and len(MERGE_REVIEWERS) > 0):
          # We have a merge commit!
          merge_commit = True
          logger.debug("Commit is a merge commit.  Adding: %s", str(MERGE_REVIEWERS))
          if MERGE_REVIEWERS is not None:
            for i in MERGE_REVIEWERS:
              add_reviewer_reason(reviewers, i, ("mergecommit",""))

        # Check for ABANDONED
        if json_change is not None:
          if json_change["status"] == "ABANDONED":
            logger.debug("Commit is marked ABANDONED")
            continue

        # Get the list of touched files
        gitout = git_repo_show_touched_files(git_command)
        if gitout is None:
          logger.error("Git show command for touched files timed out in %d seconds", TIMEOUT_TOUCHED_FILES)
          continue
        comment_added.parse_touched_files(gitout)

        # Get the commit message for the requested CRs
        gitout = git_repo_commit_message(git_command)
        if gitout is None:
          logger.error("Git log command for commit message timed out in %d seconds", TIMEOUT_COMMIT_MESSAGE)
          continue
        comment_added.parse_git_commit(gitout, REQUEST_CR)

        # It already is marked for merge
        if not merge_commit:
          if "CR: " in comment_added.commit_message or "NOCR: " in comment_added.commit_message:
            logger.debug("Skipping commit, it is already marked with CR: or NOCR:")
            continue

        # Check for NOSUBMIT tag
        if NOSUBMIT in comment_added.commit_message:
          logger.debug("Commit is marked to not be submitted.")
          if json_change is not None:
            approvals = json_change["currentPatchSet"]["approvals"]
            already_blocked = False
            for approval in approvals:
              if approval["by"]["name"] == USERNAME:
                if approval["type"] == "Code-Review" and approval["value"] == "-2":
                  already_blocked = True
                  break
            if not already_blocked and json.loads(gerrit_out[0])["status"] == "NEW":
              gerrit_cr_command = 'gerrit review --project ' + current_project + ' --message ' + \
                                '"Marking -2CR because of ' + NOSUBMIT + '" --code-review -2 ' + \
                                  comment_added.number + "," + comment_added.patch_number
              if ADD_COMMENT:
                gerrit_return = send_gerrit_command (ssh_commands, gerrit_cr_command)
              else:
                logger.debug("Would send review command: %s", gerrit_cr_command)
            else:
              logger.debug("Change is already marked -2CR")
          continue

        all_components = get_components_for_repo_and_branch(git_command, comment_added.branch, git_settings["regexbranch"])

        # Check for HIGH priority regex components
        if not merge_commit:
          for i in comment_added.touched_files:
            (match, component) = components.find_component_re(all_components["regexhigh"], i)
            if component is not None:
              high_priority_matches = True
              logger.debug("file change HIGH \"%s\" matched on %s", i, component)
              add_multiple_reviewer_reasons(reviewers, pick_owner_all(component, comment_added.author), \
                                    (i, "Matched on HIGH: " + match))

        # If they explicitly ask for an AUTOREVIEW, give it to them
        if OPTIN in comment_added.commit_message:
          author_opt_in = True

        if EMAIL_OPTIN in comment_added.commit_message:
          email_opt_in = True

        # If no opt-in, requested, or high priority matches, then ignore
        if not author_opt_in and len(comment_added.requested_cr) == 0 and not high_priority_matches and not merge_commit and not email_opt_in:
          logger.debug("Skipping commit.  There were no requested CRs, Auto Review requests, or HIGH priority matches.")
          continue

        if author_opt_in and not merge_commit:
          reviewers = process_touched_files(comment_added, all_components, starting_reviewers = reviewers)

        if email_opt_in:
          reviewers_email = process_touched_files(comment_added, all_components)
          email = sendMail.EmailMessage()
          email.setSMTPServer(SMTP_SERVER)
          email.setFromAddr(EMAIL_FROM)
          email.setToAddr([comment_added.author + "@" + USERS_EMAIL_DOMAIN])
          email.setSubject(str("GerritReviewBot[%s] matches for %s" % (platform.uname()[1].upper(), comment_added.url)))
          value = []
          value.append(comment_added.author + ", these are the " + EMAIL_OPTIN + " matches for " + comment_added.url)
          value.append("")
          for reviewer in reviewers_email.keys():
            reasons = reviewers_email[reviewer]
            value.append(reviewer)
            for i in reasons:
              value.append(comment_added.url + "/" + comment_added.patch_number + "/" + i[0].replace(" ","+") + ",unified")
            value.append("")
          email_body = "\n".join(value)
          email.setBody(str(email_body))
          if SEND_EMAILS:
            email.sendMessage()

        logger.info("Requested CRs: [%s]", " ".join(comment_added.requested_cr))
        for i in comment_added.requested_cr:
          add_reviewer_reason(reviewers, i, ("requested", ""))

        # Find the lucky reviewer who will be the main reviewer
        most_review_reasons = 0
        most_review_reviewer = None
        if author_opt_in:
          for i in reviewers.keys():
            if len(reviewers[i]) > most_review_reasons and i != AUTHOR_NO_ONE:
              most_review_reasons = len(reviewers[i])
              most_review_reviewer = i
          logger.debug("Top reviewing person %s with %s reason(s)", most_review_reviewer, most_review_reasons)

        # Add reviewers
        reviewers_to_add = [x for x in reviewers.keys() if x != AUTHOR_NO_ONE and x != AUTHOR_IGNORED]
        command_add_reviewers_base = "gerrit set-reviewers --project " + current_project + " " + \
                                    "".join([" --add " + x + "@" + USERS_EMAIL_DOMAIN for x in reviewers_to_add]) + \
                                    " "# + comment_added.number
        invalid_users = []
        if ADD_REVIEWERS:
          command_result = send_gerrit_command(ssh_commands, command_add_reviewers_base + comment_added.number)
          if command_result is not None and len(command_result[1]) > 0:
            if contains_multiple_matches(command_result[1]):
              command_result = send_gerrit_command(ssh_commands, command_add_reviewers_base + comment_added.change_id)
          if command_result is not None and len(command_result[1]) > 0:
            invalid_users = scan_for_invalid_users(command_result[1])
            if len(invalid_users) > 0:
              logger.error("Invalid users were requested for CRs: %s", invalid_users)
        else:
          logger.debug("Would send reviewer command: %s", command_add_reviewers_base + comment_added.number)

        # Construct the comment to add to gerrit
        number_reviewers = len(reviewers)

        # Check for invalid users
        if len(invalid_users) > 0:
          for invalid in invalid_users:
            if invalid in reviewers:
              del reviewers[invalid]
              number_reviewers = number_reviewers - 1
          gerrit_comment.append(" " + comment_added.author + ", the following users were invalid: " + str(invalid_users))
          gerrit_comment.append("")
          gerrit_comment.append("")

        # Files with missing owners
        if AUTHOR_NO_ONE in reviewers:
          gerrit_comment.append(" " + comment_added.author + ", the following files could not have a reviewer mapped to them:")
          gerrit_comment.append(get_review_string(AUTHOR_NO_ONE, reviewers[AUTHOR_NO_ONE], comment_added.url, comment_added.patch_number, is_unmatched = True))
          gerrit_comment.append("")
          gerrit_comment.append("")
          number_reviewers = number_reviewers - 1

        # Files we ignored
        if AUTHOR_IGNORED in reviewers:
          gerrit_comment.append(" " + comment_added.author + ", the following files are ignored by the bot:")
          gerrit_comment.append(get_review_string(AUTHOR_IGNORED, reviewers[AUTHOR_IGNORED], comment_added.url, comment_added.patch_number, is_unmatched = True))
          gerrit_comment.append("")
          gerrit_comment.append("")
          number_reviewers = number_reviewers - 1

        if number_reviewers > 0:
          gerrit_comment.append("")
          gerrit_comment.append("You were each added as a reviewer for a reason.  Reasons listed under your username")
          gerrit_comment.append("")

        # The review owner
        if most_review_reviewer is not None:
          gerrit_comment.append(get_review_string(most_review_reviewer, reviewers[most_review_reviewer], \
                                                   comment_added.url, comment_added.patch_number, is_main_reviewer = True))
        gerrit_comment.append("")
        gerrit_comment.append("")

        # The rest of the people
        for i in reviewers.keys():
          if i != most_review_reviewer and i != AUTHOR_NO_ONE and i != AUTHOR_IGNORED:
            gerrit_comment.append(get_review_string(i, reviewers[i], comment_added.url, comment_added.patch_number))
            gerrit_comment.append("")
            gerrit_comment.append("")
        gerrit_comment.append("")
        gerrit_comment.append("")

        gerrit_comment.append("-Your friendly GerritReviewer Bot")

        logger.debug("Comment for Gerrit: %s", gerrit_comment)

        # Comment on the change
        command_comment = "gerrit review --project " + current_project + " --message '" + \
                                  "\n".join(gerrit_comment) + "' --code-review 0 " + \
                                  comment_added.number + "," + comment_added.patch_number
        if ADD_COMMENT:
          send_gerrit_command(ssh_commands, command_comment)
        else:
          logger.debug("Would send comment command: %s", command_comment)
      else:
        pass # Not Verified + 1
    else:
      pass # change that isn't in supported project
    pass

logger.critical("Exited the while loop")
