#!/usr/bin/env bash

if ! grep -Fxq "[include]" /etc/supervisord.conf;
  then
    echo "[include]" | tee -a /etc/supervisord.conf
    echo "files= /etc/celerybeat.conf /etc/celery.conf /etc/celeryflower.conf /etc/daphne.conf" | tee -a /etc/supervisord.conf
fi

# Reread the supervisord config
sudo /usr/bin/supervisorctl -c /etc/supervisord.conf reread

# Update supervisord in cache without restarting all services
sudo /usr/bin/supervisorctl -c /etc/supervisord.conf update

# Start/Restart processes through supervisord
sudo /usr/bin/supervisorctl -c /etc/supervisord.conf restart daphne:*

sudo /usr/bin/supervisorctl -c /etc/supervisord.conf restart celeryd-worker
sudo /usr/bin/supervisorctl -c /etc/supervisord.conf restart celerybeat
sudo /usr/bin/supervisorctl -c /etc/supervisord.conf stop celeryflower
