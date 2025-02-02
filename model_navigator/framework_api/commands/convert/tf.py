# Copyright (c) 2021-2022, NVIDIA CORPORATION. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from pathlib import Path
from typing import Optional, Tuple

from model_navigator.converter.config import TensorRTPrecision
from model_navigator.framework_api.commands.convert.base import ConvertBase
from model_navigator.framework_api.commands.convert.converters import sm2tftrt
from model_navigator.framework_api.commands.core import Command, CommandType
from model_navigator.framework_api.execution_context import ExecutionContext
from model_navigator.framework_api.logger import LOGGER
from model_navigator.framework_api.utils import Status, format_to_relative_model_path, parse_kwargs_to_cmd
from model_navigator.model import Format
from model_navigator.utils import devices


class ConvertSavedModel2ONNX(ConvertBase):
    def __init__(
        self, enable_xla: Optional[bool] = None, jit_compile: Optional[bool] = None, requires: Tuple[Command, ...] = ()
    ):
        # pytype: disable=wrong-arg-types
        super().__init__(
            name="Convert SavedModel to ONNX",
            command_type=CommandType.CONVERT,
            target_format=Format.ONNX,
            requires=requires,
        )
        self.enable_xla = enable_xla
        self.jit_compile = jit_compile
        # pytype: enable=wrong-arg-types

    def __call__(
        self,
        workdir: Path,
        opset: int,
        model_name: str,
        verbose: bool,
        **kwargs,
    ):
        LOGGER.info("SavedModel to ONNX conversion started")
        exported_model_path = workdir / format_to_relative_model_path(
            format=Format.TF_SAVEDMODEL,
            enable_xla=self.enable_xla,
            jit_compile=self.jit_compile,
        )

        converted_model_path = workdir / self.get_output_relative_path()

        if converted_model_path.exists():
            LOGGER.info("Model already exists. Skipping conversion.")
            return self.get_output_relative_path()
        if not exported_model_path.exists():
            LOGGER.warning(f"Exported SavedModel model not found at {exported_model_path}. Skipping conversion")
            self.status = Status.SKIPPED
            return

        convert_cmd = [
            "python",
            "-m",
            "tf2onnx.convert",
            "--saved-model",
            exported_model_path.relative_to(workdir).as_posix(),
            "--output",
            converted_model_path.relative_to(workdir).as_posix(),
            "--opset",
            str(opset),
        ]

        with ExecutionContext(
            workdir=workdir,
            cmd_path=converted_model_path.parent / "reproduce_conversion.sh",
            verbose=verbose,
        ) as context:
            context.execute_cmd(convert_cmd)

        return self.get_output_relative_path()


class ConvertSavedModel2TFTRT(ConvertBase):
    def __init__(
        self,
        target_precision: TensorRTPrecision,
        enable_xla: Optional[bool] = None,
        jit_compile: Optional[bool] = None,
        requires: Tuple[Command, ...] = (),
    ):
        # pytype: disable=wrong-arg-types
        super().__init__(
            name="Convert SavedModel to TF-TRT",
            command_type=CommandType.CONVERT,
            target_format=Format.TF_TRT,
            requires=requires,
        )
        self.target_precision = target_precision
        self.enable_xla = enable_xla
        self.jit_compile = jit_compile
        # pytype: enable=wrong-arg-types

    def __call__(
        self,
        max_workspace_size: int,
        minimum_segment_size: int,
        workdir: Path,
        model_name: str,
        verbose: bool,
        batch_dim: Optional[int] = None,
        **kwargs,
    ) -> Optional[Path]:
        LOGGER.info("SavedModel to TF-TRT conversion started")
        if not devices.get_available_gpus():
            raise RuntimeError("No GPUs available.")

        exported_model_path = workdir / format_to_relative_model_path(
            format=Format.TF_SAVEDMODEL,
            enable_xla=self.enable_xla,
            jit_compile=self.jit_compile,
        )
        converted_model_path = workdir / self.get_output_relative_path()
        converted_model_path.parent.mkdir(parents=True, exist_ok=True)

        if converted_model_path.exists():
            LOGGER.info("Model already exists. Skipping conversion.")
            return self.get_output_relative_path()
        if not exported_model_path.exists():
            LOGGER.warning(f"Exported SavedModel model not found at {exported_model_path}. Skipping conversion")
            self.status = Status.SKIPPED
            return

        with ExecutionContext(
            workdir=workdir,
            script_path=converted_model_path.parent / "reproduce_conversion.py",
            cmd_path=converted_model_path.parent / "reproduce_conversion.sh",
            verbose=verbose,
        ) as context:
            kwargs = {
                "exported_model_path": exported_model_path.relative_to(workdir).as_posix(),
                "converted_model_path": converted_model_path.relative_to(workdir).as_posix(),
                "max_workspace_size": max_workspace_size,
                "target_precision": self.target_precision.value,
                "minimum_segment_size": minimum_segment_size,
                "batch_dim": batch_dim,
                "navigator_workdir": workdir.as_posix(),
            }

            args = parse_kwargs_to_cmd(kwargs, (list, dict, tuple))

            context.execute_external_runtime_script(sm2tftrt.__file__, args)

        return self.get_output_relative_path()
