#!/usr/bin/env bash
# Starts the web app against the deployed AWS stacks so that the voice page (/voice) works.
# Reads every setting from the CloudFormation outputs; nothing account-specific is stored here.
#   AWS_PROFILE=<aws-profile> bash scripts/voice_demo.sh            # start the web app
#   AWS_PROFILE=<aws-profile> bash scripts/voice_demo.sh --no-start # only check the settings
set -euo pipefail
: "${AWS_PROFILE:?Set AWS_PROFILE=<aws-profile> (run 'aws login --profile <aws-profile>' first)}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
PYTHON="${PYTHON:-python}"

out() {
  local value
  value=$(aws cloudformation describe-stacks --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text)
  if [ -z "$value" ] || [ "$value" = "None" ]; then
    echo "Could not read output $2 of stack $1 (is the profile logged in and the stack deployed?)" >&2
    exit 1
  fi
  printf '%s' "$value"
}

POOL=$(out FairTableIdentity UserPoolId)
export AUTH_PROVIDER=cognito AUTH_TOKEN_USE=access AUTH_AUDIENCE_CLAIM=client_id
AUTH_ISSUER=$(out FairTableIdentity Issuer); export AUTH_ISSUER
COGNITO_CLIENT_ID=$(out FairTableIdentity ClientIdAlexaPlusSim); export COGNITO_CLIENT_ID
COGNITO_CLIENT_SECRET=$(aws cognito-idp describe-user-pool-client --user-pool-id "$POOL" \
  --client-id "$COGNITO_CLIENT_ID" --query UserPoolClient.ClientSecret --output text); export COGNITO_CLIENT_SECRET
AUTH_AUDIENCE=$(aws cognito-idp list-user-pool-clients --user-pool-id "$POOL" \
  --query "UserPoolClients[].ClientId" --output text | tr '\t' ','); export AUTH_AUDIENCE
MCP_URL=$(out FairTableGateway GatewayUrl); export MCP_URL
export MCP_VIA_GATEWAY=true TABLE_NAME=fairtable VOICE_ENABLED=true

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
echo "Profile $AWS_PROFILE, account ending ${ACCOUNT: -4}, region $AWS_REGION"
echo "Gateway: $MCP_URL"
if [ "${1:-}" = "--no-start" ]; then echo "Settings read. --no-start given, the web app is not started."; exit 0; fi
echo "Starting the web app. Open http://localhost:8080/voice (sign in as diner-alice / alice-dev-pass)."
exec "$PYTHON" -m web
