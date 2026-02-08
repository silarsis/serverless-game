#!/bin/bash
# LocalStack initialization script
# This runs automatically when LocalStack starts

set -e

export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=ap-southeast-1
export AWS_PAGER=""

# Use LocalStack endpoint
LOCALSTACK_ENDPOINT="http://localhost:4566"

echo "Initializing LocalStack resources for serverless-game..."

# Wait for LocalStack to be ready
echo "Waiting for LocalStack to be ready..."
until aws --endpoint-url=$LOCALSTACK_ENDPOINT dynamodb list-tables > /dev/null 2>&1; do
    echo "Waiting for DynamoDB..."
    sleep 2
done

echo "Creating DynamoDB tables..."

# Entity Table (central table for all game objects)
aws --endpoint-url=$LOCALSTACK_ENDPOINT dynamodb create-table \
    --table-name entity-table-local \
    --attribute-definitions AttributeName=uuid,AttributeType=S AttributeName=location,AttributeType=S \
    --key-schema AttributeName=uuid,KeyType=HASH \
    --global-secondary-indexes \
        "IndexName=contents,KeySchema=[{AttributeName=location,KeyType=HASH},{AttributeName=uuid,KeyType=RANGE}],Projection={ProjectionType=KEYS_ONLY},ProvisionedThroughput={ReadCapacityUnits=5,WriteCapacityUnits=5}" \
    --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5 \
    --region ap-southeast-1 2>/dev/null || echo "entity-table-local already exists"

# Thing Table (legacy, kept for backward compatibility)
aws --endpoint-url=$LOCALSTACK_ENDPOINT dynamodb create-table \
    --table-name thing-table-local \
    --attribute-definitions AttributeName=uuid,AttributeType=S \
    --key-schema AttributeName=uuid,KeyType=HASH \
    --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5 \
    --region ap-southeast-1 2>/dev/null || echo "thing-table-local already exists"

# Location Table
aws --endpoint-url=$LOCALSTACK_ENDPOINT dynamodb create-table \
    --table-name location-table-local \
    --attribute-definitions AttributeName=uuid,AttributeType=S AttributeName=location,AttributeType=S \
    --key-schema AttributeName=uuid,KeyType=HASH \
    --global-secondary-indexes \
        "IndexName=contents,KeySchema=[{AttributeName=location,KeyType=HASH},{AttributeName=uuid,KeyType=RANGE}],Projection={ProjectionType=KEYS_ONLY},ProvisionedThroughput={ReadCapacityUnits=5,WriteCapacityUnits=5}" \
    --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5 \
    --region ap-southeast-1 2>/dev/null || echo "location-table-local already exists"

# Land Table
aws --endpoint-url=$LOCALSTACK_ENDPOINT dynamodb create-table \
    --table-name land-table-local \
    --attribute-definitions AttributeName=uuid,AttributeType=S AttributeName=location,AttributeType=S AttributeName=coordinates,AttributeType=S \
    --key-schema AttributeName=uuid,KeyType=HASH \
    --global-secondary-indexes \
        "IndexName=contents,KeySchema=[{AttributeName=location,KeyType=HASH},{AttributeName=uuid,KeyType=RANGE}],Projection={ProjectionType=KEYS_ONLY},ProvisionedThroughput={ReadCapacityUnits=5,WriteCapacityUnits=5}" \
        "IndexName=cartesian,KeySchema=[{AttributeName=coordinates,KeyType=HASH},{AttributeName=uuid,KeyType=RANGE}],Projection={ProjectionType=KEYS_ONLY},ProvisionedThroughput={ReadCapacityUnits=5,WriteCapacityUnits=5}" \
    --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5 \
    --region ap-southeast-1 2>/dev/null || echo "land-table-local already exists"

# Users Table
aws --endpoint-url=$LOCALSTACK_ENDPOINT dynamodb create-table \
    --table-name users-local \
    --attribute-definitions AttributeName=google_uid,AttributeType=S \
    --key-schema AttributeName=google_uid,KeyType=HASH \
    --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5 \
    --region ap-southeast-1 2>/dev/null || echo "users-local already exists"

# API Keys Table
aws --endpoint-url=$LOCALSTACK_ENDPOINT dynamodb create-table \
    --table-name api-keys-local \
    --attribute-definitions AttributeName=api_key,AttributeType=S AttributeName=google_uid,AttributeType=S \
    --key-schema AttributeName=api_key,KeyType=HASH \
    --global-secondary-indexes \
        "IndexName=by-user,KeySchema=[{AttributeName=google_uid,KeyType=HASH},{AttributeName=api_key,KeyType=RANGE}],Projection={ProjectionType=ALL},ProvisionedThroughput={ReadCapacityUnits=5,WriteCapacityUnits=5}" \
    --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5 \
    --region ap-southeast-1 2>/dev/null || echo "api-keys-local already exists"

