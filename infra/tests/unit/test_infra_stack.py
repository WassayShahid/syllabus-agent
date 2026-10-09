import json

import aws_cdk as core
import aws_cdk.assertions as assertions
import pytest

from infra.github_oidc_stack import GithubOidcStack
from infra.infra_stack import InfraStack

Match = assertions.Match


@pytest.fixture(scope="module")
def template():
    # skip asset bundling (pip download) in unit tests
    app = core.App(context={"aws:cdk:bundling-stacks": []})
    stack = InfraStack(app, "infra")
    return assertions.Template.from_stack(stack)


def test_table_uses_pk_sk_on_demand_with_user_index(template):
    template.has_resource_properties("AWS::DynamoDB::Table", {
        "KeySchema": [
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        "BillingMode": "PAY_PER_REQUEST",
        "GlobalSecondaryIndexes": [Match.object_like({
            "IndexName": "gsi1",
            "KeySchema": [
                {"AttributeName": "gsi1pk", "KeyType": "HASH"},
                {"AttributeName": "gsi1sk", "KeyType": "RANGE"},
            ],
        })],
    })


def test_bucket_allows_cors_put_and_sends_events_to_eventbridge(template):
    template.has_resource_properties("AWS::S3::Bucket", {
        "CorsConfiguration": {
            "CorsRules": [Match.object_like({"AllowedMethods": ["PUT"]})],
        },
    })
    template.has_resource_properties("Custom::S3BucketNotifications", {
        "NotificationConfiguration": {"EventBridgeConfiguration": {}},
    })


def test_upload_rule_starts_state_machine(template):
    template.has_resource_properties("AWS::Events::Rule", {
        "EventPattern": Match.object_like({
            "source": ["aws.s3"],
            "detail-type": ["Object Created"],
            "detail": Match.object_like({"object": {"key": [{"prefix": "uploads/"}]}}),
        }),
        "Targets": [Match.object_like({"Arn": {"Ref": Match.string_like_regexp("PipelineStateMachine")}})],
    })


def _definition(template):
    sm = template.find_resources("AWS::StepFunctions::StateMachine")
    (resource,) = sm.values()
    parts = resource["Properties"]["DefinitionString"]["Fn::Join"][1]
    # Lambda ARNs are tokens; replace them with placeholders to get parseable JSON
    return json.loads("".join(p if isinstance(p, str) else '"ARN"' for p in parts).replace('""ARN""', '"ARN"'))


def test_pipeline_shape_retries_and_failure_branch(template):
    states = _definition(template)["States"]
    assert states["MarkUploaded"]["Next"] == "ExtractText"
    assert states["ExtractText"]["Next"] == "ExtractAndIndex"
    branches = states["ExtractAndIndex"]["Branches"]
    assert [b["StartAt"] for b in branches] == ["ExtractDeadlines", "IndexChunks"]
    extract = branches[0]["States"]["ExtractDeadlines"]
    assert any("RetryableModelError" in r["ErrorEquals"] for r in extract["Retry"])
    for name in ("MarkUploaded", "ExtractText", "ExtractAndIndex", "Finalize"):
        assert states[name]["Catch"][0]["Next"] == "MarkFailed"
    assert states["MarkFailed"]["Next"] == "PipelineFailed"


def test_routes_exist_and_are_protected(template):
    template.has_resource_properties("AWS::ApiGatewayV2::Route", {
        "RouteKey": "GET /health", "AuthorizationType": "NONE",
    })
    for key in ("POST /uploads", "GET /syllabi", "GET /syllabi/{id}", "DELETE /syllabi/{id}",
                "GET /deadlines", "POST /ask"):
        template.has_resource_properties("AWS::ApiGatewayV2::Route", {"RouteKey": key, "AuthorizationType": "JWT"})


def test_cognito_pool_and_public_client(template):
    template.has_resource_properties("AWS::Cognito::UserPool", {
        "UsernameAttributes": ["email"],
        "AutoVerifiedAttributes": ["email"],
    })
    template.has_resource_properties("AWS::Cognito::UserPoolClient", {"GenerateSecret": False})


def test_llm_lambdas_get_model_and_bedrock_permissions(template):
    template.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "extract_deadlines.handler",
        "Environment": {"Variables": Match.object_like({"MODEL_ID": "global.anthropic.claude-sonnet-4-6"})},
    })
    # inference profile via InvokeModel: profile ARN + base model in any routed region
    template.has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": {"Statement": Match.array_with([
            Match.object_like({
                "Action": "bedrock:InvokeModel",
                "Resource": Match.array_with([
                    "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6",
                    "arn:aws:bedrock:::foundation-model/anthropic.claude-sonnet-4-6",
                ]),
            }),
        ])},
    })


def test_messages_api_models_use_mantle_permission():
    app = core.App(context={"aws:cdk:bundling-stacks": [], "modelId": "anthropic.claude-opus-4-8"})
    template = assertions.Template.from_stack(InfraStack(app, "mantle"))
    template.has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": {"Statement": Match.array_with([
            Match.object_like({"Action": "bedrock-mantle:CreateInference"}),
        ])},
    })


def test_every_lambda_has_an_error_alarm(template):
    functions = template.find_resources("AWS::Lambda::Function", {"Properties": {"Runtime": "python3.12"}})
    alarms = template.find_resources("AWS::CloudWatch::Alarm", {"Properties": {"MetricName": "Errors"}})
    assert len(functions) == 12 and len(alarms) == len(functions)
    template.has_resource_properties("AWS::CloudWatch::Alarm", {"MetricName": "ExecutionsFailed"})


def test_lambdas_get_table_and_bucket_env(template):
    template.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "uploads.handler",
        "Environment": {"Variables": {
            "TABLE_NAME": Match.any_value(),
            "BUCKET_NAME": Match.any_value(),
        }},
    })


def test_github_role_trusts_exact_subjects_in_both_formats():
    app = core.App()
    stack = GithubOidcStack(app, "oidc", repo="me/repo", owner_id=11, repo_id=22)
    assertions.Template.from_stack(stack).has_resource_properties("AWS::IAM::Role", {
        "AssumeRolePolicyDocument": {"Statement": [Match.object_like({
            "Condition": {
                "StringEquals": {
                    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                    "token.actions.githubusercontent.com:sub": [
                        "repo:me/repo:ref:refs/heads/main",
                        "repo:me/repo:environment:production",
                        "repo:me@11/repo@22:ref:refs/heads/main",
                        "repo:me@11/repo@22:environment:production",
                    ],
                },
            },
        })]},
    })
