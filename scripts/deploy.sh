#!/usr/bin/env bash
set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-deja}"
AWS_REGION="${AWS_REGION:-ap-south-1}"
FUNCTION_NAME="${FUNCTION_NAME:-deja-api}"
ECR_REPOSITORY="${ECR_REPOSITORY:-deja}"
ROLE_NAME="${ROLE_NAME:-deja-lambda-role}"
GROQ_MODEL="${GROQ_MODEL:-llama-3.3-70b-versatile}"
VOYAGE_MODEL="${VOYAGE_MODEL:-voyage-4-lite}"
FUNCTION_TIMEOUT="${FUNCTION_TIMEOUT:-90}"
EXECUTION_LEASE_SECONDS="${EXECUTION_LEASE_SECONDS:-$FUNCTION_TIMEOUT}"
DEJA_CHAOS_ENABLED="${DEJA_CHAOS_ENABLED:-false}"
ASYNC_MAX_EVENT_AGE="${ASYNC_MAX_EVENT_AGE:-3600}"
ASYNC_MAX_RETRIES="${ASYNC_MAX_RETRIES:-2}"

if ! test -n "${DATABASE_URL:-}"; then
  echo "DATABASE_URL is required" >&2
  exit 1
fi
if ! test -n "${GROQ_API_KEY:-}"; then
  echo "GROQ_API_KEY is required" >&2
  exit 1
fi
if ! test -n "${VOYAGE_API_KEY:-}"; then
  echo "VOYAGE_API_KEY is required" >&2
  exit 1
fi

for command in aws docker git; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "$command is required" >&2
    exit 1
  fi
done

ACCOUNT_ID="$(AWS_PROFILE="$AWS_PROFILE" aws sts get-caller-identity --query Account --output text)"
IMAGE_TAG="release-$(date -u +%Y%m%d%H%M%S)"
IMAGE_URI="$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPOSITORY:$IMAGE_TAG"

if ! AWS_PROFILE="$AWS_PROFILE" aws ecr describe-repositories \
  --region "$AWS_REGION" \
  --repository-names "$ECR_REPOSITORY" >/dev/null 2>&1; then
  AWS_PROFILE="$AWS_PROFILE" aws ecr create-repository \
    --region "$AWS_REGION" \
    --repository-name "$ECR_REPOSITORY" \
    --image-scanning-configuration scanOnPush=true >/dev/null
fi

ECR_PASSWORD="$(AWS_PROFILE="$AWS_PROFILE" aws ecr get-login-password --region "$AWS_REGION")"
ECR_AUTH="$(printf 'AWS:%s' "$ECR_PASSWORD" | base64 -w0)"
export DOCKER_AUTH_CONFIG="{\"auths\":{\"$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com\":{\"auth\":\"$ECR_AUTH\"}}}"
unset ECR_PASSWORD ECR_AUTH

docker build --platform linux/amd64 -t "$IMAGE_URI" .
docker push "$IMAGE_URI" >/dev/null

if ! AWS_PROFILE="$AWS_PROFILE" aws iam get-role \
  --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  AWS_PROFILE="$AWS_PROFILE" aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document file://deploy/lambda-trust-policy.json >/dev/null
  AWS_PROFILE="$AWS_PROFILE" aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  AWS_PROFILE="$AWS_PROFILE" aws iam wait role-exists --role-name "$ROLE_NAME"
  sleep 10
fi

ROLE_ARN="$(AWS_PROFILE="$AWS_PROFILE" aws iam get-role \
  --role-name "$ROLE_NAME" --query Role.Arn --output text)"
FUNCTION_ARN="arn:aws:lambda:$AWS_REGION:$ACCOUNT_ID:function:$FUNCTION_NAME"
SELF_INVOKE_POLICY="{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"lambda:InvokeFunction\",\"Resource\":\"$FUNCTION_ARN\"}]}"
AWS_PROFILE="$AWS_PROFILE" aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name deja-self-invoke \
  --policy-document "$SELF_INVOKE_POLICY"
