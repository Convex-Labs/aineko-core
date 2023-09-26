"""Tests for deploy_config models."""

import pytest
from pydantic import ValidationError

from aineko.models.deploy_config_schema import DeploymentConfig


def test_deployment_config(pipeline_config, pipelines_config):
    """Test DeploymentConfig model."""
    deploy = {
        "project": "test_project",
        "version": "1.0.0",
        "defaults": {
            "machine_config": {"type": "ec2", "mem_gib": 16, "vcpu": 4},
            "env_vars": {"key": "value"},
        },
        "pipelines": {
            "test_pipeline": pipeline_config,
        },
        "environments": {"develop": pipelines_config},
    }
    assert DeploymentConfig(**deploy)

    # Fail if extra keys are added
    deploy["extra"] = "extra"
    with pytest.raises(ValidationError):
        DeploymentConfig(**deploy)
