# The users file #
Users connecting to easyFTPD are checked against a users-file, which by default is located at /etc/easyftpd/users after installation. The lookup path for users is however defined in the config-file, and can be changed to point anywhere.

A users configuration file simply contains rows of data in the format:

```
username:password:permissions:share_path
```

where each field is specified like:
| **Name** | **Description** | **Example value** |
|:---------|:----------------|:------------------|
| **username** | The username of the user | buffi|
| **password** | The plaintext password or salted passwordhash (see below) | secretpass |
| **permissions** | The permissions granted for the user to the shared folder | rw |
| **share\_path** | The folder that the user should have access to | /home/buffi/ftp\_share |

An example users file can look like this

```
pub:banana:r:/home/buffi/ftp_share/pub
stabpaw:ujk3m!73cff165ea637d821f9ba5f9d11aa96333fd87d0:rw:/home/buffi/ftp_share/stabpaw
```

This contains two users "pub" and "stabpaw". pub's password is "banana" while stabpaw's password is "secretpassword" but saved as a salted sha-hash.
Pub has read-permissions to "/home/buffi/ftp\_share/pub" and stabpaw has read and write permissions to "/home/buffi/ftp\_share/stabpaw".

## Saving passwords as hashes ##

Saving passwords as plaintext is not very safe, and easyftpd allows sha-hashing to be used instead, if you want increased security. To use hashed passwords, replace the plain-text password with a salted sha-hash (in hex).

To get a password hash, simply use the script easyftpd-pwhash like this
```
easyftpd-pwhash "mypassword"
```
This will return a string with the syntax **salt!hash** where salt is five characters and the hash is the sha-hash of the password concatenated by the salt. Put this string in the password-field in the users-file.