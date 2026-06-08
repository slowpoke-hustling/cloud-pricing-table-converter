#!/bin/bash
# Pricing Table Generator — Deploy
set -e

PROFILE="kiro-deploy"
REGION="us-east-1"
STACK_NAME="pricing-table-generator"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --profile $PROFILE)
FRONTEND_BUCKET="pricing-table-gen-frontend-${ACCOUNT_ID}"
LAMBDA_BUCKET="pricing-table-gen-lambda-${ACCOUNT_ID}"
JSON_BUCKET="pricing-table-gen-uploads-${ACCOUNT_ID}"

echo "=== Pricing Table Generator Deployment ==="
echo "Account: $ACCOUNT_ID | Region: $REGION"

# 1. Create buckets if needed
echo "[1/5] Ensuring S3 buckets exist..."
aws s3 mb "s3://$FRONTEND_BUCKET" --region $REGION --profile $PROFILE 2>/dev/null || true
aws s3 mb "s3://$LAMBDA_BUCKET" --region $REGION --profile $PROFILE 2>/dev/null || true

# 2. Package and upload Lambda
echo "[2/5] Packaging Lambda..."
cd backend
zip -r /tmp/pricing_table_generator.zip lambda_function.py
aws s3 cp /tmp/pricing_table_generator.zip "s3://$LAMBDA_BUCKET/pricing_table_generator.zip" \
    --profile $PROFILE --region $REGION
cd ..

# Update Lambda code if it already exists (fast update path)
aws lambda update-function-code --function-name pricing-table-generator \
    --s3-bucket $LAMBDA_BUCKET --s3-key pricing_table_generator.zip \
    --profile $PROFILE --region $REGION > /dev/null 2>&1 || true

# 3. Deploy CloudFormation
echo "[3/5] Deploying CloudFormation stack..."
aws cloudformation deploy \
    --template-file template.yaml \
    --stack-name $STACK_NAME \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides \
        FrontendBucket=$FRONTEND_BUCKET \
        LambdaBucket=$LAMBDA_BUCKET \
        JsonStorageBucket=$JSON_BUCKET \
    --profile $PROFILE \
    --region $REGION

# 4. Get outputs
echo "[4/5] Getting stack outputs..."
API_URL=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' \
    --output text --profile $PROFILE --region $REGION)

CLOUDFRONT_URL=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontUrl`].OutputValue' \
    --output text --profile $PROFILE --region $REGION)

# 5. Deploy frontend with API URL injected
echo "[5/5] Deploying frontend..."
cd frontend/web
sed "s|const API_URL = ''|const API_URL = '${API_URL}'|" app.js > /tmp/app.js.deploy
aws s3 sync . "s3://$FRONTEND_BUCKET" --profile $PROFILE --region $REGION --delete \
    --exclude "app.js"
aws s3 cp /tmp/app.js.deploy "s3://$FRONTEND_BUCKET/app.js" --profile $PROFILE --region $REGION
rm /tmp/app.js.deploy
cd ../..

# Invalidate CloudFront cache
DIST_ID=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontUrl`].OutputValue' \
    --output text --profile $PROFILE --region $REGION | \
    sed 's|https://||' | sed 's|\.cloudfront\.net||')
aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/*" \
    --profile $PROFILE > /dev/null 2>&1 || true

echo ""
echo "=== Deployment Complete ==="
echo "URL:     $CLOUDFRONT_URL"
echo "API:     $API_URL"
echo "Storage: s3://$JSON_BUCKET"
