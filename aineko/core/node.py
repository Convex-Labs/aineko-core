# Copyright 2023 Aineko Authors
# SPDX-License-Identifier: Apache-2.0
"""Node base class and poison pill global actor.

Global variables that can be accessed by multiple nodes
should be stored in an actor instance (see
https://stackoverflow.com/questions/67457237/share-object-between-actors-in-ray).
The PoisonPill actor stores the boolean value that represents
if it should be activated or not. Upon activation, the Node Manager
will kill the entire pipeline. All nodes have access to this variable,
and can activate it by calling the `activate_poison_pill` method.

The AbstractNode class is the parent class for all Aineko pipeline nodes.
It contains  helper methods for setup, util methods, and dummy methods
that users should override with their own implementation.
"""
import time
import traceback
from abc import ABC, abstractmethod
from typing import Dict, Generator, List, Optional, Tuple

import ray

from aineko.config import (
    AINEKO_CONFIG,
    DEFAULT_KAFKA_CONFIG,
    TESTING_NODE_CONFIG,
)
from aineko.core.dataset import AbstractDataset
from aineko.datasets.kafka import (
    ConsumerParams,
    FakeDatasetInput,
    FakeDatasetOutput,
    ProducerParams,
)


class PoisonPill:
    """Global variable accessible to every node in pipeline.

    This is the recommended approach to share objects between
    Ray Actors.
    """

    def __init__(self) -> None:
        """Poison pill initializes with unactivated state."""
        self.state = False

    def activate(self) -> None:
        """Activate poison pill by setting state as True."""
        self.state = True

    def get_state(self) -> bool:
        """Gets poison pill state."""
        return self.state


