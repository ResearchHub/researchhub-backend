#!/usr/bin/env bash

if [ ! -f /usr/bin/supervisord ]; then
    echo "installing supervisor"
    sudo amazon-linux-extras install epel
    sudo yum install -y supervisor

else
    echo "supervisor already installed"
fi

if [ ! -d /etc/supervisor ]; then
    mkdir /etc/supervisor
    echo "create supervisor directory"
fi

if ps aux | grep "[/]usr/bin/supervisord"; then
    echo "supervisor is running"
else
    echo "starting supervisor"
    sudo /usr/bin/supervisord -c /etc/supervisord.conf
fi
