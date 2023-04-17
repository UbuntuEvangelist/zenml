#  Copyright (c) ZenML GmbH 2023. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at:
#
#       https://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
#  or implied. See the License for the specific language governing
#  permissions and limitations under the License.

import sys

import pytest

from tests.integration.examples.utils import run_example
from zenml.client import Client
from zenml.integrations.mlflow.model_registries.mlflow_model_registry import (
    MLFlowModelRegistry,
)
from zenml.post_execution.pipeline import get_pipeline


@pytest.mark.skipif(
    sys.version_info.major == 3 and sys.version_info.minor == 7,
    reason="MLflow model registry is only supported on Python>3.7",
)
def test_example(request: pytest.FixtureRequest) -> None:
    """Runs the quickstart example."""

    with run_example(
        request=request,
        name="quickstart",
        pipelines={"training_pipeline": (1, 4), "inference_pipeline": (1, 5)},
    ):
        # activate the stack set up and used by the example
        client = Client()
        model_registry = client.active_stack.model_registry
        assert isinstance(model_registry, MLFlowModelRegistry)

        # fetch the MLflow registered model
        registered_model = model_registry.get_model(
            name="zenml-quickstart-model",
        )
        assert registered_model is not None

        # fetch the MLflow registered model version
        registered_model_version = model_registry.get_model_version(
            name="zenml-quickstart-model",
            version=1,
        )
        assert registered_model_version is not None

        # Check that the deployment service is running
        from zenml.integrations.mlflow.services import MLFlowDeploymentService

        training_run = get_pipeline("inference_pipeline").runs[0]

        service = training_run.get_step("mlflow_model_deployer").output.read()
        assert isinstance(service, MLFlowDeploymentService)

        if service.is_running:
            service.stop(timeout=60)
