# RunPod Studio worker contract

## Tasks

| `task_type` | Models | Resolution | FPS |
| --- | --- | --- | --- |
| `upscale` | SeedVR2 7B | shortest edge × 2, multiple of 16 | unchanged |
| `interpolation` | RIFE 4.9 | unchanged | ×2 |
| `upscale_and_interpolation` | SeedVR2 7B → RIFE 4.9 | shortest edge × 2, multiple of 16 | ×2 |

`target_resolution` is an optional SeedVR2 shortest-edge target. The handler
rounds it up to a multiple of 16. `fps_multiplier` is currently fixed at 2 for
the interpolation task so the workflow remains tested and predictable.

## Inputs

Provide exactly one of `video_url`, `video_base64`, `video_path`, or the image
equivalents for image upscale. URLs must be reachable from the RunPod worker.
The Gateway should use a temporary R2 URL for input assets and never expose R2
secrets in a job payload.

## Outputs

Use `output: "s3"` (or `"r2"`) in production. The worker reads either the
`R2_*` or existing `S3_*` environment variables and returns:

```json
{
  "url": "https://...",
  "key": "runpod-studio/upscale-interpolation/interpolation/2026/08/17/job.mp4",
  "provider": "r2",
  "bytes": 123,
  "sha256": "..."
}
```

`output: "file_path"` remains available for volume-based debugging. The
Gateway should finalize such paths to R2 before returning a public result.

## R2 environment

Set these only on RunPod/Railway secrets, never in Git:

```text
R2_BUCKET=runpod-studio-assets
R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_REGION=auto
R2_PRESIGNED_TTL_S=86400
```

The public-base variable is optional. Without it, the worker returns a signed
GET URL. Signed URLs must be redacted from logs.
