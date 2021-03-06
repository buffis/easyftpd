#!/usr/bin/env python
# ftpserver.py
#
#  pyftpdlib is released under the MIT license, reproduced below:
#  ======================================================================
#  Copyright (C) 2007 Giampaolo Rodola' <g.rodola@gmail.com>
#
#                         All Rights Reserved
# 
#  Permission to use, copy, modify, and distribute this software and
#  its documentation for any purpose and without fee is hereby
#  granted, provided that the above copyright notice appear in all
#  copies and that both that copyright notice and this permission
#  notice appear in supporting documentation, and that the name of 
#  Giampaolo Rodola' not be used in advertising or publicity pertaining to
#  distribution of the software without specific, written prior
#  permission.
# 
#  Giampaolo Rodola' DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS SOFTWARE,
#  INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS, IN
#  NO EVENT Giampaolo Rodola' BE LIABLE FOR ANY SPECIAL, INDIRECT OR
#  CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS
#  OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT,
#  NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN
#  CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
#  ======================================================================
  

"""pyftpdlib: RFC-959 asynchronous FTP server.

pyftpdlib implements a fully functioning asynchronous FTP server as
defined in RFC-959.  A hierarchy of classes outlined below implement
the backend functionality for the FTPd:

    [FTPServer] - the base class for the backend.

    [FTPHandler] - a class representing the server-protocol-interpreter
    (server-PI, see RFC-959). Each time a new connection occurs
    FTPServer will create a new FTPHandler instance to handle the
    current PI session.

    [ActiveDTP], [PassiveDTP] - base classes for active/passive-DTP
    backends.

    [DTPHandler] - this class handles processing of data transfer
    operations (server-DTP, see RFC-959).

    [DummyAuthorizer] - an "authorizer" is a class handling FTPd
    authentications and permissions. It is used inside FTPHandler class
    to verify user passwords, to get user's home directory and to get
    permissions when a filesystem read/write occurs. "DummyAuthorizer"
    is the base authorizer class providing a platform independent
    interface for managing virtual users.

    [AbstractedFS] - class used to interact with the file system,
    providing a high level, cross-platform interface compatible
    with both Windows and UNIX style filesystems.

    [AuthorizerError] - base class for authorizers exceptions.


pyftpdlib also provides 3 different logging streams through 3 functions
which can be overridden to allow for custom logging.

    [log] - the main logger that logs the most important messages for
    the end user regarding the FTPd.

    [logline] - this function is used to log commands and responses
    passing through the control FTP channel.

    [logerror] - log traceback outputs occurring in case of errors.

    [debug] - used for logging function/method calls (disabled by
    default).


Usage example:

>>> from pyftpdlib import ftpserver
>>> authorizer = ftpserver.DummyAuthorizer()
>>> authorizer.add_user('user', '12345', '/home/user', perm=('r', 'w'))
>>> authorizer.add_anonymous('/home/nobody')
>>> ftp_handler = ftpserver.FTPHandler
>>> ftp_handler.authorizer = authorizer
>>> address = ("127.0.0.1", 21)
>>> ftpd = ftpserver.FTPServer(address, ftp_handler)
>>> ftpd.serve_forever()
Serving FTP on 127.0.0.1:21
[]127.0.0.1:2503 connected.
127.0.0.1:2503 ==> 220 Ready.
127.0.0.1:2503 <== USER anonymous
127.0.0.1:2503 ==> 331 Username ok, send password.
127.0.0.1:2503 <== PASS ******
127.0.0.1:2503 ==> 230 Login successful.
[anonymous]@127.0.0.1:2503 User anonymous logged in.
127.0.0.1:2503 <== TYPE A
127.0.0.1:2503 ==> 200 Type set to: ASCII.
127.0.0.1:2503 <== PASV
127.0.0.1:2503 ==> 227 Entering passive mode (127,0,0,1,9,201).
127.0.0.1:2503 <== LIST
127.0.0.1:2503 ==> 150 File status okay. About to open data connection.
[anonymous]@127.0.0.1:2503 OK LIST "/". Transfer starting.
127.0.0.1:2503 ==> 226 Transfer complete.
[anonymous]@127.0.0.1:2503 Transfer complete. 706 bytes transmitted.
127.0.0.1:2503 <== QUIT
127.0.0.1:2503 ==> 221 Goodbye.
[anonymous]@127.0.0.1:2503 Disconnected.
"""


import asyncore
import asynchat
import socket
import os
import sys
import traceback
import errno
import time
import glob
import fnmatch
import tempfile
import warnings
import random
import stat
from tarfile import filemode

try:
    import pwd
    import grp
except ImportError:
    pwd = grp = None
    

__all__ = ['proto_cmds', 'Error', 'log', 'logline', 'debug', 'DummyAuthorizer',
           'FTPHandler', 'FTPServer', 'PassiveDTP', 'ActiveDTP', 'DTPHandler',
           'FileProducer', 'AbstractedFS',]


__pname__   = 'Python FTP server library (pyftpdlib)'
__ver__     = '0.2.0'  # XXX change ver
__date__    = '2007-17-09'  # XXX change date
__author__  = "Giampaolo Rodola' <g.rodola@gmail.com>"
__web__     = 'http://code.google.com/p/pyftpdlib/'


proto_cmds = {
    'ABOR': 'Syntax: ABOR (abort transfer).',
    'ALLO': 'Syntax: ALLO <SP> bytes (obsolete; allocate storage).',
    'APPE': 'Syntax: APPE <SP> file-name (append data to an existent file).',
    'CDUP': 'Syntax: CDUP (go to parent directory).',
    'CWD' : 'Syntax: CWD <SP> dir-name (change current working directory).',
    'DELE': 'Syntax: DELE <SP> file-name (delete file).',
    'FEAT': 'Syntax: FEAT (list all new features supported).',
    'HELP': 'Syntax: HELP [<SP> cmd] (show help).',
    'LIST': 'Syntax: LIST [<SP> path-name] (list files).',
    'MDTM': 'Syntax: MDTM <SP> file-name (get last modification time).',
    'MLSD': 'Syntax: MLSD [<SP> dir-name] (list files in a machine-processable form)',
    'MLST': 'Syntax: MLST [<SP> path-name] (show a path in a machine-processable form)',
    'MODE': 'Syntax: MODE <SP> mode (obsolete; set data transfer mode).',
    'MKD' : 'Syntax: MDK <SP> dir-name (create directory).',
    'NLST': 'Syntax: NLST [<SP> path-name] (list files in a compact form).',
    'NOOP': 'Syntax: NOOP (just do nothing).',
    'PASS': 'Syntax: PASS <SP> user-name (set user password).',
    'PASV': 'Syntax: PASV (set server in passive mode).',
    'PORT': 'Syntax: PORT <sp> h1,h2,h3,h4,p1,p2 (set server in active mode).',
    'PWD' : 'Syntax: PWD (get current working directory).',
    'QUIT': 'Syntax: QUIT (quit current session).',
    'REIN': 'Syntax: REIN (reinitialize / flush account).',
    'REST': 'Syntax: REST <SP> marker (restart file position).',
    'RETR': 'Syntax: RETR <SP> file-name (retrieve a file).',
    'RMD' : 'Syntax: RMD <SP> dir-name (remove directory).',
    'RNFR': 'Syntax: RNFR <SP> file-name (file renaming (source name)).',
    'RNTO': 'Syntax: RNTO <SP> file-name (file renaming (destination name)).',
    'SIZE': 'Syntax: HELP <SP> file-name (get file size).',
    'STAT': 'Syntax: STAT [<SP> path name] (status information [list files]).',
    'STOR': 'Syntax: STOR <SP> file-name (store a file).',
    'STOU': 'Syntax: STOU [<SP> file-name] (store a file with a unique name).',
    'STRU': 'Syntax: STRU <SP> type (obsolete; set file structure).',
    'SYST': 'Syntax: SYST (get operating system type).',
    'TYPE': 'Syntax: TYPE <SP> [A | I] (set transfer type).',
    'USER': 'Syntax: USER <SP> user-name (set username).',
    }

deprecated_cmds = {
    'XCUP': 'Syntax: XCUP (obsolete; go to parent directory).',
    'XCWD': 'Syntax: XCWD <SP> dir-name (obsolete; change current directory).',
    'XMKD': 'Syntax: XMDK <SP> dir-name (obsolete; create directory).',
    'XPWD': 'Syntax: XPWD (obsolete; get current dir).',
    'XRMD': 'Syntax: XRMD <SP> dir-name (obsolete; remove directory).',
    }

proto_cmds.update(deprecated_cmds)

# The following RFC-959 commands are not implemented. These commands
# are also not implemented by many other FTP servers
not_implemented_cmds = {
    'ACCT': 'Syntax: ACCT account-info (specify account information).',
    'SITE': 'Syntax: SITE [<SP> site-cmd] (site specific server services).',
    'SMNT': 'Syntax: SMNT <SP> path-name (mount file-system structure).'
    }


# hack around format_exc function of traceback module to grant
# backward compatibility with python < 2.4
if not hasattr(traceback, 'format_exc'):
    try:
        import cStringIO as StringIO
    except ImportError:
        import StringIO

    def _format_exc():
        f = StringIO.StringIO()
        traceback.print_exc(file=f)
        data = f.getvalue()
        f.close()
        return data

    traceback.format_exc = _format_exc


def _strerror(err):
    """A wrap around os.strerror() which may be not available on all
    platforms (e.g. pythonCE).  err argument expected must be an
    EnvironmentError (or derived) class instance.
    """
    if hasattr(os, 'strerror'):
        return os.strerror(err.errno)
    else:
        return err.strerror


# --- library defined exceptions

class Error(Exception):
    """Base class for module exceptions."""

class AuthorizerError(Error):
    """Base class for authorizer exceptions."""
    

# --- loggers

def log(msg):
    """Log messages intended for the end user."""
    print msg

def logline(msg):
    """Log commands and responses passing through the command channel."""
    print msg

def logerror(msg):
    """Log traceback outputs occurring in case of errors."""
    sys.stderr.write(str(msg) + '\n')
    sys.stderr.flush()

def debug(msg):
    """Log function/method calls (disabled by default)."""


# --- authorizers

