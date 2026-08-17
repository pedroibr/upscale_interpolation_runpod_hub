# Independent production image for RunPod Studio.
#
# This intentionally does not use the upstream RunPod Hub image. The first
# build is expensive because it materialises ComfyUI, custom nodes and the
# SeedVR2/RIFE weights into our own GHCR image. Later handler-only changes
# reuse those immutable layers.
FROM wlsdml1114/engui_genai-base_ada_flash:1.1

USER root
ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_ENABLE_HF_TRANSFER=1 \
    PYTHONUNBUFFERED=1

ARG COMFYUI_COMMIT=7d39997e9f3897d8a50506bdc5f86dce844e0223
ARG MANAGER_COMMIT=4f56cf3dfa7de5d8a8614dfe202ff8d613ba2244
ARG FRAME_INTERPOLATION_COMMIT=26545cc2dd95bc3d27f056016300673bdeee78f5
ARG LAYERSTYLE_COMMIT=64f976fec8492ea4930c0e30c32369573189b23d
ARG KJ_NODES_COMMIT=3f20054214fec9f9234fd3841ae6f1e4287948f6
ARG VIDEO_HELPER_COMMIT=4ee72c065db22c9d96c2427954dc69e7b908444b
ARG SEEDVR2_COMMIT=4490bd1f482e026674543386bb2a4d176da245b9

RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "huggingface_hub[hf_transfer]" runpod websocket-client boto3

WORKDIR /

# Clone every code dependency at an immutable commit.
RUN git init /ComfyUI \
    && git -C /ComfyUI remote add origin https://github.com/comfyanonymous/ComfyUI.git \
    && git -C /ComfyUI fetch --depth 1 origin ${COMFYUI_COMMIT} \
    && git -C /ComfyUI checkout --detach FETCH_HEAD \
    && pip install --no-cache-dir -r /ComfyUI/requirements.txt

RUN git init /ComfyUI/custom_nodes/ComfyUI-Manager \
    && git -C /ComfyUI/custom_nodes/ComfyUI-Manager remote add origin https://github.com/Comfy-Org/ComfyUI-Manager.git \
    && git -C /ComfyUI/custom_nodes/ComfyUI-Manager fetch --depth 1 origin ${MANAGER_COMMIT} \
    && git -C /ComfyUI/custom_nodes/ComfyUI-Manager checkout --detach FETCH_HEAD \
    && pip install --no-cache-dir -r /ComfyUI/custom_nodes/ComfyUI-Manager/requirements.txt

RUN git init /ComfyUI/custom_nodes/ComfyUI-Frame-Interpolation \
    && git -C /ComfyUI/custom_nodes/ComfyUI-Frame-Interpolation remote add origin https://github.com/Fannovel16/ComfyUI-Frame-Interpolation.git \
    && git -C /ComfyUI/custom_nodes/ComfyUI-Frame-Interpolation fetch --depth 1 origin ${FRAME_INTERPOLATION_COMMIT} \
    && git -C /ComfyUI/custom_nodes/ComfyUI-Frame-Interpolation checkout --detach FETCH_HEAD \
    && python /ComfyUI/custom_nodes/ComfyUI-Frame-Interpolation/install.py

RUN git init /ComfyUI/custom_nodes/ComfyUI_LayerStyle \
    && git -C /ComfyUI/custom_nodes/ComfyUI_LayerStyle remote add origin https://github.com/chflame163/ComfyUI_LayerStyle.git \
    && git -C /ComfyUI/custom_nodes/ComfyUI_LayerStyle fetch --depth 1 origin ${LAYERSTYLE_COMMIT} \
    && git -C /ComfyUI/custom_nodes/ComfyUI_LayerStyle checkout --detach FETCH_HEAD \
    && pip install --no-cache-dir -r /ComfyUI/custom_nodes/ComfyUI_LayerStyle/requirements.txt

RUN git init /ComfyUI/custom_nodes/ComfyUI-KJNodes \
    && git -C /ComfyUI/custom_nodes/ComfyUI-KJNodes remote add origin https://github.com/kijai/ComfyUI-KJNodes.git \
    && git -C /ComfyUI/custom_nodes/ComfyUI-KJNodes fetch --depth 1 origin ${KJ_NODES_COMMIT} \
    && git -C /ComfyUI/custom_nodes/ComfyUI-KJNodes checkout --detach FETCH_HEAD \
    && pip install --no-cache-dir -r /ComfyUI/custom_nodes/ComfyUI-KJNodes/requirements.txt

