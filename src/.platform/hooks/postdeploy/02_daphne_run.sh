#!/usr/bin/env bash

daphne=$(sudo grep -o DAPHNE=.* /opt/elasticbeanstalk/deployment/env)
if ! [ "$daphne" == "DAPHNE=True" ]; then
    /usr/bin/supervisorctl -c /etc/supervisord.conf stop daphne:*
    echo "Exiting daphne script"
    exit 0
else
    echo "Running daphne script"
fi

sudo /usr/bin/supervisorctl -c /etc/supervisord.conf restart daphne:*