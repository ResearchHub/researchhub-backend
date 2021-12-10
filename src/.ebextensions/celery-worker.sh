#!/usr/bin/env bash
# Builds and runs a supervisord script to daemonize celery

# If CELERY_WORKER is True, run this script, otherwise stop the existing celery daemon
celery_worker=$(sudo grep -o CELERY_WORKER=.* /opt/elasticbeanstalk/deployment/env)
if ! [ "$celery_worker" == "CELERY_WORKER=True" ]; then
        /usr/bin/supervisorctl -c /etc/supervisord.conf stop celeryd-worker
        /usr/bin/supervisorctl -c /etc/supervisord.conf stop celerybeat
        /usr/bin/supervisorctl -c /etc/supervisord.conf stop celeryflower
        echo "Exiting worker script"
    exit 0
else
    echo "Running worker script"
fi

# Get eb environment variables
app_env=`sudo grep -oP "(?<=APP_ENV=).*(?=)" /opt/elasticbeanstalk/deployment/env`
queue=`sudo grep -oP "(?<=QUEUE=).*(?=)" /opt/elasticbeanstalk/deployment/env`
celery_env=`sudo cat /opt/elasticbeanstalk/deployment/env | sed 's/=/="/' | sed ':a;N;$!ba;s/\n/",/g' | sed 's/%/%%/g' | sed 's/export //g' | sed 's/$PATH/%(ENV_PATH)s/g' | sed 's/$PYTHONPATH//g' | sed 's/$LD_LIBRARY_PATH//g'`
celery_env="$celery_env\","
celery_env=${celery_env%?}

celery_conf="[program:celeryd-worker]

; Run celery from virtual env
command=/var/app/venv/staging-LQM1lest/bin/celery worker -A researchhub -P prefork --loglevel=INFO -Q ${queue} -E -n ${queue} --prefetch-multiplier=1

directory=/var/app/current/
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
command=/var/app/venv/staging-LQM1lest/bin/celery beat -A researchhub -S redbeat.RedBeatScheduler --loglevel=INFO --pidfile /tmp/celerybeat.pid
directory=/var/app/current/
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
priority=998

environment=$celery_env"

celeryflowerconf="[program:celeryflower]
; Set full path to celery program if using virtualenv
command=/var/app/venv/staging-LQM1lest/bin/flower -A researchhub --port=5555 --url_prefix=flower
directory=/var/app/current/
user=ec2-user
numprocs=1
stdout_logfile=/var/log/celery/flower.out.log
stderr_logfile=/var/log/celery/flower.err.log
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
priority=998

environment=$celery_env"
# Copy the above script into celery.conf file
echo "$celery_conf" | tee /etc/celery.conf
echo "$celerybeatconf" | tee /etc/celerybeat.conf
echo "$celeryflowerconf" | tee /etc/celeryflower.conf

# Add the conf to supervisord (if not already there)
if ! grep -Fxq "[include]" /etc/supervisord.conf
  then
  echo "[include]" | tee -a /etc/supervisord.conf
  echo "files= /etc/celerybeat.conf /etc/celery.conf /etc/celeryflower.conf" | tee -a /etc/supervisord.conf
fi

# Reread the conf
/usr/bin/supervisorctl -c /etc/supervisord.conf reread

# Update supvisord in cache without restarting all services
/usr/bin/supervisorctl -c /etc/supervisord.conf update

# Restart celeryd
/usr/bin/supervisorctl -c /etc/supervisord.conf restart celeryd-worker
/usr/bin/supervisorctl -c /etc/supervisord.conf restart celerybeat
/usr/bin/supervisorctl -c /etc/supervisord.conf stop celeryflower