class DummyAuthorizer:
    """Basic "dummy" authorizer class, suitable for subclassing to
    create your own custom authorizers.

    An "authorizer" is a class handling authentications and permissions
    of the FTP server.  It is used inside FTPHandler class for verifying
    user's password, getting users home directory and checking user
    permissions when a file read/write event occurs.

    DummyAuthorizer is the base authorizer, providing a platform
    independent interface for managing "virtual" FTP users. System
    dependent authorizers can by written by subclassing this base
    class and overriding appropriate methods as necessary.
    """

    user_table = {}

    def add_user(self, username, password, homedir, perm=('r'),
                    msg_login="Login successful.", msg_quit="Goodbye."):
        """Add a user to the virtual users table.  AuthorizerError
        exceptions raised on error conditions such as invalid
        permissions, missing home directory or duplicate usernames.

        Optional perm argument is a tuple defaulting to ("r")
        referencing user's permissions.  Valid values are "r"
        (read access), "w" (write access) or none at all (no access).

        Optional msg_login and msg_quit arguments can be specified to
        provide customized response strings when user log-in and quit.
        """
        if self.has_user(username):
            raise AuthorizerError('User "%s" already exists' %username)
        if not os.path.isdir(homedir):
            raise AuthorizerError('No such directory: "%s"' %homedir)
        for p in perm:
            if p not in ('', 'r', 'w'):
                raise AuthorizerError('No such permission "%s"' %p)
            if (p in 'w') and (username == 'anonymous'):
                warnings.warn("write permissions assigned to anonymous user.",
                                RuntimeWarning)
        dic = {'pwd': str(password),
               'home': str(homedir),
               'perm': perm,
               'msg_login': str(msg_login),
               'msg_quit': str(msg_quit)
               }
        self.user_table[username] = dic

    def add_anonymous(self, homedir, **kwargs):
        """Add an anonymous user to the virtual users table.
        AuthorizerError exception raised on error conditions such as
        insufficient permissions, missing home directory, or duplicate
        anonymous users.

        The keyword arguments in kwargs are the same expected by
        add_user method: "perm", "msg_login" and "msg_quit".
        The optional "perm" keyword argument is a tuple defaulting to
        ("r") referencing "read-only" anonymous user's permission.
        Using a "w" (write access) value results in a warning message
        printed to stderr.
        """
        DummyAuthorizer.add_user(self, 'anonymous', '', homedir, **kwargs)

    def remove_user(self, username):
        """Remove a user from the virtual users table."""
        del self.user_table[username]

    def validate_authentication(self, username, password):
        """Return True if the supplied username and password match the
        stored credentials."""
        return self.user_table[username]['pwd'] == password

    def has_user(self, username):
        """Whether the username exists in the virtual users table."""
        return username in self.user_table

    def get_home_dir(self, username):
        """Return the user's home directory."""
        return self.user_table[username]['home']

    def get_msg_login(self, username):
        """Return the user's login message."""
        return self.user_table[username]['msg_login']

    def get_msg_quit(self, username):
        """Return the user's quitting message."""
        return self.user_table[username]['msg_quit']

    def r_perm(self, username, obj=None):
        """Whether the user has read permissions for obj (an absolute
        pathname of a file or a directory)"""
        return 'r' in self.user_table[username]['perm']

    def w_perm(self, username, obj=None):
        """Whether the user has write permission for obj (an absolute
        pathname of a file or a directory)"""
        return 'w' in self.user_table[username]['perm']


# --- DTP classes

class PassiveDTP(asyncore.dispatcher):
    """This class is an asyncore.disptacher subclass.  It creates a
    socket listening on a local port, dispatching the resultant
    connection DTPHandler.
    """

    def __init__(self, cmd_channel):
        asyncore.dispatcher.__init__(self)
        self.cmd_channel = cmd_channel

        ip = self.cmd_channel.getsockname()[0]
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)

        if not self.cmd_channel.passive_ports:
        # By using 0 as port number value we let kernel choose a free
        # unprivileged random port.
            self.bind((ip, 0))
        else:
            ports = list(self.cmd_channel.passive_ports)
            while ports:
                port = ports.pop(random.randint(0, len(ports) -1))
                try:
                    self.bind((ip, port))
                except socket.error, why:
                    if why[0] == errno.EADDRINUSE:  # port already in use
                        if ports:
                            continue
                        # If cannot use one of the ports in the configured
                        # range we'll use a kernel-assigned port, and log
                        # a message reporting the issue.
                        # By using 0 as port number value we let kernel
                        # choose a free unprivileged random port.
                        else:
                            self.bind((ip, 0))
                            self.cmd_channel.log(
                                "Can't find a valid passive port in the "
                                "configured range. A random kernel-assigned "
                                "port will be used."
                                )
                    else:
                        raise
                else:
                    break
        self.listen(5)
        if self.cmd_channel.masquerade_address:
            ip = self.cmd_channel.masquerade_address
        port = self.socket.getsockname()[1]

        # The format of 227 response in not standardized.
        # This is the most expected:
        self.cmd_channel.respond('227 Entering passive mode (%s,%d,%d).' %(
                ip.replace('.', ','), port / 256, port % 256))

    def __del__(self):
        self.cmd_channel.debug("PassiveDTP.__del__()")

    # --- connection / overridden
    
    def handle_accept(self):
        """Called when remote client initiates a connection."""
        self.cmd_channel.debug("PassiveDTP.handle_accept()")
        sock, addr = self.accept()

        # Check the origin of data connection.  If not expressively
        # configured we drop the incoming data connection if remote
        # IP address does not match the client's IP address.
        if (self.cmd_channel.remote_ip != addr[0]):
            if not self.cmd_channel.permit_foreign_addresses:
                try:
                    sock.close()
                except socket.error:
                    pass
                msg = 'Rejected data connection from foreign address %s:%s.' \
                        %(addr[0], addr[1])
                self.cmd_channel.respond("425 %s" %msg)
                self.cmd_channel.log(msg)
                # do not close listening socket: it couldn't be client's blame
                return
            else:
                # site-to-site FTP allowed
                msg = 'Established data connection with foreign address %s:%s.'\
                        %(addr[0], addr[1])
                self.cmd_channel.log(msg)
        # Immediately close the current channel (we accept only one
        # connection at time) and avoid running out of max connections
        # limit.
        self.close()
        # delegate such connection to DTP handler
        handler = self.cmd_channel.dtp_handler(sock, self.cmd_channel)
        self.cmd_channel.data_channel = handler
        self.cmd_channel.on_dtp_connection()

    def writable(self):
        return 0

    def handle_error(self):
        """Called to handle any uncaught exceptions."""
        self.cmd_channel.debug("PassiveDTP.handle_error()")
        logerror(traceback.format_exc())
        self.close()
            
    def handle_close(self):
        """Called on closing the data connection."""
        self.cmd_channel.debug("PassiveDTP.handle_close()")
        self.close()

    def close(self):
        """Close the dispatcher socket."""
        self.cmd_channel.debug("PassiveDTP.close()")
        asyncore.dispatcher.close(self)


class ActiveDTP(asyncore.dispatcher):
    """This class is an asyncore.disptacher subclass. It creates a
    socket resulting from the connection to a remote user-port,
    dispatching it to DTPHandler.
    """

    def __init__(self, ip, port, cmd_channel):
        asyncore.dispatcher.__init__(self)
        self.cmd_channel = cmd_channel       
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.connect((ip, port))
        except socket.error:
            self.cmd_channel.respond("425 Can't connect to %s:%s." %(ip, port))
            self.close()     

    def __del__(self):
        self.cmd_channel.debug("ActiveDTP.__del__()")

    # --- connection / overridden

    def handle_write(self):
        """NOOP, must be overridden to prevent unhandled write event."""
        # without overriding this we would get an "unhandled write event"
        # message from asyncore once connection occurs.

    def handle_connect(self):
        """Called when connection is established."""
        self.cmd_channel.debug("ActiveDTP.handle_connect()")
        self.cmd_channel.respond('200 PORT command successful.')
        # delegate such connection to DTP handler
        handler = self.cmd_channel.dtp_handler(self.socket, self.cmd_channel)
        self.cmd_channel.data_channel = handler
        self.cmd_channel.on_dtp_connection()
        #self.close()  # <-- (done automatically)

    def handle_error(self):
        """Called to handle any uncaught exceptions."""
        self.cmd_channel.debug("ActiveDTP.handle_error()")
        logerror(traceback.format_exc())
        self.close()
            
    def handle_close(self):
        """Called on closing the data channel."""
        self.cmd_channel.debug("ActiveDTP.handle_close()")
        self.close()

    def close(self):
        """Close the dispatcher socket."""
        self.cmd_channel.debug("ActiveDTP.close()")
        asyncore.dispatcher.close(self)


try:
    from collections import deque
except ImportError:
    # backward compatibility with Python < 2.4 by replacing deque with a list
    class deque(list):
        def appendleft(self, obj):
            list.insert(self, 0, obj)


