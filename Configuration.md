# Configuration #

All of easyFTPD's configurations are stored in a configuration-file. When installing easyFTPD this file is located at /etc/easyftpd/config .
You may copy this file elsewhere if you want to be able to have separate configurations available as well. In that case, start easyftpd with the **-c CONFIGFILE** option to choose the other config.

## The config-file ##

The configfile is made up of rows of data with the syntax

```
configuration_option: value
```

The following options are available
| **Option** | **Description** | **Default value** |
|:-----------|:----------------|:------------------|
|default\_port| The port to run the server at |21|
|anonymous| Allow anonymous access |no|
|anonymous\_root| Shared folder for anonymous access |/tmp|
|anonymous\_perm| Read/write permissions for anonymous users |r |
|disable\_logging| Disable logging |no|
|banner| Banner being displayed to users connecting |Test FTP|
|welcome\_msg| Welcome message to logged in users | Welcome!|
|goodbye\_msg| Goodbye message to disconnecting users | Goodbye! I hope you enjoyed your visit!|
|max\_login\_attempts| Maximum login attempts |3 |
|max\_connections| Maximum connections at once |50|
|max\_connections\_per\_ip| Maximum connections from one IP |10|
|user\_file| Path to file containing virtual users |/etc/easyftpd/users|

The permissions for the anonymous\_perm option should be **r**, **w** or **rw** for **read**, **write** or **read and write**.