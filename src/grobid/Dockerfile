# FROM openjdk:8-jre-slim
# FROM python:3.8-slim
# RUN pip install --no-cache-dir requests awslambdaric

FROM python:3.8-slim
RUN pip install --no-cache-dir requests awslambdaric

# FROM openjdk:8-jdk-slim
FROM ibmjava:8-sdk
RUN apt-get update
RUN apt-get upgrade -y
RUN apt-get install wget -y
RUN apt-get install unzip -y

WORKDIR /usr/src
RUN mkdir /opt/gradle
RUN wget https://services.gradle.org/distributions/gradle-7.2-bin.zip
RUN unzip -d /opt/gradle gradle-7.2-bin.zip
# RUN export PATH=$PATH:/opt/gradle/gradle-7.2/bin
ENV PATH=$PATH:/opt/gradle/gradle-7.2/bin
RUN wget https://github.com/kermitt2/grobid/archive/0.7.3.zip
RUN unzip 0.7.3.zip
RUN cd grobid-0.7.3
RUN export PATH=$PATH:/opt/gradle/gradle-7.2/bin
WORKDIR /usr/src/grobid-0.7.3
RUN gradle clean install

COPY --from=python:3.8-slim /usr/local/bin/python3.8 /usr/local/bin/python3.8
COPY --from=python:3.8-slim /usr/local/lib/python3.8 /usr/local/lib/python3.8
COPY --from=python:3.8-slim /usr/local/bin/pip3.8 /usr/local/bin/pip3.8
COPY --from=python:3.8-slim /usr/local/lib/python3.8/site-packages/  /usr/local/lib/python3.8/site-packages/

# WORKDIR /usr/src
# COPY .  /usr/src/
# ENTRYPOINT [ "/usr/local/bin/python3.8", "-m", "awslambdaric" ]
# CMD [ "lambda_handler.handler" ]

# This is for debugging
# CMD [ "/bin/bash" ]

# java -Xmx4G -Djava.library.path=/usr/src/grobid-0.7.3/grobid-home/lib/lin-64:/usr/src/grobid-0.7.3/grobid-home/lib/lin-64/jep -jar /usr/src/grobid-0.7.3/grobid-core/build/libs/grobid-core-0.7.3-onejar.jar -gH /usr/src/grobid-0.7.3/grobid-home -dIn /tmp/test/pdf -dOut /tmp/test/pdf -exe processFullText
