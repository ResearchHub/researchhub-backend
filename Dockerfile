FROM docker.elastic.co/elasticsearch/elasticsearch:7.4.1
RUN bin/elasticsearch-plugin install --batch ingest-attachment
