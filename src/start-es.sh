docker network create researchhub-network

docker run \
  --name researchhub-elasticsearch \
  --network researchhub-network \
  --publish 9200:9200 \
  --publish 9300:9300 \
  --env "discovery.type=single-node" \
  docker.elastic.co/elasticsearch/elasticsearch:7.10.1
