"""RunPod worker for video upscaling and frame interpolation."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import os
import shutil
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import runpod
import websocket
from PIL import Image


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("runpod-studio-upscale-interpolation")

SERVER_ADDRESS = os.getenv("SERVER_ADDRESS", "127.0.0.1")
COMFY_URL = f"http://{SERVER_ADDRESS}:8188"
COMFY_ROOT = Path("/ComfyUI")
COMFY_INPUT = COMFY_ROOT / "input"
COMFY_OUTPUT = COMFY_ROOT / "output"
COMFY_TEMP = COMFY_ROOT / "temp"
WORKFLOW_DIR = Path(__file__).resolve().parent / "workflow"
RUNPOD_VOLUME = Path("/runpod-volume")

TASK_ALIASES = {
    "upscale": "upscale",
    "video_upscale": "upscale",
    "interpolation": "interpolation",
    "video_interpolation": "interpolation",
    "upscale_and_interpolation": "upscale_and_interpolation",
    "video_upscale_and_interpolation": "upscale_and_interpolation",
}


def _check_cuda() -> None:
    try:
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required but is not available")
        os.environ["CUDA_VISIBLE_DEVICES"] = "0"
        logger.info(
            "stage=bootstrap cuda=available device=%s vram_mb=%s",
            torch.cuda.get_device_name(0),
            round(torch.cuda.get_device_properties(0).total_memory / 1024**2),
        )
    except Exception as exc:
        logger.exception("stage=bootstrap cuda_check_failed")
        raise RuntimeError(f"CUDA initialization failed: {exc}") from exc


_check_cuda()


def _error(stage: str, code: str, message: str) -> dict[str, Any]:
    safe_message = str(message).replace("\n", " ")[:1000]
    logger.error("stage=%s code=%s error=%s", stage, code, safe_message)
    return {"error": safe_message, "stage": stage, "code": code}


def _input_value(job_input: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = job_input.get(name)
        if value not in (None, ""):
            return value
    return None


def _safe_task_type(value: Any) -> str:
    normalized = str(value or "upscale").strip().lower()
    if normalized not in TASK_ALIASES:
        raise ValueError(
            "task_type must be one of: upscale, interpolation, "
            "upscale_and_interpolation"
        )
    return TASK_ALIASES[normalized]


def _safe_name(name: str, default_suffix: str) -> str:
    parsed = urllib.parse.urlparse(name)
    candidate = Path(parsed.path).name or f"input{default_suffix}"
    return candidate.replace("..", "_")


def _decode_input(job_input: dict[str, Any], task_dir: Path, input_type: str) -> Path:
    if input_type == "video":
        path_value = _input_value(job_input, "video_path")
        url_value = _input_value(job_input, "video_url")
        encoded_value = _input_value(job_input, "video_base64")
        default_name = "input_video.mp4"
    else:
        path_value = _input_value(job_input, "image_path")
        url_value = _input_value(job_input, "image_url")
        encoded_value = _input_value(job_input, "image_base64")
        default_name = "input_image.png"

    if path_value:
        source = Path(str(path_value)).expanduser()
        if not source.is_file():
            raise FileNotFoundError(f"input path does not exist: {source}")
        destination = task_dir / source.name
        shutil.copy2(source, destination)
        return destination

    if url_value:
        destination = task_dir / _safe_name(str(url_value), Path(default_name).suffix)
        urllib.request.urlretrieve(str(url_value), destination)
        logger.info("stage=inputs_downloaded source=url type=%s", input_type)
        return destination

    if encoded_value:
        destination = task_dir / default_name
        try:
            raw = base64.b64decode(str(encoded_value), validate=True)
        except Exception as exc:
            raise ValueError(f"invalid {input_type}_base64 payload: {exc}") from exc
        destination.write_bytes(raw)
        logger.info("stage=inputs_downloaded source=base64 type=%s bytes=%d", input_type, len(raw))
        return destination

    raise ValueError(
        f"missing {input_type} input; provide {input_type}_url, "
        f"{input_type}_base64, or {input_type}_path"
    )


def _image_dimensions(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.width, image.height


def _video_metadata(path: Path) -> tuple[int, int, float]:
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError(f"could not open video: {path}")
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
    finally:
        capture.release()
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid video dimensions: {width}x{height}")
    if fps <= 0:
        raise ValueError(f"invalid video FPS: {fps}")
    return width, height, fps


def _multiple_of_16(value: int) -> int:
    return max(16, ((int(value) + 15) // 16) * 16)


def _target_resolution(width: int, height: int, requested: Any = None) -> int:
    raw = int(requested) if requested not in (None, "") else min(width, height) * 2
    if raw < 16:
        raise ValueError("target_resolution must be at least 16 pixels")
    resolution = _multiple_of_16(raw)
    logger.info(
        "stage=workflow_prepared input=%dx%d target_short_side=%d aligned_multiple=16",
        width,
        height,
        resolution,
    )
    return resolution


def _load_workflow(name: str) -> dict[str, Any]:
    path = WORKFLOW_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"workflow not found: {path}")
    return json.loads(path.read_text())


def _queue_prompt(prompt: dict[str, Any], client_id: str) -> str:
    payload = {"prompt": prompt, "client_id": client_id}
    request = urllib.request.Request(
        f"{COMFY_URL}/prompt",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        queued = json.loads(response.read())
    if queued.get("error"):
        raise RuntimeError(f"ComfyUI rejected workflow: {queued['error']}")
    prompt_id = queued.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI did not return prompt_id: {queued}")
    return str(prompt_id)


def _get_history(prompt_id: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{COMFY_URL}/history/{prompt_id}", timeout=30) as response:
        history = json.loads(response.read())
    if prompt_id not in history:
        raise RuntimeError(f"ComfyUI history is missing prompt {prompt_id}")
    return history[prompt_id]


def _wait_for_workflow(prompt: dict[str, Any], client_id: str) -> dict[str, Any]:
    prompt_id = _queue_prompt(prompt, client_id)
    logger.info("stage=sampling prompt_id=%s", prompt_id)
    socket = websocket.WebSocket()
    socket.settimeout(5)
    try:
        socket.connect(f"ws://{SERVER_ADDRESS}:8188/ws?clientId={client_id}", timeout=30)
        while True:
            try:
                raw = socket.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if not isinstance(raw, str):
                continue
            message = json.loads(raw)
            message_type = message.get("type")
            data = message.get("data", {})
            if message_type == "execution_error" and data.get("prompt_id") == prompt_id:
                node_id = data.get("node_id")
                error = data.get("exception_message") or data.get("error") or "unknown execution error"
                raise RuntimeError(f"ComfyUI execution error at node {node_id}: {error}")
            if message_type == "execution_interrupted" and data.get("prompt_id") == prompt_id:
                raise RuntimeError("ComfyUI execution was interrupted")
            if (
                message_type == "executing"
                and data.get("node") is None
                and data.get("prompt_id") == prompt_id
            ):
                break
        history = _get_history(prompt_id)
        logger.info("stage=encoding prompt_id=%s output_nodes=%s", prompt_id, list((history.get("outputs") or {}).keys()))
        return history
    finally:
        socket.close()


def _output_root(folder_type: str) -> Path:
    return {"output": COMFY_OUTPUT, "temp": COMFY_TEMP, "input": COMFY_INPUT}.get(
        folder_type, COMFY_OUTPUT
    )


def _resolve_output_item(item: Any) -> Path | None:
    if not isinstance(item, dict):
        return None
    fullpath = item.get("fullpath")
    if fullpath and Path(fullpath).is_file():
        return Path(fullpath)
    filename = item.get("filename")
    if not filename:
        return None
    candidate = (_output_root(str(item.get("type", "output"))) / str(item.get("subfolder", "")) / str(filename)).resolve()
    allowed_roots = [COMFY_OUTPUT.resolve(), COMFY_TEMP.resolve(), COMFY_INPUT.resolve()]
    if not any(candidate == root or root in candidate.parents for root in allowed_roots):
        return None
    return candidate if candidate.is_file() else None


def _find_video(history: dict[str, Any]) -> Path:
    outputs = history.get("outputs") or {}
    for node_id, node_output in outputs.items():
        if not isinstance(node_output, dict):
            continue
        logger.info("stage=encoding node=%s output_keys=%s", node_id, list(node_output.keys()))
        for key in ("gifs", "videos"):
            for item in node_output.get(key, []) or []:
                path = _resolve_output_item(item)
                if path:
                    return path
    raise FileNotFoundError(
        "ComfyUI completed without a readable video output; "
        f"output_keys={[(node, list(value.keys())) for node, value in outputs.items() if isinstance(value, dict)]}"
    )


def _find_image(history: dict[str, Any]) -> Path:
    outputs = history.get("outputs") or {}
    for node_id, node_output in outputs.items():
        if not isinstance(node_output, dict):
            continue
        logger.info("stage=encoding node=%s output_keys=%s", node_id, list(node_output.keys()))
        for item in node_output.get("images", []) or []:
            path = _resolve_output_item(item)
            if path:
                return path
    raise FileNotFoundError("ComfyUI completed without a readable image output")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _upload_r2(path: Path, job_id: str, task_type: str) -> dict[str, Any]:
    import boto3
    from botocore.config import Config

    bucket = _env_first("R2_BUCKET", "S3_BUCKET")
    access_key = _env_first("R2_ACCESS_KEY_ID", "S3_ACCESS_KEY_ID")
    secret_key = _env_first("R2_SECRET_ACCESS_KEY", "S3_SECRET_ACCESS_KEY")
    endpoint = _env_first("R2_ENDPOINT_URL", "S3_ENDPOINT_URL")
    if not bucket or not access_key or not secret_key or not endpoint:
        raise RuntimeError("R2/S3 configuration is incomplete")
    day = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    key = f"runpod-studio/upscale-interpolation/{task_type}/{day}/{job_id}{path.suffix.lower()}"
    mime_type = mimetypes.guess_type(path.name)[0] or "video/mp4"
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=_env_first("R2_REGION", "S3_REGION") or "auto",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4", retries={"max_attempts": 5}),
    )
    logger.info("stage=uploading provider=r2 bucket=%s key=%s", bucket, key)
    client.upload_file(str(path), bucket, key, ExtraArgs={"ContentType": mime_type})
    public_base = (_env_first("R2_PUBLIC_BASE_URL", "S3_PUBLIC_BASE_URL") or "").rstrip("/")
    if public_base:
        url = f"{public_base}/{urllib.parse.quote(key)}"
    else:
        ttl = int(_env_first("R2_PRESIGNED_TTL_S", "S3_PRESIGNED_TTL_S") or "3600")
        url = client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=ttl
        )
    return {"url": url, "key": key, "provider": "r2", "mime_type": mime_type, "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _publish(path: Path, output: str, task_id: str, task_type: str) -> dict[str, Any]:
    if output in {"s3", "r2"}:
        return _upload_r2(path, task_id, task_type)
    if output in {"base64", "data_url"}:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        if output == "data_url":
            mime = mimetypes.guess_type(path.name)[0] or "video/mp4"
            return {"url": f"data:{mime};base64,{encoded}", "provider": "inline"}
        return {"video": encoded, "provider": "inline"}
    RUNPOD_VOLUME.mkdir(parents=True, exist_ok=True)
    destination = RUNPOD_VOLUME / f"upscale_{task_id}{path.suffix.lower()}"
    shutil.copy2(path, destination)
    logger.info("stage=completed output_path=%s bytes=%d", destination, destination.stat().st_size)
    return {"video_path": str(destination), "provider": "runpod_volume"}


def _prepare_workflow(task_type: str, input_name: str, width: int, height: int, fps: float, job_input: dict[str, Any]) -> dict[str, Any]:
    if task_type == "upscale":
        workflow = _load_workflow("video_upscale_api.json")
        workflow["10"]["inputs"]["resolution"] = _target_resolution(width, height, job_input.get("target_resolution"))
        workflow["21"]["inputs"]["file"] = input_name
        workflow["25"]["inputs"]["frame_rate"] = fps
        return workflow
    if task_type == "interpolation":
        workflow = _load_workflow("video_interpolation_api.json")
        workflow["21"]["inputs"]["file"] = input_name
        multiplier = int(job_input.get("fps_multiplier", 2))
        if multiplier != 2:
            raise ValueError("fps_multiplier currently supports only 2")
        workflow["26"]["inputs"]["multiplier"] = multiplier
        workflow["25"]["inputs"]["frame_rate"] = fps * multiplier
        return workflow
    workflow = _load_workflow("video_upscale_interpolation_api.json")
    workflow["10"]["inputs"]["resolution"] = _target_resolution(width, height, job_input.get("target_resolution"))
    workflow["21"]["inputs"]["file"] = input_name
    workflow["26"]["inputs"]["multiplier"] = 2
    workflow["25"]["inputs"]["frame_rate"] = fps * 2
    return workflow


def _handle_video(job_input: dict[str, Any], task_id: str, task_dir: Path) -> dict[str, Any]:
    task_type = _safe_task_type(job_input.get("task_type"))
    input_path = _decode_input(job_input, task_dir, "video")
    COMFY_INPUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_path, COMFY_INPUT / input_path.name)
    width, height, fps = _video_metadata(input_path)
    logger.info("stage=inputs_downloaded task_type=%s input=%s dimensions=%dx%d fps=%.4f", task_type, input_path.name, width, height, fps)
    prompt = _prepare_workflow(task_type, input_path.name, width, height, fps, job_input)
    history = _wait_for_workflow(prompt, str(uuid.uuid4()))
    result_path = _find_video(history)
    output = str(job_input.get("output") or job_input.get("output_mode") or "file_path").lower()
    result = _publish(result_path, output, task_id, task_type)
    result.update({"task_type": task_type, "input_width": width, "input_height": height, "input_fps": fps, "output_fps": fps * (2 if task_type in {"interpolation", "upscale_and_interpolation"} else 1)})
    return result


def _handle_image(job_input: dict[str, Any], task_id: str, task_dir: Path) -> dict[str, Any]:
    input_path = _decode_input(job_input, task_dir, "image")
    COMFY_INPUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_path, COMFY_INPUT / input_path.name)
    width, height = _image_dimensions(input_path)
    workflow = _load_workflow("image_upscale.json")
    workflow["16"]["inputs"]["image"] = input_path.name
    workflow["10"]["inputs"]["resolution"] = _target_resolution(width, height, job_input.get("target_resolution"))
    history = _wait_for_workflow(workflow, str(uuid.uuid4()))
    result_path = _find_image(history)
    output = str(job_input.get("output") or job_input.get("output_mode") or "file_path").lower()
    result = _publish(result_path, output, task_id, "image_upscale")
    result.update({"task_type": "image_upscale", "input_width": width, "input_height": height})
    return result


def handler(job: dict[str, Any]) -> dict[str, Any]:
    job_input = job.get("input") or {}
    task_id = str(job.get("id") or f"task_{uuid.uuid4()}")
    task_dir = Path("/tmp/runpod-studio") / task_id.replace("/", "_")
    task_dir.mkdir(parents=True, exist_ok=True)
    try:
        has_image = any(_input_value(job_input, name) for name in ("image_path", "image_url", "image_base64"))
        has_video = any(_input_value(job_input, name) for name in ("video_path", "video_url", "video_base64"))
        if has_image == has_video:
            return _error("inputs", "invalid_input", "provide exactly one image or video input")
        if has_image:
            return _handle_image(job_input, task_id, task_dir)
        return _handle_video(job_input, task_id, task_dir)
    except FileNotFoundError as exc:
        return _error("encoding", "output_not_found", str(exc))
    except urllib.error.URLError as exc:
        return _error("inputs", "download_failed", str(exc.reason))
    except Exception as exc:
        logger.error("stage=failed traceback=%s", traceback.format_exc(limit=8))
        return _error("processing", "worker_error", str(exc))
    finally:
        if os.getenv("DEBUG_KEEP_TEMP", "0") != "1":
            shutil.rmtree(task_dir, ignore_errors=True)


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
