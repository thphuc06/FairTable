# Starts the web app against the deployed AWS stacks so that the voice page (/voice) works.
# Reads every setting from the CloudFormation outputs; nothing account-specific is stored here.
#   .\scripts\voice_demo.ps1 -Profile <aws-profile>            # start the web app
#   .\scripts\voice_demo.ps1 -Profile <aws-profile> -NoStart   # only check the settings
param(
    [string]$Profile = $env:AWS_PROFILE,
    [string]$Region = "us-east-1",
    [string]$Python = "python",
    [switch]$NoStart
)
$ErrorActionPreference = "Stop"
if (-not $Profile) { throw "Pass -Profile <aws-profile> (or set AWS_PROFILE). Run 'aws login --profile <aws-profile>' first." }
$env:AWS_PROFILE = $Profile
$env:AWS_REGION = $Region

function Get-StackOutput($stack, $key) {
    $value = aws cloudformation describe-stacks --stack-name $stack --query "Stacks[0].Outputs[?OutputKey=='$key'].OutputValue" --output text
    if ($LASTEXITCODE -ne 0 -or -not $value -or $value -eq "None") { throw "Could not read output $key of stack $stack (is the profile logged in and the stack deployed?)" }
    return $value.Trim()
}

$pool = Get-StackOutput FairTableIdentity UserPoolId
$env:AUTH_PROVIDER = "cognito"
$env:AUTH_TOKEN_USE = "access"
$env:AUTH_AUDIENCE_CLAIM = "client_id"
$env:AUTH_ISSUER = Get-StackOutput FairTableIdentity Issuer
$env:COGNITO_CLIENT_ID = Get-StackOutput FairTableIdentity ClientIdAlexaPlusSim
$env:COGNITO_CLIENT_SECRET = (aws cognito-idp describe-user-pool-client --user-pool-id $pool --client-id $env:COGNITO_CLIENT_ID --query UserPoolClient.ClientSecret --output text).Trim()
$env:AUTH_AUDIENCE = ((aws cognito-idp list-user-pool-clients --user-pool-id $pool --query "UserPoolClients[].ClientId" --output text) -replace "\s+", ",").Trim()
$env:MCP_URL = Get-StackOutput FairTableGateway GatewayUrl
$env:MCP_VIA_GATEWAY = "true"
$env:TABLE_NAME = "fairtable"
$env:VOICE_ENABLED = "true"

$account = (aws sts get-caller-identity --query Account --output text).Trim()
Write-Host ("Profile {0}, account ending {1}, region {2}" -f $Profile, $account.Substring($account.Length - 4), $Region)
Write-Host ("Gateway: {0}" -f $env:MCP_URL)
if ($NoStart) { Write-Host "Settings read. -NoStart given, the web app is not started."; return }
Write-Host "Starting the web app. Open http://localhost:8080/voice (sign in as diner-alice / alice-dev-pass)."
& $Python -m web
