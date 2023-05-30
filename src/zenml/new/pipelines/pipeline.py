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
"""Definition of a ZenML pipeline."""
import copy
import hashlib
import inspect
from datetime import datetime
from pathlib import Path
from types import FunctionType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Dict,
    List,
    Mapping,
    Optional,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
)
from uuid import UUID

import yaml
from pydantic import ValidationError

from zenml import constants
from zenml.client import Client
from zenml.config.compiler import Compiler
from zenml.config.pipeline_configurations import (
    PipelineConfiguration,
    PipelineConfigurationUpdate,
)
from zenml.config.pipeline_run_configuration import PipelineRunConfiguration
from zenml.config.pipeline_spec import PipelineSpec
from zenml.config.schedule import Schedule
from zenml.config.step_configurations import StepConfigurationUpdate
from zenml.enums import StackComponentType
from zenml.hooks.hook_validators import resolve_and_validate_hook
from zenml.logger import get_logger
from zenml.models import (
    CodeReferenceRequestModel,
    PipelineBuildResponseModel,
    PipelineDeploymentRequestModel,
    PipelineDeploymentResponseModel,
    PipelineRequestModel,
    PipelineResponseModel,
    ScheduleRequestModel,
)
from zenml.models.pipeline_build_models import (
    PipelineBuildBaseModel,
)
from zenml.models.pipeline_deployment_models import PipelineDeploymentBaseModel
from zenml.new.pipelines import build_utils
from zenml.stack import Stack
from zenml.steps import BaseStep
from zenml.steps.entrypoint_function_utils import (
    StepArtifact,
)
from zenml.steps.external_artifact import ExternalArtifact
from zenml.steps.step_invocation import StepInvocation
from zenml.utils import (
    code_repository_utils,
    dashboard_utils,
    dict_utils,
    pydantic_utils,
    settings_utils,
    source_utils,
    yaml_utils,
)
from zenml.utils.analytics_utils import AnalyticsEvent, event_handler

if TYPE_CHECKING:
    from zenml.config.base_settings import SettingsOrDict
    from zenml.config.source import Source
    from zenml.post_execution import (
        PipelineRunView,
        PipelineVersionView,
        PipelineView,
    )

    StepConfigurationUpdateOrDict = Union[
        Dict[str, Any], StepConfigurationUpdate
    ]
    HookSpecification = Union[str, "Source", FunctionType]

logger = get_logger(__name__)

T = TypeVar("T", bound="Pipeline")
F = TypeVar("F", bound=Callable[..., None])


class GetRunsDescriptor:
    """Descriptor to define the `BasePipeline.get_runs`.

    Descriptors (https://docs.python.org/3/reference/datamodel.html#implementing-descriptors)
    allow us to define different behaviors for pipeline classes and instances.
    """

    def __get__(
        self, instance: Optional["Pipeline"], cls: Type["Pipeline"]
    ) -> Callable[[], List["PipelineRunView"]]:
        """Get all runs of this pipeline instance or class.

        Args:
            instance: The pipeline instance if called on an instance else None.
            cls: The pipeline class.

        Returns:
            A list of all runs of this pipeline instance or class.

        Raises:
            RuntimeError: If the method is called on a pipeline instance that
                has not been run yet.
        """
        from zenml.post_execution import get_pipeline

        pipeline_view: Union["PipelineVersionView", "PipelineView"]
        if instance is None:
            pipeline_view = get_pipeline(cls)
        else:
            instance._prepare_if_possible()
            pipeline_view = get_pipeline(instance)

        if pipeline_view:
            return lambda: pipeline_view.runs
        raise RuntimeError(
            "The pipeline view for this pipeline was not found. Please check "
            "that the pipeline has been run already."
        )


