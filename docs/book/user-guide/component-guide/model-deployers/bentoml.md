---
description: Deploying your models locally with BentoML.
---

# BentoML

BentoML is an open-source framework for machine learning model serving. it can be used to deploy models locally, in a
cloud environment, or in a Kubernetes environment.

The BentoML Model Deployer is one of the available flavors of the [Model Deployer](model-deployers.md) stack component.
Provided with the BentoML integration it can be used to deploy and
manage [BentoML models](https://docs.bentoml.org/en/latest/concepts/model.html)
or [Bento](https://docs.bentoml.org/en/latest/concepts/bento.html) on a local running HTTP server.

{% hint style="warning" %}
The BentoML Model Deployer can be used to deploy models for local development and production use cases. While the
integration mainly works in a local environment where pipelines are run, the
used [Bento](https://docs.bentoml.org/en/latest/concepts/bento.html) can be exported and containerized, and deployed in
a remote environment. Within the BentoML ecosystem, [Yatai](https://github.com/bentoml/Yatai)
and [`bentoctl`](https://github.com/bentoml/bentoctl) are the tools responsible for deploying the Bentos into the
Kubernetes cluster and Cloud Platforms. Full support for these advanced tools is in progress and will be available soon.
{% endhint %}

### When to use it?

You should use the BentoML Model Deployer to:

* Standardize the way you deploy your models to production within your organization.
* if you are looking to deploy your models in a simple way, while you are still able to transform your model into a
  production-ready solution when that time comes.

If you are looking to deploy your models with other Kubernetes-based solutions, you can take a look at one of the
other [Model Deployer Flavors](model-deployers.md#model-deployers-flavors) available in ZenML (e.g. Seldon Core, KServe,
etc.)

BentoML also allows you to deploy your models in a more complex production-grade
setting. [Bentoctl](https://github.com/bentoml/bentoctl) is one of the tools that can help you get there. Bentoctl takes
your built Bento from a ZenML pipeline and deploys it with `bentoctl` into a cloud environment such as AWS Lambda, AWS
SageMaker, Google Cloud Functions, Google Cloud AI Platform, or Azure Functions. Read more about this in
the [From Local to Cloud with `bentoctl` section](bentoml.md#from-local-to-cloud-with-bentoctl).

{% hint style="info" %}
The `bentoctl` integration implementation is still in progress and will be available soon. The integration will allow
you to deploy your models to a specific cloud provider with just a few lines of code using ZenML built-in steps.
{% endhint %}

### How do you deploy it?

Within ZenML you can quickly get started with BentoML by simply creating Model Deployer Stack Component with the BentoML
flavor. To do so you'll need to install the required Python packages on your local machine to be able to deploy your
models:

```bash
zenml integration install bentoml -y
```

To register the BentoML model deployer with ZenML you need to run the following command:

```bash
zenml model-deployer register bentoml_deployer --flavor=bentoml
```

The ZenML integration will provision a local HTTP deployment server as a daemon process that will continue to run in the
background to serve the latest models and Bentos.

### How do you use it?

In order to use the BentoML Model Deployer, We need to understand these three main concepts:

#### BentoML Service and Runner

The first step to being able to deploy your models and use BentoML is to create
a [bento service](https://docs.bentoml.org/en/latest/concepts/service.html) which is the main logic that defines how
your model will be served, and a [bento runner](https://docs.bentoml.org/en/latest/concepts/runner.html) which
represents a unit of execution for your model on a remote Python worker.

The following example shows how to create a basic bento service and runner that will be used to serve a basic
scikit-learn model.

```python
import numpy as np
import bentoml
from bentoml.io import NumpyNdarray

iris_clf_runner = bentoml.sklearn.get("iris_clf:latest").to_runner()

svc = bentoml.Service("iris_classifier", runners=[iris_clf_runner])


@svc.api(input=NumpyNdarray(), output=NumpyNdarray())
def classify(input_series: np.ndarray) -> np.ndarray:
    result = iris_clf_runner.predict.run(input_series)
    return result

```

#### ZenML Bento Builder step

Once you have your bento service and runner defined, we can use the built-in bento builder step to build the bento
bundle that will be used to serve the model. The following example shows how can call the built-in bento builder step
within a ZenML pipeline.

```python
# Import the step and parameters class
from zenml.integrations.bentoml.steps import BentoMLBuilderParameters, bento_builder_step,

# The name we gave to our deployed model
MODEL_NAME = "pytorch_mnist"

# Call the step with the parameters
bento_builder = bento_builder_step(
    params=BentoMLBuilderParameters(
        model_name=MODEL_NAME,  # Name of the model
        model_type="pytorch",  # Type of the model (pytorch, tensorflow, sklearn, xgboost..)
        service="service.py:svc",  # Path to the service file within zenml repo
        labels={  # Labels to be added to the bento bundle
            "framework": "pytorch",
            "dataset": "mnist",
            "zenml_version": "0.21.1",
        },
        exclude=["data"],  # Exclude files from the bento bundle
    )
)
```

The Bento Builder step can be used in any orchestration pipeline that you create with ZenML. The step will build the
bento bundle and save it to the used artifact store. Which can be used to serve the model in a local setting using the
BentoML Model Deployer Step, or in a remote setting using the `bentoctl` or Yatai. This gives you the flexibility to
package your model in a way that is ready for different deployment scenarios.

#### ZenML BentoML Deployer step

We have now built our bento bundle, and we can use the built-in bento deployer step to deploy the bento bundle to our
local HTTP server. The following example shows how to call the built-in bento deployer step within a ZenML pipeline.

Note: the bentoml deployer step can only be used in a local environment.

```python
# Import the step and parameters class
from zenml.integrations.bentoml.steps import BentoMLDeployerParameters, bentoml_model_deployer_step,

# The name we gave to our deployed model
MODEL_NAME = "pytorch_mnist"

# Call the step with the parameters
bentoml_model_deployer = bentoml_model_deployer_step(
    params=BentoMLDeployerParameters(
        model_name=MODEL_NAME,  # Name of the model
        port=3001,  # Port to be used by the http server
        production=False,  # Deploy the model in production mode
    )
)
```

#### ZenML BentoML Pipeline examples

Once all the steps have been defined, we can create a ZenML pipeline and run it. The bento builder step expects to get
the trained model as an input, so we need to make sure either we have a previous step that trains the model and outputs
it or loads the model from a previous run. Then the deployer step expects to get the bento bundle as an input, so we
need to make sure either we have a previous step that builds the bento bundle and outputs it or load the bento bundle
from a previous run or external source.

The following example shows how to create a ZenML pipeline that trains a model, builds a bento bundle, and deploys it to
a local HTTP server.

```python
# Import the pipeline to use the pipeline decorator
from zenml.pipelines import pipeline


# Pipeline definition
@pipeline
def bentoml_pipeline(
        importer,
        trainer,
        evaluator,
        deployment_trigger,
        bento_builder,
        deployer,
):
    """Link all the steps and artifacts together"""
    train_dataloader, test_dataloader = importer()
    model = trainer(train_dataloader)
    accuracy = evaluator(test_dataloader=test_dataloader, model=model)
    decision = deployment_trigger(accuracy=accuracy)
    bento = bento_builder(model=model)
    deployer(deploy_decision=decision, bento=bento)

```

In more complex scenarios, you might want to build a pipeline that trains a model and builds a bento bundle in a remote
environment. Then creates a new pipeline that retrieves the bento bundle and deploys it to a local http server, or to a
cloud provider. The following example shows a pipeline example that does exactly that.

```python
# Import the pipeline to use the pipeline decorator
from zenml.pipelines import pipeline


# Pipeline definition
@pipeline
def remote_train_pipeline(
        importer,
        trainer,
        evaluator,
        bento_builder,
):
    """Link all the steps and artifacts together"""
    train_dataloader, test_dataloader = importer()
    model = trainer(train_dataloader)
    accuracy = evaluator(test_dataloader=test_dataloader, model=model)
    bento = bento_builder(model=model)


@pipeline
def local_deploy_pipeline(
        bento_loader,
        deployer,
):
    """Link all the steps and artifacts together"""
    bento = bento_loader()
    deployer(deploy_decision=decision, bento=bento)

```

#### Predicting with the local deployed model

Once the model has been deployed we can use the BentoML client to send requests to the deployed model. ZenML will
automatically create a BentoML client for you and you can use it to send requests to the deployed model by simply
calling the service to predict the method and passing the input data and the API function name.

The following example shows how to use the BentoML client to send requests to the deployed model.

```python
@step
def predictor(
        inference_data: Dict[str, List],
        service: BentoMLDeploymentService,
) -> None:
    """Run an inference request against the BentoML prediction service.

    Args:
        service: The BentoML service.
        data: The data to predict.
    """

    service.start(timeout=10)  # should be a NOP if already started
    for img, data in inference_data.items():
        prediction = service.predict("predict_ndarray", np.array(data))
        result = to_labels(prediction[0])
        rich_print(f"Prediction for {img} is {result}")
```

Deploying and testing locally is a great way to get started and test your model. However, a real-world scenario will
most likely require you to deploy your model to a remote environment. The next section will show you how to deploy the
Bento you built with ZenML pipelines to a cloud environment using the `bentoctl` CLI.

#### From Local to Cloud with `bentoctl`

Bentoctl helps deploy any machine learning models as production-ready API endpoints into the cloud. It is a command line
tool that provides a simple interface to manage your BentoML bundles.

The `bentoctl` CLI provides a list of operators which are plugins that interact with cloud services, some of these
operators are:

* [AWS Lambda](https://github.com/bentoml/aws-lambda-deploy)
* [AWS SageMaker](https://github.com/bentoml/aws-sagemaker-deploy)
* [AWS EC2](https://github.com/bentoml/aws-ec2-deploy)
* [Google Cloud Run](https://github.com/bentoml/google-cloud-run-deploy)
* [Google Compute Engine](https://github.com/bentoml/google-compute-engine-deploy)
* [Azure Container Instances](https://github.com/bentoml/azure-container-instances-deploy)
* [Heroku](https://github.com/bentoml/heroku-deploy)

To deploy your BentoML bundle to the cloud, you need to install the `bentoctl` CLI and the operator plugin for the cloud
service you want to deploy to.

```bash
# Install bentoctl CLI
pip install bentoctl
# Install a choose operator
bentoctl operator install $OPERATOR # example: aws-lambda
```

Once you have the `bentoctl` CLI and the operator plugin installed, you can use the `bentoctl` CLI to deploy your
BentoML bundle to the cloud.

```bash
# Let's get the name of the BentoML bundle we want to deploy
bentoml list

# Generate deployment configuration file
bentoctl init

# Build and push the docker image to the cloud
bentoctl build -b $BENTO_TAG -f deployment_config.yaml

# Deploy to the cloud
bentoctl apply -f deployment_config.yaml
```

You can check the BentoML deployment example for more details.

* [Model Deployer with BentoML](https://github.com/zenml-io/zenml/tree/main/examples/bentoml\_deployment)

For more information and a full list of configurable attributes of the BentoML Model Deployer, check out
the [API Docs](https://apidocs.zenml.io/latest/api\_docs/integration\_code\_docs/integrations-bentoml/#zenml.integrations.bentoml)
.
