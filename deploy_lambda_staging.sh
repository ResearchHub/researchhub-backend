#!/bin/bash

AWS_VER=`aws --version`
AWS_REGEX="aws-cli\/2.+"
echo "Using $AWS_VER"

if [[ $AWS_VER =~ $AWS_REGEX ]]; then
	aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin 794128250202.dkr.ecr.us-west-2.amazonaws.com
else
	$(aws ecr get-login --no-include-email --region us-west-2 --profile researchhub);
fi

docker build -t researchhub-backend-lambda:latest .
docker tag researchhub-backend-lambda:latest 794128250202.dkr.ecr.us-west-2.amazonaws.com/researchhub-backend-staging
docker push 794128250202.dkr.ecr.us-west-2.amazonaws.com/researchhub-backend-staging:latest
aws lambda update-function-code --function-name ResearchHub-Backend-Staging --image-uri 794128250202.dkr.ecr.us-west-2.amazonaws.com/researchhub-backend-staging:latest
