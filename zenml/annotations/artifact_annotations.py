#  Copyright (c) ZenML GmbH 2021. All Rights Reserved.
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

from zenml.annotations.base_annotations import BaseAnnotation
from zenml.artifacts.base_artifact import BaseArtifact

# General Artifact Annotations

Input = type("Input", (BaseAnnotation,), {"VALID_TYPES": [BaseArtifact]})

Output = type("Output", (BaseAnnotation,), {"VALID_TYPES": [BaseArtifact]})

# Specialized Output Artifact Annotations

BeamOutput = type("BeamOutput", (Output,), {"VALID_TYPES": [BaseArtifact]})

PandasOutput = type("PandasOutput", (Output,), {"VALID_TYPES": [BaseArtifact]})

JSONOutput = type("JSONOutput", (Output,), {"VALID_TYPES": [BaseArtifact]})
