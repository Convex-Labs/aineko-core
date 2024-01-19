# Copyright 2023 Aineko Authors
# SPDX-License-Identifier: Apache-2.0
"""Module to load config files."""
import logging
import os
import re
from typing import overload

from pydantic import ValidationError

from aineko.config import AINEKO_CONFIG
from aineko.models.config_schema import Config
from aineko.utils.io import load_yaml

logger = logging.getLogger(__name__)

NodeParamTypes = dict | list | str | int | float | bool | None


class ConfigLoader:
    """Class to read yaml config files.

    Args:
        pipeline_config_file: path of pipeline config file. Defaults
        to `DEFAULT_PIPELINE_CONFIG`.

    Attributes:
        pipeline_config_file (str): path to the pipeline configuration file
        config_schema (Config): Pydantic model to validate a pipeline config

    Methods:
        load_config: loads and validates the pipeline config from a yaml file
        inject_env_vars: injects environment variables into node params
    """

    def __init__(
        self,
        pipeline_config_file: str,
    ):
        """Initialize ConfigLoader."""
        self.pipeline_config_file = pipeline_config_file or AINEKO_CONFIG.get(
            "DEFAULT_PIPELINE_CONFIG"
        )

        # Setup config schema
        self.config_schema = Config

    def load_config(self) -> dict:
        """Load and validate the pipeline config.

        Raises:
            ValidationError: If the config does not match the schema

        Returns:
            The pipeline config as a dictionary
        """
        config = load_yaml(self.pipeline_config_file)

        try:
            Config(**config)
        except ValidationError as e:
            logger.error(
                "Schema validation failed for pipeline `%s` loaded from %s. "
                "See detailed error below.",
                config["pipeline"]["name"],
                self.pipeline_config_file,
            )
            raise e

        # Inject environment variables into node params
        for node in config["pipeline"]["nodes"].values():
            if "node_params" in node and node["node_params"] is not None:
                node["node_params"] = self.inject_env_vars(node["node_params"])

        return config

    @overload
    def _update_params(self, value: dict, params: dict) -> dict:
        ...

    @overload
    def _update_params(self, value: list, params: dict) -> list:
        ...

    @overload
    def _update_params(self, value: str, params: dict) -> str:
        ...

    @overload
    def _update_params(self, value: int, params: dict) -> int:
        ...

    def _update_params(
        self, value: dict | list | str | int, params: dict
    ) -> dict | list | str | int:
        """Update value with params.

        Recursively calls the method if value is a list or dictionary until it
        reaches a string or int. If string then formats the str with variable
        mapping in params dict.

        Args:
            value: value to update
            params: params to update value with

        Returns:
            object with updated values (dict, list, str, or int)
        """
        if isinstance(value, dict):
            new_dict_val = {}
            for key, val in value.items():
                new_dict_val[key] = self._update_params(val, params)
            return new_dict_val
        if isinstance(value, list):
            new_list_val: list = []
            for val in value:
                new_list_val.append(self._update_params(val, params))
            return new_list_val
        if isinstance(value, str):
            for key, val in params.items():
                value = value.replace(f"${key}", val)
            return value
        if isinstance(value, (int, float)):
            return value
        raise ValueError(
            f"Invalid value type {type(value)}. "
            "Expected dict, list, str, or int."
        )

    @overload
    def inject_env_vars(self, node_params: dict) -> dict:
        ...

    @overload
    def inject_env_vars(self, node_params: list) -> list:
        ...

    @overload
    def inject_env_vars(self, node_params: str) -> str:
        ...

    @overload
    def inject_env_vars(self, node_params: int) -> int:
        ...

    @overload
    def inject_env_vars(self, node_params: float) -> float:
        ...

    @overload
    def inject_env_vars(self, node_params: None) -> None:
        ...

    def inject_env_vars(self, node_params: NodeParamTypes) -> NodeParamTypes:
        """Inject environment variables into node params.

        This function is used to recursively inject environment variables
        into strings passed through node params via the pipeline config.
        We only recursively parse strings, dicts, and lists, as these are
        the only types that can contain environment variables (i.e.
        excluding ints, floats, and Nones).

        Environment variables are identified in strings by the pattern
        {$ENV_VAR} where ENV_VAR is the name of the environment variable
        to inject. For example, given the following environment variables:

        ```
        $ export SECRET1=secret1
        $ export SECRET2=secret2
        ```

        The following node params dict:

            ```
            {
                "key1": "A string with a {$SECRET1} and a {$SECRET2}.",
                "key2": {
                    "key3": "A string with a {$SECRET1} and a {$SECRET2}.",
                    "key4": [
                        "A string with a {$SECRET1} and a {$SECRET2}.",
                        "A string with a {$SECRET1} and a {$SECRET2}."
                    ]
                }
            }
            ```

        Will be transformed to:

                ```
                {
                    "key1": "A string with a secret1 and a secret2.",
                    "key2": {
                        "key3": "A string with a secret1 and a secret2.",
                        "key4": [
                            "A string with a secret1 and a secret2.",
                            "A string with a secret1 and a secret2."
                        ]
                    }
                }
                ```
        """
        if isinstance(node_params, dict):
            for k, v in list(node_params.items()):
                node_params[k] = self.inject_env_vars(v)
        elif isinstance(node_params, list):
            for i, v in enumerate(node_params):
                node_params[i] = self.inject_env_vars(v)
        elif isinstance(node_params, str):
            env_var_pattern = r"\{\$.*?\}"
            env_var_match = re.search(env_var_pattern, node_params, re.DOTALL)
            if env_var_match:
                env_var_env_str = env_var_match.group()
                env_var_value = os.getenv(
                    env_var_env_str[2:][:-1], default=None
                )
                if env_var_value is None:
                    raise ValueError(
                        "Failed to inject environment variable. "
                        f"{env_var_env_str[2:][:-1]} was not found."
                    )
                node_params = node_params.replace(
                    env_var_env_str, env_var_value
                )
                return self.inject_env_vars(node_params)

        return node_params
