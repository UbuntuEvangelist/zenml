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

from typing import TYPE_CHECKING, Any, List, Sequence, Tuple

from pydantic import BaseModel, Field

from tests.harness.model.base import BaseTestConfigModel
from tests.harness.model.deployment import DeploymentConfig
from tests.harness.model.environment import EnvironmentConfig
from tests.harness.model.requirements import TestRequirements
from tests.harness.model.secret import Secret
from tests.harness.model.test import TestConfig

if TYPE_CHECKING:
    from tests.harness.harness import TestHarness


class Configuration(BaseTestConfigModel):
    """ZenML configuration settings."""

    deployments: List[DeploymentConfig] = Field(default_factory=list)
    secrets: List[Secret] = Field(default_factory=list)
    tests: List[TestConfig] = Field(default_factory=list)
    requirements: List[TestRequirements] = Field(default_factory=list)
    environments: List[EnvironmentConfig] = Field(default_factory=list)

    _config_file: str

    def __init__(self, config_file: str, **data: Any) -> None:
        self._config_file = config_file
        super().__init__(**data)

    def merge(self, config: "Configuration") -> None:
        """Updates the configuration with the contents of another configuration.

        Args:
            config: The configuration to merge into this one.
        """

        def check_duplicate_keys(
            entries: Sequence[BaseModel], key_attr: str
        ) -> List[str]:
            """Checks for duplicated keys.

            Args:
                entries: List of pydantic objects.
                key_attr: The attribute to use as key.

            Returns:
                A list of duplicate keys.
            """
            keys = [getattr(entry, key_attr) for entry in entries]
            return [key for key in keys if keys.count(key) > 1]

        self.deployments += config.deployments
        self.secrets += config.secrets
        self.tests += config.tests
        self.requirements += config.requirements
        self.environments += config.environments

        # Check each list for duplicate keys after merging
        lists_to_check: Sequence[Tuple[List[Any], str, str]] = [
            (self.deployments, "name", "deployment"),
            (self.secrets, "name", "secret"),
            (self.tests, "module", "test requirement"),
            (self.requirements, "name", "global requirement"),
            (self.environments, "name", "environment"),
        ]

        for item_list, key_attr, item_name in lists_to_check:
            duplicates = check_duplicate_keys(item_list, key_attr)
            if duplicates:
                raise ValueError(
                    f"Configuration error: {item_name}s with duplicate "
                    f"names loaded from configuration file "
                    f"`{self._config_file}`: {', '.join(duplicates)}"
                )

    def compile(self, harness: "TestHarness") -> None:
        """Validates and compiles the configuration.

        Args:
            harness: The test harness to validate against.
        """
        lists_to_compile: Sequence[List[Any]] = [
            self.secrets,
            self.deployments,
            self.requirements,
            self.environments,
            self.tests,
        ]

        for item_list in lists_to_compile:
            for item in item_list:
                item.compile(harness)