# Suggestion Table
aws --endpoint-url=$LOCALSTACK_ENDPOINT dynamodb create-table \
    --table-name suggestion-table-local \
    --attribute-definitions AttributeName=uuid,AttributeType=S \
    --key-schema AttributeName=uuid,KeyType=HASH \
    --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5 \
    --region ap-southeast-1 2>/dev/null || echo "suggestion-table-local already exists"

echo "Creating SNS topic..."
THING_TOPIC_ARN=$(aws --endpoint-url=$LOCALSTACK_ENDPOINT sns create-topic \
    --name thing-topic-local \
    --region ap-southeast-1 \
    --query 'TopicArn' --output text 2>/dev/null || echo "arn:aws:sns:ap-southeast-1:000000000000:thing-topic-local")

echo "Creating IAM role for Step Functions..."
TRUST_POLICY='{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "states.ap-southeast-1.amazonaws.com"
            },
            "Action": "sts:AssumeRole"
        }
    ]
}'

aws --endpoint-url=$LOCALSTACK_ENDPOINT iam create-role \
    --role-name stepfunctions-service-role \
    --assume-role-policy-document "$TRUST_POLICY" \
    --region ap-southeast-1 2>/dev/null || echo "stepfunctions-service-role already exists"

echo "Attaching policies to IAM role..."
aws --endpoint-url=$LOCALSTACK_ENDPOINT iam attach-role-policy \
    --role-name stepfunctions-service-role \
    --policy-arn arn:aws:iam::aws:policy/AWSStepFunctionsFullAccess \
    --region ap-southeast-1 2>/dev/null || true

# Create inline policy for SNS publish
SNS_POLICY='{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "sns:Publish",
            "Resource": "*"
        }
    ]
}'

aws --endpoint-url=$LOCALSTACK_ENDPOINT iam put-role-policy \
    --role-name stepfunctions-service-role \
    --policy-name SNSPublishPolicy \
    --policy-document "$SNS_POLICY" \
    --region ap-southeast-1 2>/dev/null || true

echo "Creating Step Functions state machine for message delay..."

SFN_DEFINITION=$(cat <<EOF
{
    "StartAt": "Delay",
    "Comment": "Publish to SNS with delay",
    "States": {
        "Delay": {
            "Type": "Wait",
            "SecondsPath": "\$.delay_seconds",
            "Next": "Publish to SNS"
        },
        "Publish to SNS": {
            "Type": "Task",
            "Resource": "arn:aws:states:::sns:publish",
            "Parameters": {
                "TopicArn": "${THING_TOPIC_ARN}",
                "Message.\$": "\$.data",
                "MessageAttributes": {
                    "aspect": {
                        "DataType": "String",
                        "StringValue.\$": "\$.data.aspect"
                    },
                    "action": {
                        "DataType": "String",
                        "StringValue.\$": "\$.data.action"
                    },
                    "uuid": {
                        "DataType": "String",
                        "StringValue.\$": "\$.data.uuid"
                    }
                }
            },
            "End": true
        }
    }
}
EOF
)

ROLE_ARN="arn:aws:iam::000000000000:role/stepfunctions-service-role"

aws --endpoint-url=$LOCALSTACK_ENDPOINT stepfunctions create-state-machine \
    --name message-delayer-local \
    --definition "$SFN_DEFINITION" \
    --role-arn "$ROLE_ARN" \
    --region ap-southeast-1 2>/dev/null || echo "message-delayer-local already exists"

echo ""
echo "=============================================="
echo "LocalStack initialization complete!"
echo "=============================================="
echo ""
echo "Resource ARNs (for local development):"
echo "----------------------------------------------"
echo "DynamoDB Tables:"
echo "  - entity-table-local"
echo "  - thing-table-local"
echo "  - location-table-local"
echo "  - land-table-local"
echo "  - users-local"
echo "  - api-keys-local"
echo "  - suggestion-table-local"
echo ""
echo "SNS Topic ARN:"
echo "  $THING_TOPIC_ARN"
echo ""
echo "Step Functions State Machine:"
echo "  arn:aws:states:ap-southeast-1:000000000000:stateMachine:message-delayer-local"
echo ""
echo "LocalStack Endpoint: http://localhost:4566"
echo "=============================================="
