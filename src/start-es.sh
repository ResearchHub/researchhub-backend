docker build . -t researchhub-elasticsearch
docker run -p 9200:9200 -p 9300:9300 -e "discovery.type=single-node" researchhub-elasticsearch