RUN git init /ComfyUI/custom_nodes/ComfyUI-VideoHelperSuite \
    && git -C /ComfyUI/custom_nodes/ComfyUI-VideoHelperSuite remote add origin https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git \
    && git -C /ComfyUI/custom_nodes/ComfyUI-VideoHelperSuite fetch --depth 1 origin ${VIDEO_HELPER_COMMIT} \
    && git -C /ComfyUI/custom_nodes/ComfyUI-VideoHelperSuite checkout --detach FETCH_HEAD \
    && pip install --no-cache-dir -r /ComfyUI/custom_nodes/ComfyUI-VideoHelperSuite/requirements.txt

RUN git init /ComfyUI/custom_nodes/ComfyUI-SeedVR2_VideoUpscaler \
    && git -C /ComfyUI/custom_nodes/ComfyUI-SeedVR2_VideoUpscaler remote add origin https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler.git \
    && git -C /ComfyUI/custom_nodes/ComfyUI-SeedVR2_VideoUpscaler fetch --depth 1 origin ${SEEDVR2_COMMIT} \
    && git -C /ComfyUI/custom_nodes/ComfyUI-SeedVR2_VideoUpscaler checkout --detach FETCH_HEAD \
    && pip install --no-cache-dir -r /ComfyUI/custom_nodes/ComfyUI-SeedVR2_VideoUpscaler/requirements.txt

# Model weights are downloaded once into the image at fixed Hub revisions.
RUN mkdir -p /ComfyUI/models/SEEDVR2 /ComfyUI/custom_nodes/ComfyUI-Frame-Interpolation/ckpts/rife \
    && curl -fL --retry 5 --retry-all-errors https://huggingface.co/AInVFX/SeedVR2_comfyUI/resolve/ac66d6d98fa49975d893b58c55bff7677191c862/seedvr2_ema_7b_sharp_fp8_e4m3fn_mixed_block35_fp16.safetensors -o /ComfyUI/models/SEEDVR2/seedvr2_ema_7b_sharp_fp8_e4m3fn_mixed_block35_fp16.safetensors \
    && curl -fL --retry 5 --retry-all-errors https://huggingface.co/numz/SeedVR2_comfyUI/resolve/09ced71023636e9bc8cdf9cdecfb2625d1e691e8/ema_vae_fp16.safetensors -o /ComfyUI/models/SEEDVR2/ema_vae_fp16.safetensors \
    && curl -fL --retry 5 --retry-all-errors https://huggingface.co/hfmaster/models-moved/resolve/135ab0aa526a5be5e61677043b1ec2fbbed7cb3d/rife/rife49.pth -o /ComfyUI/custom_nodes/ComfyUI-Frame-Interpolation/ckpts/rife/rife49.pth \
    && test -s /ComfyUI/models/SEEDVR2/seedvr2_ema_7b_sharp_fp8_e4m3fn_mixed_block35_fp16.safetensors \
    && test -s /ComfyUI/models/SEEDVR2/ema_vae_fp16.safetensors \
    && test -s /ComfyUI/custom_nodes/ComfyUI-Frame-Interpolation/ckpts/rife/rife49.pth

COPY config.ini /ComfyUI/user/default/ComfyUI-Manager/config.ini
COPY entrypoint.sh /entrypoint.sh
COPY handler.py /handler.py
COPY workflow /workflow

RUN chmod +x /entrypoint.sh \
    && python -m py_compile /handler.py \
    && python - <<'PY'
from pathlib import Path
required = [
    Path('/ComfyUI/models/SEEDVR2/seedvr2_ema_7b_sharp_fp8_e4m3fn_mixed_block35_fp16.safetensors'),
    Path('/ComfyUI/models/SEEDVR2/ema_vae_fp16.safetensors'),
    Path('/ComfyUI/custom_nodes/ComfyUI-Frame-Interpolation/ckpts/rife/rife49.pth'),
]
for path in required:
    if not path.is_file() or path.stat().st_size < 1024:
        raise SystemExit(f'model validation failed: {path}')
print('model validation passed')
PY

CMD ["/entrypoint.sh"]
