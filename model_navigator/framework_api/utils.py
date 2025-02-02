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
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy
from polygraphy.backend.trt import Profile

from model_navigator.converter.config import TensorRTPrecision
from model_navigator.framework_api.common import Sample
from model_navigator.framework_api.exceptions import UserError
from model_navigator.model import Format
from model_navigator.utils import devices as devices_utils
from model_navigator.utils import enums


def get_supported_onnx_providers(exclude_trt: bool = False):
    gpu_available = bool(devices_utils.get_available_gpus())
    supported_providers = []
    if gpu_available:
        supported_providers.append(RuntimeProvider.CUDA)
    supported_providers.append(RuntimeProvider.CPU)
    if gpu_available and not exclude_trt:
        supported_providers.append(RuntimeProvider.TRT)
    return supported_providers


def get_available_onnx_providers(exclude_trt: bool = False) -> List:
    import onnxruntime as onnxrt  # pytype: disable=import-error

    supported_providers = get_supported_onnx_providers(exclude_trt=exclude_trt)
    available_providers = onnxrt.get_available_providers()
    onnx_providers = [prov for prov in supported_providers if prov in available_providers]
    return onnx_providers


def numpy_to_torch_dtype(np_dtype):
    np_dtype = numpy.dtype(np_dtype).type
    import torch  # pytype: disable=import-error

    return {
        numpy.bool_: torch.bool,
        numpy.uint8: torch.uint8,
        numpy.int8: torch.int8,
        numpy.int16: torch.int16,
        numpy.int32: torch.int32,
        numpy.int64: torch.int64,
        numpy.float16: torch.float16,
        numpy.float32: torch.float32,
        numpy.float64: torch.float64,
        numpy.complex64: torch.complex64,
        numpy.complex128: torch.complex128,
    }[np_dtype]


class Parameter(Enum):
    def __str__(self):
        return self.value

    @classmethod
    def to_yaml(cls, representer, node):
        return representer.represent_scalar(f"{cls.name}: {node._value_}")


class RuntimeProvider(str, Parameter):
    TRT = "TensorrtExecutionProvider"
    TRT_EXEC = "TrtexecExecutionProvider"
    CUDA = "CUDAExecutionProvider"
    CPU = "CPUExecutionProvider"
    TF = "TensorFlowExecutionProvider"
    PYT = "PyTorchExecutionProvider"


def format2runtimes(model_format: Format) -> Tuple:
    if model_format == Format.ONNX:
        return enums.parse(get_available_onnx_providers(), RuntimeProvider)
    elif model_format in (Format.TORCHSCRIPT, Format.TORCH_TRT):
        return (RuntimeProvider.PYT,)
    elif model_format in (Format.TF_SAVEDMODEL, Format.TF_TRT):
        return (RuntimeProvider.TF,)
    elif model_format == Format.TENSORRT:
        return (RuntimeProvider.TRT, RuntimeProvider.TRT_EXEC)
    else:
        return ()


class Status(str, Parameter):
    OK = "OK"
    FAIL = "FAIL"
    NOOP = "NOOP"
    INITIALIZED = "INITIALIZED"
    SKIPPED = "SKIPPED"


class Framework(Parameter):
    TF2 = "tensorflow2"
    PYT = "pytorch"
    ONNX = "onnx"
    JAX = "jax"


class Indent(str, Parameter):
    SINGLE = "  "
    DOUBLE = 2 * SINGLE
    TRIPLE = 3 * SINGLE


class Extension(Parameter):
    ONNX = "onnx"
    PT = "pt"
    SAVEDMODEL = "savedmodel"
    TRT = "plan"


class JitType(Parameter):
    SCRIPT = "script"
    TRACE = "trace"


def get_default_model_name():
    return "navigator_model"


def get_default_status_filename():
    return "status.yaml"


def get_default_workdir():
    return Path.cwd() / "navigator_workdir"


def get_default_max_workspace_size():
    return 8589934592


def pad_string(s: str):
    s = f"{30 * '='} {s} "
    s = s.ljust(100, "=")
    return s


def to_numpy(tensor, from_framework: Framework):
    if isinstance(tensor, numpy.ndarray):
        return tensor
    if from_framework == Framework.PYT:
        return tensor.detach().cpu().numpy()
    else:
        return tensor.numpy()


# pytype: disable=wrong-arg-types
# pytype: disable=attribute-error
def format_to_relative_model_path(
    format: Optional[Format] = None,
    jit_type: Optional[JitType] = None,
    precision: Optional[TensorRTPrecision] = None,
    enable_xla: Optional[bool] = None,
    jit_compile: Optional[bool] = None,
) -> Path:
    path_str = f"{format.value}"
    if jit_type:
        path_str += f"-{jit_type.value}"
    if enable_xla is True:
        path_str += "-xla"
    if jit_compile is True:
        path_str += "-jit"
    if precision:
        path_str += f"-{precision.value}"

    path = Path(path_str)

    if format == Format.ONNX:
        return path / "model.onnx"
    if format == Format.TORCHSCRIPT and jit_type:
        return path / "model.pt"
    if format == Format.TORCH_TRT and jit_type and precision:
        return path / "model.pt"
    if format == Format.TF_SAVEDMODEL:
        return path / "model.savedmodel"
    if format == Format.TF_TRT and precision:
        return path / "model.savedmodel"
    if format == Format.TENSORRT and precision:
        return path / "model.plan"
    else:
        raise Exception(
            f"No model path found for format: {format}, jit_type: {jit_type}, precision: {precision}, provide valid arguments or implmenet this method in your Command."
        )


