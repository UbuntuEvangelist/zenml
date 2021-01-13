#  Copyright (c) maiot GmbH 2021. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at:
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
#  or implied. See the License for the specific language governing
#  permissions and limitations under the License.

import click
from tabulate import tabulate
from zenml.cli.cli import cli
from zenml.cli.utils import error
from zenml.core.repo.repo import Repository
from zenml.utils.print_utils import to_pretty_string


@cli.group()
def steps():
    """Steps group"""
    pass


@steps.command("list")
def list_steps():
    try:
        repo: Repository = Repository.get_instance()
    except Exception as e:
        error(e)
        return

    step_versions = repo.get_step_versions()
    click.echo(tabulate(step_versions, headers="keys"))


@steps.command("get-versions")
def get_step_versions():
    pass
