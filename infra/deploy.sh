#!/bin/bash
# Cloud Pricing Table Converter — Deploy (single S3 bucket)
# Usage:
#   First deploy:  GOOGLE_CLIENT_ID=xxx ./deploy.sh
#   Subsequent:    AWS_PROFILE=kiro-deploy ./deploy.sh
set -e

PROFILE="${AWS_PROFILE:-default}"
REGION="us-east-1"
STACK_NAME="pricing-table-generator"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --profile $PROFILE)
BUCKET="pricing-table-gen-${ACCOUNT_ID}"

GOOGLE_CLIENT_ID="${GOOGLE_CLIENT_ID:-}"   # required on first deploy; optional after

echo "=== Pricing Table Generator Deployment ==="
echo "Account: $ACCOUNT_ID | Region: $REGION | Bucket: $BUCKET"

# 1. Create bucket if it doesn't exist
echo "[1/5] Creating S3 bucket..."
aws s3api create-bucket --bucket $BUCKET --region $REGION \
    --profile $PROFILE 2>/dev/null && echo "  Bucket created" || echo "  Bucket already exists"

# 2. Package and upload Lambda zips
echo "[2/5] Packaging and uploading Lambda..."

# main function — includes openpyxl
rm -f /tmp/pricing_table_generator.zip
LAMBDA_PKG_DIR=$(mktemp -d)
pip3 install openpyxl --quiet --target "$LAMBDA_PKG_DIR" 2>/dev/null || python3 -m pip install openpyxl --quiet --target "$LAMBDA_PKG_DIR"
cp "$SCRIPT_DIR/../backend/lambda_function.py" "$LAMBDA_PKG_DIR/lambda_function.py"
python3 -c "
import zipfile, os
pkg = '$LAMBDA_PKG_DIR'
with zipfile.ZipFile('/tmp/pricing_table_generator.zip', 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(pkg):
        for f in files:
            fullpath = os.path.join(root, f)
            arcname = os.path.relpath(fullpath, pkg)
            zf.write(fullpath, arcname)
"
rm -rf "$LAMBDA_PKG_DIR"
aws s3 cp /tmp/pricing_table_generator.zip "s3://$BUCKET/lambda/pricing_table_generator.zip" \
    --profile $PROFILE --region $REGION

# auth function — single file, no dependencies
zip -j /tmp/auth_handler.zip "$SCRIPT_DIR/../backend/auth_handler.py"
aws s3 cp /tmp/auth_handler.zip "s3://$BUCKET/lambda/auth_handler.zip" \
    --profile $PROFILE --region $REGION

# 3. Deploy CloudFormation
echo "[3/5] Deploying CloudFormation stack..."
TEMPLATE_HASH=$(python3 -c "import hashlib,sys; print(hashlib.md5(open(sys.argv[1],'rb').read()).hexdigest())" "$SCRIPT_DIR/template.yaml")
HASH_FILE="/tmp/ptg-template-hash-${ACCOUNT_ID}"
PREV_HASH=$(cat "$HASH_FILE" 2>/dev/null || echo "")

# Build parameter overrides — only pass GoogleClientId if explicitly provided
CF_PARAMS="BucketName=$BUCKET"
if [ -n "$GOOGLE_CLIENT_ID" ]; then
    CF_PARAMS="$CF_PARAMS GoogleClientId=$GOOGLE_CLIENT_ID"
fi

if [ "$TEMPLATE_HASH" != "$PREV_HASH" ] || [ -n "$GOOGLE_CLIENT_ID" ]; then
    aws cloudformation deploy \
        --template-file "$SCRIPT_DIR/template.yaml" \
        --stack-name $STACK_NAME \
        --capabilities CAPABILITY_IAM \
        --parameter-overrides $CF_PARAMS \
        --profile $PROFILE \
        --region $REGION
    echo "$TEMPLATE_HASH" > "$HASH_FILE"

    # Force a new API Gateway deployment so CORS/method changes go live immediately
    API_ID=$(aws cloudformation describe-stacks \
        --stack-name $STACK_NAME \
        --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' \
        --output text --profile $PROFILE --region $REGION 2>/dev/null | grep -o '[a-z0-9]*\.execute-api' | cut -d. -f1)
    if [ -n "$API_ID" ]; then
        aws apigateway create-deployment \
            --rest-api-id "$API_ID" \
            --stage-name prod \
            --description "deploy.sh forced redeploy" \
            --profile $PROFILE --region $REGION > /dev/null 2>&1 || true
        echo "  API Gateway redeployed"
    fi
else
    echo "  Template unchanged — skipping CloudFormation deploy"
fi

# Always force Lambda code updates
echo "  Updating Lambda function code..."
aws lambda update-function-code \
    --function-name pricing-table-generator \
    --s3-bucket $BUCKET \
    --s3-key lambda/pricing_table_generator.zip \
    --profile $PROFILE \
    --region $REGION > /dev/null
aws lambda update-function-code \
    --function-name pricing-table-generator-auth \
    --s3-bucket $BUCKET \
    --s3-key lambda/auth_handler.zip \
    --profile $PROFILE \
    --region $REGION > /dev/null 2>&1 || echo "  (auth function not yet created — will be after CloudFormation)"

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
DEPLOY_TS=$(date +%s)
sed "s|const API_URL = ''|const API_URL = '${API_URL}'|; s|const GOOGLE_CLIENT_ID = ''|const GOOGLE_CLIENT_ID = '${GOOGLE_CLIENT_ID}'|" \
    "$SCRIPT_DIR/../frontend/src/app.js" > /tmp/app.js.deploy
# Inject deploy timestamp and Google Client ID into index.html for cache busting + GSI
sed "s|__DEPLOY_TS__|${DEPLOY_TS}|g; s|__GOOGLE_CLIENT_ID__|${GOOGLE_CLIENT_ID}|g" \
    "$SCRIPT_DIR/../frontend/src/index.html" > /tmp/index.html.deploy
# Static assets (logos) — immutable, cache hard
aws s3 sync "$SCRIPT_DIR/../frontend/src/" "s3://$BUCKET/frontend/" \
    --profile $PROFILE --region $REGION --delete \
    --exclude "app.js" --exclude "index.html" --exclude "style.css" \
    --cache-control "public, max-age=31536000"

# CSS and JS — explicit Content-Type is REQUIRED for CloudFront to gzip them.
# Without it S3 defaults to application/octet-stream, which CloudFront skips.
aws s3 cp "$SCRIPT_DIR/../frontend/src/style.css" "s3://$BUCKET/frontend/style.css" \
    --profile $PROFILE --region $REGION \
    --content-type "text/css" \
    --cache-control "public, max-age=300"
aws s3 cp /tmp/app.js.deploy "s3://$BUCKET/frontend/app.js" \
    --profile $PROFILE --region $REGION \
    --content-type "application/javascript" \
    --cache-control "public, max-age=300"

# index.html — never cache, it carries the ?v={DEPLOY_TS} pointer to the current app.js
aws s3 cp /tmp/index.html.deploy "s3://$BUCKET/frontend/index.html" \
    --profile $PROFILE --region $REGION \
    --content-type "text/html" \
    --cache-control "no-cache, must-revalidate"
rm /tmp/app.js.deploy /tmp/index.html.deploy

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
echo "  s3://$BUCKET/lambda/     <- Lambda zips"
echo "  s3://$BUCKET/uploads/    <- customer JSON uploads"
echo "  s3://$BUCKET/jobs/       <- temp processing files"
if [ -z "$GOOGLE_CLIENT_ID" ]; then
    echo ""
    echo "⚠️  GOOGLE_CLIENT_ID not set — auth Lambda will reject all logins."
    echo "   First time setup: GOOGLE_CLIENT_ID=xxx AWS_PROFILE=kiro-deploy ./deploy.sh"
fi