class DTPHandler(asyncore.dispatcher):
    """Class handling server-data-transfer-process (server-DTP, see
    RFC-959) managing data-transfer operations.

    sock_obj is the underlying socket used for the connection,
    cmd_channel is the FTPHandler class instance.
    
    DTPHandler implementation note:
    When a producer is consumed and close_when_done() has been called
    previously, refill_buffer() erroneously calls close() instead of
    handle_close() - (see: http://bugs.python.org/issue1740572)

    To avoid this problem, DTPHandler is implemented as a subclass of
    asyncore.dispatcher. This implementation follows the same approach
    that asynchat module should use in Python 2.6.

    The most important change in the implementation is related to
    producer_fifo, which is a pure deque object instead of a
    producer_fifo instance.

    Since we don't want to break backward compatibily with older python
    versions (deque has been introduced in Python 2.4), if deque is not
    available we use a list instead.
    """

    ac_in_buffer_size = 8192
    ac_out_buffer_size  = 8192

    def __init__(self, sock_obj, cmd_channel):        
        """Initialize the DTPHandler instance, replacing asynchat's
        "simple producer" deque wrapper with a pure deque object.
        """
        asyncore.dispatcher.__init__(self, sock_obj)
        # we toss the use of the asynchat's "simple producer" and
        # replace it  with a pure deque, which the original fifo
        # was a wrapping of
        self.producer_fifo = deque()

        self.cmd_channel = cmd_channel
        self.file_obj = None
        self.receive = False
        self.transfer_finished = False
        self.tot_bytes_sent = 0
        self.tot_bytes_received = 0        

    def __del__(self):
        self.cmd_channel.debug("DTPHandler.__del__()")

    # --- utility methods
    
    def enable_receiving(self, type):
        """Enable receiving of data over the channel. Depending on the
        TYPE currently in use it creates an appropriate wrapper for the
        incoming data.
        """
        if type == 'a':
            self.data_wrapper = lambda x: x.replace('\r\n', os.linesep)
        else:
            self.data_wrapper = lambda x: x
        self.receive = True

    def get_transmitted_bytes(self):
        "Return the number of transmitted bytes."
        return self.tot_bytes_sent + self.tot_bytes_received

    def transfer_in_progress(self):
        "Return True if a transfer is in progress, else False."
        return self.get_transmitted_bytes() != 0

    # --- connection

    def handle_read(self):
        """Called when there is data waiting to be read."""
        try:
            chunk = self.recv(self.ac_in_buffer_size)
        except socket.error:
            self.handle_error()
        else:
            self.tot_bytes_received += len(chunk)
            if not chunk:
                self.transfer_finished = True
                #self.close()  # <-- asyncore.recv() already do that...
                return
            # while we're writing on the file an exception could occur
            # in case  that filesystem gets full;  if this happens we
            # let handle_error() method handle this exception, providing
            # a detailed error message.
            self.file_obj.write(self.data_wrapper(chunk))

    def handle_write(self):
        """Called when data is ready to be written, initiates send."""
        self.initiate_send()

    def push(self, data):
        """Pushes data onto the deque and initiate send."""
        sabs = self.ac_out_buffer_size
        if len(data) > sabs:
            for i in xrange(0, len(data), sabs):
                self.producer_fifo.append(data[i:i+sabs])
        else:
            self.producer_fifo.append(data)
        self.initiate_send()

    def push_with_producer(self, producer):
        """Push data using a producer and initiate send."""
        self.producer_fifo.append(producer)
        self.initiate_send()

    def readable(self):
        """Predicate for inclusion in the readable for select()."""
        # cannot use the old predicate, it violates the claim of the
        # set_terminator method.
        #return (len(self.ac_in_buffer) <= self.ac_in_buffer_size)
        return self.receive

    def writable(self):
        """Predicate for inclusion in the writable for select()."""
        return self.producer_fifo or (not self.connected)

    def close_when_done(self):
        """Automatically close this channel once the outgoing queue is empty."""
        self.producer_fifo.append(None)

    def initiate_send(self):
        """Attempt to send data in fifo order."""
        while self.producer_fifo and self.connected:
            first = self.producer_fifo[0]
            # handle empty string/buffer or None entry
            if not first:
                del self.producer_fifo[0]
                if first is None:
                    self.transfer_finished = True
                    self.handle_close()
                    return

            # handle classic producer behavior
            obs = self.ac_out_buffer_size
            try:
                data = buffer(first, 0, obs)
            except TypeError:
                self.producer_fifo.appendleft(first.more())
                continue

            # send the data
            try:
               num_sent = self.send(data)
            except socket.error:
               self.handle_error()
               return

            if num_sent:
                self.tot_bytes_sent += num_sent
                if num_sent < len(data) or obs < len(first):
                    self.producer_fifo[0] = first[num_sent:]
                else:
                    del self.producer_fifo[0]
            # we tried to send some actual data
            return

    def handle_expt(self):
        """Called on "exceptional" data events."""
        self.cmd_channel.debug("DTPHandler.handle_expt()")
        self.cmd_channel.respond("426 Connection error; transfer aborted.")
        self.close()

    def handle_error(self):
        """Called when an exception is raised and not otherwise handled."""
        self.cmd_channel.debug("DTPHandler.handle_error()")
        try:
            raise
        # if error is connection related we provide a detailed
        # information about it
        except socket.error, err:
            if err[0] in errno.errorcode:
                error = err[1]
            else:
                error = "Unknown connection error"
        # an error could occur in case we fail reading / writing
        # from / to file (e.g. file system gets full)
        except EnvironmentError, err:
            error = _strerror(err)
        except:
            # some other exception occurred; we don't want to provide
            # confidential error messages to user so we return a
            # generic "unknown error" response.
            logerror(traceback.format_exc())            
            error = "Unknown error"
        self.cmd_channel.respond("426 %s; transfer aborted." %error)
        self.close()

    def handle_close(self):
        """Called when the socket is closed."""
        self.cmd_channel.debug("DTPHandler.handle_close()")
        tot_bytes = self.get_transmitted_bytes()
        # If we used channel for receiving we assume that transfer is
        # finished when client close connection , if we used channel
        # for sending we have to check that all data has been sent
        # (responding with 226) or not (responding with 426).
        if self.receive:
            self.transfer_finished = True
        if self.transfer_finished:
            self.cmd_channel.respond("226 Transfer complete.")
            self.cmd_channel.log("Transfer complete; "
                                 "%d bytes transmitted." %tot_bytes)
        else:
            self.cmd_channel.respond("426 Connection closed; transfer aborted.")
            self.cmd_channel.log("Transfer aborted; "
                                 "%d bytes transmitted." %tot_bytes)
        self.close()

    def close(self):
        """Close the data channel, first attempting to close any remaining
        file handles."""
        self.cmd_channel.debug("DTPHandler.close()")
        if self.file_obj:
            if not self.file_obj.closed:
                self.file_obj.close()
        while self.producer_fifo:
            first = self.producer_fifo.pop()
            if hasattr(first, 'close'):
                first.close()
        asyncore.dispatcher.close(self)
        self.cmd_channel.on_dtp_close()



# --- file producer

# Taken from Sam Rushing's Medusa-framework. Similar to
# asynchat.simple_producer class, but operates on file(-like)
# objects instead of strings.

class FileProducer:
    """Producer wrapper for file[-like] objects.

    Depending on the type it creates an appropriate wrapper for the
    outgoing data.
    """

    out_buffer_size = 65536

    def __init__(self, file, type):
        """Intialize the producer with a data_wrapper appropriate to TYPE."""
        self.done = 0
        self.file = file
        if type == 'a':
            self.data_wrapper = lambda x: x.replace(os.linesep, '\r\n')
        else:
            self.data_wrapper = lambda x: x

    def more(self):
        """Attempt a chunk of data of size self.out_buffer_size."""
        if self.done:
            return ''
        else:
            data = self.data_wrapper(
                self.file.read(self.out_buffer_size))
            if not data:
                self.done = 1
                self.close()
            else:
                return data

    def close(self):
        """Close the file[-like] object."""
        if not self.file.closed:
            self.file.close()


# --- filesystem

