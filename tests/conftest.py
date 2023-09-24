"""Aineko test fixtures."""
import datetime
import os
import time
from typing import Optional

import pytest

from aineko import AbstractNode, ConfigLoader, Runner


@pytest.fixture(scope="module")
def conf_directory():
    """Config directory fixture.

    Returns:
        str: Path to config directory
    """
    return os.path.join(os.path.dirname(__file__), "conf")


@pytest.fixture(scope="module")
def test_pipeline_config_file(conf_directory: str):
    """Pipeline config file fixture.

    Returns:
        str: Path to pipeline config file
    """
    return os.path.join(conf_directory, "test_pipeline.yml")


@pytest.fixture(scope="module")
def test_pipeline_config_file_runs(conf_directory: str):
    """Pipeline config file with runs fixture.

    Returns:
        str: Path to pipeline config with runs file
    """
    return os.path.join(conf_directory, "test_pipeline_runs.yml")


# Aineko test fixtures.


@pytest.fixture(scope="module")
def config_loader(test_pipeline_config_file: str):
    """Config loader fixture.

    Returns:
        ConfigLoader: Test config loader
    """
    return ConfigLoader(
        pipeline_config_file=test_pipeline_config_file,
    )


@pytest.fixture(scope="module")
def config_loader_runs(test_pipeline_config_file_runs: str):
    """Config loader fixture for pipeline config with runs.

    Returns:
        ConfigLoader: Test config loader
    """
    return ConfigLoader(
        pipeline_config_file=test_pipeline_config_file_runs,
        pipeline="test_run_1",
    )


@pytest.fixture(scope="module")
def runner(test_pipeline_config_file: str):
    """Runner fixture.

    Returns:
        Runner: Test runner
    """
    return Runner(pipeline_config_file=test_pipeline_config_file)


@pytest.fixture(scope="module")
def dummy_node():
    """Creates dummy node."""

    class DummyNode(AbstractNode):
        """Dummy node that passes through messages."""

        def _execute(self, params: Optional[dict] = None) -> Optional[bool]:
            """Consumes message from input and outputs it to output."""
            msg = self.consumers["input"].consume(how="next", timeout=0)
            self.producers["output"].produce(msg)

    return DummyNode


# Test nodes.


@pytest.fixture(scope="module")
def test_sequencer_node():
    """Returns a sample sequencer node."""

    class TestSequencer(AbstractNode):
        """Test sequencer node."""

        def _pre_loop_hook(self, params: Optional[dict] = None) -> None:
            """Pre loop hook."""
            self.cur_integer = int(params.get("start_int", 0))
            self.num_messages = 0
            self.log(f"Starting at {self.cur_integer}", level="info")

        def _execute(self, params: Optional[dict] = None) -> None:
            """Generates a sequence of integers and writes them to a dataset.

            Args:
                params: Parameters for the node
            """
            # Break if duration has been exceeded
            if self.num_messages >= params.get("num_messages", 25):
                return False

            # Write message to producer
            self.producers["integer_sequence"].produce(self.cur_integer)
            self.log(f"Produced {self.cur_integer}", level="info")
            self.log("Just a red herring", level="error")
            self.num_messages += 1

            # Increment integer and sleep
            self.cur_integer += 1
            time.sleep(params.get("sleep_time", 1))

    return TestSequencer


@pytest.fixture(scope="module")
def test_doubler_node():
    """Returns a sample doubler node."""

    class TestDoubler(AbstractNode):
        """Test doubler node."""

        def _pre_loop_hook(self, params: Optional[dict] = None) -> None:
            """Initializes node with current time.

            Args:
                params: Defaults to None.
            """
            self.cur_time = time.time()

        def _execute(self, params: Optional[dict] = None) -> None:
            """Generates a sequence of integers and writes them to a dataset.

            Args:
                params: Parameters for the node
            """
            # Break if duration has been exceeded
            if time.time() - self.cur_time > params.get("duration", 30):
                return False

            # Read message from consumer
            cur_integer = self.consumers["integer_sequence"].consume(
                how="next", timeout=0
            )

            # Validate message
            if cur_integer is None:
                return

            # Calculate latency
            latency = (
                time.time()
                - datetime.datetime.strptime(
                    cur_integer["timestamp"], "%Y-%m-%d %H:%M:%S.%f"
                ).timestamp()
            )

            # Log message
            self.log(
                f"Consumed: {cur_integer} - "
                f"Latency (ms): {round(latency*1000, 2)}",
                level="info",
            )

            # Convert message to integer
            cur_integer = int(cur_integer["message"])

            # Write message to producer
            self.producers["integer_doubles"].produce(cur_integer * 2)
            self.log(f"Produced {cur_integer * 2}", level="info")

    return TestDoubler
