# =============================================================================
# Supply Chain Ghost — Full Deployment Script (Windows PowerShell)
# =============================================================================
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$ScriptDir = Split-Path -Parent $PSCommandPath

function Log($msg) { Write-Host "[SCG] $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "[OK] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Err($msg) { Write-Host "[X] $msg" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
Log "Starting Supply Chain Ghost deployment..."

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) { Err "AWS CLI not found. Install: https://aws.amazon.com/cli/" }
if (-not (Get-Command cdk -ErrorAction SilentlyContinue)) { Err "AWS CDK CLI not found. Run: npm install -g aws-cdk" }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Err "Node.js not found. Install from https://nodejs.org/" }

# Verify AWS credentials
try {
    $CallerIdentity = aws sts get-caller-identity --output json | ConvertFrom-Json
    $AwsAccount = $CallerIdentity.Account
}
catch {
    Err "AWS credentials not configured. Set environment variables or AWS profile first."
}

$AwsRegion = if ($env:AWS_REGION) { $env:AWS_REGION } else { "us-east-1" }
Log "Account: $AwsAccount | Region: $AwsRegion"

# ---------------------------------------------------------------------------
# Step 1: Activate venv & install Python dependencies
# ---------------------------------------------------------------------------
Log "Installing Python dependencies..."
Push-Location $ProjectRoot

if (-not (Test-Path "venv\Scripts\activate.ps1")) {
    Log "Creating virtual environment..."
    python -m venv venv
}

& venv\Scripts\activate.ps1

# Install core deps (skip nova-act and strands if unavailable)
pip install boto3 botocore aws-cdk-lib constructs requests feedparser beautifulsoup4 python-dateutil python-dotenv pydantic tenacity structlog Pillow --quiet 2>$null
pip install strands-agents strands-agents-tools --quiet 2>$null
pip install nova-act --quiet 2>$null
Ok "Python dependencies installed"

# ---------------------------------------------------------------------------
# Step 2: CDK Bootstrap
# ---------------------------------------------------------------------------
Log "Bootstrapping CDK environment..."
Push-Location "$ProjectRoot\infra"

$env:CDK_DEFAULT_ACCOUNT = $AwsAccount
$env:CDK_DEFAULT_REGION = $AwsRegion

try {
    cdk bootstrap "aws://$AwsAccount/$AwsRegion" 2>$null
    Ok "CDK bootstrapped"
}
catch {
    Warn "CDK bootstrap skipped (may already be bootstrapped)"
}

# ---------------------------------------------------------------------------
# Step 3: CDK Synth
# ---------------------------------------------------------------------------
Log "Synthesizing CloudFormation templates..."
try {
    cdk synth --quiet
    Ok "Templates synthesized"
}
catch {
    Err "CDK synth failed. Check stack code for errors: $_"
}

# ---------------------------------------------------------------------------
# Step 4: CDK Deploy All Stacks
# ---------------------------------------------------------------------------
Log "Deploying all stacks (this takes 15-25 minutes)..."
cdk deploy --all `
    --require-approval never `
    --outputs-file "$ProjectRoot\cdk-outputs.json" `
    --context "account=$AwsAccount" `
    --context "region=$AwsRegion"

Ok "All CDK stacks deployed!"

# ---------------------------------------------------------------------------
# Step 5: Extract outputs
# ---------------------------------------------------------------------------
Log "Extracting deployment outputs..."
$Outputs = @{}
if (Test-Path "$ProjectRoot\cdk-outputs.json") {
    $CdkOutputs = Get-Content "$ProjectRoot\cdk-outputs.json" | ConvertFrom-Json
    foreach ($stack in $CdkOutputs.PSObject.Properties) {
        foreach ($output in $stack.Value.PSObject.Properties) {
            $Outputs[$output.Name] = $output.Value
        }
    }
    
    $UserPoolId = ($Outputs.GetEnumerator() | Where-Object { $_.Key -match "UserPoolId" } | Select-Object -First 1).Value
    $ClientId = ($Outputs.GetEnumerator() | Where-Object { $_.Key -match "ClientId" } | Select-Object -First 1).Value
    $ApiUrl = ($Outputs.GetEnumerator() | Where-Object { $_.Key -match "ApiUrl|RestApiEndpoint" } | Select-Object -First 1).Value
    $CfDomain = ($Outputs.GetEnumerator() | Where-Object { $_.Key -match "Distribution|CloudFront" } | Select-Object -First 1).Value

    Log "User Pool ID:  $UserPoolId"
    Log "Client ID:     $ClientId"
    Log "API URL:       $ApiUrl"
    Log "CloudFront:    $CfDomain"
}

