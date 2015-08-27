#!/bin/usr/env python

import os
import re


#https://gerrit-documentation.googlecode.com/svn/Documentation/2.4.2/cmd-stream-events.html

class GerritEvent:
  pass

class CommentAddedEvent (GerritEvent):
  def __init__ (self, change):
    if change["type"] != "comment-added":
      return None
    self.code_review = ""
    self.verified = ""
    if "approvals" in change:
      for i in change["approvals"]:
        if i["type"] == "Code-Review":
          self.code_review = i["value"]
        elif i["type"] == "Verified":
          self.verified = i["value"]
    self.change_id = change["change"]["id"]
    self.project = change["change"]["project"]
    self.number = change["change"]["number"]
    self.url = change["change"]["url"].replace("/" + self.number, \
                                               "/#/c/" + self.number)
    self.branch = change["change"]["branch"]
    self.subject = change["change"]["subject"]
    self.author = change["change"]["owner"]["email"]
    if "@" in self.author:
      self.author = self.author[:self.author.index("@")]
    self.patch_number = change["patchSet"]["number"]
    self.ref = change["patchSet"]["ref"]
    self.commit_message = ""
    self.touched_files = []
    self.requested_cr = []

  def parse_touched_files (self, log):
    self.touched_files = []
    for i in log.split(os.linesep)[1:]:
      splitted = i.split(None, 1) # Max 1 because some files have spaces
      splitted = i.split("\t")
      if len(splitted) > 1:
        #Renamed files will use the new filename
        if i.startswith("R") and len(splitted) > 2:
          self.touched_files.append(splitted[2].strip())
        else:
          self.touched_files.append(splitted[1].strip())

  def parse_git_commit (self, commit, request_cr = None):
    self.commit_message = str(commit)
    self.requested_cr = []
    if request_cr is not None:
      for i in commit.split(os.linesep):
        if request_cr in i:
          index = i.index(request_cr)
          requested = re.split("[\s,]+", i[index+len(request_cr):])
          self.requested_cr.extend(requested)
    self.requested_cr = list(set(self.requested_cr))
    self.requested_cr = [ i.replace("\"","") for i in self.requested_cr ] # For Git Revert Quotes


