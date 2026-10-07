import aws_cdk as cdk

from infra.github_oidc_stack import GithubOidcStack
from infra.infra_stack import InfraStack

app = cdk.App()
env = cdk.Environment(region="us-east-1")

InfraStack(app, "SyllabusAgentStack", env=env)

# One-time, deployed by hand: `cdk deploy SyllabusAgentGithubOidc`
GithubOidcStack(app, "SyllabusAgentGithubOidc", env=env,
                repo=app.node.try_get_context("githubRepo") or "WassayShahid/syllabus-agent")

app.synth()
