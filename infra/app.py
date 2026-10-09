import aws_cdk as cdk

from infra.github_oidc_stack import GithubOidcStack
from infra.infra_stack import InfraStack

app = cdk.App()
env = cdk.Environment(region="us-east-1")

InfraStack(app, "SyllabusAgentStack", env=env)

# One-time, deployed by hand: `cdk deploy SyllabusAgentGithubOidc`
# IDs are GitHub's immutable owner/repo IDs, which appear in the OIDC subject
# (repo:WassayShahid@123102361/syllabus-agent@1409130119:...). Override them for a fork.
GithubOidcStack(app, "SyllabusAgentGithubOidc", env=env,
                repo=app.node.try_get_context("githubRepo") or "WassayShahid/syllabus-agent",
                owner_id=int(app.node.try_get_context("githubOwnerId") or 123102361),
                repo_id=int(app.node.try_get_context("githubRepoId") or 1409130119))

app.synth()