class AbstractedFS:
    """A class used to interact with the file system, providing a high
    level, cross-platform interface compatible with both Windows and
    UNIX style filesystems.

    It provides some utility methods and some wraps around operations
    involved in file object creation and file system operations like
    moving files or removing directories.
    """

    def __init__(self):
        self.root = None
        self.cwd = '/'
        self.rnfr = None

    # --- Conversion utilities

    def ftpnorm(self, ftppath):
        """Normalize a "virtual" ftp pathname (tipically the raw string
        coming from client) depending on the current working directory.
        
        Example (having "/foo" as current working directory):
        'x' -> '/foo/x'

        Note: directory separators are system independent ("/").
        Pathname returned is always absolutized.
        """
        if os.path.isabs(ftppath):
            p = os.path.normpath(ftppath)
        else:
            p = os.path.normpath(os.path.join(self.cwd, ftppath))
        # normalize string in a standard web-path notation having '/'
        # as separator.
        p = p.replace("\\", "/")
        # os.path.normpath supports UNC paths (e.g. "//a/b/c") but we
        # don't need them.  In case we get an UNC path we collapse
        # redundant separators appearing at the beginning of the string
        while p[:2] == '//':
            p = p[1:]
        # Anti path traversal: don't trust user input, in the event
        # that self.cwd is not absolute, return "/" as a safety measure.
        # This is for extra protection, maybe not really necessary.
        if not os.path.isabs(p):
            p = "/"
        return p

    def ftp2fs(self, ftppath):
        """Translate a "virtual" ftp pathname (tipically the raw string
        coming from client) into equivalent absolute "real" filesystem
        pathname.
        
        Example (having "/home/user" as root directory):
        'x' -> '/home/user/x'
        
        Note: directory separators are system dependent.
        """
        # as far as I know, it should always be path traversal safe...
        if os.path.normpath(self.root) == os.sep:
            return os.path.normpath(self.ftpnorm(ftppath))
        else:
            p = self.ftpnorm(ftppath)[1:]
            return os.path.normpath(os.path.join(self.root, p))
        
    def fs2ftp(self, fspath):
        """Translate a "real" filesystem pathname into equivalent
        absolute "virtual" ftp pathname depending on the user's
        root directory.
        
        Example (having "/home/user" as root directory):
        '/home/user/x' -> '/x'
        
        As for ftpnorm, directory separators are system independent
        ("/") and pathname returned is always absolutized.

        On invalid pathnames escaping from user's root directory
        (e.g. "/home" when root is "/home/user") always return "/".
        """
        if os.path.isabs(fspath):
            p = os.path.normpath(fspath)
        else:
            p = os.path.normpath(os.path.join(self.root, fspath))
        if not self.validpath(p):
            return '/'
        p = p.replace(os.sep, "/")
        p = p[len(self.root):]
        if not p.startswith('/'):
            p = '/' + p
        return p
    
    # alias for backward compatibility with 0.2.0
    normalize = ftpnorm
    translate = ftp2fs
        
    # --- Wrapper methods around open() and tempfile.mkstemp
    
    def open(self, filename, mode):
        """Open a file returning its handler."""
        return open(filename, mode)

    def mkstemp(self, suffix='', prefix='', dir=None, mode='wb'):
        """A wrap around tempfile.mkstemp creating a file with a unique
        name. Unlike mkstemp it returns an object with a file-like
        interface. The 'name' attribute contains the absolute file name.
        """
        class FileWrapper:
            def __init__(self, fd, name):
                self.file = fd
                self.name = name
            def __getattr__(self, attr):
                return getattr(self.file, attr)

        text = not 'b' in mode
        # max number of tries to find out a unique file name
        tempfile.TMP_MAX = 50 
        fd, name = tempfile.mkstemp(suffix, prefix, dir, text=text)
        file = os.fdopen(fd, mode)
        return FileWrapper(file, name)
    
    # --- Wrapper methods around os.*
    
    def chdir(self, path):
        """Change the current directory."""
        # temporarily join the specified directory to see if we have
        # permissions to do so
        basedir = os.getcwd()
        try:
            os.chdir(path)
        except os.error:
            raise
        else:
            os.chdir(basedir)
            self.cwd = self.fs2ftp(path)

    def mkdir(self, path):
        """Create the specified directory."""
        os.mkdir(path)

    def listdir(self, path):
        """List the content of a directory."""
        return os.listdir(path)

    def rmdir(self, path):
        """Remove the specified directory."""
        os.rmdir(path)

    def remove(self, path):
        """Remove the specified file."""
        os.remove(path)
        
    def rename(self, src, dst):
        """Rename the specified src file to the dst filename."""
        os.rename(src, dst)

    def stat(self, path):
        """Perform a stat() system call on the given path."""
        return os.stat(path)

    def lstat(self, path):
        """Like stat but does not follow symbolic links."""
        return os.lstat(path)

    if not hasattr(os, 'lstat'):
        lstat = stat
        
    # --- Wrapper methods around os.path.*

    def isfile(self, path):
        """Return True if path is a file."""
        return os.path.isfile(path)

    def islink(self, path):
        """Return True if path is a symbolic link."""
        return os.path.islink(path)

    def isdir(self, path):
        """Return True if path is a directory."""
        return os.path.isdir(path)
    
    def getsize(self, path):
        """Return the size of the specified file in bytes."""
        return os.path.getsize(path)

    def getmtime(self, path):
        """Return the last modified time as a number of seconds since
        the epoch."""
        return os.path.getmtime(path)
    
    def realpath(self, path):
        """Return the canonical version of path eliminating any
        symbolic links encountered in the path (if they are
        supported by the operating system).
        """
        return os.path.realpath(path)
    
    def lexists(self, path):
        """Return True if path refers to an existing path, including
        a broken or circular symbolic link.
        """
        if hasattr(os.path, 'lexists'):
            return os.path.lexists(path)
        # grant backward compatibility with python 2.3
        elif hasattr(os, 'lstat'):
            try:
                st = os.lstat(path)
            except os.error:
                return False
            return True
        # fallback
        else:
            return os.path.exists(path)

    exists = lexists  # alias for backward compatibility with 0.2.0

    # --- Utility methods
    
    def validpath(self, path):
        """Check whether the path belongs to user's home directory.
        Expected argument is a "real" filesystem path. If path is a
        symbolic link it is resolved to check its real destination.
        Pathnames escaping from user's root directory are considered
        not valid.
        """
        root = self.realpath(self.root)
        path = self.realpath(path)
        if not self.root.endswith(os.sep):
            root = self.root + os.sep
        if not path.endswith(os.sep):
            path = path + os.sep
        if path[0:len(root)] == root:
            return True
        return False
    
    def glob1(self, dirname, pattern):
        """Return a list of files matching a dirname pattern
        non-recursively.
        Unlike glob.glob1 raises exception if os.listdir() fails.
        """
        names = self.listdir(dirname)
        if pattern[0] != '.':
            names = filter(lambda x: x[0] != '.',names)
        return fnmatch.filter(names, pattern)
    
    # --- Listing utilities
    
    # Note that these are resource-intensive blocking operations so
    # you may want to override and move them into another
    # process/thread in some way.
    
    def get_list_dir(self, path):
        """Return a directory listing in a form suitable for LIST command."""
        if self.isdir(path):
            listing = self.listdir(path)
            listing.sort()
            return self.format_list(path, listing)
        # if path is a file or a symlink we return information about it
        else:
            basedir, filename = os.path.split(path)
            return self.format_list(basedir, [filename], ignore_err=False)

    def get_stat_dir(self, rawline):
        """Return a list of files matching a dirname pattern
        non-recursively in a form suitable for STAT command.
        rawline is the argument passed by client.
        """
        path = self.ftpnorm(rawline)
        basedir, basename = os.path.split(path)
        if not glob.has_magic(path):
            data = self.get_list_dir(self.ftp2fs(rawline))
        else:
            if not basedir:
                basedir = self.ftp2fs(self.cwd)
                listing = self.glob1(basedir, basename)
                listing.sort()
                data = self.format_list(basedir, listing)
            elif glob.has_magic(basedir):
                return 'Directory recursion not supported.\r\n'
            else:
                basedir = self.ftp2fs(basedir)
                listing = self.glob1(basedir, basename)
                listing.sort()
                data = self.format_list(basedir, listing)
        if not data:
            return "Directory is empty.\r\n"
        return data

    def format_list(self, basedir, listing, ignore_err=True):
        """Return a directory listing emulating "/bin/ls -lA" UNIX
        command output.

         - basedir: the absolute dirname
         - listing: a list containing the names of the entries in basedir
         - ignore_err: if False raise exception if os.stat() call fails
    
        On platforms which do not support the pwd and grp modules (such
        as Windows), ownership is printed as "owner" and "group" as a
        default, and number of hard links is always "1". On UNIX
        systems, the actual owner, group, and number of links are
        printed.
    
        This is how output appears to client:
    
        -rw-rw-rw-   1 owner   group    7045120 Sep 02  3:47 music.mp3
        drwxrwxrwx   1 owner   group          0 Aug 31 18:50 e-books
        -rw-rw-rw-   1 owner   group        380 Sep 02  3:40 module.py
        """
        result = []
        for basename in listing:
            file = os.path.join(basedir, basename)
            try:
                st = self.lstat(file)
            except os.error:
                if ignore_err:
                    continue
                raise
            perms = filemode(st.st_mode)  # permissions
            nlinks = st.st_nlink  # number of links to inode
            if not nlinks:  # non-posix system, let's use a bogus value
                nlinks = 1
            size = st.st_size  # file size
            if pwd and grp:
                # get user and group name, else just use the raw uid/gid
                try:
                    uname = pwd.getpwuid(st.st_uid).pw_name
                except KeyError:
                    uname = st.st_uid
                try:
                    gname = grp.getgrgid(st.st_gid).gr_name
                except KeyError:
                    gname = st.st_gid
            else:
                # on non-posix systems the only chance we use default
                # bogus values for owner and group
                uname = "owner"
                gname = "group"
            # stat.st_mtime could fail (-1) if last mtime is too old
            # in which case we return the local time as last mtime
            try:
                mtime = time.strftime("%b %d %H:%M", time.localtime(st.st_mtime))
            except ValueError:
                mtime = time.strftime("%b %d %H:%M")
            # if the file is a symlink, resolve it, e.g. "symlink -> realfile"
            if stat.S_ISLNK(st.st_mode):
                basename = basename + " -> " + os.readlink(file)
                
            # formatting is matched with proftpd ls output
            result.append("%s %3s %-8s %-8s %8s %s %s\r\n" %(perms, nlinks,
                                                             uname, gname, size,
                                                             mtime, basename))
        return ''.join(result)
    
    def format_mlsx(self, basedir, listing, ignore_err=True):
        """Return a directory listing in a form suitable with MLSD and
        MLST commands including a list of "facts" referring the listed
        elements.
        
        See RFC-3659, chapter 7, to see what every single fact stands
        for.

         - basedir: the absolute dirname
         - listing: a list containing the names of the entries in basedir
         - ignore_err: if False raise exception if os.stat() call fails

        Note that "facts" returned may change depending on the platform
        and on what user specified by using the OPTS command (if
        implemented).

        This is how output could appear to the client issuing
        a MLSD request:

        type=file;size=156;modify=20071029155301;unique=801cd012; music.mp3
        type=dir;size=4096;modify=20071127230206;unique=801e38e3; ebooks
        type=file;size=211;modify=20071103093626;unique=801e38e2; module.py
        """
        ftype = size = modify = create = mode = uid = gid = unique = ""
        result = []
        for basename in listing:
            file = os.path.join(basedir, basename)
            try:
                st = self.stat(file)
            except OSError:
                if ignore_err:
                    continue
                raise
            # file type
            if stat.S_ISDIR(st.st_mode):
                if basename == '.':
                    ftype = 'type=cdir;'
                elif basename == '..':
                    ftype = 'type=pdir;'
                else:
                    ftype = 'type=dir;'
            else:
                ftype = 'type=file;'
            size = 'size=%s;' %st.st_size  # file size
            # last modification time
            try:
                modify = 'modify=%s;' %time.strftime("%Y%m%d%H%M%S",
                                       time.localtime(st.st_mtime))
            except ValueError:
                # stat.st_mtime could fail (-1) if last mtime is too old
                modify = ""
            if os.name == 'nt':
                # on Windows we can provide also the creation time
                try:
                    create = 'create=%s;' %time.strftime("%Y%m%d%H%M%S",
                                           time.localtime(st.st_ctime))
                except ValueError:
                    create = ""
            # Provide uid, gid and mode facts if we're on a UNIX system.
            # We assume that by checking if pwd and grp are imported.
            # Theorically we could provide mode also on Windows but I'm
            # not sure about its reliability.
            if pwd and grp:
                mode = 'UNIX.mode=%s;' %oct(st.st_mode & 0777)
                uid = 'UNIX.uid=%s;' %st.st_uid
                gid = 'UNIX.gid=%s;' %st.st_gid
            # Provide unique fact (see RFC-3659, chapter 7.5.2) on
            # posix platforms only; we get it by mixing st_dev and
            # st_ino values which should be enough for granting an
            # uniqueness for the file listed.
            # The same approach is used by pure-ftpd.
            # Implementors who want to provide unique fact on other
            # platforms should use some platform-specific method (e.g.
            # on Windows NTFS filesystems MTF records could be used).
            if os.name == 'posix':
                unique = "unique=%x%x;" %(st.st_dev, st.st_ino)

            result.append("%s%s%s%s%s%s%s%s %s\r\n" %(ftype, size, modify,
                                                      create, mode, uid, gid,
                                                      unique, basename))
        return ''.join(result)


# --- FTP

