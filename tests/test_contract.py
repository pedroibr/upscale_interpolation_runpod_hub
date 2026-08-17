"""Dependency-light contract tests for the worker's workflow selection."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_worker():
    runpod = types.ModuleType("runpod")
    runpod.serverless = types.SimpleNamespace(start=lambda *args, **kwargs: None)
    cv2 = types.ModuleType("cv2")
    websocket = types.ModuleType("websocket")
    websocket.WebSocket = object
    pil = types.ModuleType("PIL")
    pil_image = types.ModuleType("PIL.Image")
    pil_image.Image = object
    pil.Image = pil_image
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(
        is_available=lambda: True,
        get_device_name=lambda _: "test-gpu",
        get_device_properties=lambda _: types.SimpleNamespace(total_memory=24 * 1024**3),
    )
    sys.modules.update(
        {
            "runpod": runpod,
            "cv2": cv2,
            "websocket": websocket,
            "PIL": pil,
            "PIL.Image": pil_image,
            "torch": torch,
        }
    )
    spec = importlib.util.spec_from_file_location("worker_under_test", ROOT / "handler.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class WorkerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worker = load_worker()

    def test_interpolation_does_not_include_seedvr2(self):
        workflow = self.worker._prepare_workflow("interpolation", "input.mp4", 1280, 704, 24.0, {})
        self.assertNotIn("10", workflow)
        self.assertEqual(workflow["25"]["inputs"]["frame_rate"], 48.0)
        self.assertEqual(workflow["26"]["inputs"]["multiplier"], 2)
        self.assertEqual(
            {key: workflow["26"]["inputs"][key] for key in ("dtype", "torch_compile", "batch_size")},
            {"dtype": "float32", "torch_compile": False, "batch_size": 1},
        )

    def test_upscale_preserves_fps_and_aligns_resolution(self):
        workflow = self.worker._prepare_workflow("upscale", "input.mp4", 1280, 704, 23.976, {})
        self.assertEqual(workflow["10"]["inputs"]["resolution"], 1408)
        self.assertEqual(workflow["25"]["inputs"]["frame_rate"], 23.976)

    def test_combined_workflow_doubles_fps_and_upscales(self):
        workflow = self.worker._prepare_workflow(
            "upscale_and_interpolation", "input.mp4", 1280, 704, 24.0, {}
        )
        self.assertEqual(workflow["10"]["inputs"]["resolution"], 1408)
        self.assertEqual(workflow["25"]["inputs"]["frame_rate"], 48.0)
        self.assertEqual(workflow["26"]["inputs"]["frames"], ["10", 0])
        self.assertEqual(workflow["26"]["inputs"]["dtype"], "float32")
        self.assertFalse(workflow["26"]["inputs"]["torch_compile"])
        self.assertEqual(workflow["26"]["inputs"]["batch_size"], 1)


if __name__ == "__main__":
    unittest.main()
