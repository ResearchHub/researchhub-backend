docker network create researchhub-network

docker run \
  --name researchhub-kibana \
  --publish 5601:5601 \
  --network researchhub-network \
  --env "ELASTICSEARCH_HOSTS=http://researchhub-elasticsearch:9200" \
  docker.elastic.co/kibana/kibana:7.4.1