class AbstractNode(ABC):
    """Node base class for all nodes in the pipeline.

    Nodes are the building blocks of the pipeline and are responsible for
    executing the pipeline. Nodes are designed to be modular and can be
    combined to create a pipeline. The node base class provides helper methods
    for setting up the consumer and producer for a node. The execute method is
    a wrapper for the _execute method which is to be implemented by subclasses.
    The _execute method is where the node logic is implemented by the user.

    Attributes:
        name (str): name of the node
        pipeline_name (str): name of the pipeline
        params (dict): dict of parameters to be used by the node
        inputs (dict): dict of AbstractDataset objects for inputs that node
            can read / consume.
        outputs (dict): dict of AbstractDataset objects for outputs that node
            can write / produce.
        last_hearbeat (float): timestamp of the last heartbeat
        test (bool): True if node is in test mode else False
        log_levels (tuple): tuple of allowed log levels
        local_state (dict): shared local state between nodes. Used for intra-
            pipeline communication without dataset dependency.

    Methods:
        setup_datasets: setup the consumers and producers for a node
        execute: execute the node, wrapper for _execute method
        _execute: execute the node, to be implemented by subclasses
    """

    def __init__(
        self,
        pipeline_name: str,
        node_name: Optional[str] = None,
        poison_pill: Optional[ray.actor.ActorHandle] = None,
        test: bool = False,
    ) -> None:
        """Initialize the node."""
        self.name = node_name or self.__class__.__name__
        self.pipeline_name = pipeline_name
        self.last_heartbeat = time.time()
        self.inputs: dict = {}
        self.outputs: dict = {}
        self.params: Dict = {}
        self.test = test
        self.log_levels = AINEKO_CONFIG.get("LOG_LEVELS")
        self.poison_pill = poison_pill

    def enable_test_mode(self) -> None:
        """Enable test mode."""
        self.test = True

    def setup_datasets(
        self,
        datasets: Dict[str, Dict],
        inputs: Optional[List[str]] = None,
        outputs: Optional[List[str]] = None,
        prefix: Optional[str] = None,
        has_pipeline_prefix: bool = False,
    ) -> None:
        """Setup the consumer and producer for a node.

        Args:
            datasets: dataset configuration
            inputs: list of dataset names for the inputs to the node
            outputs: list of dataset names for the outputs of the node
            prefix: prefix for topic name (`<prefix>.<dataset_name>`)
            has_pipeline_prefix: whether the dataset name has pipeline name
                prefix
        """
        inputs = inputs or []
        # initialize the datasets:
        self.inputs.update(
            {
                dataset_name: AbstractDataset.from_config(
                    name=dataset_name, config=datasets.get(dataset_name, {})
                )
                for dataset_name in inputs
            }
        )

        outputs = outputs or []
        self.outputs.update(
            {
                dataset_name: AbstractDataset.from_config(
                    name=dataset_name, config=datasets.get(dataset_name, {})
                )
                for dataset_name in outputs
            }
        )

        for dataset_name in inputs:
            if self.inputs[dataset_name].type == "kafka":
                consumer_params = ConsumerParams(
                    **{
                        "dataset_name": dataset_name,
                        "node_name": self.name,
                        "pipeline_name": self.pipeline_name,
                        "prefix": prefix,
                        "has_pipeline_prefix": has_pipeline_prefix,
                        "consumer_config": DEFAULT_KAFKA_CONFIG.get(
                            "CONSUMER_CONFIG"
                        ),
                    }
                )
                self.inputs[dataset_name].initialize(
                    create_consumer=True, connection_params=consumer_params
                )
        for dataset_name in outputs:
            if self.outputs[dataset_name].type == "kafka":
                producer_params = ProducerParams(
                    **{
                        "dataset_name": dataset_name,
                        "node_name": self.name,
                        "pipeline_name": self.pipeline_name,
                        "prefix": prefix,
                        "has_pipeline_prefix": has_pipeline_prefix,
                        "producer_config": DEFAULT_KAFKA_CONFIG.get(
                            "PRODUCER_CONFIG"
                        ),
                    }
                )
                self.outputs[dataset_name].initialize(
                    create_producer=True, connection_params=producer_params
                )

    def setup_test(
        self,
        inputs: Optional[dict] = None,
        outputs: Optional[list] = None,
        params: Optional[dict] = None,
    ) -> None:
        """Setup the node for testing.

        Args:
            inputs: inputs to the node, format should be {"dataset": [1, 2, 3]}
            outputs: outputs of the node, format should be ["dataset_1",
                "dataset_2", ...]
            params: dictionary of parameters to make accessible to _execute

        Raises:
            RuntimeError: if node is not in test mode
        """
        if self.test is False:
            raise RuntimeError(
                "Node is not in test mode. "
                "Please initialize with `enable_test_mode()`."
            )

        inputs = inputs or {}

        self.inputs = {
            dataset_name: FakeDatasetInput(
                dataset_name=dataset_name,
                node_name=self.__class__.__name__,
                values=values,
            )
            for dataset_name, values in inputs.items()
        }
        outputs = outputs or []
        outputs.extend(TESTING_NODE_CONFIG.get("DATASETS"))

        self.outputs = {
            dataset_name: FakeDatasetOutput(
                dataset_name=dataset_name,
                node_name=self.__class__.__name__,
            )
            for dataset_name in outputs
        }
        self.params = params or {}

    def log(self, message: str, level: str = "info") -> None:
        """Log a message to the logging dataset.

        Args:
            message: Message to log
            level: Logging level. Defaults to "info". Options are:
                "info", "debug", "warning", "error", "critical"
        Raises:
            ValueError: if invalid logging level is provided
        """
        if level not in self.log_levels:
            raise ValueError(
                f"Invalid logging level {level}. Valid options are: "
                f"{', '.join(self.log_levels)}"
            )
        out_msg = {"log": message, "level": level}

        self.outputs[DEFAULT_KAFKA_CONFIG.get("LOGGING_DATASET")].write(out_msg)

    def _log_traceback(self) -> None:
        """Logs the traceback of an exception."""
        exc_info = traceback.format_exc()
        self.log(exc_info, level="debug")

    def execute(self, params: Optional[dict] = None) -> None:
        """Execute the node.

        Wrapper for _execute method to be implemented by subclasses.

        Args:
            params: Parameters to use to execute the node. Defaults to None.
        """
        params = params or {}
        run_loop = True

        try:
            self._pre_loop_hook(params)
        except Exception:  # pylint: disable=broad-except
            self._log_traceback()
            raise

        while run_loop is not False:
            # Monitoring
            try:
                run_loop = self._execute(params)  # type: ignore
            except Exception:  # pylint: disable=broad-except
                self._log_traceback()
                raise

        self.log(f"Execution loop complete for node: {self.__class__.__name__}")
        self._post_loop_hook(params)

    def activate_poison_pill(self) -> None:
        """Activates poison pill, shutting down entire pipeline."""
        if self.poison_pill:
            ray.get(self.poison_pill.activate.remote())

    @abstractmethod
    def _execute(self, params: dict) -> Optional[bool]:
        """Execute the node.

        Args:
            params: Parameters to use to execute the node.

        Note:
            Method to be implemented by subclasses

        Raises:
            NotImplementedError: if method is not implemented in subclass
        """
        raise NotImplementedError("_execute method not implemented")

    def run_test(self, runtime: Optional[int] = None) -> dict:
        """Execute the node in testing mode.

        Runs the steps in execute that involves the user defined methods.
        Includes pre_loop_hook, _execute, and post_loop_hook.

        Args:
            runtime: Number of seconds to run the execute loop for.

        Returns:
            dict: dataset names and values produced by the node.
        """
        if self.test is False:
            raise RuntimeError(
                "Node is not in test mode. "
                "Please initialize with `enable_test_mode()`."
            )
        run_loop = True
        start_time = time.time()

        self._pre_loop_hook(self.params)
        while run_loop is not False:
            run_loop = self._execute(self.params)  # type: ignore

            # Do not end loop if runtime not exceeded
            if runtime is not None:
                if time.time() - start_time < runtime:
                    continue

            # End loop if all inputs are empty
            if self.inputs and all(
                input.empty for input in self.inputs.values()
            ):
                run_loop = False

        self._post_loop_hook(self.params)

        return {
            dataset_name: output.values
            for dataset_name, output in self.outputs.items()
        }

    def run_test_yield(
        self, runtime: Optional[int] = None
    ) -> Generator[Tuple[dict, dict, "AbstractNode"], None, None]:
        """Execute the node in testing mode, yielding at each iteration.

        This method is an alternative to `run_test`. Instead of returning the
        aggregated output, it yields the most recently consumed value, the
        produced value and the current node instance at each iteration. This is
        useful for testing nodes that either don't produce any output or if you
        need to test intermediate outputs. Testing state modifications is also
        possible using this method.

        Args:
            runtime: Number of seconds to run the execute loop for.

        Yields:
            A tuple containing the most recent input value, output value and
            the node instance.

        Example:
            >>> for input, output, node_instance in sequencer.run_test_yield():
            >>>     print(f"Input: {input}, Output: {output})
            >>>     print(f"Node Instance: {node_instance}")
        """
        if self.test is False:
            raise RuntimeError(
                "Node is not in test mode. "
                "Please initialize with `enable_test_mode()`."
            )
        run_loop = True
        start_time = time.time()

        self._pre_loop_hook(self.params)
        while run_loop is not False:
            last_produced_values = {}
            last_consumed_values = {}

            # Capture last consumed values
            for dataset_name, input_dataset in self.inputs.items():
                if input_dataset.values:
                    last_value = input_dataset.values[0]
                    last_consumed_values[dataset_name] = last_value

            run_loop = self._execute(self.params)  # type: ignore

            # Do not end loop if runtime not exceeded
            if runtime is not None:
                if time.time() - start_time < runtime:
                    continue

            # End loop if all consumers are empty
            if self.inputs and all(
                input.empty for input in self.inputs.values()
            ):
                run_loop = False

            # Capture last produced values
            for dataset_name, output in self.outputs.items():
                if output.values:
                    last_value = output.values[-1]
                    last_produced_values[dataset_name] = last_value

            yield (last_consumed_values, last_produced_values, self)

        self._post_loop_hook(self.params)

    def _pre_loop_hook(self, params: Optional[dict] = None) -> None:
        """Hook to be called before the node loop. User overrideable.

        Args:
            params: Parameters to use to execute the node.

        Note:
            Method (optional) to be implemented by subclasses.
        """
        pass

    def _post_loop_hook(self, params: Optional[dict] = None) -> None:
        """Hook to be called after the node loop. User overrideable.

        Args:
            params: Parameters to use to execute the node.

        Note:
            Method (optional) to be implemented by subclasses.
        """
        pass
