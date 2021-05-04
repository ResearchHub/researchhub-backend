FROM ubuntu:18.04

RUN apt-get update && \
    apt-get install --no-install-recommends -y gcc && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN apt-get update -y
RUN apt-get install -y python3
RUN apt-get -y install python3-setuptools
RUN apt-get -y install python3-pip
RUN python3 -m pip install --upgrade pip


COPY requirements.txt .

RUN pip3 install -r requirements.txt

RUN mkdir -p /usr/app/src
COPY .  /usr/app/src/

WORKDIR /usr/app/src
ENTRYPOINT [ "/usr/bin/python3.6", "-m", "awslambdaric" ]
CMD [ "researchhub.aws_lambda.handler" ]