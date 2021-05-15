aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin 794128250202.dkr.ecr.us-west-2.amazonaws.com
docker build -t researchhub-backend-lambda:latest .
docker tag researchhub-backend-lambda:latest 794128250202.dkr.ecr.us-west-2.amazonaws.com/researchhub-backend-staging
docker push 794128250202.dkr.ecr.us-west-2.amazonaws.com/researchhub-backend-staging:latest
docker tag researchhub-backend-lambda:latest 794128250202.dkr.ecr.us-west-2.amazonaws.com/researchhub-backend
docker push 794128250202.dkr.ecr.us-west-2.amazonaws.com/researchhub-backend:latest
aws lambda update-function-code --function-name ResearchHub-Backend-Staging --image-uri 794128250202.dkr.ecr.us-west-2.amazonaws.com/researchhub-backend-staging:latest
aws lambda update-function-code --function-name ResearchHub-Backend --image-uri 794128250202.dkr.ecr.us-west-2.amazonaws.com/researchhub-backend:latest