class FTPHandler(asynchat.async_chat):
    """Implements the FTP server Protocol Interpreter (see RFC-959),
    handling commands received from the client on the control channel
    by calling the command's corresponding method. e.g. for received
    command "MKD pathname", ftp_MKD() method is called with "pathname"
    as the argument.

    conn and ftpd_instance parameters are automatically passed by
    FTPServer class instance.

    All relevant session information is stored in instance variables.
    """
    # these are overridable defaults:

    # default classes
    authorizer = DummyAuthorizer()
    active_dtp = ActiveDTP
    passive_dtp = PassiveDTP
    dtp_handler = DTPHandler
    abstracted_fs = AbstractedFS

    # String returned when client connects
    banner = "pyftpdlib %s ready." %__ver__

    # Maximum number of wrong authentications before disconnecting
    max_login_attempts = 3

    # FTP site-to-site transfer feature: also referenced as "FXP" it
    # permits for transferring a file between two remote FTP servers
    # without the transfer going through the client's host (not
    # recommended for security reasons as described in RFC-2577).
    # Having this attribute set to False means that all data
    # connections from/to remote IP addresses which do not match the
    # client's IP address will be dropped.
    permit_foreign_addresses = False

    # Set to True if you want to permit active data connections (PORT)
    # over privileged ports (not recommended).
    permit_privileged_ports = False

    # The "masqueraded" IP address to provide along PASV reply when
    # pyftpdlib is running behind a NAT or other types of gateways.
    # When configured pyftpdlib will hide its local address and instead
    # use the public address of your NAT.
    masquerade_address = None

    # What ports ftpd will use for its passive data transfers.
    # Value expected is a list of integers (e.g. range(60000, 65535)).
    # When configured pyftpdlib will no longer use kernel-assigned
    # random ports.
    passive_ports = None

    def __init__(self, conn, ftpd_instance):
        asynchat.async_chat.__init__(self, conn=conn)
        self.ftpd_instance = ftpd_instance
        self.remote_ip, self.remote_port = self.socket.getpeername()
        self.in_buffer = []
        self.in_buffer_len = 0
        self.set_terminator("\r\n")

        # session attributes
        self.fs = self.abstracted_fs()
        self.in_dtp_queue = None
        self.out_dtp_queue = None
        self.authenticated = False
        self.username = ""
        self.attempted_logins = 0
        self.current_type = 'a'
        self.restart_position = 0
        self.quit_pending = False

        # dtp attributes
        self.data_server = None
        self.data_channel = None

    def __del__(self):
        debug("FTPHandler.__del__()")

    def handle(self):
        """Return a 220 'Ready' response to the client over the command
        channel.
        """
        if len(self.banner) <= 75:
            self.respond("220 %s" %str(self.banner))
        else:
            self.push('220-%s\r\n' %str(self.banner))
            self.respond('220 ')

    def handle_max_cons(self):
        """Called when limit for maximum number of connections is reached."""
        msg = "Too many connections. Service temporary unavailable."
        self.respond("421 %s" %msg)
        self.log(msg)
        # If self.push is used, data could not be sent immediately in
        # which case a new "loop" will occur exposing us to the risk of
        # accepting new connections.  Since this could cause asyncore to
        # run out of fds (...and exposes the server to DoS attacks), we
        # immediately close the channel by using close() instead of
        # close_when_done(). If data has not been sent yet client will
        # be silently disconnected.
        self.close()

    def handle_max_cons_per_ip(self):
        """Called when too many clients are connected from the same IP."""
        msg = "Too many connections from the same IP address."
        self.respond("421 %s" %msg)
        self.log(msg)
        self.close_when_done()

    # --- asyncore / asynchat overridden methods

    def readable(self):
        # if there's a quit pending we stop reading data from socket
        return not self.quit_pending

    def collect_incoming_data(self, data):
        """Read incoming data and append to the input buffer."""
        self.in_buffer.append(data)
        self.in_buffer_len += len(data)
        # Flush buffer if it gets too long (possible DoS attacks).
        # RFC-959 specifies that a 500 response could be given in
        # such cases
        buflimit = 2048
        if self.in_buffer_len > buflimit:
            self.respond('500 Command too long.')
            self.log('Command received exceeded buffer limit of %s.' %(buflimit))
            self.in_buffer = []
            self.in_buffer_len = 0

    # commands accepted before authentication
    unauth_cmds = ('FEAT','HELP','NOOP','PASS','QUIT','STAT','SYST','USER')

    # commands needing an argument
    arg_cmds = ('ALLO','APPE','DELE','MDTM','MODE','MKD', 'PORT','REST','RETR','RMD',
                'RNFR','RNTO','SIZE', 'STOR','STRU','TYPE','USER','XMKD','XRMD')

    # commands needing no argument
    unarg_cmds = ('ABOR','CDUP','FEAT','NOOP','PASV','PWD','QUIT','REIN','SYST',
                  'XCUP','XPWD')

    def found_terminator(self):
        r"""Called when the incoming data stream matches the \r\n terminator."""
        line = ''.join(self.in_buffer)
        self.in_buffer = []
        self.in_buffer_len = 0

        cmd = line.split(' ')[0].upper()
        space = line.find(' ')
        if space != -1:
            arg = line[space + 1:]
        else:
            arg = ""

        if cmd != 'PASS':
            self.logline("<== %s" %line)
        else:
            self.logline("<== %s %s" %(line.split(' ')[0], '*' * 6))

        # let's check if user provided an argument for those commands
        # needing one
        if not arg and cmd in self.arg_cmds:
            self.cmd_missing_arg()
            return

        # let's do the same for those commands requiring no argument.
        elif arg and cmd in self.unarg_cmds:
            self.cmd_needs_no_arg()
            return

        # provide a limited set of commands if user isn't
        # authenticated yet
        if (not self.authenticated):
            if cmd in self.unauth_cmds:
                # we permit STAT during this phase but we don't want
                # STAT to return a directory LISTing if the user is
                # not authenticated yet (this could happen if STAT
                # is used with an argument)
                if (cmd == 'STAT') and arg:
                    self.respond("530 Log in with USER and PASS first.")
                else:
                    method = getattr(self, 'ftp_' + cmd)
                    method(arg)  # call the proper ftp_* method
            elif cmd in proto_cmds:
                self.respond("530 Log in with USER and PASS first.")
            else:
                self.cmd_not_understood(line)

        # provide full command set
        elif (self.authenticated) and (cmd in proto_cmds):
            # For the following commands we have to make sure that the
            # real path destination belongs to the user's root
            # directory.  If provided path is a symlink we follow its
            # final destination to do so.
            if cmd in ('APPE','CWD','DELE','MDTM','NLST','MLSD','MLST','RETR',
                       'RMD','SIZE','STOR','XCWD','XRMD'):
                if not self.fs.validpath(self.fs.ftp2fs(arg)):
                    line = self.fs.ftpnorm(arg)
                    err = '"%s" points to a path which is outside ' \
                          "the user's root directory" %line
                    self.respond("550 %s." %err)
                    self.log('FAIL %s "%s". %s.' %(cmd, line, err))
                    return
            method = getattr(self, 'ftp_' + cmd)
            method(arg)  # call the proper ftp_* method

        else:
            # recognize those commands having "special semantics"
            if 'ABOR' in cmd:
                self.ftp_ABOR("")
            elif 'STAT' in cmd:
                self.ftp_STAT("")
            # unknown command
            else:
                self.cmd_not_understood(line)

    def handle_expt(self):
        """Called when there is out of band (OOB) data for the socket
        connection. This could happen in case of such commands needing
        "special action" (typically STAT and ABOR) in which case we
        append OOB data to incoming buffer.
        """
        self.debug("FTPHandler.handle_expt()")
        if hasattr(socket, 'MSG_OOB'):
            try:
                data = self.socket.recv(1024, socket.MSG_OOB)
            except socket.error:
                pass
            else:
                self.in_buffer.append(data)
                return
        self.log("Can't handle OOB data.")
        self.close()

    def handle_error(self):
        self.debug("FTPHandler.handle_error()")
        logerror(traceback.format_exc())
        self.close()

    def handle_close(self):
        self.debug("FTPHandler.handle_close()")
        self.close()

    def close(self):
        """Close the current channel disconnecting the client."""
        self.debug("FTPHandler.close()")

        if self.data_server:
            self.data_server.close()
            del self.data_server

        if self.data_channel:
            self.data_channel.close()
            del self.data_channel

        del self.out_dtp_queue
        del self.in_dtp_queue

        # remove client IP address from ip map
        self.ftpd_instance.ip_map.remove(self.remote_ip)
        asynchat.async_chat.close(self)
        self.log("Disconnected.")


    # --- callbacks

    def on_dtp_connection(self):
        """Called every time data channel connects (either active or
        passive). Incoming and outgoing queues are checked for pending
        data. If outbound data is pending, it is pushed into the data
        channel. If awaiting inbound data, the data channel is enabled
        for receiving.
        """
        self.debug("FTPHandler.on_dtp_connection()")
        if self.data_server:
            self.data_server.close()
        self.data_server = None

        # check for data to send
        if self.out_dtp_queue:
            data, isproducer, log = self.out_dtp_queue
            if log:
                self.log(log)
            if not isproducer:
                self.data_channel.push(data)
            else:
                self.data_channel.push_with_producer(data)
            if self.data_channel:
                self.data_channel.close_when_done()
            self.out_dtp_queue = None

        # check for data to receive
        elif self.in_dtp_queue:
            fd, log = self.in_dtp_queue
            if log:
                self.log(log)
            self.data_channel.file_obj = fd
            self.data_channel.enable_receiving(self.current_type)
            self.in_dtp_queue = None

    def on_dtp_close(self):
        """Called on DTPHandler.close()."""
        self.debug("FTPHandler.on_dtp_close()")
        self.data_channel = None
        if self.quit_pending:
            self.close_when_done()

    # --- utility

    def respond(self, resp):
        """Send a response to the client using the command channel."""
        self.push(resp + '\r\n')
        self.logline('==> %s' % resp)

    def push_dtp_data(self, data, isproducer=False, log=''):
        """Called every time a RETR, LIST or NLST is received. Pushes
        data into the data channel.  If data channel does not exist yet,
        we queue the data to send later.  Data will then be pushed into
        data channel when on_dtp_connection() is called.

        "data" argument can be either a string or a producer of data to
        push. boolean argument isproducer; if True we assume that is a
        producer. log argument is a string to log this push event with.
        """
        if self.data_channel:
            self.respond("125 Data connection already open. Transfer starting.")
            if log:
                self.log(log)
            if not isproducer:
                self.data_channel.push(data)
            else:
                self.data_channel.push_with_producer(data)
            if self.data_channel:
                self.data_channel.close_when_done()
        else:
            self.respond("150 File status okay. About to open data connection.")
            self.out_dtp_queue = (data, isproducer, log)

    def cmd_not_understood(self, line):
        """Return a 'command not understood' message to the client."""
        self.respond('500 Command "%s" not understood.' %line)

    def cmd_missing_arg(self):
        """Return a 'missing argument' message to the client."""
        self.respond("501 Syntax error: command needs an argument.")

    def cmd_needs_no_arg(self):
        """Return a 'command does not accept arguments' message to the client."""
        self.respond("501 Syntax error: command does not accept arguments.")

    def log(self, msg):
        """Log a message, including additional identifying session data."""
        log("[%s]@%s:%s %s" %(self.username, self.remote_ip, self.remote_port, msg))

    def logline(self, msg):
        """Log a line including additional indentifying session data."""
        logline("%s:%s %s" %(self.remote_ip, self.remote_port, msg))

    def debug(self, msg):
        """Log a debug message."""
        debug(msg)

    def flush_account(self):
        """Flush account information by clearing attributes that need
        to be reset on a REIN or new USER command.
        """
        if self.data_channel:
            if not self.data_channel.transfer_in_progress():
                self.data_channel.close()
                self.data_channel = None
        if self.data_server:
            self.data_server.close()
            self.data_server = None

        self.fs.rnfr = None
        self.authenticated = False
        self.username = ""
        self.attempted_logins = 0
        self.current_type = 'a'
        self.restart_position = 0
        self.quit_pending = False
        self.in_dtp_queue = None
        self.out_dtp_queue = None


        # --- connection

    def ftp_PORT(self, line):
        """Start an active data-channel."""
        # Parse PORT request for getting IP and PORT.
        # Request comes in as:
        # > h1,h2,h3,h4,p1,p2
        # ...where the client's IP address is h1.h2.h3.h4 and the TCP
        # port number is (p1 * 256) + p2.
        try:
            line = line.split(',')
            ip = ".".join(line[:4]).replace(',','.')
            port = (int(line[4]) * 256) + int(line[5])
        except (ValueError, OverflowError):
            self.respond("501 Invalid PORT format.")
            return

        # FTP bounce attacks protection: according to RFC-2577 it's
        # recommended to reject PORT if IP address specified in it
        # does not match client IP address.
        if not self.permit_foreign_addresses:
            if ip != self.remote_ip:
                self.log("Rejected data connection to foreign address %s:%s."
                        %(ip, port))
                self.respond("501 Can't connect to a foreign address.")
                return

        # ...another RFC-2577 recommendation is rejecting connections
        # to privileged ports (< 1024) for security reasons.
        if not self.permit_privileged_ports:
            if port < 1024:
                self.log('PORT against the privileged port "%s" refused.' %port)
                self.respond("501 Can't connect over a privileged port.")
                return

        # close existent DTP-server instance, if any.
        if self.data_server:
            self.data_server.close()
            self.data_server = None

        if self.data_channel:
            self.data_channel.close()
            self.data_channel = None

        # make sure we are not hitting the max connections limit
        if self.ftpd_instance.max_cons:
            if len(self._map) >= self.ftpd_instance.max_cons:
                msg = "Too many connections. Can't open data channel."
                self.respond("425 %s" %msg)
                self.log(msg)
                return

        # open DTP channel
        self.active_dtp(ip, port, self)

    def ftp_PASV(self, line):
        """Start a passive data-channel."""
        # close existing DTP-server instance, if any
        if self.data_server:
            self.data_server.close()
            self.data_server = None

        if self.data_channel:
            self.data_channel.close()
            self.data_channel = None

        # make sure we are not hitting the max connections limit
        if self.ftpd_instance.max_cons:
            if len(self._map) >= self.ftpd_instance.max_cons:
                msg = "Too many connections. Can't open data channel."
                self.respond("425 %s" %msg)
                self.log(msg)
                return

        # open DTP channel
        self.data_server = self.passive_dtp(self)

    def ftp_QUIT(self, line):
        """Quit the current session."""
        # From RFC-959:
        # This command terminates a USER and if file transfer is not
        # in progress, the server closes the control connection.
        # If file transfer is in progress, the connection will remain
        # open for result response and the server will then close it.
        if self.authenticated:
            msg_quit = self.authorizer.get_msg_quit(self.username)
        else:
            msg_quit = "Goodbye."
        if len(msg_quit) <= 75:
            self.respond("221 %s" %msg_quit)
        else:
            self.push("221-%s\r\n" %msg_quit)
            self.respond("221 ")

        if not self.data_channel:
            self.close_when_done()
        else:
            # tell the cmd channel to stop responding to commands.
            self.quit_pending = True


        # --- data transferring

    def ftp_LIST(self, line):
        """Return a list of files in the specified directory to the
        client.
        """
        # - If no argument, fall back on cwd as default.
        # - Some older FTP clients erroneously issue /bin/ls-like LIST
        #   formats in which case we fall back on cwd as default.
        if not line or line.lower() in ('-a', '-l', '-al', '-la'):
            line = self.fs.cwd
        path = self.fs.ftp2fs(line)
        line = self.fs.ftpnorm(line)
        try:
            data = self.fs.get_list_dir(path)
        except OSError, err:
            why = _strerror(err)
            self.log('FAIL LIST "%s". %s.' %(line, why))
            self.respond('550 %s.' %why)
        else:
            self.push_dtp_data(data, log='OK LIST "%s". Transfer starting.' %line)

    def ftp_NLST(self, line):
        """Return a list of files in the specified directory in a
        compact form to the client.
        """
        if not line:
            line = self.fs.cwd
        path = self.fs.ftp2fs(line)
        line = self.fs.ftpnorm(line)
        try:
            if self.fs.isdir(path):
                listing = self.fs.listdir(path)
            else:
                # if path is a file we just list its name
                self.fs.lstat(path)  # raise exc in case of problems
                basedir, filename = os.path.split(path)
                listing = [filename]
        except OSError, err:
            why = _strerror(err)
            self.log('FAIL NLST "%s". %s.' %(line, why))
            self.respond('550 %s.' %why)
        else:
            data = ''
            if listing:
                listing.sort()
                data = '\r\n'.join(listing) + '\r\n'
            self.push_dtp_data(data, log='OK NLST "%s". Transfer starting.' %line)

        # --- MLST and MLSD commands

    # The MLST and MLSD commands are intended to standardize the file and
    # directory information returned by the server-FTP process.  These
    # commands differ from the LIST command in that the format of the
    # replies is strictly defined although extensible.

    def ftp_MLST(self, line):
        """Return information about a pathname in a machine-processable
        form as defined in RFC-3659.
        """
        # if no argument, fall back on cwd as default
        if not line:
            line = self.fs.cwd
        path = self.fs.ftp2fs(line)
        line = self.fs.ftpnorm(line)
        basedir, basename = os.path.split(path)
        try:
            data = self.fs.format_mlsx(basedir, [basename], ignore_err=False)
        except OSError, err:
            why = _strerror(err)
            self.log('FAIL MLST "%s". %s.' %(line, why))
            self.respond('550 %s.' %why)
        else:
            # where TVFS is supported, a fully qualified pathname
            # should be returned
            data = data.split(' ')[0] + ' %s\r\n'%line
            # response is expected on the command channel
            self.push('250-Listing "%s":\r\n' %line)
            # the fact set must be preceded by a space
            self.push(' ' + data)
            self.respond('250 End MLST.')

    def ftp_MLSD(self, line):
        """Return contents of a directory in a machine-processable form
        as defined in RFC-3659.
        """
        # if no argument, fall back on cwd as default
        if not line:
            line = self.fs.cwd
        path = self.fs.ftp2fs(line)
        line = self.fs.ftpnorm(line)
        # RFC-3659 requires 501 response code if path is not a directory
        if not self.fs.isdir(path):
            err = 'No such directory'
            self.log('FAIL MLSD "%s". %s.' %(line, err))
            self.respond("501 %s." %err)
            return
        try:
            listing = self.fs.listdir(path)
        except OSError, err:
            why = _str(err)
            self.log('FAIL MLSD "%s". %s.' %(line, why))
            self.respond('550 %s.' %why)
        else:
            data = self.fs.format_mlsx(path, listing)
            self.push_dtp_data(data, log='OK MLSD "%s". Transfer starting.' %line)

        
    def ftp_RETR(self, line):
        """Retrieve the specified file (transfer from the server to the
        client)
        """
        file = self.fs.ftp2fs(line)

        if not self.authorizer.r_perm(self.username, file):
            self.log('FAIL RETR "s". Not enough privileges.'
                        %self.fs.ftpnorm(line))
            self.respond("550 Can't RETR: not enough privileges.")
            return

        try:
            fd = self.fs.open(file, 'rb')
        except IOError, err:
            why = _strerror(err)
            self.log('FAIL RETR "%s". %s.' %(self.fs.ftpnorm(line), why))
            self.respond('550 %s.' %why)
            return

        if self.restart_position:
            # Make sure that the requested offset is valid (within the
            # size of the file being resumed).
            # According to RFC-1123 a 554 reply may result in case that
            # the existing file cannot be repositioned as specified in
            # the REST.
            ok = 0
            try:
                assert not self.restart_position > self.fs.getsize(file)
                fd.seek(self.restart_position)
                ok = 1
            except AssertionError:
                why = "Invalid REST parameter"
            except IOError, err:
                why = _strerror(err)
            self.restart_position = 0
            if not ok:
                self.respond('554 %s' %why)
                self.log('FAIL RETR "%s". %s.' %(self.fs.ftpnorm(line), why))
                return
        producer = FileProducer(fd, self.current_type)
        self.push_dtp_data(producer, isproducer=1,
            log='OK RETR "%s". Download starting.' %self.fs.ftpnorm(line))


    def ftp_STOR(self, line, mode='w'):
        """Store a file (transfer from the client to the server)."""
        # A resume could occur in case of APPE or REST commands.
        # In that case we have to open file object in different ways:
        # STOR: mode = 'w'
        # APPE: mode = 'a'
        # REST: mode = 'r+' (to permit seeking on file object)
        if 'a' in mode:
            cmd = 'APPE'
        else:
            cmd = 'STOR'
        file = self.fs.ftp2fs(line)

        if not self.authorizer.w_perm(self.username, os.path.dirname(file)):
            self.log('FAIL %s "%s". Not enough privileges.'
                        %(cmd, self.fs.ftpnorm(line)))
            self.respond("550 Can't STOR: not enough privileges.")
            return

        if self.restart_position:
            mode = 'r+'

        try:
            fd = self.fs.open(file, mode + 'b')
        except IOError, err:
            why = _strerror(err)
            self.log('FAIL %s "%s". %s.' %(cmd, self.fs.ftpnorm(line), why))
            self.respond('550 %s.' %why)
            return

        if self.restart_position:
            # Make sure that the requested offset is valid (within the
            # size of the file being resumed).
            # According to RFC-1123 a 554 reply may result in case
            # that the existing file cannot be repositioned as
            # specified in the REST.
            ok = 0
            try:
                assert not self.restart_position > self.fs.getsize(file)
                fd.seek(self.restart_position)
                ok = 1
            except AssertionError:
                why = "Invalid REST parameter"
            except IOError, err:
                why = _strerror(err)
            self.restart_position = 0
            if not ok:
                self.respond('554 %s' %why)
                self.log('FAIL %s "%s". %s.' %(cmd, self.fs.ftpnorm(line), why))
                return

        log = 'OK %s "%s". Upload starting.' %(cmd, self.fs.ftpnorm(line))
        if self.data_channel:
            self.respond("125 Data connection already open. Transfer starting.")
            self.log(log)
            self.data_channel.file_obj = fd
            self.data_channel.enable_receiving(self.current_type)
        else:
            self.respond("150 File status okay. About to open data connection.")
            self.in_dtp_queue = (fd, log)


    def ftp_STOU(self, line):
        """Store a file on the server with a unique name."""
        # Note 1: RFC-959 prohibited STOU parameters, but this
        # prohibition is obsolete.
        # Note 2: 250 response wanted by RFC-959 has been declared
        # incorrect in RFC-1123 that wants 125/150 instead.
        # Note 3: RFC-1123 also provided an exact output format
        # defined to be as follow:
        # > 125 FILE: pppp
        # ...where pppp represents the unique path name of the
        # file that will be written.

        # watch for STOU preceded by REST, which makes no sense.
        if self.restart_position:
            self.respond("550 Can't STOU while REST request is pending.")
            return

        if line:
            basedir, prefix = os.path.split(self.fs.ftp2fs(line))
            prefix = prefix + '.'
        else:
            basedir = self.fs.ftp2fs(self.fs.cwd)
            prefix = 'ftpd.'

        if not self.authorizer.w_perm(self.username, basedir):
            self.log('FAIL STOU "%s". Not enough privileges' \
                        %self.fs.ftpnorm(line))
            self.respond("550 Can't STOU: not enough privileges.")
            return

        try:
            fd = self.fs.mkstemp(prefix=prefix, dir=basedir)
        except IOError, err:
            # hitted the max number of tries to find out file with
            # unique name
            if err.errno == errno.EEXIST:
                why = 'No usable unique file name found.'
            # something else happened
            else:
                why = _strerror(err)
            self.respond("450 %s." %why)
            self.log('FAIL STOU "%s". %s.' %(self.fs.ftpnorm(line), why))
            return

        filename = os.path.basename(fd.name)

        # now just acts like STOR except that restarting isn't allowed
        log = 'OK STOU "%s". Upload starting.' %filename
        if self.data_channel:
            self.respond("125 FILE: %s" %filename)
            self.log(log)
            self.data_channel.file_obj = fd
            self.data_channel.enable_receiving(self.current_type)
        else:
            self.respond("150 FILE: %s" %filename)
            self.in_dtp_queue = (fd, log)


    def ftp_APPE(self, line):
        """Append data to an existing file on the server."""
        # watch for APPE preceded by REST, which makes no sense.
        if self.restart_position:
            self.respond("550 Can't APPE while REST request is pending.")
            return
        self.ftp_STOR(line, mode='a')

    def ftp_REST(self, line):
        """Restart a file transfer from a previous mark."""
        try:
            marker = int(line)
            if marker < 0:
                raise ValueError
        except (ValueError, OverflowError):
            self.respond("501 Invalid parameter.")
        else:
            self.respond("350 Restarting at position %s. "
                        "Now use RETR/STOR for resuming." %marker)
            self.log("OK REST %s." %marker)
            self.restart_position = marker

    def ftp_ABOR(self, line):
        """Abort the current data transfer."""

        # ABOR received while no data channel exists
        if (self.data_server is None) and (self.data_channel is None):
            resp = "225 No transfer to abort."
        else:
            # a PASV was received but connection wasn't made yet
            if self.data_server:
                self.data_server.close()
                self.data_server = None
                resp = "225 ABOR command successful; data channel closed."

            # If a data transfer is in progress the server must first
            # close the data connection, returning a 426 reply to
            # indicate that the transfer terminated abnormally, then it
            # must send a 226 reply, indicating that the abort command
            # was successfully processed.
            # If no data has been transmitted we just respond with 225
            # indicating that no transfer was in progress.
            if self.data_channel:
                if self.data_channel.transfer_in_progress():
                    self.data_channel.close()
                    self.data_channel = None
                    self.respond("426 Connection closed; transfer aborted.")
                    self.log("OK ABOR. Transfer aborted, data channel closed.")
                    resp = "226 ABOR command successful."
                else:
                    self.data_channel.close()
                    self.data_channel = None
                    self.log("OK ABOR. Data channel closed.")
                    resp = "225 ABOR command successful; data channel closed."
        self.respond(resp)


        # --- authentication

    def ftp_USER(self, line):
        """Set the username for the current session."""
        # we always treat anonymous user as lower-case string.
        if line.lower() == "anonymous":
            line = "anonymous"

        # RFC-959 specifies a 530 response to the USER command if the
        # username is not valid.  If the username is valid is required
        # ftpd returns a 331 response instead.  In order to prevent a
        # malicious client from determining valid usernames on a server,
        # it is suggested by RFC-2577 that a server always return 331 to
        # the USER command and then reject the combination of username
        # and password for an invalid username when PASS is provided later.
        if not self.authenticated:
            self.respond('331 Username ok, send password.')
        else:
            # a new USER command could be entered at any point in order
            # to change the access control flushing any user, password,
            # and account information already supplied and beginning the
            # login sequence again.
            self.flush_account()
            self.log('OK USER "%s". Previous account information was flushed.' %line)
            self.respond('331 Previous account information was flushed, send password.')
        self.username = line

    def ftp_PASS(self, line):
        """Check username's password against the authorizer."""

        if self.authenticated:
            self.respond("503 User already authenticated.")
            return
        if not self.username:
            self.respond("503 Login with USER first.")
            return

        # username ok
        if self.authorizer.has_user(self.username):
            if self.authorizer.validate_authentication(self.username, line) \
            or self.username == 'anonymous':
                msg_login = self.authorizer.get_msg_login(self.username)
                if len(msg_login) <= 75:
                    self.respond('230 %s' %msg_login)
                else:
                    self.push("230-%s\r\n" %msg_login)
                    self.respond("230 ")

                self.authenticated = True
                self.attempted_logins = 0
                self.fs.root = self.authorizer.get_home_dir(self.username)
                self.log("User %s logged in." %self.username)
            else:
                self.attempted_logins += 1
                if self.attempted_logins >= self.max_login_attempts:
                    self.respond("530 Maximum login attempts. Disconnecting.")
                    self.close()
                else:
                    self.respond("530 Authentication failed.")
                    self.username = ""
                self.log('Authentication failed (user: "%s").' %self.username)

        # wrong username
        else:
            self.attempted_logins += 1
            if self.attempted_logins >= self.max_login_attempts:
                self.log('Authentication failed: unknown username "%s".'
                            %self.username)
                self.respond("530 Maximum login attempts. Disconnecting.")
                self.close()
            elif self.username.lower() == 'anonymous':
                self.respond("530 Anonymous access not allowed.")
                self.log('Authentication failed: anonymous access not allowed.')
            else:
                self.respond("530 Authentication failed.")
                self.log('Authentication failed: unknown username "%s".'
                            %self.username)
                self.username = ""

    def ftp_REIN(self, line):
        """Reinitialize user's current session."""
        # From RFC-959:
        # REIN command terminates a USER, flushing all I/O and account
        # information, except to allow any transfer in progress to be
        # completed.  All parameters are reset to the default settings
        # and the control connection is left open.  This is identical
        # to the state in which a user finds himself immediately after
        # the control connection is opened.
        self.log("OK REIN. Flushing account information.")
        self.flush_account()
        # Note: RFC-959 erroneously mention "220" as the correct response
        # code to be given in this case, but this is wrong...
        self.respond("230 Ready for new user.")


        # --- filesystem operations

    def ftp_PWD(self, line):
        """Return the name of the current working directory to the client."""
        self.respond('257 "%s" is the current directory.' %self.fs.cwd)

    def ftp_CWD(self, line):
        """Change the current working directory."""
        # TODO: a lot of FTP servers go back to root directory if no arg is
        # provided but this is not specified in RFC-959. Search for
        # official references about this behaviour.
        if not line:
            line = '/'
        path = self.fs.ftp2fs(line)
        try:
            self.fs.chdir(path)
        except OSError, err:
            why = _strerror(err)
            self.log('FAIL CWD "%s". %s.' %(self.fs.ftpnorm(line), why))
            self.respond('550 %s.' %why)
        else:
            self.log('OK CWD "%s".' %self.fs.cwd)
            self.respond('250 "%s" is the current directory.' %self.fs.cwd)

    def ftp_CDUP(self, line):
        """Change into the parent directory."""
        # Note: RFC-959 says that code 200 is required but it also says
        # that CDUP uses the same codes as CWD.
        self.ftp_CWD('..')

    def ftp_SIZE(self, line):
        """Return size of file in a format suitable for using with
        RESTart as defined in RFC-3659.

        Implementation note:
        properly handling the SIZE command when TYPE ASCII is used would
        require to scan the entire file to perform the ASCII translation
        logic (file.read().replace(os.linesep, '\r\n')) and then
        calculating the len of such data which may be different than
        the actual size of the file on the server.  Considering that
        calculating such result could be very resource-intensive it
        could be easy for a malicious client to try a DoS attack, thus
        we do not perform the ASCII translation.

        However, clients in general should not be resuming downloads in
        ASCII mode.  Resuming downloads in binary mode is the recommended
        way as specified in RFC-3659.
        """
        path = self.fs.ftp2fs(line)
        if self.fs.isdir(path):
            self.respond("550 Could not get a directory size.")
            return
        try:
            size = self.fs.getsize(path)
        except OSError, err:
            why = _strerror(err)
            self.log('FAIL SIZE "%s". %s' %(self.fs.ftpnorm(line), why))
            self.respond('550 %s.' %why)
        else:
            self.respond("213 %s" %size)
            self.log('OK SIZE "%s".' %self.fs.ftpnorm(line))

    def ftp_MDTM(self, line):
        """Return last modification time of file to the client as an ISO
        3307 style timestamp (YYYYMMDDHHMMSS) as defined in RFC-3659.
        """
        path = self.fs.ftp2fs(line)
        if not self.fs.isfile(path):
            self.respond("550 No such file.")
            return
        try:
            lmt = self.fs.getmtime(path)
        except OSError, err:
            why = _strerror(err)
            self.log('FAIL MDTM "%s". %s' %(self.fs.ftpnorm(line), why))
            self.respond('550 %s.' %why)
        else:
            lmt = time.strftime("%Y%m%d%H%M%S", time.localtime(lmt))
            self.respond("213 %s" %lmt)
            self.log('OK MDTM "%s".' %self.fs.ftpnorm(line))
            
    def ftp_MKD(self, line):
        """Create the specified directory."""
        path = self.fs.ftp2fs(line)

        if not self.authorizer.w_perm(self.username, os.path.dirname(path)):
            self.log('FAIL MKD "%s". Not enough privileges.'
                        %self.fs.ftpnorm(line))
            self.respond("550 Can't MKD: not enough privileges.")
            return

        try:
            self.fs.mkdir(path)
        except OSError, err:
            why = _strerror(err)
            self.log('FAIL MKD "%s". %s.' %(self.fs.ftpnorm(line), why))
            self.respond('550 %s.' %why)
        else:
            self.log('OK MKD "%s".' %self.fs.ftpnorm(line))
            self.respond("257 Directory created.")

    def ftp_RMD(self, line):
        """Remove the specified directory."""
        path = self.fs.ftp2fs(line)

        if path == self.fs.root:
            msg = "Can't remove root directory."
            self.respond("550 %s" %msg)
            self.log('FAIL MKD "/". %s' %msg)
            return

        if not self.authorizer.w_perm(self.username, path):
            self.log('FAIL RMD "%s". Not enough privileges.' %self.fs.ftpnorm(line))
            self.respond("550 Can't RMD: not enough privileges.")
            return

        try:
            self.fs.rmdir(path)
        except OSError, err:
            why = _strerror(err)
            self.log('FAIL RMD "%s". %s.' %(self.fs.ftpnorm(line), why))
            self.respond('550 %s.' %why)
        else:
            self.log('OK RMD "%s".' %self.fs.ftpnorm(line))
            self.respond("250 Directory removed.")

    def ftp_DELE(self, line):
        """Delete the specified file."""
        path = self.fs.ftp2fs(line)

        if not self.authorizer.w_perm(self.username, path):
            self.log('FAIL DELE "%s". Not enough privileges.'
                        %self.fs.ftpnorm(line))
            self.respond("550 Can't DELE: not enough privileges.")
            return

        try:
            self.fs.remove(path)
        except OSError, err:
            why = _strerror(err)
            self.log('FAIL DELE "%s". %s.' %(self.fs.ftpnorm(line), why))
            self.respond('550 %s.' %why)
        else:
            self.log('OK DELE "%s".' %self.fs.ftpnorm(line))
            self.respond("250 File removed.")

    def ftp_RNFR(self, line):
        """Rename the specified (only the source name is specified
        here, see RNTO command)"""
        path = self.fs.ftp2fs(line)

        if not self.authorizer.w_perm(self.username, path):
            self.log('FAIL RNFR "%s". Not enough privileges for renaming.'
                     %(self.fs.ftpnorm(line)))
            self.respond("550 Can't RNRF: not enough privileges.")
            return

        if self.fs.lexists(path):
            self.fs.rnfr = line
            self.respond("350 Ready for destination name.")
        else:
            self.respond("550 No such file or directory.")

    def ftp_RNTO(self, line):
        """Rename file (destination name only, source is specified with
        RNFR).
        """
        if not self.fs.rnfr:
            self.respond("503 Bad sequence of commands: use RNFR first.")
            return

        src = self.fs.ftp2fs(self.fs.rnfr)
        dst = self.fs.ftp2fs(line)

        if not self.authorizer.w_perm(self.username, self.fs.rnfr):
            self.log('FAIL RNFR/RNTO "%s ==> %s". ' 'Not enough privileges for '
                     'renaming.' %(self.fs.ftpnorm(self.fs.rnfr),
                                   self.fs.ftpnorm(line)))
            self.respond("550 Can't RNTO: not enough privileges.")
            self.fs.rnfr = None
            return

        try:
            try:
                self.fs.rename(src, dst)
            except OSError, err:
                why = _strerror(err)
                self.log('FAIL RNFR/RNTO "%s ==> %s". %s.'
                    %(self.fs.ftpnorm(self.fs.rnfr), self.fs.ftpnorm(line), why))
                self.respond('550 %s.' %why)
            else:
                self.log('OK RNFR/RNTO "%s ==> %s".'
                    %(self.fs.ftpnorm(self.fs.rnfr), self.fs.ftpnorm(line)))
                self.respond("250 Renaming ok.")
        finally:
            self.fs.rnfr = None


        # --- others

    def ftp_TYPE(self, line):
        """Set current type data type to binary/ascii"""
        line = line.upper()
        if line in ("A", "AN", "A N"):
            self.respond("200 Type set to: ASCII.")
            self.current_type = 'a'
        elif line in ("I", "L8", "L 8"):
            self.respond("200 Type set to: Binary.")
            self.current_type = 'i'
        else:
            self.respond('504 Unsupported type "%s".' %line)

    def ftp_STRU(self, line):
        """Set file structure (obsolete)."""
        # obsolete (backward compatibility with older ftp clients)
        if line in ('f','F'):
            self.respond('200 File transfer structure set to: F.')
        else:
            self.respond('504 Unimplemented STRU type.')

    def ftp_MODE(self, line):
        """Set data transfer mode (obsolete)"""
        # obsolete (backward compatibility with older ftp clients)
        if line in ('s', 'S'):
            self.respond('200 Transfer mode set to: S')
        else:
            self.respond('504 Unimplemented MODE type.')

    def ftp_STAT(self, line):
        """Return statistics about current ftp session. If an argument
        is provided return directory listing over command channel.
        """
        # return STATus information about ftpd
        if not line:
            s = []
            s.append('Connected to: %s:%s' %self.socket.getsockname())
            if self.authenticated:
                s.append('Logged in as: %s' %self.username)
            else:
                if not self.username:
                    s.append("Waiting for username.")
                else:
                    s.append("Waiting for password.")
            if self.current_type == 'a':
                type = 'ASCII'
            else:
                type = 'Binary'
            s.append("TYPE: %s; STRUcture: File; MODE: Stream" %type)
            if self.data_server:
                s.append('Passive data channel waiting for connection.')
            elif self.data_channel:
                dc = self.data_channel
                s.append('Data connection open:')
                s.append('Total bytes sent: %s' %dc.tot_bytes_sent)
                s.append('Total bytes received: %s' %dc.tot_bytes_received)
            else:
                s.append('Data connection closed.')

            self.push('211-FTP server status:\r\n')
            self.push(''.join([' %s\r\n' %item for item in s]))
            self.respond('211 End of status.')

        # return directory LISTing over the command channel
        else:
            # When argument is provided along STAT we should return
            # directory LISTing over the command channel.
            # RFC-959 do not explicitly mention globbing; this means
            # that FTP servers are not required to support globbing
            # in order to be compliant.  However, many FTP servers do
            # support globbing as a measure of convenience for FTP
            # clients and users.

            # In order to search for and match the given globbing
            # expression, the code has to search (possibly) many
            # directories, examine each contained filename, and
            # build a list of matching files in memory.
            # Since this operation can be quite intensive, both CPU-
            # and memory-wise, we limit the search to only one
            # directory non-recursively, as LIST does.
            try:
                data = self.fs.get_stat_dir(line)
            except OSError, err:
                data = _strerror(err) + '.\r\n'
            self.push('213-Status of "%s":\r\n' %self.fs.ftpnorm(line))
            self.push(data)
            self.respond('213 End of status.')

    def ftp_FEAT(self, line):
        """List all new features supported as defined in RFC-2398."""
        features = ['MDTM','REST STREAM','SIZE','TVFS']
        features.sort()
        self.push("211-Features supported:\r\n")
        self.push("".join([" %s\r\n" %x for x in features]))
        self.respond('211 End FEAT.')

    def ftp_NOOP(self, line):
        """Do nothing."""
        self.respond("250 I successfully done nothin'.")

    def ftp_SYST(self, line):
        """Return system type (always returns UNIX type L8)."""
        # This command is used to find out the type of operating system
        # at the server.  The reply shall have as its first word one of
        # the system names listed in RFC-943.
        # Since that we always return a "/bin/ls -lA"-like output on
        # LIST we  prefer to respond as if we would on Unix in any case.
        self.respond("215 UNIX Type: L8")

    def ftp_ALLO(self, line):
        """Allocate bytes for storage (obsolete)."""
        # obsolete (always respond with 202)
        self.respond("202 No storage allocation necessary.")

    def ftp_HELP(self, line):
        """Return help text to the client."""
        if line:
            if line.upper() in proto_cmds:
                self.respond("214 %s" %proto_cmds[line.upper()])
            else:
                self.respond("501 Unrecognized command.")
        else:
            # provide a compact list of recognized commands
            def formatted_help():
                cmds = []
                keys = proto_cmds.keys()
                keys.sort()
                while keys:
                    elems = tuple((keys[0:8]))
                    cmds.append(' %-6s' * len(elems) %elems + '\r\n')
                    del keys[0:8]
                return ''.join(cmds)

            self.push("214-The following commands are recognized:\r\n")
            self.push(formatted_help())
            self.respond("214 Help command successful.")


        # --- support for deprecated cmds

    # RFC-1123 requires that the server treat XCUP, XCWD, XMKD, XPWD
    # and XRMD commands as synonyms for CDUP, CWD, MKD, LIST and RMD.
    # Such commands are obsoleted but some ftp clients (e.g. Windows
    # ftp.exe) still use them.

    def ftp_XCUP(self, line):
        """Change to the parent directory. Synonym for CDUP. Deprecated."""
        self.ftp_CDUP(line)

    def ftp_XCWD(self, line):
        """Change the current working directory. Synonym for CWD. Deprecated."""
        self.ftp_CWD(line)

    def ftp_XMKD(self, line):
        """Create the specified directory. Synonym for MKD. Deprecated."""
        self.ftp_MKD(line)

    def ftp_XPWD(self, line):
        """Return the current working directory. Synonym for PWD. Deprecated."""
        self.ftp_PWD(line)

    def ftp_XRMD(self, line):
        """Remove the specified directory. Synonym for RMD. Deprecated."""
        self.ftp_RMD(line)


