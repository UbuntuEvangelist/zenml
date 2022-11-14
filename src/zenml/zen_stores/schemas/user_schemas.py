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

from datetime import datetime
from typing import List, Optional

from sqlmodel import Field, Relationship

from zenml.new_models import (
    UserRequestModel,
    UserResponseModel,
    UserUpdateModel,
)
from zenml.zen_stores.schemas import (
    FlavorSchema,
    PipelineRunSchema,
    PipelineSchema,
    StackComponentSchema,
    StackSchema,
    TeamAssignmentSchema,
    TeamSchema,
    UserRoleAssignmentSchema,
)
from zenml.zen_stores.schemas.base_schemas import NamedSchema


class UserSchema(NamedSchema, table=True):
    """SQL Model for users."""

    full_name: str
    email: Optional[str] = Field(nullable=True)
    active: bool
    password: Optional[str] = Field(nullable=True)
    activation_token: Optional[str] = Field(nullable=True)

    email_opted_in: Optional[bool] = Field(nullable=True)

    teams: List["TeamSchema"] = Relationship(
        back_populates="users", link_model=TeamAssignmentSchema
    )
    assigned_roles: List["UserRoleAssignmentSchema"] = Relationship(
        back_populates="user", sa_relationship_kwargs={"cascade": "delete"}
    )
    stacks: List["StackSchema"] = Relationship(back_populates="user")
    components: List["StackComponentSchema"] = Relationship(
        back_populates="user",
    )
    flavors: List["FlavorSchema"] = Relationship(back_populates="user")
    pipelines: List["PipelineSchema"] = Relationship(back_populates="user")
    runs: List["PipelineRunSchema"] = Relationship(back_populates="user")

    @classmethod
    def from_request(cls, model: UserRequestModel) -> "UserSchema":
        """Create a `UserSchema` from a `UserModel`.

        Args:
            model: The `UserModel` from which to create the schema.

        Returns:
            The created `UserSchema`.
        """
        return cls(
            name=model.name,
            full_name=model.full_name,
            active=model.active,
            password=model.create_hashed_password(),
            activation_token=model.create_hashed_activation_token(),
        )

    def update(self, user_update: UserUpdateModel):
        for field, value in user_update.dict(exclude_unset=True).items():
            setattr(self, field, value)

        self.updated = datetime.now()
        return self

    def to_model(self, _block_recursion: bool = False) -> UserResponseModel:
        """Convert a `UserSchema` to a `UserResponseModel`.

        Args:
            _block_recursion: Don't recursively fill attributes

        Returns:
            The converted `UserResponseModel`.
        """
        if _block_recursion:
            return UserResponseModel(
                id=self.id,
                name=self.name,
                active=self.active,
                email_opted_in=self.email_opted_in,
                full_name=self.full_name,
                created=self.created,
                updated=self.updated,
            )
        else:
            return UserResponseModel(
                id=self.id,
                name=self.name,
                active=self.active,
                email_opted_in=self.email_opted_in,
                teams=[t.to_model(_block_recursion=True) for t in self.teams],
                full_name=self.full_name,
                created=self.created,
                updated=self.updated,
            )
