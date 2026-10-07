from aws_cdk import Stack, CfnOutput, Duration, RemovalPolicy
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk.aws_apigatewayv2_integrations import HttpLambdaIntegration
from constructs import Construct


class InfraStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Private bucket where syllabus PDFs will be uploaded
        uploads = s3.Bucket(
            self, "UploadsBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,   # fine for a dev project
            auto_delete_objects=True,
        )

        # Health-check Lambda
        health_fn = _lambda.Function(
            self, "HealthFn",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="health.handler",
            code=_lambda.Code.from_asset("../backend/health"),
            timeout=Duration.seconds(10),
        )

        # HTTP API -> Lambda
        api = apigw.HttpApi(self, "SyllabusApi")
        api.add_routes(
            path="/health",
            methods=[apigw.HttpMethod.GET],
            integration=HttpLambdaIntegration("HealthIntegration", health_fn),
        )

        CfnOutput(self, "ApiUrl", value=api.url)
        CfnOutput(self, "UploadsBucketName", value=uploads.bucket_name)