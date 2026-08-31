# RunPod Studio — Video Upscale & Frame Interpolation
[한국어 README 보기](README_kr.md)

This RunPod Studio fork builds an independent, self-contained image containing
the CUDA base, pinned ComfyUI/custom nodes, SeedVR2 and RIFE weights, and a
stable handler for upscale-only, interpolation-only, and combined video
processing. It supports direct Cloudflare R2 output; the current Gateway
endpoint does not require a RunPod network volume.

[![Runpod](https://api.runpod.io/badge/wlsdml1114/upscale_interpolation_runpod_hub)](https://console.runpod.io/hub/wlsdml1114/upscale_interpolation_runpod_hub)

## 🎨 Engui Studio Integration

[![EnguiStudio](https://raw.githubusercontent.com/wlsdml1114/Engui_Studio/main/assets/banner.png)](https://github.com/wlsdml1114/Engui_Studio)

This worker is consumed by the RunPod Studio Gateway. The upstream Engui Studio
integration remains useful as a reference, but Gateway/R2 is the canonical
production path for this project.

**Engui Studio Benefits:**
- **Expanded Model Support**: Access to a wider variety of AI models beyond what's available through API
- **Enhanced User Interface**: Intuitive workflow management and model selection
- **Advanced Features**: Additional tools and capabilities for AI model deployment
- **Seamless Integration**: Optimized for Engui Studio's ecosystem

> **Note**: While this template works perfectly with API calls, Engui Studio users will have access to additional models and features that are planned for future releases.

## ✨ Key Features

*   **Video Upscaling**: High-quality video upscaling for resolution enhancement
*   **Frame Interpolation**: RIFE-only mode that preserves resolution and doubles FPS
*   **Combined Enhancement**: SeedVR2 upscale followed by RIFE interpolation
*   **ComfyUI Integration**: Flexible workflow management based on ComfyUI
*   **VHS Support**: Efficient video processing using Video Helper Suite
*   **Multiple Input Formats**: Support for Base64, URL, and file path inputs

## 🚀 RunPod Serverless Template

### Building the self-contained image

The production `Dockerfile` does not depend on the upstream RunPod Hub image.
It pins the ComfyUI and custom-node commits and downloads the three required
weights at immutable Hugging Face revisions. Publish the resulting image as an
immutable GHCR tag, for example:

```text
ghcr.io/pedroibr/runpod-studio-upscale-interpolation:v1.0.0
```

After this first build, handler changes should use that image as their base so
the ComfyUI and model layers remain cached. Publish immutable tags and configure
the Gateway with the resulting endpoint ID through Railway secrets.

### RunPod Studio task contract

The handler accepts these video tasks:

| `task_type` | Behavior |
| --- | --- |
| `upscale` | SeedVR2 upscale; FPS unchanged |
| `interpolation` | RIFE interpolation; resolution unchanged and FPS ×2 |
| `upscale_and_interpolation` | SeedVR2 followed by RIFE; resolution ×2 and FPS ×2 |

`target_resolution` is an optional SeedVR2 shortest-edge target and is rounded
up to a multiple of 16. Use `output: "s3"` or `output: "r2"` in production to
upload directly to Cloudflare R2. The worker reads `R2_*` or the existing
`S3_*` environment variables. See [CONTRACT.md](CONTRACT.md) for the complete
Gateway contract and secret configuration.

This template includes all necessary components to run video upscaling and frame interpolation as a RunPod Serverless Worker.

*   **Dockerfile**: Environment configuration and installation of all dependencies required for model execution
*   **handler.py**: Handler function that processes requests for RunPod Serverless
*   **entrypoint.sh**: Performs initialization tasks when the worker starts
*   **workflow/video_upscale_api.json**: SeedVR2 upscale-only workflow
*   **workflow/video_interpolation_api.json**: RIFE interpolation-only workflow
*   **workflow/video_upscale_interpolation_api.json**: SeedVR2 + RIFE workflow

### Input

The `input` object must contain the following fields. Videos can be input using **path, URL, or Base64** - one method for each.

#### Workflow Selection Parameters
| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `task_type` | `string` | No | `"upscale"` | Task type: `"upscale"` (upscaling only) or `"upscale_and_interpolation"` (upscaling + frame interpolation) |
| `network_volume` | `boolean` | No | `false` | Legacy debugging option. Production uses R2 and should leave this unset. |

#### Video Input (use only one)
| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `video_path` | `string` | No | `/example_video.mp4` | Local path to the input video file |
| `video_url` | `string` | No | `/example_video.mp4` | URL to the input video file |
| `video_base64` | `string` | No | `/example_video.mp4` | Base64 encoded string of the input video file |

**Request Examples:**

#### 1. Upscaling Only (using URL)
```json
{
  "input": {
    "task_type": "upscale",
    "video_url": "https://sample-videos.com/zip/10/mp4/SampleVideo_1280x720_1mb.mp4"
  }
}
```

#### 2. Upscaling + Frame Interpolation (using file path)
```json
{
  "input": {
    "task_type": "upscale_and_interpolation",
    "video_path": "/my_volume/input_video.mp4"
  }
}
```

#### 3. Using Base64 (Upscaling Only)
```json
{
  "input": {
    "task_type": "upscale",
    "video_base64": "data:video/mp4;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
  }
}
```

#### 4. Using Network Volume (File Path Output)
```json
{
  "input": {
    "task_type": "upscale_and_interpolation",
    "video_path": "/my_volume/input_video.mp4",
    "network_volume": true
  }
}
```

### Output

#### Success

If the job is successful, it returns a JSON object. The response format depends on the `network_volume` parameter.

**When `network_volume: true`:**

| Parameter | Type | Description |
| --- | --- | --- |
| `video_path` | `string` | Path to the generated video file |

```json
{
  "video_path": "/runpod-volume/upscale_e5f6c1c3-e784-4e90-96a7-32f0be222d3c.mp4"
}
```

**When `network_volume: false` (default):**

| Parameter | Type | Description |
| --- | --- | --- |
| `video` | `string` | Base64 encoded video file data |

```json
{
  "video": "data:video/mp4;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
}
```

#### Error

If the job fails, it returns a JSON object containing an error message.

| Parameter | Type | Description |
| --- | --- | --- |
| `error` | `string` | Description of the error that occurred |

**Error Response Example:**

```json
{
  "error": "비디오를 찾을 수 없습니다."
}
```

## 🛠️ Usage and API Reference

1.  Create a Serverless Endpoint on RunPod based on this repository.
2.  Once the build is complete and the endpoint is active, submit jobs via HTTP POST requests according to the API Reference below.

### 📁 Input and output storage

The Gateway uploads user media to Cloudflare R2 and passes a temporary HTTPS
URL as `video_url` or `image_url`. The worker uploads the generated artifact
back to R2 and returns its metadata. Local paths and network-volume paths are
reserved for isolated debugging; the current production endpoint has no model
or output volume attached.

## 🔧 Workflow Configuration

This template includes two workflow configurations that are automatically selected based on your input parameters:

*   **upscale.json**: Video upscaling only workflow
*   **upscale_and_interpolation.json**: Upscaling + frame interpolation workflow

### Workflow Selection Logic

The handler automatically selects the appropriate workflow based on your input parameters:

| task_type | Selected Workflow |
|-----------|-------------------|
| `"upscale"` | upscale.json |
| `"upscale_and_interpolation"` | upscale_and_interpolation.json |

The workflows are based on ComfyUI and include all necessary nodes for video upscaling and frame interpolation processing. Each workflow is optimized for its specific use case and includes the appropriate model configurations.

## 🙏 Original Project

This project is based on the following original repositories. All rights to the models and core logic belong to the original authors.

*   **ComfyUI:** [https://github.com/comfyanonymous/ComfyUI](https://github.com/comfyanonymous/ComfyUI)
*   **ComfyUI-Frame-Interpolation:** [https://github.com/Fannovel16/ComfyUI-Frame-Interpolation](https://github.com/Fannovel16/ComfyUI-Frame-Interpolation)
*   **VHS (Video Helper Suite):** [https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite)

## 📄 License

This project follows the Apache 2.0 License.
