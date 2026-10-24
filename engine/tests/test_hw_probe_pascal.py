# -*- coding: utf-8 -*-
"""Pascal 1060 ComfyUI 启动建议 + kernel 自检（1060 实机踩坑结论固化）"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from picwf import hw_probe


def test_pascal_recognized():
    adv = hw_probe.pascal_launch_advice(
        {"gpu": {"arch": "Pascal", "cc": "6.1", "driver_version": "577.00"}})
    assert adv["is_pascal"] is True
    assert adv["recommended_cuda"] == "cu126"
    assert "cu129" in adv["forbidden_cuda"] and "cu130" in adv["forbidden_cuda"]


def test_pascal_env_injection():
    adv = hw_probe.pascal_launch_advice(
        {"gpu": {"arch": "Pascal", "cc": "6.1"}})
    assert adv["env"]["TORCH_CUDA_ARCH_LIST"] == "6.1"
    assert adv["env"]["NVIDIA_TF32_OVERRIDE"] == "0"
    assert "--cuda" in adv["drop_arg"]


def test_pascal_requires_base_model():
    adv = hw_probe.pascal_launch_advice({"gpu": {"arch": "Pascal", "cc": "6.1"}})
    assert "checkpoints" in adv["require_base_model"]
    assert any("no kernel image" in n for n in adv["notes"])


def test_non_pascal_no_pascal_advice():
    adv = hw_probe.pascal_launch_advice(
        {"gpu": {"arch": "Ampere", "cc": "8.6", "driver_version": "550.00"}})
    assert adv["is_pascal"] is False
    assert adv["forbidden_cuda"] == []
    assert adv["drop_arg"] == []


def test_kernel_selfcheck_no_torch_or_cuda():
    """沙箱无 torch/cuda 时，kernel 自检应安全返回 ok=False，不抛异常。"""
    kc = hw_probe.kernel_selfcheck()
    assert isinstance(kc, dict)
    assert kc["ok"] is False
    assert kc["error"]  # 必有原因说明


def test_drv_below_helper():
    assert hw_probe._drv_below("525.100", "530") is True
    assert hw_probe._drv_below("577.00", "530") is False
    assert hw_probe._drv_below("abc", "530") is False  # 非法输入安全返回 False


def test_old_driver_gets_upgrade_note():
    adv = hw_probe.pascal_launch_advice(
        {"gpu": {"arch": "Pascal", "cc": "6.1", "driver_version": "525.100"}})
    assert any("驱动" in n and "530" in n for n in adv["notes"])