class Pipeline:
    """ZenML pipeline class."""

    # The active pipeline is the pipeline to which step invocations will be
    # added when a step is called. It is set using a context manager when a
    # pipeline is called (see Pipeline.__call__ for more context)
    ACTIVE_PIPELINE: ClassVar[Optional["Pipeline"]] = None

    def __init__(
        self,
        name: str,
        entrypoint: F,
        enable_cache: Optional[bool] = None,
        enable_artifact_metadata: Optional[bool] = None,
        enable_artifact_visualization: Optional[bool] = None,
        settings: Optional[Mapping[str, "SettingsOrDict"]] = None,
        extra: Optional[Dict[str, Any]] = None,
        on_failure: Optional["HookSpecification"] = None,
        on_success: Optional["HookSpecification"] = None,
    ) -> None:
        """Initializes a pipeline.

        Args:
            name: The name of the pipeline.
            entrypoint: The entrypoint function of the pipeline.
            enable_cache: If caching should be enabled for this pipeline.
            enable_artifact_metadata: If artifact metadata should be enabled for
                this pipeline.
            enable_artifact_visualization: If artifact visualization should be
                enabled for this pipeline.
            settings: settings for this pipeline.
            extra: Extra configurations for this pipeline.
            on_failure: Callback function in event of failure of the step. Can
                be a function with three possible parameters, `StepContext`,
                `BaseParameters`, and `BaseException`, or a source path to a
                function of the same specifications (e.g. `module.my_function`).
            on_success: Callback function in event of failure of the step. Can
                be a function with two possible parameters, `StepContext` and
                `BaseParameters, or a source path to a function of the same
                specifications (e.g. `module.my_function`).
        """
        self._invocations: Dict[str, StepInvocation] = {}
        self._run_args: Dict[str, Any] = {}

        self._configuration = PipelineConfiguration(
            name=name,
        )
        self.configure(
            enable_cache=enable_cache,
            enable_artifact_metadata=enable_artifact_metadata,
            enable_artifact_visualization=enable_artifact_visualization,
            settings=settings,
            extra=extra,
            on_failure=on_failure,
            on_success=on_success,
        )
        self.entrypoint = entrypoint
        self._parameters: Dict[str, Any] = {}

    @property
    def name(self) -> str:
        """The name of the pipeline.

        Returns:
            The name of the pipeline.
        """
        return self.configuration.name

    @property
    def enable_cache(self) -> Optional[bool]:
        """If caching is enabled for the pipeline.

        Returns:
            If caching is enabled for the pipeline.
        """
        return self.configuration.enable_cache

    @property
    def configuration(self) -> PipelineConfiguration:
        """The configuration of the pipeline.

        Returns:
            The configuration of the pipeline.
        """
        return self._configuration

    @property
    def invocations(self) -> Dict[str, StepInvocation]:
        """Returns the step invocations of this pipeline.

        This dictionary will only be populated once the pipeline has been
        called.

        Returns:
            The step invocations.
        """
        return self._invocations

    def resolve(self) -> "Source":
        """Resolves the pipeline.

        Returns:
            The pipeline source.
        """
        return source_utils.resolve(self.entrypoint, skip_validation=True)

    @property
    def source_object(self) -> Any:
        """The source object of this pipeline.

        Returns:
            The source object of this pipeline.
        """
        return self.entrypoint

    @property
    def source_code(self) -> str:
        """The source code of this pipeline.

        Returns:
            The source code of this pipeline.
        """
        return inspect.getsource(self.source_object)

    @classmethod
    def from_model(cls, model: "PipelineResponseModel") -> "Pipeline":
        """Creates a pipeline instance from a model.

        Args:
            model: The model to load the pipeline instance from.

        Returns:
            The pipeline instance.
        """
        from zenml.new.pipelines.deserialization_utils import load_pipeline

        return load_pipeline(model=model)

    def configure(
        self: T,
        enable_cache: Optional[bool] = None,
        enable_artifact_metadata: Optional[bool] = None,
        enable_artifact_visualization: Optional[bool] = None,
        settings: Optional[Mapping[str, "SettingsOrDict"]] = None,
        extra: Optional[Dict[str, Any]] = None,
        on_failure: Optional["HookSpecification"] = None,
        on_success: Optional["HookSpecification"] = None,
        merge: bool = True,
    ) -> T:
        """Configures the pipeline.

        Configuration merging example:
        * `merge==True`:
            pipeline.configure(extra={"key1": 1})
            pipeline.configure(extra={"key2": 2}, merge=True)
            pipeline.configuration.extra # {"key1": 1, "key2": 2}
        * `merge==False`:
            pipeline.configure(extra={"key1": 1})
            pipeline.configure(extra={"key2": 2}, merge=False)
            pipeline.configuration.extra # {"key2": 2}

        Args:
            enable_cache: If caching should be enabled for this pipeline.
            enable_artifact_metadata: If artifact metadata should be enabled for
                this pipeline.
            enable_artifact_visualization: If artifact visualization should be
                enabled for this pipeline.
            settings: settings for this pipeline.
            extra: Extra configurations for this pipeline.
            on_failure: Callback function in event of failure of the step. Can
                be a function with three possible parameters, `StepContext`,
                `BaseParameters`, and `BaseException`, or a source path to a
                function of the same specifications (e.g. `module.my_function`).
            on_success: Callback function in event of failure of the step. Can
                be a function with two possible parameters, `StepContext` and
                `BaseParameters, or a source path to a function of the same
                specifications (e.g. `module.my_function`).
            merge: If `True`, will merge the given dictionary configurations
                like `extra` and `settings` with existing
                configurations. If `False` the given configurations will
                overwrite all existing ones. See the general description of this
                method for an example.

        Returns:
            The pipeline instance that this method was called on.
        """
        failure_hook_source = None
        if on_failure:
            # string of on_failure hook function to be used for this pipeline
            failure_hook_source = resolve_and_validate_hook(on_failure)

        success_hook_source = None
        if on_success:
            # string of on_success hook function to be used for this pipeline
            success_hook_source = resolve_and_validate_hook(on_success)

        values = dict_utils.remove_none_values(
            {
                "enable_cache": enable_cache,
                "enable_artifact_metadata": enable_artifact_metadata,
                "enable_artifact_visualization": enable_artifact_visualization,
                "settings": settings,
                "extra": extra,
                "failure_hook_source": failure_hook_source,
                "success_hook_source": success_hook_source,
            }
        )
        config = PipelineConfigurationUpdate(**values)
        self._apply_configuration(config, merge=merge)
        return self

    @property
    def requires_parameters(self) -> bool:
        """If the pipeline entrypoint requires parameters.

        Returns:
            If the pipeline entrypoint requires parameters.
        """
        signature = inspect.signature(self.entrypoint, follow_wrapped=True)
        return any(
            parameter.default is inspect.Parameter.empty
            for parameter in signature.parameters.values()
        )

    @property
    def is_prepared(self) -> bool:
        """If the pipeline is prepared.

        Prepared means that the pipeline entrypoint has been called and the
        pipeline is fully defined.

        Returns:
            If the pipeline is prepared.
        """
        return len(self.invocations) > 0

    def prepare(self, *args: Any, **kwargs: Any) -> None:
        """Prepares the pipeline.

        Args:
            *args: Pipeline entrypoint input arguments.
            **kwargs: Pipeline entrypoint input keyword arguments.
        """
        # Clear existing parameters and invocations
        self._parameters = {}
        self._invocations = {}

        with self:
            # Enter the context manager so we become the active pipeline. This
            # means that all steps that get called while the entrypoint function
            # is executed will be added as invocation to this pipeline instance.
            self._call_entrypoint(*args, **kwargs)

    def register(self) -> "PipelineResponseModel":
        """Register the pipeline in the server.

        Returns:
            The registered pipeline model.
        """
        # Activating the built-in integrations to load all materializers
        from zenml.integrations.registry import integration_registry

        self._prepare_if_possible()
        integration_registry.activate_integrations()

        custom_configurations = self.configuration.dict(
            exclude_defaults=True, exclude={"name"}
        )
        if custom_configurations:
            logger.warning(
                f"The pipeline `{self.name}` that you're registering has "
                "custom configurations applied to it. These will not be "
                "registered with the pipeline and won't be set when you build "
                "images or run the pipeline from the CLI. To provide these "
                "configurations, use the `--config` option of the `zenml "
                "pipeline build/run` commands."
            )

        pipeline_spec = Compiler().compile_spec(self)
        return self._register(pipeline_spec=pipeline_spec)

    def build(
        self,
        settings: Optional[Mapping[str, "SettingsOrDict"]] = None,
        step_configurations: Optional[
            Mapping[str, "StepConfigurationUpdateOrDict"]
        ] = None,
        config_path: Optional[str] = None,
    ) -> Optional["PipelineBuildResponseModel"]:
        """Builds Docker images for the pipeline.

        Args:
            settings: Settings for the pipeline.
            step_configurations: Configurations for steps of the pipeline.
            config_path: Path to a yaml configuration file. This file will
                be parsed as a
                `zenml.config.pipeline_configurations.PipelineRunConfiguration`
                object. Options provided in this file will be overwritten by
                options provided in code using the other arguments of this
                method.

        Returns:
            The build output.
        """
        with event_handler(event=AnalyticsEvent.BUILD_PIPELINE, v2=True):
            self._prepare_if_possible()
            deployment, pipeline_spec, _, _ = self._compile(
                config_path=config_path,
                steps=step_configurations,
                settings=settings,
            )
            pipeline_id = self._register(pipeline_spec=pipeline_spec).id

            local_repo = code_repository_utils.find_active_code_repository()
            code_repository = build_utils.verify_local_repository_context(
                deployment=deployment, local_repo_context=local_repo
            )

            return build_utils.create_pipeline_build(
                deployment=deployment,
                pipeline_id=pipeline_id,
                code_repository=code_repository,
            )

    def _run(
        self,
        *,
        run_name: Optional[str] = None,
        enable_cache: Optional[bool] = None,
        enable_artifact_metadata: Optional[bool] = None,
        enable_artifact_visualization: Optional[bool] = None,
        schedule: Optional[Schedule] = None,
        build: Union[str, "UUID", "PipelineBuildBaseModel", None] = None,
        settings: Optional[Mapping[str, "SettingsOrDict"]] = None,
        step_configurations: Optional[
            Mapping[str, "StepConfigurationUpdateOrDict"]
        ] = None,
        extra: Optional[Dict[str, Any]] = None,
        config_path: Optional[str] = None,
        unlisted: bool = False,
        prevent_build_reuse: bool = False,
    ) -> None:
        """Runs the pipeline on the active stack.

        Args:
            run_name: Name of the pipeline run.
            enable_cache: If caching should be enabled for this pipeline run.
            enable_artifact_metadata: If artifact metadata should be enabled
                for this pipeline run.
            enable_artifact_visualization: If artifact visualization should be
                enabled for this pipeline run.
            schedule: Optional schedule to use for the run.
            build: Optional build to use for the run.
            settings: Settings for this pipeline run.
            step_configurations: Configurations for steps of the pipeline.
            extra: Extra configurations for this pipeline run.
            config_path: Path to a yaml configuration file. This file will
                be parsed as a
                `zenml.config.pipeline_configurations.PipelineRunConfiguration`
                object. Options provided in this file will be overwritten by
                options provided in code using the other arguments of this
                method.
            unlisted: Whether the pipeline run should be unlisted (not assigned
                to any pipeline).
            prevent_build_reuse: Whether to prevent the reuse of a build.
        """
        if constants.SHOULD_PREVENT_PIPELINE_EXECUTION:
            # An environment variable was set to stop the execution of
            # pipelines. This is done to prevent execution of module-level
            # pipeline.run() calls when importing modules needed to run a step.
            logger.info(
                "Preventing execution of pipeline '%s'. If this is not "
                "intended behavior, make sure to unset the environment "
                "variable '%s'.",
                self.name,
                constants.ENV_ZENML_PREVENT_PIPELINE_EXECUTION,
            )
            return

        with event_handler(
            event=AnalyticsEvent.RUN_PIPELINE, v2=True
        ) as analytics_handler:
            deployment, pipeline_spec, schedule, build = self._compile(
                config_path=config_path,
                run_name=run_name,
                enable_cache=enable_cache,
                enable_artifact_metadata=enable_artifact_metadata,
                enable_artifact_visualization=enable_artifact_visualization,
                steps=step_configurations,
                settings=settings,
                schedule=schedule,
                build=build,
                extra=extra,
            )

            skip_pipeline_registration = constants.handle_bool_env_var(
                constants.ENV_ZENML_SKIP_PIPELINE_REGISTRATION,
                default=False,
            )

            register_pipeline = not (skip_pipeline_registration or unlisted)

            pipeline_id = None
            if register_pipeline:
                pipeline_id = self._register(pipeline_spec=pipeline_spec).id

            # TODO: check whether orchestrator even support scheduling before
            # registering the schedule
            schedule_id = None
            if schedule:
                if schedule.name:
                    schedule_name = schedule.name
                else:
                    date = datetime.utcnow().strftime("%Y_%m_%d")
                    time = datetime.utcnow().strftime("%H_%M_%S_%f")
                    schedule_name = deployment.run_name_template.format(
                        date=date, time=time
                    )
                components = Client().active_stack_model.components
                orchestrator = components[StackComponentType.ORCHESTRATOR][0]
                schedule_model = ScheduleRequestModel(
                    workspace=Client().active_workspace.id,
                    user=Client().active_user.id,
                    pipeline_id=pipeline_id,
                    orchestrator_id=orchestrator.id,
                    name=schedule_name,
                    active=True,
                    cron_expression=schedule.cron_expression,
                    start_time=schedule.start_time,
                    end_time=schedule.end_time,
                    interval_second=schedule.interval_second,
                    catchup=schedule.catchup,
                )
                schedule_id = (
                    Client().zen_store.create_schedule(schedule_model).id
                )
                logger.info(
                    f"Created schedule `{schedule_name}` for pipeline "
                    f"`{deployment.pipeline_configuration.name}`."
                )

            stack = Client().active_stack

            local_repo_context = (
                code_repository_utils.find_active_code_repository()
            )
            code_repository = build_utils.verify_local_repository_context(
                deployment=deployment, local_repo_context=local_repo_context
            )

            build_model = build_utils.reuse_or_create_pipeline_build(
                deployment=deployment,
                pipeline_id=pipeline_id,
                allow_build_reuse=not prevent_build_reuse,
                build=build,
                code_repository=code_repository,
            )
            build_id = build_model.id if build_model else None

            code_reference = None
            if local_repo_context and not local_repo_context.is_dirty:
                source_root = source_utils.get_source_root()
                subdirectory = (
                    Path(source_root)
                    .resolve()
                    .relative_to(local_repo_context.root)
                )

                code_reference = CodeReferenceRequestModel(
                    commit=local_repo_context.current_commit,
                    subdirectory=subdirectory.as_posix(),
                    code_repository=local_repo_context.code_repository_id,
                )

            deployment_request = PipelineDeploymentRequestModel(
                user=Client().active_user.id,
                workspace=Client().active_workspace.id,
                stack=stack.id,
                pipeline=pipeline_id,
                build=build_id,
                schedule=schedule_id,
                code_reference=code_reference,
                **deployment.dict(),
            )
            deployment_model = Client().zen_store.create_deployment(
                deployment=deployment_request
            )

            analytics_handler.metadata = self._get_pipeline_analytics_metadata(
                deployment=deployment_model, stack=stack
            )
            caching_status = (
                "enabled"
                if deployment.pipeline_configuration.enable_cache is not False
                else "disabled"
            )
            logger.info(
                "%s %s on stack `%s` (caching %s)",
                "Scheduling" if deployment_model.schedule else "Running",
                f"pipeline `{deployment_model.pipeline_configuration.name}`"
                if register_pipeline
                else "unlisted pipeline",
                stack.name,
                caching_status,
            )

            stack.prepare_pipeline_deployment(deployment=deployment_model)

            # Prevent execution of nested pipelines which might lead to
            # unexpected behavior
            constants.SHOULD_PREVENT_PIPELINE_EXECUTION = True
            try:
                stack.deploy_pipeline(deployment=deployment_model)
            finally:
                constants.SHOULD_PREVENT_PIPELINE_EXECUTION = False

            # Log the dashboard URL
            dashboard_utils.print_run_url(
                run_name=deployment.run_name_template,
                pipeline_id=pipeline_id,
            )

    get_runs = GetRunsDescriptor()

    def write_run_configuration_template(
        self, path: str, stack: Optional["Stack"] = None
    ) -> None:
        """Writes a run configuration yaml template.

        Args:
            path: The path where the template will be written.
            stack: The stack for which the template should be generated. If
                not given, the active stack will be used.
        """
        from zenml.config.base_settings import ConfigurationLevel
        from zenml.config.step_configurations import (
            PartialArtifactConfiguration,
        )

        self._prepare_if_possible()

        stack = stack or Client().active_stack

        setting_classes = stack.setting_classes
        setting_classes.update(settings_utils.get_general_settings())

        pipeline_settings = {}
        step_settings = {}
        for key, setting_class in setting_classes.items():
            fields = pydantic_utils.TemplateGenerator(setting_class).run()
            if ConfigurationLevel.PIPELINE in setting_class.LEVEL:
                pipeline_settings[key] = fields
            if ConfigurationLevel.STEP in setting_class.LEVEL:
                step_settings[key] = fields

        steps = {}
        for step_name, invocation in self.invocations.items():
            step = invocation.step
            parameters = (
                pydantic_utils.TemplateGenerator(
                    step.entrypoint_definition.legacy_params.annotation
                ).run()
                if step.entrypoint_definition.legacy_params
                else {}
            )
            outputs = {
                name: PartialArtifactConfiguration()
                for name in step.entrypoint_definition.outputs
            }
            step_template = StepConfigurationUpdate(
                parameters=parameters,
                settings=step_settings,
                outputs=outputs,
            )
            steps[step_name] = step_template

        run_config = PipelineRunConfiguration(
            settings=pipeline_settings, steps=steps
        )
        template = pydantic_utils.TemplateGenerator(run_config).run()
        yaml_string = yaml.dump(template)
        yaml_string = yaml_utils.comment_out_yaml(yaml_string)

        with open(path, "w") as f:
            f.write(yaml_string)

    def _apply_configuration(
        self,
        config: PipelineConfigurationUpdate,
        merge: bool = True,
    ) -> None:
        """Applies an update to the pipeline configuration.

        Args:
            config: The configuration update.
            merge: Whether to merge the updates with the existing configuration
                or not. See the `BasePipeline.configure(...)` method for a
                detailed explanation.
        """
        self._validate_configuration(config)
        self._configuration = pydantic_utils.update_model(
            self._configuration, update=config, recursive=merge
        )
        logger.debug("Updated pipeline configuration:")
        logger.debug(self._configuration)

    @staticmethod
    def _validate_configuration(config: PipelineConfigurationUpdate) -> None:
        """Validates a configuration update.

        Args:
            config: The configuration update to validate.
        """
        settings_utils.validate_setting_keys(list(config.settings))

    def _get_pipeline_analytics_metadata(
        self,
        deployment: "PipelineDeploymentResponseModel",
        stack: "Stack",
    ) -> Dict[str, Any]:
        """Returns the pipeline deployment metadata.

        Args:
            deployment: The pipeline deployment to track.
            stack: The stack on which the pipeline will be deployed.

        Returns:
            the metadata about the pipeline deployment
        """
        custom_materializer = False
        for step in deployment.step_configurations.values():
            for output in step.config.outputs.values():
                for source in output.materializer_source:
                    if not source.is_internal:
                        custom_materializer = True

        stack_creator = Client().get_stack(stack.id).user
        active_user = Client().active_user
        own_stack = stack_creator and stack_creator.id == active_user.id

        stack_metadata = {
            component_type.value: component.flavor
            for component_type, component in stack.components.items()
        }
        return {
            "store_type": Client().zen_store.type.value,
            **stack_metadata,
            "total_steps": len(self.invocations),
            "schedule": bool(deployment.schedule),
            "custom_materializer": custom_materializer,
            "own_stack": own_stack,
        }

    def _compile(
        self, config_path: Optional[str] = None, **run_configuration_args: Any
    ) -> Tuple[
        "PipelineDeploymentBaseModel",
        "PipelineSpec",
        Optional["Schedule"],
        Union["PipelineBuildBaseModel", UUID, None],
    ]:
        """Compiles the pipeline.

        Args:
            config_path: Path to a config file.
            **run_configuration_args: Configurations for the pipeline run.

        Returns:
            A tuple containing the deployment, spec, schedule and build of
            the compiled pipeline.
        """
        # Activating the built-in integrations to load all materializers
        from zenml.integrations.registry import integration_registry

        integration_registry.activate_integrations()

        if config_path:
            run_config = PipelineRunConfiguration.from_yaml(config_path)
        else:
            run_config = PipelineRunConfiguration()

        new_values = dict_utils.remove_none_values(run_configuration_args)
        update = PipelineRunConfiguration.parse_obj(new_values)

        # Update with the values in code so they take precedence
        run_config = pydantic_utils.update_model(run_config, update=update)

        deployment, pipeline_spec = Compiler().compile(
            pipeline=self,
            stack=Client().active_stack,
            run_configuration=run_config,
        )

        return deployment, pipeline_spec, run_config.schedule, run_config.build

    def _register(
        self, pipeline_spec: "PipelineSpec"
    ) -> "PipelineResponseModel":
        """Register the pipeline in the server.

        Args:
            pipeline_spec: The pipeline spec to register.

        Returns:
            The registered pipeline model.
        """
        version_hash = self._compute_unique_identifier(
            pipeline_spec=pipeline_spec
        )

        client = Client()
        matching_pipelines = client.list_pipelines(
            name=self.name,
            version_hash=version_hash,
            size=1,
            sort_by="desc:created",
        )
        if matching_pipelines.total:
            registered_pipeline = matching_pipelines.items[0]
            logger.info(
                "Reusing registered pipeline `%s` (version: %s).",
                registered_pipeline.name,
                registered_pipeline.version,
            )
            return registered_pipeline

        latest_version = self._get_latest_version() or 0
        version = str(latest_version + 1)

        request = PipelineRequestModel(
            workspace=client.active_workspace.id,
            user=client.active_user.id,
            name=self.name,
            version=version,
            version_hash=version_hash,
            spec=pipeline_spec,
            docstring=self.__doc__,
        )

        registered_pipeline = client.zen_store.create_pipeline(
            pipeline=request
        )
        logger.info(
            "Registered pipeline `%s` (version %s).",
            registered_pipeline.name,
            registered_pipeline.version,
        )
        return registered_pipeline

    def _compute_unique_identifier(self, pipeline_spec: PipelineSpec) -> str:
        """Computes a unique identifier from the pipeline spec and steps.

        Args:
            pipeline_spec: Compiled spec of the pipeline.

        Returns:
            The unique identifier of the pipeline.
        """
        from packaging import version

        hash_ = hashlib.md5()
        hash_.update(pipeline_spec.json_with_string_sources.encode())

        if version.parse(pipeline_spec.version) >= version.parse("0.4"):
            # Only add this for newer versions to keep backwards compatibility
            hash_.update(self.source_code.encode())

        for step_spec in pipeline_spec.steps:
            invocation = self.invocations[step_spec.pipeline_parameter_name]
            step_source = invocation.step.source_code
            hash_.update(step_source.encode())

        return hash_.hexdigest()

    def _get_latest_version(self) -> Optional[int]:
        """Gets the latest version of this pipeline.

        Returns:
            The latest version or `None` if no version exists.
        """
        all_pipelines = Client().list_pipelines(
            name=self.name, sort_by="desc:created", size=1
        )
        if all_pipelines.total:
            pipeline = all_pipelines.items[0]
            if pipeline.version == "UNVERSIONED":
                return None
            return int(all_pipelines.items[0].version)
        else:
            return None

    def _get_registered_model(self) -> Optional[PipelineResponseModel]:
        """Gets the registered pipeline model for this instance.

        Returns:
            The registered pipeline model or None if no model is registered yet.
        """
        self._prepare_if_possible()

        pipeline_spec = Compiler().compile_spec(self)
        version_hash = self._compute_unique_identifier(
            pipeline_spec=pipeline_spec
        )

        pipelines = Client().list_pipelines(
            name=self.name, version_hash=version_hash
        )
        if len(pipelines) == 1:
            return pipelines.items[0]

        return None

    def add_step_invocation(
        self,
        step: "BaseStep",
        input_artifacts: Dict[str, StepArtifact],
        external_artifacts: Dict[str, ExternalArtifact],
        parameters: Dict[str, Any],
        upstream_steps: Set[str],
        custom_id: Optional[str] = None,
        allow_id_suffix: bool = True,
    ) -> str:
        """Adds a step invocation to the pipeline.

        Args:
            step: The step for which to add an invocation.
            input_artifacts: The input artifacts for the invocation.
            external_artifacts: The external artifacts for the invocation.
            parameters: The parameters for the invocation.
            upstream_steps: The upstream steps for the invocation.
            custom_id: Custom ID to use for the invocation.
            allow_id_suffix: Whether a suffix can be appended to the invocation
                ID.

        Raises:
            RuntimeError: If the method is called on an inactive pipeline.
            RuntimeError: If the invocation was called with an artifact from
                a different pipeline.

        Returns:
            The step invocation ID.
        """
        if Pipeline.ACTIVE_PIPELINE != self:
            raise RuntimeError(
                "A step invocation can only be added to an active pipeline."
            )

        for artifact in input_artifacts.values():
            if artifact.pipeline is not self:
                raise RuntimeError(
                    "Got invalid input artifact for invocation of step "
                    f"{step.name}: The input artifact was produced by a step "
                    f"inside a different pipeline {artifact.pipeline.name}."
                )

        invocation_id = self._compute_invocation_id(
            step=step, custom_id=custom_id, allow_suffix=allow_id_suffix
        )
        invocation = StepInvocation(
            id=invocation_id,
            step=step,
            input_artifacts=input_artifacts,
            external_artifacts=external_artifacts,
            parameters=parameters,
            upstream_steps=upstream_steps,
            pipeline=self,
        )
        self._invocations[invocation_id] = invocation
        return invocation_id

    def _compute_invocation_id(
        self,
        step: "BaseStep",
        custom_id: Optional[str] = None,
        allow_suffix: bool = True,
    ) -> str:
        """Compute the invocation ID.

        Args:
            step: The step for which to compute the ID.
            custom_id: Custom ID to use for the invocation.
            allow_suffix: Whether a suffix can be appended to the invocation
                ID.

        Raises:
            RuntimeError: If no ID suffix is allowed and an invocation for the
                same ID already exists.
            RuntimeError: If no unique invocation ID can be found.

        Returns:
            The invocation ID.
        """
        base_id = id_ = custom_id or step.name

        if id_ not in self.invocations:
            return id_

        if not allow_suffix:
            raise RuntimeError("Duplicate step ID")

        for index in range(2, 10000):
            id_ = f"{base_id}_{index}"
            if id_ not in self.invocations:
                return id_

        raise RuntimeError("Unable to find step ID")

    def __enter__(self: T) -> T:
        """Activate the pipeline context.

        Raises:
            RuntimeError: If a different pipeline is already active.

        Returns:
            The pipeline instance.
        """
        if Pipeline.ACTIVE_PIPELINE:
            raise RuntimeError(
                "Unable to enter pipeline context. A different pipeline "
                f"{Pipeline.ACTIVE_PIPELINE.name} is already active."
            )

        Pipeline.ACTIVE_PIPELINE = self
        return self

    def __exit__(self, *args: Any) -> None:
        """Deactivates the pipeline context.

        Args:
            *args: The arguments passed to the context exit handler.
        """
        Pipeline.ACTIVE_PIPELINE = None

    def with_options(
        self,
        run_name: Optional[str] = None,
        schedule: Optional[Schedule] = None,
        build: Union[str, "UUID", "PipelineBuildBaseModel", None] = None,
        step_configurations: Optional[
            Mapping[str, "StepConfigurationUpdateOrDict"]
        ] = None,
        config_path: Optional[str] = None,
        unlisted: bool = False,
        prevent_build_reuse: bool = False,
        **kwargs: Any,
    ) -> "Pipeline":
        """Copies the pipeline and applies the given configurations.

        Args:
            run_name: Name of the pipeline run.
            schedule: Optional schedule to use for the run.
            build: Optional build to use for the run.
            step_configurations: Configurations for steps of the pipeline.
            config_path: Path to a yaml configuration file. This file will
                be parsed as a
                `zenml.config.pipeline_configurations.PipelineRunConfiguration`
                object. Options provided in this file will be overwritten by
                options provided in code using the other arguments of this
                method.
            unlisted: Whether the pipeline run should be unlisted (not assigned
                to any pipeline).
            prevent_build_reuse: Whether to prevent the reuse of a build.
            **kwargs: Pipeline configuration options. These will be passed
                to the `pipeline.configure(...)` method.

        Returns:
            The copied pipeline instance.
        """
        pipeline_copy = self.copy()
        pipeline_copy.configure(**kwargs)

        run_args = dict_utils.remove_none_values(
            {
                "run_name": run_name,
                "schedule": schedule,
                "build": build,
                "step_configurations": step_configurations,
                "config_path": config_path,
                "unlisted": unlisted,
                "prevent_build_reuse": prevent_build_reuse,
            }
        )
        pipeline_copy._run_args.update(run_args)
        return pipeline_copy

    def copy(self) -> "Pipeline":
        """Copies the pipeline.

        Returns:
            The pipeline copy.
        """
        return copy.deepcopy(self)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Handle a call of the pipeline.

        This method does one of two things:
        * If there is an active pipeline context, it calls the pipeline
          entrypoint function within that context and the step invocations
          will be added to the active pipeline.
        * If no pipeline is active, it activates this pipeline before calling
          the entrypoint function.

        Args:
            *args: Entrypoint function arguments.
            **kwargs: Entrypoint function keyword arguments.

        Returns:
            The outputs of the entrypoint function call.
        """
        if Pipeline.ACTIVE_PIPELINE:
            # Calling a pipeline inside a pipeline, we return the potential
            # outputs of the entrypoint function

            # TODO: This currently ignores the configuration of the pipeline
            # and instead applies the configuration of the previously active
            # pipeline. Is this what we want?
            return self.entrypoint(*args, **kwargs)

        self.prepare(*args, **kwargs)
        return self._run(**self._run_args)

    def _call_entrypoint(self, *args: Any, **kwargs: Any) -> None:
        """Calls the pipeline entrypoint function with the given arguments.

        Args:
            *args: Entrypoint function arguments.
            **kwargs: Entrypoint function keyword arguments.

        Raises:
            ValueError: If an input argument is missing or not JSON
                serializable.
        """
        try:
            validated_args = pydantic_utils.validate_function_args(
                self.entrypoint,
                {"arbitrary_types_allowed": False, "smart_union": True},
                *args,
                **kwargs,
            )
        except ValidationError as e:
            raise ValueError(
                "Invalid or missing inputs for pipeline entrypoint function. "
                "Only JSON serializable inputs are allowed as pipeline inputs."
            ) from e

        self._parameters = validated_args
        self.entrypoint(**validated_args)

    def _prepare_if_possible(self) -> None:
        """Prepares the pipeline if possible.

        Raises:
            RuntimeError: If the pipeline is not prepared and the preparation
                requires parameters.
        """
        if not self.is_prepared:
            if self.requires_parameters:
                raise RuntimeError(
                    f"Failed while trying to prepare pipeline {self.name}. "
                    "The entrypoint function of the pipeline requires "
                    "arguments. Please prepare the pipeline by calling "
                    "`pipeline_instance.prepare(...)` and try again."
                )
            else:
                self.prepare()
