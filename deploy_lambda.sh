docker build -t researchhub-backend-lambda:latest .
docker tag researchhub-backend-lambda:latest 794128250202.dkr.ecr.us-west-2.amazonaws.com/researchhub-backend-staging
docker push 794128250202.dkr.ecr.us-west-2.amazonaws.com/researchhub-backend-staging:latest
aws lambda update-function-code --function-name  test2 --image-uri 794128250202.dkr.ecr.us-west-2.amazonaws.com/researchhub-backend-staging:latest