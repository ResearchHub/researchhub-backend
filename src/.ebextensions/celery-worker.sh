#!/usr/bin/env bash
# Builds and runs a supervisord script to daemonize celery

# If CELERY_WORKER is True, run this script, otherwise stop the existing celery daemon
celery_worker=`grep -o "CELERY_WORKER=\".*\"" /opt/python/current/env`
if ! [ $celery_worker = "CELERY_WORKER=\"True\"" ]; then
        /usr/local/bin/supervisorctl -c /opt/python/etc/supervisord.conf stop celeryd-worker
        echo "Exiting worker script"
    exit 0
else
    echo "Running worker script"
fi

# Get eb environment variables
app_env=`grep -oP "(?<=APP_ENV=\").*(?=\")" /opt/python/current/env`
celery_env=`cat /opt/python/current/env | tr '\n' ',' | sed 's/%/%%/g' | sed 's/export //g' | sed 's/$PATH/%(ENV_PATH)s/g' | sed 's/$PYTHONPATH//g' | sed 's/$LD_LIBRARY_PATH//g'`
celery_env=${celery_env%?}

celery_conf="[program:celeryd-worker]

; Run celery from virtual env
command=/opt/python/run/venv/bin/celery worker -A researchhub -P solo --loglevel=INFO -Q ${app_env}

directory=/opt/python/current/app
user=ec2-user
numprocs=1
stdout_logfile=/var/log/celery/worker.out.log
stderr_logfile=/var/log/celery/worker.err.log
autostart=true
autorestart=true
startsecs=10
startretries=2

; Time to wait for currently executing tasks to finish at shutdown
stopwaitsecs=600

; Send SIGKILL to the process group to terminate child processes
killasgroup=true

priority=998

environment=$celery_env"

celerybeatconf="[program:celerybeat]
; Set full path to celery program if using virtualenv
command=/opt/python/run/venv/bin/celery beat –A researchhub -S redbeat.RedBeatScheduler --loglevel=INFO -Q ${app}

directory=/opt/python/current/app
user=ec2-user
numprocs=1
stdout_logfile=/var/log/celery/beat.out.log
stderr_logfile=/var/log/celery/beat.err.log
autostart=true
autorestart=true
startsecs=10
startretries=2

; Need to wait for currently executing tasks to finish at shutdown.
; Increase this if you have very long running tasks.
stopwaitsecs=60

; When resorting to send SIGKILL to the program to terminate it
; send SIGKILL to its whole process group instead,
; taking care of its children as well.
killasgroup=true

; if rabbitmq is supervised, set its priority higher
; so it starts first
priority=997

environment=$celeryenv"

# Copy the above script into celery.conf file
echo "$celery_conf" | tee /opt/python/etc/celery.conf
echo "$celerybeatconff" | tee /opt/python/etc/celerybeat.conf

# Add the conf to supervisord (if not already there)
if ! grep -Fxq "[include]" /opt/python/etc/supervisord.conf
  then
  echo "[include]" | tee -a /opt/python/etc/supervisord.conf
  echo "files=/opt/python/etc/celery.conf /opt/python/etc/celerybeat.conf" | tee -a /opt/python/etc/supervisord.conf
fi

# Reread the conf
/usr/local/bin/supervisorctl -c /opt/python/etc/supervisord.conf reread

# Update supvisord in cache without restarting all services
/usr/local/bin/supervisorctl -c /opt/python/etc/supervisord.conf update

# Restart celeryd
/usr/local/bin/supervisorctl -c /opt/python/etc/supervisord.conf restart celeryd-worker
/usr/local/bin/supervisorctl -c /opt/python/etc/supervisord.conf restart celerybeat
