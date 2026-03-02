#!/bin/bash
# =============================================================================
# Supply Chain Ghost — Full Deployment Script
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${CYAN}[SCG]${NC} $1"; }
ok()   { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
log "Starting Supply Chain Ghost deployment..."

command -v aws   >/dev/null 2>&1 || err "AWS CLI not found. Install: https://aws.amazon.com/cli/"
command -v cdk   >/dev/null 2>&1 || err "AWS CDK not found. Install: npm install -g aws-cdk"
command -v node  >/dev/null 2>&1 || err "Node.js not found."
command -v python3 >/dev/null 2>&1 || err "Python 3 not found."

AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || err "AWS credentials not configured."
AWS_REGION=${AWS_REGION:-us-east-1}
log "Account: $AWS_ACCOUNT | Region: $AWS_REGION"

# ---------------------------------------------------------------------------
# Step 1: Python dependencies
# ---------------------------------------------------------------------------
log "Installing Python dependencies..."
cd "$PROJECT_ROOT"
python3 -m pip install -r requirements.txt --quiet
ok "Python dependencies installed"

# ---------------------------------------------------------------------------
# Step 2: Build Lambda layers
# ---------------------------------------------------------------------------
log "Building Lambda layers..."
bash "$SCRIPT_DIR/build_layers.sh"
ok "Lambda layers built"

# ---------------------------------------------------------------------------
# Step 3: CDK Bootstrap (if needed)
# ---------------------------------------------------------------------------
log "Bootstrapping CDK environment..."
cd "$PROJECT_ROOT/infra"
cdk bootstrap aws://$AWS_ACCOUNT/$AWS_REGION 2>/dev/null || warn "CDK bootstrap skipped (already bootstrapped)"
ok "CDK environment ready"

# ---------------------------------------------------------------------------
# Step 4: CDK Synth & Deploy
# ---------------------------------------------------------------------------
log "Synthesizing CloudFormation templates..."
cdk synth --quiet
ok "Templates synthesized"

log "Deploying all stacks (this may take 15-20 minutes)..."
cdk deploy --all \
  --require-approval never \
  --outputs-file "$PROJECT_ROOT/cdk-outputs.json" \
  --context account=$AWS_ACCOUNT \
  --context region=$AWS_REGION
ok "All CDK stacks deployed"

# ---------------------------------------------------------------------------
# Step 5: Extract outputs
# ---------------------------------------------------------------------------
log "Extracting deployment outputs..."
if [ -f "$PROJECT_ROOT/cdk-outputs.json" ]; then
  USER_POOL_ID=$(python3 -c "import json; d=json.load(open('$PROJECT_ROOT/cdk-outputs.json')); print([v for k,v in list(d.values())[0].items() if 'UserPoolId' in k][0])" 2>/dev/null || echo "UNKNOWN")
  CLIENT_ID=$(python3 -c "import json; d=json.load(open('$PROJECT_ROOT/cdk-outputs.json')); print([v for k,v in list(d.values())[0].items() if 'ClientId' in k][0])" 2>/dev/null || echo "UNKNOWN")
  API_URL=$(python3 -c "import json; d=json.load(open('$PROJECT_ROOT/cdk-outputs.json')); print([v for k,v in list(d.values())[0].items() if 'ApiUrl' in k or 'RestApiEndpoint' in k][0])" 2>/dev/null || echo "UNKNOWN")
  CF_DOMAIN=$(python3 -c "import json; d=json.load(open('$PROJECT_ROOT/cdk-outputs.json')); print([v for k,v in list(d.values())[0].items() if 'Distribution' in k or 'CloudFront' in k][0])" 2>/dev/null || echo "UNKNOWN")

  log "User Pool ID:  $USER_POOL_ID"
  log "Client ID:     $CLIENT_ID"
  log "API URL:       $API_URL"
  log "CloudFront:    $CF_DOMAIN"
fi

# ---------------------------------------------------------------------------
# Step 6: Build & Deploy Frontend
# ---------------------------------------------------------------------------
log "Building React frontend..."
cd "$PROJECT_ROOT/frontend"
npm install --legacy-peer-deps

# Inject environment variables
cat > .env <<EOF
REACT_APP_USER_POOL_ID=${USER_POOL_ID:-PLACEHOLDER}
REACT_APP_USER_POOL_CLIENT_ID=${CLIENT_ID:-PLACEHOLDER}
REACT_APP_API_URL=${API_URL:-PLACEHOLDER}
REACT_APP_REGION=${AWS_REGION}
EOF

npm run build
ok "Frontend built"

# Upload to S3
DASHBOARD_BUCKET=$(aws cloudformation describe-stacks \
  --stack-name SCG-Dashboard \
  --query "Stacks[0].Outputs[?contains(OutputKey,'Bucket')].OutputValue" \
  --output text 2>/dev/null || echo "")

if [ -n "$DASHBOARD_BUCKET" ]; then
  log "Deploying frontend to S3: $DASHBOARD_BUCKET"
  aws s3 sync build/ "s3://$DASHBOARD_BUCKET/" --delete --cache-control "max-age=31536000,public"
  aws s3 cp build/index.html "s3://$DASHBOARD_BUCKET/index.html" --cache-control "no-cache"

  # Invalidate CloudFront
  CF_DIST_ID=$(aws cloudformation describe-stacks \
    --stack-name SCG-Dashboard \
    --query "Stacks[0].Outputs[?contains(OutputKey,'DistributionId')].OutputValue" \
    --output text 2>/dev/null || echo "")
  if [ -n "$CF_DIST_ID" ]; then
    aws cloudfront create-invalidation --distribution-id "$CF_DIST_ID" --paths "/*" >/dev/null 2>&1
    ok "CloudFront cache invalidated"
  fi
  ok "Frontend deployed"
else
  warn "Could not find dashboard S3 bucket. Deploy frontend manually."
fi

# ---------------------------------------------------------------------------
# Step 7: Create initial admin user
# ---------------------------------------------------------------------------
log "Creating admin user..."
ADMIN_EMAIL=${ADMIN_EMAIL:-admin@supplychain-ghost.com}
ADMIN_PASS=${ADMIN_PASS:-Ghost\$ecure123!}

if [ "$USER_POOL_ID" != "UNKNOWN" ]; then
  aws cognito-idp admin-create-user \
    --user-pool-id "$USER_POOL_ID" \
    --username "$ADMIN_EMAIL" \
    --user-attributes Name=email,Value="$ADMIN_EMAIL" Name=email_verified,Value=true \
    --temporary-password "$ADMIN_PASS" \
    --message-action SUPPRESS 2>/dev/null || warn "Admin user may already exist"

  aws cognito-idp admin-add-user-to-group \
    --user-pool-id "$USER_POOL_ID" \
    --username "$ADMIN_EMAIL" \
    --group-name SCGAdmins 2>/dev/null || warn "Could not add to admin group"
  ok "Admin user created: $ADMIN_EMAIL"
fi

# ---------------------------------------------------------------------------
# Step 8: Seed Knowledge Base
# ---------------------------------------------------------------------------
log "Seeding Bedrock Knowledge Base..."
python3 "$SCRIPT_DIR/seed_knowledge_base.py" || warn "Knowledge base seeding skipped"
ok "Knowledge base seeded"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  Supply Chain Ghost — Deployment Complete!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo -e "  Dashboard:  ${CYAN}https://${CF_DOMAIN:-localhost}${NC}"
echo -e "  API:        ${CYAN}${API_URL:-http://localhost}${NC}"
echo -e "  Admin:      ${CYAN}${ADMIN_EMAIL}${NC} / (temporary password)"
echo ""
echo -e "  Next steps:"
echo -e "    1. Log in to change temporary password"
echo -e "    2. Run a disruption simulation from the dashboard"
echo -e "    3. Monitor the pipeline in the Workflow view"
echo ""
