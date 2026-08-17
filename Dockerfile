# Thin overlay: CUDA, ComfyUI, custom nodes, and model layers come from the
# exact upstream v1.8 image that passed the startup checks.
FROM registry.runpod.net/wlsdml1114-upscale-interpolation-runpod-hub-main-dockerfile@sha256:1df5cc3c8a1c0d879e898dddb4e83ae41bfb48944c452a708ea2556733d87909

USER root
RUN pip install --no-cache-dir boto3

COPY handler.py /handler.py
COPY workflow/video_interpolation_api.json /workflow/video_interpolation_api.json

RUN python -m py_compile /handler.py

# Keep the upstream CMD/entrypoint: it starts ComfyUI and then /handler.py.
