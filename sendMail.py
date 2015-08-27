#!/usr/bin/env python2.6

import smtplib,sys,getopt,os,platform
from email.MIMEMultipart import MIMEMultipart
from email.MIMEBase import MIMEBase
from email.MIMEText import MIMEText
from email.Utils import COMMASPACE, formatdate
from email import Encoders

"""
  A script and class to help send emails.
"""

class EmailMessage:
  """
    An email message class that can attach files, have multiple recipients, and is easy to use.
  """
  def __init__ (self):
    self.msg = MIMEMultipart()
    self.bodyText = ""
    self.smtpserver = None
    self.attachments = []
    self.toAddrs = []

  def setSMTPServer (self, smtpserver):
    if type(smtpserver) is not str:
      raise TypeError("SMTP Server must be a string")
    self.smtpserver = smtpserver

  def setFromAddr (self, fromAddr):
    if type(fromAddr) is not str:
      raise TypeError("From address must be a string")
    self.msg['From'] = fromAddr

  def setToAddr (self, toAddrs):
    """Set the list of recipients for the email"""
    if type(toAddrs) is not list:
      raise TypeError("This function requires a list of the addresses to send emails to")
    self.toAddrs = toAddrs

  def addToAddr (self, toAddr):
    """Add to the list of recipients for the email"""
    if type(toAddr) is not str:
      raise TypeError("The to-address added to the list must be a str")
    self.toAddrs.append(toAddr)

  def setSubject (self, subject):
    if type(subject) is not str:
      raise TypeError("The subject must be a str")
    self.msg['Subject'] = subject

  def setBody (self, body, html=False):
    if type(body) is not str:
      raise TypeError("The body must be a str")
    self.bodyText = body
    self.isHtml = html

  def setAttach (self, files):
    """Set the list of filenames the class will attach when it is time to send"""
    if type(files) is not list:
      raise TypeError("This function requires a list of str defining files to attach")
    self.attachments = files

  def addAttach (self, fileName):
    """Add a filename to the list of attachments"""
    if type(fileName) is not str:
      raise TypeError("The filename added must be a str")
    self.attachments.append(fileName)

  def sendMessage (self):
    """Send the actual message."""
    self.msg['To'] = COMMASPACE.join(self.toAddrs)
    self.msg['Date'] = formatdate(localtime=True)
    if self.isHtml:
      self.msg.attach( MIMEText(self.bodyText,'html') )
    else:
      self.msg.attach ( MIMEText(self.bodyText) )

    if len(self.attachments) > 0:
      for filename in self.attachments:
        if os.path.isfile(filename):
          part = MIMEBase('application', "octet-stream")
          part.set_payload( open(filename,"rb").read() )
          Encoders.encode_base64(part)
          part.add_header('Content-Disposition', 'attachment; filename="%s"' % os.path.basename(filename))
          self.msg.attach(part)

    assert self.smtpserver is not None, "SMTP Server is not set"
    server = smtplib.SMTP(self.smtpserver)
    server.sendmail(self.msg['From'], self.toAddrs, self.msg.as_string())
    server.quit()



