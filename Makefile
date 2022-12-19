project=researchhub_backend

all: docker.build docker.start

docker.build:
	@docker build --tag researchhub-backend .

docker.start:
	@docker-compose up
