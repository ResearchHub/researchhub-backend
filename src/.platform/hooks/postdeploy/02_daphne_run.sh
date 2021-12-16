#!/usr/bin/env bash

daphne=$(sudo grep -o DAPHNE=.* /opt/elasticbeanstalk/deployment/env)
if ! [ "$daphne" == "DAPHNE=True" ]; then
  /usr/bin/supervisorctl -c /etc/supervisord.conf stop daphne:*
  echo "Exiting daphne script"
exit 0
else
echo "Running daphne script"
fi

# Get django environment variables
djangoenv=`sudo cat /opt/elasticbeanstalk/deployment/env | sed 's/=/="/' | sed ':a;N;$!ba;s/\n/",/g' | sed 's/%/%%/g' | sed 's/export //g' | sed 's/$PATH/%(ENV_PATH)s/g' | sed 's/$PYTHONPATH//g' | sed 's/$LD_LIBRARY_PATH//g'`
djangoenv="$djangoenv\","
djangoenv=${djangoenv%?}

# Create daemon configuraiton script
daphne="[program:daphne]
; Set full path to channels program if using virtualenv
command=/var/app/venv/staging-LQM1lest/bin/daphne -b 0.0.0.0 -p 5000 researchhub.asgi:application
directory=/var/app/current
user=ec2-user
numprocs=1
# Give each process a unique name so they can be told apart
process_name=asgi%(process_num)d
stdout_logfile=/var/log/stdout_daphne.log
redirect_stderr=true
autostart=true
autorestart=true
startsecs=10

; Need to wait for currently executing tasks to finish at shutdown.
; Increase this if you have very long running tasks.
stopwaitsecs = 600

; When resorting to send SIGKILL to the program to terminate it
; send SIGKILL to its whole process group instead,
; taking care of its children as well.
killasgroup=true

; if rabbitmq is supervised, set its priority higher
; so it starts first
priority=998

environment=$djangoenv"

# Create the supervisord conf script
echo "$daphne" | sudo tee /etc/daphne.conf

# Add configuration script to supervisord conf (if not there already)
if grep -xq "files=.* daphne.conf.*" /etc/supervisord.conf;
  then
      echo "conf already set"
  else
      echo "[include]" | tee -a /etc/supervisord.conf
      sudo sed -e 's/files=.*/& /etc/daphne.conf/' -i /etc/supervisord.conf
fi

# Reread the supervisord config
sudo /usr/bin/supervisorctl -c /etc/supervisord.conf reread

# Update supervisord in cache without restarting all services
sudo /usr/bin/supervisorctl -c /etc/supervisord.conf update

# Start/Restart processes through supervisord
sudo /usr/bin/supervisorctl -c /etc/supervisord.conf restart daphne:*
