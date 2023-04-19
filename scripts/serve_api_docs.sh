#!/usr/bin/env bash
set -e
set -x

SRC=${1:-"src/zenml"}

export ZENML_DEBUG=1
export ZENML_ANALYTICS_OPT_IN=false
rm -rf docs/mkdocs/core_python_sdk_docs || true
rm -rf docs/mkdocs/integration_code_docs || true
rm docs/mkdocs/index.md || true

python docs/mkdocstrings_helper.py --path $SRC --output_path docs/mkdocs/
cd docs
mkdocs serve