# pytype: enable=wrong-arg-types
# pytype: enable=attribute-error


def sample_to_tuple(input: Any) -> Tuple[Any, ...]:
    if isinstance(input, Sequence):
        return tuple(input)
    if isinstance(input, Mapping):
        return tuple(input.values())
    return (input,)


def extract_sample(sample, input_metadata, framework: Framework) -> Sample:
    sample = sample_to_tuple(sample)
    sample = {n: to_numpy(t, framework) for n, t in zip(input_metadata, sample)}
    return sample


def extract_bs1(sample: Sample, batch_dim: Optional[int]) -> Sample:
    if batch_dim is not None:
        return {name: tensor.take([0], batch_dim) for name, tensor in sample.items()}
    return sample


def get_framework_export_formats(framework: Framework):
    return {
        Framework.PYT: {Format.TORCHSCRIPT, Format.ONNX},
        Framework.TF2: {
            Format.TF_SAVEDMODEL,
        },
        Framework.ONNX: {Format.ONNX},
        Framework.JAX: {Format.TF_SAVEDMODEL},
    }[framework]


def get_base_format(format: Format, framework: Framework):
    return {
        Framework.PYT: {
            Format.TENSORRT: Format.ONNX,
            Format.TORCH_TRT: Format.TORCHSCRIPT,
        },
        Framework.TF2: {
            Format.ONNX: Format.TF_SAVEDMODEL,
            Format.TENSORRT: Format.TF_SAVEDMODEL,
            Format.TF_TRT: Format.TF_SAVEDMODEL,
        },
        Framework.ONNX: {Format.TENSORRT: Format.ONNX},
        Framework.JAX: {
            Format.ONNX: Format.TF_SAVEDMODEL,
            Format.TENSORRT: Format.TF_SAVEDMODEL,
            Format.TF_TRT: Format.TF_SAVEDMODEL,
        },
    }[framework].get(format)


def is_tensor(tensor, framework: Framework):
    if framework == Framework.PYT:
        import torch  # pytype: disable=import-error

        return torch.is_tensor(tensor) or isinstance(tensor, numpy.ndarray)
    elif framework == Framework.TF2:
        import tensorflow  # pytype: disable=import-error

        return tensorflow.is_tensor(tensor) or isinstance(tensor, numpy.ndarray)
    else:
        return isinstance(tensor, numpy.ndarray)


def get_tensor_type_name(framework: Framework):
    if framework == Framework.PYT:
        return "Union[torch.Tensor, numpy.ndarray]"
    elif framework == Framework.TF2:
        return "Union[tensorflow.Tensor, numpy.ndarray]"
    else:
        return "numpy.ndarray"


def _is_valid_io(sample, framework):
    if is_tensor(sample, framework):
        return True
    if isinstance(sample, Mapping):
        for tensor in sample.values():
            if not is_tensor(tensor, framework):
                return False
        return True
    elif isinstance(sample, Iterable):
        for tensor in sample:
            if not is_tensor(tensor, framework):
                return False
        return True
    return False


def validate_sample_input(sample, framework: Framework):

    if not _is_valid_io(sample, framework):
        tensor_type = get_tensor_type_name(framework)
        raise UserError(
            f"Invalid sample type. Sample must be of type Union[{tensor_type}, Iterable[{tensor_type}], Mapping[str, {tensor_type}]]. Dataloader returned {sample}."
        )


def validate_sample_output(sample, framework: Framework):

    if not _is_valid_io(sample, framework):
        tensor_type = get_tensor_type_name(framework)
        raise UserError(
            f"Invalid model output type. Output must be of type Union[{tensor_type}, Iterable[{tensor_type}]], Mapping[str, {tensor_type}]]. Model returned {sample}."
        )


def load_samples(samples_name, workdir, batch_dim):
    if isinstance(workdir, str):
        workdir = Path(workdir)
    samples_type = samples_name.split("_")[0]
    samples_dirname = "model_output" if samples_name.split("_")[-1] == "output" else "model_input"
    samples_dirpath = workdir / samples_dirname / samples_type
    samples = []
    for sample_filepath in samples_dirpath.iterdir():
        sample = {}
        with numpy.load(sample_filepath.as_posix()) as data:
            for k, v in data.items():
                if batch_dim is not None:
                    v = numpy.expand_dims(v, batch_dim)
                    # v = numpy.repeat(v, max_batch_size, batch_dim)
                sample[k] = v
        samples.append(sample)
    if samples_type == "profiling":
        samples = samples[0]

    return samples


def get_trt_profile_from_trt_dynamic_axes(trt_dynamic_axes):
    trt_profile = Profile()
    if trt_dynamic_axes is None:
        return trt_profile
    for name, axes in trt_dynamic_axes.items():
        if axes:
            trt_profile.add(name, *list(zip(*list(axes.values()))))
    return trt_profile


def parse_kwargs_to_cmd(kwargs, quote_wrap_classes=None):
    if quote_wrap_classes is None:
        quote_wrap_classes = ()
    args = []
    for k, v in kwargs.items():
        s = str(v).replace("'", '"')
        args.extend([f"--{k}", f"'{s}'" if isinstance(v, quote_wrap_classes) else s])
    return args
