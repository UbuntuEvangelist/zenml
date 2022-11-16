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
"""SQL Model Implementations for Flavors."""

from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import Column, ForeignKey, String
from sqlmodel import Field, Relationship

from zenml.enums import StackComponentType
from zenml.models.flavor_models import FlavorResponseModel
from zenml.zen_stores.schemas.base_schemas import NamedSchema

if TYPE_CHECKING:
    from zenml.zen_stores.schemas import ProjectSchema, UserSchema


class FlavorSchema(NamedSchema, table=True):
    """SQL Model for flavors.

    Attributes:
        type: The type of the flavor.
        source: The source of the flavor.
        config_schema: The config schema of the flavor.
        integration: The integration associated with the flavor.
    """

    type: StackComponentType
    source: str
    config_schema: str = Field(sa_column=Column(String(4096)), nullable=False)
    integration: Optional[str] = Field(default="")

    user_id: UUID = Field(
        sa_column=Column(ForeignKey("userschema.id", ondelete="SET NULL"))
    )
    project_id: UUID = Field(
        sa_column=Column(ForeignKey("projectschema.id", ondelete="CASCADE"))
    )
    project: "ProjectSchema" = Relationship(back_populates="flavors")
    user: "UserSchema" = Relationship(back_populates="flavors")

    def to_model(self) -> FlavorResponseModel:
        """Converts a flavor schema to a flavor model.

        Returns:
            The flavor model.
        """
        return FlavorResponseModel(
            id=self.id,
            name=self.name,
            type=self.type,
            source=self.source,
            config_schema=self.config_schema,
            integration=self.integration,
            user=self.user.to_model(),
            project=self.project.to_model(),
            created=self.created,
            updated=self.updated,
        )
