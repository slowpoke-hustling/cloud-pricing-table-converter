#!/bin/bash
# Pricing Table Generator — Deploy (single S3 bucket)
# The bucket is managed outside CloudFormation to avoid chicken-and-egg
# with Lambda requiring the zip to exist before stack creation.
set -e

PROFILE="${AWS_PROFILE:-default}"   # override: AWS_PROFILE=your-profile ./deploy.sh
REGION="us-east-1"
STACK_NAME="pricing-table-generator"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --profile $PROFILE)
BUCKET="pricing-table-gen-${ACCOUNT_ID}"

echo "=== Pricing Table Generator Deployment ==="
echo "Account: $ACCOUNT_ID | Region: $REGION | Bucket: $BUCKET"

# 1. Create bucket if it doesn't exist
echo "[1/5] Creating S3 bucket..."
aws s3api create-bucket --bucket $BUCKET --region $REGION \
    --profile $PROFILE 2>/dev/null && echo "  Bucket created" || echo "  Bucket already exists"

# 2. Package and upload Lambda zip (must exist before CloudFormation)
echo "[2/5] Packaging and uploading Lambda..."
rm -f /tmp/pricing_table_generator.zip
zip -j /tmp/pricing_table_generator.zip "$SCRIPT_DIR/backend/lambda_function.py"
aws s3 cp /tmp/pricing_table_generator.zip "s3://$BUCKET/lambda/pricing_table_generator.zip" \
    --profile $PROFILE --region $REGION

# 3. Deploy CloudFormation (Lambda zip now exists in bucket)
echo "[3/5] Deploying CloudFormation stack..."
aws cloudformation deploy \
    --template-file "$SCRIPT_DIR/template.yaml" \
    --stack-name $STACK_NAME \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides BucketName=$BUCKET \
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
sed "s|const API_URL = ''|const API_URL = '${API_URL}'|" \
    "$SCRIPT_DIR/frontend/web/app.js" > /tmp/app.js.deploy
aws s3 sync "$SCRIPT_DIR/frontend/web/" "s3://$BUCKET/frontend/" \
    --profile $PROFILE --region $REGION --delete --exclude "app.js"
aws s3 cp /tmp/app.js.deploy "s3://$BUCKET/frontend/app.js" \
    --profile $PROFILE --region $REGION
rm /tmp/app.js.deploy

# Invalidate CloudFront cache on re-deploys
DIST_ID=$(aws cloudfront list-distributions --profile $PROFILE \
    --query "DistributionList.Items[?Origins.Items[0].DomainName=='${BUCKET}.s3.amazonaws.com'].Id" \
    --output text 2>/dev/null | head -1)
if [ -n "$DIST_ID" ]; then
    aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/*" \
        --profile $PROFILE > /dev/null 2>&1 || true
fi

echo ""
echo "=== Deployment Complete ==="
echo "URL:    $CLOUDFRONT_URL"
echo "API:    $API_URL"
echo "Bucket: s3://$BUCKET"
echo ""
echo "  s3://$BUCKET/frontend/   <- web files (served by CloudFront)"
echo "  s3://$BUCKET/lambda/     <- Lambda zip"
echo "  s3://$BUCKET/uploads/    <- customer JSON uploads"
echo "  s3://$BUCKET/jobs/       <- temp processing files"
