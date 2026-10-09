"""Deploy once by hand: lets GitHub Actions on `main` assume a role via OIDC (no long-lived keys).

The role can only assume the CDK bootstrap roles, which is all `cdk deploy` needs.

A job that declares `environment: <name>` presents the subject `repo:<repo>:environment:<name>`
instead of `repo:<repo>:ref:refs/heads/<branch>`, so both forms are trusted. Restrict the
environment to `main` in GitHub (Settings > Environments > Deployment branches).

GitHub may also put immutable numeric IDs in the subject
(`repo:Owner@<ownerId>/name@<repoId>:...`). Pass `owner_id`/`repo_id` to trust that form
exactly; never use wildcards here, or a look-alike account name could assume the role.
"""
from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_iam as iam
from constructs import Construct


class GithubOidcStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, repo: str, branch: str = "main",
                 environment: str = "production", owner_id: int | None = None, repo_id: int | None = None,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        owner, name = repo.split("/", 1)
        repo_forms = [repo]
        if owner_id and repo_id:
            repo_forms.append(f"{owner}@{owner_id}/{name}@{repo_id}")
        subjects = [s for r in repo_forms
                    for s in (f"repo:{r}:ref:refs/heads/{branch}", f"repo:{r}:environment:{environment}")]

        provider = iam.OpenIdConnectProvider(
            self, "GithubProvider",
            url="https://token.actions.githubusercontent.com",
            client_ids=["sts.amazonaws.com"],
        )
        role = iam.Role(
            self, "DeployRole",
            assumed_by=iam.WebIdentityPrincipal(
                provider.open_id_connect_provider_arn,
                conditions={
                    # exact matches only (no wildcards)
                    "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                                     "token.actions.githubusercontent.com:sub": subjects},
                },
            ),
            max_session_duration=Duration.hours(1),
            description=f"cdk deploy from GitHub Actions ({repo}@{branch})",
        )
        role.add_to_policy(iam.PolicyStatement(
            actions=["sts:AssumeRole"],
            resources=[f"arn:aws:iam::{self.account}:role/cdk-*"],
        ))
        CfnOutput(self, "DeployRoleArn", value=role.role_arn)