ENVIRONMENT="Variables={DATABASE_URL=$DATABASE_URL,DATABASE_CA_CERT=/var/task/certs/cockroach-cloud-root.crt,GROQ_API_KEY=$GROQ_API_KEY,GROQ_MODEL=$GROQ_MODEL,VOYAGE_API_KEY=$VOYAGE_API_KEY,VOYAGE_MODEL=$VOYAGE_MODEL,EXECUTION_LEASE_SECONDS=$EXECUTION_LEASE_SECONDS,DEJA_CHAOS_ENABLED=$DEJA_CHAOS_ENABLED}"

if AWS_PROFILE="$AWS_PROFILE" aws lambda get-function \
  --region "$AWS_REGION" \
  --function-name "$FUNCTION_NAME" >/dev/null 2>&1; then
  AWS_PROFILE="$AWS_PROFILE" aws lambda update-function-configuration \
    --region "$AWS_REGION" \
    --function-name "$FUNCTION_NAME" \
    --timeout "$FUNCTION_TIMEOUT" \
    --memory-size 1024 \
    --environment "$ENVIRONMENT" >/dev/null
  AWS_PROFILE="$AWS_PROFILE" aws lambda wait function-updated-v2 \
    --region "$AWS_REGION" \
    --function-name "$FUNCTION_NAME"
  AWS_PROFILE="$AWS_PROFILE" aws lambda update-function-code \
    --region "$AWS_REGION" \
    --function-name "$FUNCTION_NAME" \
    --image-uri "$IMAGE_URI" >/dev/null
  AWS_PROFILE="$AWS_PROFILE" aws lambda wait function-updated-v2 \
    --region "$AWS_REGION" \
    --function-name "$FUNCTION_NAME"
else
  AWS_PROFILE="$AWS_PROFILE" aws lambda create-function \
    --region "$AWS_REGION" \
    --function-name "$FUNCTION_NAME" \
    --package-type Image \
    --code "ImageUri=$IMAGE_URI" \
    --role "$ROLE_ARN" \
    --architectures x86_64 \
    --timeout "$FUNCTION_TIMEOUT" \
    --memory-size 1024 \
    --environment "$ENVIRONMENT" >/dev/null
fi

AWS_PROFILE="$AWS_PROFILE" aws lambda wait function-active-v2 \
  --region "$AWS_REGION" \
  --function-name "$FUNCTION_NAME"

if AWS_PROFILE="$AWS_PROFILE" aws lambda get-function-event-invoke-config \
  --region "$AWS_REGION" \
  --function-name "$FUNCTION_NAME" >/dev/null 2>&1; then
  AWS_PROFILE="$AWS_PROFILE" aws lambda update-function-event-invoke-config \
    --region "$AWS_REGION" \
    --function-name "$FUNCTION_NAME" \
    --maximum-event-age-in-seconds "$ASYNC_MAX_EVENT_AGE" \
    --maximum-retry-attempts "$ASYNC_MAX_RETRIES" >/dev/null
else
  AWS_PROFILE="$AWS_PROFILE" aws lambda put-function-event-invoke-config \
    --region "$AWS_REGION" \
    --function-name "$FUNCTION_NAME" \
    --maximum-event-age-in-seconds "$ASYNC_MAX_EVENT_AGE" \
    --maximum-retry-attempts "$ASYNC_MAX_RETRIES" >/dev/null
fi

if ! AWS_PROFILE="$AWS_PROFILE" aws lambda get-function-url-config \
  --region "$AWS_REGION" \
  --function-name "$FUNCTION_NAME" >/dev/null 2>&1; then
  AWS_PROFILE="$AWS_PROFILE" aws lambda create-function-url-config \
    --region "$AWS_REGION" \
    --function-name "$FUNCTION_NAME" \
    --auth-type AWS_IAM >/dev/null
fi

AWS_PROFILE="$AWS_PROFILE" aws lambda get-function-url-config \
  --region "$AWS_REGION" \
  --function-name "$FUNCTION_NAME" \
  --query FunctionUrl \
  --output text
