FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

RUN apt-get update && \
    apt-get install --no-install-recommends -y gcc && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN apt-get update -y
RUN apt-get -y install python3.8-dev
RUN apt-get -y install python3-setuptools
RUN apt-get -y install python3-pip
RUN apt-get -y install libpq-dev libxml2-dev libxslt1-dev libldap2-dev libsasl2-dev libffi-dev
RUN python3 -m pip install --upgrade pip
RUN apt-get -y install default-jre
RUN apt-get -y install redis-server

COPY src/requirements.txt .

RUN pip3 install -r requirements.txt --no-deps

RUN mkdir -p /usr/app/src
COPY .  /usr/app/
COPY /misc/hub_hub.csv /usr/misc/hub_hub.csv
RUN mkdir -p /tmp/pdf_cermine/
RUN cp /usr/bin/python3 /usr/bin/python


WORKDIR /usr/app/src
# ENTRYPOINT [ "/usr/bin/python3.6", "-m", "awslambdaric" ]
# CMD [ "researchhub.aws_lambda.handler" ]

# This is for debugging
#CMD [ "/bin/bash" ]