class FTPServer(asyncore.dispatcher):
    """This class is an asyncore.disptacher subclass.  It creates a FTP
    socket listening on <address>, dispatching the requests to a <handler>
    (typically FTPHandler class).
    """

    # Overiddable defaults (overriding is strongly recommended to avoid
    # running out of file descriptors (DoS) !).

    # number of maximum simultaneous connections accepted
    # (0 == unlimited)
    max_cons = 0

    # number of maximum connections accepted for the same IP address
    # (0 == unlimited)
    max_cons_per_ip = 0

    def __init__(self, address, handler):
        asyncore.dispatcher.__init__(self)
        self.handler = handler
        self.ip_map = []
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name == 'posix':
            self.set_reuse_addr()
        self.bind(address)
        self.listen(5)

    def __del__(self):
        debug("FTPServer.__del__()")

    def serve_forever(self, **kwargs):
        """A wrap around asyncore.loop(); starts the asyncore polling
        loop.

        The keyword arguments in kwargs are the same expected by
        asyncore.loop() function: timeout, use_poll, map and count.
        """
        if not 'count' in kwargs:
            log("Serving FTP on %s:%s" %self.socket.getsockname())

        # backward compatibility for python < 2.4
        if not hasattr(self, '_map'):
            if not 'map' in kwargs:
                map = asyncore.socket_map
            else:
                map = kwargs['map']
            self._map = self.handler._map = map
            
        try:
            # FIX #16, #26
            # use_poll specifies whether to use select module's poll()
            # with asyncore or whether to use asyncore's own poll()
            # method Python versions < 2.4 need use_poll set to False
            # This breaks on OS X systems if use_poll is set to True.
            # All systems seem to work fine with it set to False
            # (tested on Linux, Windows, and OS X platforms)
            if kwargs:
                asyncore.loop(**kwargs)
            else:
                asyncore.loop(timeout=1, use_poll=False)
        except (KeyboardInterrupt, SystemExit, asyncore.ExitNow):
            log("Shutting down FTPd.")
            self.close_all()

    def handle_accept(self):
        """Called when remote client initiates a connection."""
        debug("FTPServer.handle_accept()")
        sock_obj, addr = self.accept()
        log("[]%s:%s Connected." %addr)

        handler = self.handler(sock_obj, self)
        ip = addr[0]
        self.ip_map.append(ip)

        # For performance and security reasons we should always set a
        # limit for the number of file descriptors that socket_map
        # should contain.  When we're running out of such limit we'll
        # use the last available channel for sending a 421 response
        # to the client before disconnecting it.
        if self.max_cons:
            if len(self._map) > self.max_cons:
                handler.handle_max_cons()
                return

        # accept only a limited number of connections from the same
        # source address.
        if self.max_cons_per_ip:
            if self.ip_map.count(ip) > self.max_cons_per_ip:
                handler.handle_max_cons_per_ip()
                return

        handler.handle()

    def writable(self):
        return 0

    def handle_error(self):
        """Called to handle any uncaught exceptions."""
        debug("FTPServer.handle_error()")
        logerror(traceback.format_exc())
        self.close()

    def close_all(self, map=None, ignore_all=False):
        """Stop serving; close all existent connections disconnecting
        clients.

        The map parameter is a dictionary whose items are the channels to
        close.
        If map is omitted, the default asyncore.socket_map is used.
        Having ignore_all parameter set to False results in raising
        exception in case of unexpected errors.
        """
        # Implementation note:
        # instead of using the current asyncore.close_all() function
        # which only close sockets, we iterate over all existent
        # channels calling close() method for each one of them,
        # avoiding memory leaks.
        # This is how close_all() function should appear in the fixed
        # version of asyncore that will be included in Python 2.6.
        if map is None:
            map = self._map
        for x in map.values():
            try:
                x.close()
            except OSError, x:
                if x[0] == errno.EBADF:
                    pass
                elif not ignore_all:
                    raise
            except (asyncore.ExitNow, KeyboardInterrupt, SystemExit):
                raise
            except:
                if not ignore_all:
                    raise
        map.clear()


def test():
    # cmd line usage (provide a read-only anonymous ftp server):
    # python -m pyftpdlib.FTPServer
    authorizer = DummyAuthorizer()
    authorizer.add_anonymous(os.getcwd())
    FTPHandler.authorizer = authorizer
    address = ('', 21)
    ftpd = FTPServer(address, FTPHandler)
    ftpd.serve_forever()


if __name__ == '__main__':
    test()
