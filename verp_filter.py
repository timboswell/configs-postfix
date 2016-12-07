#!/usr/bin/python
# -*- coding: utf-8 -*-
""" /etc/postfix/filters/verp_filter
Author: Tim Boswell
Version: 1.0
Date: 21/09/2016
Related Standard: STD378_Postfix VERP Configuration

This script accepts an email input from Postfix, rewrites the Return-Path
header, and stores data about the email in a SQLite database file, before
re-injecting the mail back into the Postfix mail flow. It is intended to
work alongside /etc/postfix/filters/bounce_filter to provide a simple
complement to Postfix's built in VERP functionality.

Actions:
    * Accepts the sender (Return-Path) and recipient as arguments from
        Postfix
    * Extracts the subject from the message headers, provided on stdin
    * Prefixes the Return-Path header with a specified string and the Epoch
        date
    * Stores the VERP address with the original sender, recipient and subject
        in the mails table in the specified SQLite Database
    * Re-submits the modified mail back into Postfix for continued processing

Attributes:
    logging_filename (str): The path of the file where log data will be
        written. This location must be writable by the filter user, and
        on SELinux implementations, should be assigned the
        postfix_pipe_tmp_t security context.
    database_filename (str): The path of the file where the SQLite database
        can be found. This location must be writable by the filter user, and on
        SELinux implementations, should be assigned the postfix_var_run_t
        security context.
    cli_from (str): The Envelope Sender of the mail as passed by Postfix.
        This will include any VERP rules already applied by Postfix.
    cli_to (str): The Envelope Recipient of the mail passed by Postfix.
        The current implementation supports only a single recipient address.
    prefix (str): The text to prefix to the provided cli_from. This string is
        included before the Epoch time stamp.

Todo:
    * Correctly identify VERP using regex (currently we just check for the prefix)

"""

from email import Parser
import smtplib
import sys
import logging
import subprocess
import time
import sqlite3
import re

logging_filename = '/tmp/content-filter.log'
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(levelname)s %(message)s',
                    filename=logging_filename,
                    filemode='a')

try:
    cli_from = sys.argv[2].lower()
    cli_to = sys.argv[4]
    logging.debug("To / From : %r" % sys.argv)
except:
    logging.error("Invalid to / from : %r" % sys.argv)
    sys.exit(69) # Hard Bounce - don't retry bad arguments
logging.debug("From : %s, to : %r" % (cli_from, cli_to))

try:
    conn = sqlite3.connect('/etc/postfix/db/undel.db')
    logging.debug("Opening database")
except Exception, e:
    logging.error("Error opening database: %s" % (e))
    sys.exit(75) # tempfail

if "uatbounce." not in cli_from:
    logging.debug("Starting Outbound Mail Process")
    verp = "uatbounce." + str(time.time()) + "." + cli_from
    sender = re.sub(r'\+.+@', '@', cli_from)
    content = ''.join(sys.stdin.readlines())
    p = Parser.Parser()
    parsed = p.parsestr(content, True)
    logging.debug("email source : %s" % parsed.as_string())
    subject = parsed.get('Subject')
    try:
        sql = ("INSERT INTO mails"
               "(verp, sender, recipient, subject, bouncetime)"
               " VALUES ('%s', '%s', '%s', '%s', 0)"
               % (verp, sender, cli_to, subject))
        logging.debug("Trying SQL: %s" % (sql))
        conn.execute(sql)
    except Exception, e:
        logging.error("Error inserting record: %s" % (e))
    conn.commit()
    conn.close()

# and let's try reinjecting it into Postfix.
command = ["/usr/sbin/sendmail", "-G", "-i", "-f", str(verp), str(cli_to)]
stdout = ''
stderr = ''
retval = 0
try :
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    (stdout, stderr) = process.communicate(content);
    retval = process.wait()
    if retval == 0:
        logging.debug("Mail resent via sendmail, stdout: %s, stderr: %s"
                      % (stdout, stderr))
        sys.exit(0)
    else:
        raise Exception("retval not zero - %s" % retval)
except Exception, e:
    print "Error re-injecting via /usr/sbin/sendmail."
    logging.error("Error resending mail %s "
                  "-- stdout:%s, stderr:%s, retval: %s"
                  % (e, stdout, stderr, retval))
    sys.exit(75) # tempfail, we hope.
