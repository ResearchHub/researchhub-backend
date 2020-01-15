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
celery_env=`cat /opt/python/current/env | tr '\n' ',' | sed 's/export //g' | sed 's/$PATH/%(ENV_PATH)s/g' | sed 's/$PYTHONPATH//g' | sed 's/$LD_LIBRARY_PATH//g'`
celery_env=${celery_env%?}

celery_conf="[program:celeryd-worker]

; Run celery from virtual env
command=/opt/python/run/venv/bin/celery worker -A researchhub -B -P solo --loglevel=INFO -n worker.%%h -Q ${app_env}
process_name=%(program_name)s_%(process_num)02d

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

environment=$celery_env
"

# Copy the above script into celery.conf file
echo "$celery_conf" | tee /opt/python/etc/celery.conf

# Add the conf to supervisord (if not already there)
if ! grep -Fxq "[include]" /opt/python/etc/supervisord.conf
  then
  echo "[include]" | tee -a /opt/python/etc/supervisord.conf
  echo "files: celery.conf" | tee -a /opt/python/etc/supervisord.conf
fi

# Reread the conf
/usr/local/bin/supervisorctl -c /opt/python/etc/supervisord.conf reread

# Update supvisord in cache without restarting all services
/usr/local/bin/supervisorctl -c /opt/python/etc/supervisord.conf update

# Restart celeryd
/usr/local/bin/supervisorctl -c /opt/python/etc/supervisord.conf restart celeryd-worker
