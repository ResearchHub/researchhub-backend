#!/usr/bin/env bash

if [ ! -f /usr/bin/supervisord ]; then
    echo "installing supervisor"
    sudo amazon-linux-extras install epel
    sudo yum install -y supervisor

else
    echo "supervisor already installed"
fi

if [ ! -f /usr/bin/java ]; then
    echo "installing java"
    sudo yum install -y java-1.8.0
else
    echo "java already installed"
fi

if [ ! -d /etc/supervisor ]; then
    mkdir /etc/supervisor
    echo "create supervisor directory"
fi
