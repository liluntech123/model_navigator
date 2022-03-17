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

from model_navigator.framework_api.commands.config_gen.config_cli import ConfigCli
from model_navigator.framework_api.commands.convert.onnx import ConvertONNX2TRT
from model_navigator.framework_api.commands.correctness.pyt import (
    CorrectnessPYT2ONNX,
    CorrectnessPYT2TorchScript,
    CorrectnessPYT2TRT,
)
from model_navigator.framework_api.commands.data_dump.samples import (
    DumpInputModelData,
    DumpOutputModelData,
    FetchInputModelData,
)
from model_navigator.framework_api.commands.export.pyt import (
    ExportPYT2ONNX,
    ExportPYT2TorchScript,
    ExportPYT2TorchTensorRT,
)
from model_navigator.framework_api.commands.infer_metadata import InferInputMetadata, InferOutputMetadata
from model_navigator.framework_api.commands.performance.onnx import PerformanceONNX
from model_navigator.framework_api.commands.performance.pyt import PerformanceTorchScript
from model_navigator.framework_api.commands.performance.trt import PerformanceTRT
from model_navigator.framework_api.pipelines.pipeline import Pipeline
from model_navigator.framework_api.pipelines.pipeline_manager_base import PipelineManager
from model_navigator.framework_api.utils import Framework, RuntimeProvider
from model_navigator.model import Format


class TorchPipelineManager(PipelineManager):
    def _get_pipeline(self, config) -> Pipeline:
        infer_input = InferInputMetadata()
        fetch_input = FetchInputModelData(requires=(infer_input,))
        infer_output = InferOutputMetadata(requires=(infer_input, fetch_input))
        commands = [infer_input, fetch_input, infer_output]
        if Format.TORCHSCRIPT in config.target_formats:
            for target_jit_type in config.target_jit_type:
                export = ExportPYT2TorchScript(
                    target_jit_type=target_jit_type, requires=(infer_input, fetch_input, infer_output)
                )
                commands.append(export)
                commands.append(
                    CorrectnessPYT2TorchScript(
                        target_format=Format.TORCHSCRIPT, target_jit_type=target_jit_type, requires=(export,)
                    )
                )
                commands.append(
                    PerformanceTorchScript(
                        target_format=Format.TORCHSCRIPT, target_jit_type=target_jit_type, requires=(export,)
                    )
                )
                commands.append(
                    ConfigCli(target_format=Format.TORCHSCRIPT, target_jit_type=target_jit_type, requires=(export,))
                )
        if Format.ONNX in config.target_formats:
            onnx_export = ExportPYT2ONNX(requires=(infer_input, fetch_input, infer_output))
            commands.append(onnx_export)
            for provider in [RuntimeProvider.CUDA, RuntimeProvider.TRT, RuntimeProvider.CPU]:
                commands.append(CorrectnessPYT2ONNX(runtime_provider=provider, requires=(onnx_export,)))
                commands.append(PerformanceONNX(runtime_provider=provider, requires=(onnx_export,)))
            commands.append(ConfigCli(target_format=Format.ONNX, requires=(onnx_export,)))
        if Format.TORCH_TRT in config.target_formats:
            for target_jit_type in config.target_jit_type:
                export = ExportPYT2TorchTensorRT(
                    target_jit_type=target_jit_type, requires=(infer_input, fetch_input, infer_output)
                )
                commands.append(export)
                commands.append(
                    CorrectnessPYT2TorchScript(
                        target_format=Format.TORCH_TRT, target_jit_type=target_jit_type, requires=(export,)
                    )
                )
                commands.append(
                    PerformanceTorchScript(
                        target_format=Format.TORCH_TRT, target_jit_type=target_jit_type, requires=(export,)
                    )
                )
                commands.append(
                    ConfigCli(target_format=Format.TORCH_TRT, target_jit_type=target_jit_type, requires=(export,))
                )
        if Format.TENSORRT in config.target_formats:
            if Format.ONNX not in config.target_formats:
                onnx_export = ExportPYT2ONNX(requires=(infer_input, fetch_input, infer_output))
                commands.append(onnx_export)
                for provider in [RuntimeProvider.CUDA, RuntimeProvider.TRT, RuntimeProvider.CPU]:
                    commands.append(CorrectnessPYT2ONNX(runtime_provider=provider, requires=(onnx_export,)))
                    commands.append(PerformanceONNX(runtime_provider=provider, requires=(onnx_export,)))
            for target_precision in config.target_precisions:
                convert = ConvertONNX2TRT(target_precision=target_precision, requires=(onnx_export,))
                commands.append(convert)
                commands.append(CorrectnessPYT2TRT(target_precision=target_precision, requires=(convert,)))
                commands.append(PerformanceTRT(target_precision=target_precision, requires=(convert,)))
                commands.append(
                    ConfigCli(target_format=Format.TENSORRT, target_precision=target_precision, requires=(convert,))
                )

        if config.save_data:
            commands.append(DumpInputModelData(requires=(infer_input, fetch_input)))
            commands.append(DumpOutputModelData(requires=(fetch_input, infer_output)))
        return Pipeline(name="PyTorch pipeline", framework=Framework.PYT, commands=commands)
