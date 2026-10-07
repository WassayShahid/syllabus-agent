"""One shared code asset for every Lambda: backend/src + backend/requirements.txt.

Bundles locally with pip (downloading Linux wheels for the Lambda runtime), so `cdk deploy`
works on Windows/macOS without Docker. Docker bundling is the fallback if local pip fails.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import jsii
from aws_cdk import BundlingOptions, ILocalBundling
from aws_cdk import aws_lambda as _lambda

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
RUNTIME = _lambda.Runtime.PYTHON_3_12
PYTHON_VERSION = "3.12"


@jsii.implements(ILocalBundling)
class LocalPipBundling:
    def try_bundle(self, output_dir, options=None, **kwargs):
        try:
            shutil.copytree(BACKEND_DIR / "src", output_dir, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet",
                 "--requirement", str(BACKEND_DIR / "requirements.txt"),
                 "--target", output_dir,
                 "--platform", "manylinux2014_x86_64", "--implementation", "cp",
                 "--python-version", PYTHON_VERSION, "--only-binary=:all:"],
                check=True,
            )
            return True
        except (OSError, subprocess.CalledProcessError) as e:
            print(f"Local bundling failed ({e}); falling back to Docker.")
            return False


def backend_code():
    return _lambda.Code.from_asset(
        str(BACKEND_DIR),
        exclude=["tests", "**/__pycache__", ".pytest_cache", "requirements-dev.txt"],
        bundling=BundlingOptions(
            image=RUNTIME.bundling_image,
            command=["bash", "-c",
                     "pip install -r requirements.txt -t /asset-output && cp -r src/. /asset-output/"],
            local=LocalPipBundling(),
        ),
    )
