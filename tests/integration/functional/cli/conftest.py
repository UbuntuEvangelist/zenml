#  Copyright (c) ZenML GmbH 2022. All Rights Reserved.
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

import pytest

from tests.integration.functional.zen_stores.utils import (
    constant_int_output_test_step,
    int_plus_one_test_step,
)
from zenml.config.schedule import Schedule


@pytest.fixture(scope="session", autouse=True)
def initialize_store():
    """Fixture to initialize the zen and secrets stores.

    NOTE: this fixture initializes the Zen store and the secrets store
    before any CLI tests are run because some backends (AWS) are known to mess
    up the stdout and stderr streams upon initialization and this impacts the
    click.testing.CliRunner ability to capture the output and restore the
    streams upon exit.
    """
    from zenml.client import Client

    _ = Client().zen_store


@pytest.fixture
def clean_workspace_with_run(clean_workspace, connected_two_step_pipeline):
    """Fixture to get a clean workspace with an existing pipeline run in it."""
    connected_two_step_pipeline(
        step_1=constant_int_output_test_step(),
        step_2=int_plus_one_test_step(),
    ).run()
    return clean_workspace


@pytest.fixture
def clean_workspace_with_scheduled_run(
    clean_workspace, connected_two_step_pipeline
):
    """Fixture to get a clean workspace with an existing scheduled run in it."""
    schedule = Schedule(cron_expression="*/5 * * * *")
    connected_two_step_pipeline(
        step_1=constant_int_output_test_step(),
        step_2=int_plus_one_test_step(),
    ).run(schedule=schedule)
    return clean_workspace
