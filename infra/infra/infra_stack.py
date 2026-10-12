from aws_cdk import Stack, CfnOutput, Duration, RemovalPolicy
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_ses as ses
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from aws_cdk.aws_apigatewayv2_authorizers import HttpUserPoolAuthorizer
from aws_cdk.aws_apigatewayv2_integrations import HttpLambdaIntegration
from constructs import Construct

from infra.bundling import RUNTIME, backend_code

DEFAULT_MODEL_ID = "global.anthropic.claude-sonnet-4-6"
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
METRICS_NAMESPACE = "SyllabusAgent"


class InfraStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        model_id = self.node.try_get_context("modelId") or DEFAULT_MODEL_ID
        alarm_email = self.node.try_get_context("alarmEmail")
        allowed_origins = self.node.try_get_context("allowedOrigins") or ["*"]
        # Email reminders are off unless a sender address is given (AWS emails it a verification link)
        notify_from = self.node.try_get_context("notifyFromEmail")
        ses_sandbox = str(self.node.try_get_context("sesSandbox") or "true").lower()
        app_url = self.node.try_get_context("appUrl") or ""

        # ---------------- storage ----------------
        # Private bucket: uploads/<id>.pdf from the browser, text/<id>.json from the pipeline
        uploads = s3.Bucket(
            self, "UploadsBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            event_bridge_enabled=True,              # Object Created -> EventBridge -> Step Functions
            removal_policy=RemovalPolicy.DESTROY,   # fine for a dev project
            auto_delete_objects=True,
            # browsers PUT directly to S3 with presigned URLs
            cors=[s3.CorsRule(
                allowed_methods=[s3.HttpMethods.PUT],
                allowed_origins=allowed_origins,
                allowed_headers=["*"],
                max_age=3000,
            )],
        )

        # Single table for syllabi, deadlines and text chunks (pk/sk design, see backend/src/lib/db.py)
        table = dynamodb.Table(
            self, "SyllabusTable",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,   # fine for a dev project
        )
        table.add_global_secondary_index(
            index_name="gsi1",
            partition_key=dynamodb.Attribute(name="gsi1pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="gsi1sk", type=dynamodb.AttributeType.STRING),
        )

        # ---------------- auth ----------------
        user_pool = cognito.UserPool(
            self, "UserPool",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            password_policy=cognito.PasswordPolicy(min_length=8, require_symbols=False),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=RemovalPolicy.DESTROY,
        )
        web_client = user_pool.add_client(
            "WebClient",
            auth_flows=cognito.AuthFlow(user_srp=True),
            generate_secret=False,
            prevent_user_existence_errors=True,
        )

        # ---------------- lambdas ----------------
        code = backend_code()
        common_env = {"TABLE_NAME": table.table_name, "BUCKET_NAME": uploads.bucket_name}
        self.functions = {}

        def fn(name, handler, timeout=30, memory=512, env=None):
            f = _lambda.Function(
                self, name,
                runtime=RUNTIME,
                handler=handler,
                code=code,
                timeout=Duration.seconds(timeout),
                memory_size=memory,
                environment={**common_env, **(env or {})},
                tracing=_lambda.Tracing.ACTIVE,
            )
            self.functions[name] = f
            return f

        if model_id.startswith("anthropic."):
            claude = iam.PolicyStatement(
                # Claude in Amazon Bedrock (Messages API endpoint, Opus 4.7 and later)
                actions=["bedrock-mantle:CreateInference"],
                resources=["*"],
            )
        else:
            # Cross-region inference profile (e.g. global.anthropic.claude-sonnet-4-6) via InvokeModel:
            # needs the profile plus the base model in whichever region the request is routed to.
            base_model = model_id.split(".", 1)[1]
            claude = iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[
                    f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/{model_id}",
                    f"arn:aws:bedrock:*::foundation-model/{base_model}",
                    f"arn:aws:bedrock:::foundation-model/{base_model}",
                ],
            )
        titan = iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=[f"arn:aws:bedrock:{self.region}::foundation-model/{EMBEDDING_MODEL_ID}"],
        )
        llm_env = {"MODEL_ID": model_id}

        health_fn = fn("HealthFn", "health.handler", timeout=10)

        # POST /uploads -> registers a syllabus and returns a presigned PUT URL
        uploads_fn = fn("UploadsFn", "uploads.handler", timeout=10)
        uploads.grant_put(uploads_fn, "uploads/*")
        table.grant_write_data(uploads_fn)

        # GET /syllabi, GET|DELETE /syllabi/{id}, GET /deadlines
        notify_env = {"NOTIFY_FROM_EMAIL": notify_from or "", "SES_SANDBOX": ses_sandbox, "APP_URL": app_url,
                      "NOTIFY_TIMEZONE": "America/Toronto"}
        send_email = iam.PolicyStatement(
            actions=["ses:SendEmail"],
            resources=[f"arn:aws:ses:{self.region}:{self.account}:identity/*"],
        )

        # syllabi, deadline edits, reminder settings
        api_fn = fn("ApiFn", "api.handler", timeout=15, env=notify_env)
        table.grant_read_write_data(api_fn)
        uploads.grant_delete(api_fn, "uploads/*")
        uploads.grant_delete(api_fn, "text/*")
        api_fn.add_to_role_policy(send_email)           # "send test email"
        api_fn.add_to_role_policy(iam.PolicyStatement(  # sandbox: ask AWS to verify a recipient
            actions=["ses:VerifyEmailIdentity", "ses:GetIdentityVerificationAttributes"],
            resources=["*"],
        ))

        if notify_from:
            ses.EmailIdentity(self, "NotifySender", identity=ses.Identity.email(notify_from))
            notify_fn = fn("NotifyDailyFn", "notify_daily.handler", timeout=300, env=notify_env)
            table.grant_read_data(notify_fn)
            notify_fn.add_to_role_policy(send_email)
            events.Rule(
                self, "DailyReminderSchedule",
                schedule=events.Schedule.cron(minute="0", hour="12"),   # 12:00 UTC = 7-8 am Toronto
                targets=[targets.LambdaFunction(notify_fn)],
            )

        # POST /ask -> tool-using agent (API Gateway caps integrations at 30 s)
        ask_fn = fn("AskFn", "ask.handler", timeout=29, memory=1024, env=llm_env)
        table.grant_read_data(ask_fn)
        ask_fn.add_to_role_policy(claude)
        ask_fn.add_to_role_policy(titan)

        # ---------------- pipeline: one Lambda per stage ----------------
        mark_uploaded_fn = fn("MarkUploadedFn", "mark_uploaded.handler", timeout=10)
        table.grant_read_write_data(mark_uploaded_fn)

        extract_text_fn = fn("ExtractTextFn", "extract_text.handler", timeout=120, memory=1024)
        uploads.grant_read(extract_text_fn, "uploads/*")
        uploads.grant_put(extract_text_fn, "text/*")

        extract_deadlines_fn = fn("ExtractDeadlinesFn", "extract_deadlines.handler",
                                  timeout=300, memory=1024, env=llm_env)
        uploads.grant_read(extract_deadlines_fn, "text/*")
        extract_deadlines_fn.add_to_role_policy(claude)

        validate_fn = fn("ValidateFn", "validate.handler", timeout=10)

        save_fn = fn("SaveDeadlinesFn", "save_deadlines.handler", timeout=30)
        table.grant_read_write_data(save_fn)

        index_fn = fn("IndexChunksFn", "index_chunks.handler", timeout=300, memory=1024)
        uploads.grant_read(index_fn, "text/*")
        table.grant_read_write_data(index_fn)
        index_fn.add_to_role_policy(titan)

        finalize_fn = fn("FinalizeFn", "finalize.handler", timeout=10)
        table.grant_write_data(finalize_fn)

        mark_failed_fn = fn("MarkFailedFn", "mark_failed.handler", timeout=10)
        table.grant_write_data(mark_failed_fn)

        # ---------------- state machine ----------------
        def step(name, f, result_path):
            task = tasks.LambdaInvoke(self, name, lambda_function=f, payload_response_only=True,
                                      result_path=result_path)
            # transient model trouble: back off and try again (Lambda service errors are retried by default)
            task.add_retry(errors=["RetryableModelError", "ExtractionFormatError"],
                           interval=Duration.seconds(5), max_attempts=3, backoff_rate=2.0)
            return task

        failed = (
            tasks.LambdaInvoke(self, "MarkFailed", lambda_function=mark_failed_fn,
                               payload_response_only=True, result_path="$.failure")
            .next(sfn.Fail(self, "PipelineFailed", error="SyllabusProcessingFailed"))
        )

        mark_uploaded = step("MarkUploaded", mark_uploaded_fn, "$")
        extract_text = step("ExtractText", extract_text_fn, "$.text")
        extraction_branch = (
            step("ExtractDeadlines", extract_deadlines_fn, "$.extraction")
            .next(step("Validate", validate_fn, "$.validated"))
            .next(step("SaveDeadlines", save_fn, "$.saved"))
        )
        index_branch = step("IndexChunks", index_fn, "$.indexed")
        process = sfn.Parallel(
            self, "ExtractAndIndex",
            result_path="$.results",
            result_selector={"saved.$": "$[0].saved", "indexed.$": "$[1].indexed"},
        ).branch(extraction_branch).branch(index_branch)
        finalize = step("Finalize", finalize_fn, "$.done")

        for state in (mark_uploaded, extract_text, process, finalize):
            state.add_catch(failed, errors=["States.ALL"], result_path="$.error")

        definition = mark_uploaded.next(extract_text).next(process).next(finalize).next(sfn.Succeed(self, "Done"))
        state_machine = sfn.StateMachine(
            self, "PipelineStateMachine",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=Duration.minutes(15),
            tracing_enabled=True,
            logs=sfn.LogOptions(
                destination=logs.LogGroup(self, "PipelineLogs", retention=logs.RetentionDays.ONE_MONTH,
                                          removal_policy=RemovalPolicy.DESTROY),
                level=sfn.LogLevel.ERROR,
            ),
        )

        # S3 Object Created (uploads/ only) -> start the pipeline
        events.Rule(
            self, "UploadCreatedRule",
            event_pattern=events.EventPattern(
                source=["aws.s3"],
                detail_type=["Object Created"],
                detail={
                    "bucket": {"name": [uploads.bucket_name]},
                    "object": {"key": [{"prefix": "uploads/"}]},
                },
            ),
            targets=[targets.SfnStateMachine(state_machine)],
        )

        # ---------------- HTTP API ----------------
        authorizer = HttpUserPoolAuthorizer("CognitoAuthorizer", user_pool, user_pool_clients=[web_client])
        api = apigw.HttpApi(
            self, "SyllabusApi",
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=allowed_origins,
                allow_methods=[apigw.CorsHttpMethod.GET, apigw.CorsHttpMethod.POST, apigw.CorsHttpMethod.PUT,
                               apigw.CorsHttpMethod.PATCH, apigw.CorsHttpMethod.DELETE],
                allow_headers=["content-type", "authorization"],
                max_age=Duration.hours(1),
            ),
        )
        api.add_routes(
            path="/health",
            methods=[apigw.HttpMethod.GET],
            integration=HttpLambdaIntegration("HealthIntegration", health_fn),
        )
        uploads_integration = HttpLambdaIntegration("UploadsFnIntegration", uploads_fn)
        api_integration = HttpLambdaIntegration("ApiFnIntegration", api_fn)
        ask_integration = HttpLambdaIntegration("AskFnIntegration", ask_fn)
        for path, methods, integration in [
            ("/uploads", [apigw.HttpMethod.POST], uploads_integration),
            ("/syllabi", [apigw.HttpMethod.GET], api_integration),
            ("/syllabi/{id}", [apigw.HttpMethod.GET, apigw.HttpMethod.DELETE], api_integration),
            ("/syllabi/{id}/deadlines", [apigw.HttpMethod.POST], api_integration),
            ("/syllabi/{id}/deadlines/{n}", [apigw.HttpMethod.PATCH, apigw.HttpMethod.DELETE], api_integration),
            ("/deadlines", [apigw.HttpMethod.GET], api_integration),
            ("/settings", [apigw.HttpMethod.GET, apigw.HttpMethod.PUT], api_integration),
            ("/settings/test-email", [apigw.HttpMethod.POST], api_integration),
            ("/ask", [apigw.HttpMethod.POST], ask_integration),
        ]:
            api.add_routes(path=path, methods=methods, integration=integration, authorizer=authorizer)

        # ---------------- monitoring ----------------
        alarm_topic = sns.Topic(self, "AlarmTopic", display_name="syllabus-agent alarms")
        if alarm_email:
            alarm_topic.add_subscription(subs.EmailSubscription(alarm_email))
        alarm_action = cw_actions.SnsAction(alarm_topic)

        for name, f in self.functions.items():
            alarm = f.metric_errors(period=Duration.minutes(5)).create_alarm(
                self, f"{name}Errors",
                threshold=1,
                evaluation_periods=1,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
                alarm_description=f"{name} threw an error in the last 5 minutes",
            )
            alarm.add_alarm_action(alarm_action)

        pipeline_alarm = state_machine.metric_failed(period=Duration.minutes(5)).create_alarm(
            self, "PipelineFailures",
            threshold=1,
            evaluation_periods=1,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            alarm_description="A syllabus failed to process",
        )
        pipeline_alarm.add_alarm_action(alarm_action)

        def tokens(metric, operation):
            return cw.Metric(namespace=METRICS_NAMESPACE, metric_name=metric,
                             dimensions_map={"Operation": operation}, statistic="Sum", period=Duration.hours(1))

        dashboard = cw.Dashboard(self, "Dashboard", dashboard_name="syllabus-agent")
        dashboard.add_widgets(
            cw.GraphWidget(title="Claude tokens / hour", width=12, left=[
                tokens("InputTokens", "extract_deadlines"), tokens("OutputTokens", "extract_deadlines"),
                tokens("InputTokens", "ask"), tokens("OutputTokens", "ask"),
            ]),
            cw.GraphWidget(title="Pipeline executions", width=12, left=[
                state_machine.metric_succeeded(), state_machine.metric_failed(),
            ]),
        )

        CfnOutput(self, "ApiUrl", value=api.url)
        CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=web_client.user_pool_client_id)
        CfnOutput(self, "Region", value=self.region)
        CfnOutput(self, "UploadsBucketName", value=uploads.bucket_name)
        CfnOutput(self, "TableName", value=table.table_name)
        CfnOutput(self, "StateMachineArn", value=state_machine.state_machine_arn)
        CfnOutput(self, "AlarmTopicArn", value=alarm_topic.topic_arn)
