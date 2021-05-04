$(aws ecr get-login --no-include-email --region us-west-2 --profile researchhub);
docker build -t researchhub-backend-lambda:latest .
docker tag researchhub-backend-lambda:latest 794128250202.dkr.ecr.us-west-2.amazonaws.com/researchhub-backend-staging
docker push 794128250202.dkr.ecr.us-west-2.amazonaws.com/researchhub-backend-staging:latest