# ---------------------------------------------------------------------------
# Step 6: Build & Deploy Frontend
# ---------------------------------------------------------------------------
Log "Building React frontend..."
Push-Location "$ProjectRoot\frontend"
npm install --legacy-peer-deps

# Write .env for React build
@"
REACT_APP_USER_POOL_ID=$UserPoolId
REACT_APP_USER_POOL_CLIENT_ID=$ClientId
REACT_APP_API_URL=$ApiUrl
REACT_APP_REGION=$AwsRegion
"@ | Out-File -Encoding utf8 .env

npm run build
Ok "Frontend built"

# Upload to S3
try {
    $DashboardBucket = (aws cloudformation describe-stacks `
            --stack-name "SupplyChainGhost-Dashboard" `
            --query "Stacks[0].Outputs[?contains(OutputKey,'Bucket')].OutputValue" `
            --output text 2>$null)
    
    if ($DashboardBucket) {
        Log "Deploying frontend to S3: $DashboardBucket"
        aws s3 sync build/ "s3://$DashboardBucket/" --delete --cache-control "max-age=31536000,public"
        aws s3 cp build/index.html "s3://$DashboardBucket/index.html" --cache-control "no-cache"
        Ok "Frontend deployed to S3"
    }
}
catch {
    Warn "Could not deploy frontend to S3. Deploy manually later."
}

Pop-Location

# ---------------------------------------------------------------------------
# Step 7: Create admin user
# ---------------------------------------------------------------------------
Log "Creating admin user in Cognito..."
$AdminEmail = if ($env:ADMIN_EMAIL) { $env:ADMIN_EMAIL } else { "admin@supplychain-ghost.com" }
$AdminPass = if ($env:ADMIN_PASS) { $env:ADMIN_PASS } else { 'GhostSecure123!' }

if ($UserPoolId) {
    try {
        aws cognito-idp admin-create-user `
            --user-pool-id $UserPoolId `
            --username $AdminEmail `
            --user-attributes "Name=email,Value=$AdminEmail" "Name=email_verified,Value=true" `
            --temporary-password $AdminPass `
            --message-action SUPPRESS 2>$null
        
        aws cognito-idp admin-add-user-to-group `
            --user-pool-id $UserPoolId `
            --username $AdminEmail `
            --group-name SCGAdmins 2>$null
        
        Ok "Admin user created: $AdminEmail"
    }
    catch {
        Warn "Admin user may already exist"
    }
}

# ---------------------------------------------------------------------------
# Step 8: Seed Knowledge Base
# ---------------------------------------------------------------------------
Log "Seeding Knowledge Base..."
try {
    python "$ScriptDir\seed_knowledge_base.py"
    Ok "Knowledge base seeded"
}
catch {
    Warn "Knowledge base seeding skipped"
}

Pop-Location  # back to project root

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Supply Chain Ghost — Deployment Complete!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Dashboard:  https://$CfDomain" -ForegroundColor Cyan
Write-Host "  API:        $ApiUrl" -ForegroundColor Cyan
Write-Host "  Admin:      $AdminEmail / (temporary password)" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor White
Write-Host "    1. Log in and change the temporary password"
Write-Host "    2. Run a disruption simulation from the dashboard"
Write-Host "    3. Watch the pipeline in the Workflow view"
Write-Host ""
