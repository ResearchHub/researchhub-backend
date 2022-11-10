FROM python:3.8-slim
RUN pip install --no-cache-dir requests scholarly awslambdaric


WORKDIR /usr/src
COPY .  /usr/src/
ENTRYPOINT [ "/usr/local/bin/python3.8", "-m", "awslambdaric" ]
CMD [ "lambda_handler.handler" ]

# This is for debugging
# CMD [ "/bin/bash" ]
