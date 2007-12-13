#!/usr/bin/env python

from distutils.core import setup

setup(name='EasyFTPd',
      version='0.1',
      description='An easy to use FTP daemon',
      author='Bjorn Kempen',
      author_email='bjorn.kempen@gmail.com',
      url='http://buffis.com',
      packages=['easy_ftpd','easy_ftpd.lib','easy_ftpd.tools'],
      scripts=['easyftpd'],
      data_files=[
    ('/etc/easyftpd', ['configs/config', 'configs/users']),
    ('/var/log/easyftpd', ['logs/access', 'logs/error'])
    ]
      
     )

