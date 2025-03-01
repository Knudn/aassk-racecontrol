#!/bin/bash

apt install samba samba-client samba-common -y

mkdir /share
chmod -R 777 /share

if grep -wq "SMB_SHARE" /etc/samba/smb.conf; then 
    echo "Exists" 
else 
    echo -en "[PDF share]\n   comment = SMB_SHARE\n   path = /share\n   read only = No\n" >> /etc/samba/smb.conf
fi

#User for SMB
#Username will be root
pass="secret"
echo -e "$pass\n$pass" | smbpasswd -a -s $(id -un)

systemctl stop smbd
systemctl start smbd
systemctl enable smbd
