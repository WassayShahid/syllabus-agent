import aws_cdk as cdk
from infra.infra_stack import InfraStack

app = cdk.App()
InfraStack(app, "SyllabusAgentStack", env=cdk.Environment(region="us-east-1"))
app.synth()