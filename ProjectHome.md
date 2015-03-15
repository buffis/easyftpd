# easyFTPD #

## About ##
easyFTPD is a FTP-server constructed to easily handle virtual users.
Most large ftp-servers are complicated to configure, especially when handling virtual users. easyFTPD simply handles a "users" configuration-file which lists virtual users and what they should access.

It should run on any unix-like system (linux/BSD/solaris...) and has **python 2.3** (or higher) as its only dependancy.

## Virtual users ##
The main idea of easyFTPD is to be able to quickly set up an ftp-server for virtual users. A **users** configuration file simply contains rows of data in the format:

```
username:password:permissions:share_path
```

where each field is specified like:
  * username = The username of the user (ex: buffi)
  * password = The plaintext password or salted passwordhash (ex: secretpass or 12345!0021eaf783f7743cb542f3920bfa508f368b1631)
  * permissions = The permissions granted for the user to the shared folder (ex: rw)
  * share\_path = The folder that the user should have access to (ex: /home/buffi/ftp\_share)

An example **users** file can look like this

```
pub:banana:r:/home/buffi/ftp_share/pub
buffi:skA3fas2:rw:/home/buffi
stabpaw:ujk3m!73cff165ea637d821f9ba5f9d11aa96333fd87d0:rw:/home/buffi/ftp_share/stabpaw
```

## Quick start ##
  * Download the application and unpack it
  * Install it by issuing the following command as root
```
python setup.py install
```
  * Run it!
```
easyftpd
```

Optional arguments can be passed when starting the application. For an example, to run easyFTPD as a daemon process in the background on port 12345 start it with

```
easyftpd -p 12345 -d
```

## Thanks to ##

The guys behind [pyftpdlib](http://code.google.com/p/pyftpdlib/) which is used as the backbone of easyftpd.