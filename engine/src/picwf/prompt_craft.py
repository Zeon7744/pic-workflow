# -*- coding: utf-8 -*-
"""prompt_craft：分镜提示词工程（精确 / 人性化 / 生成不偏移）。

把现在 script_to_shots 里单薄的 "景别（运动）动作：台词。情绪基调：X"
升级成 6 维镜头语言 + 人性化情绪层。维度：
  1. framing   景别（远/全/中/近/特）
  2. angle     机位角度（平拍/俯拍/仰拍/过肩/主观）
  3. motion    镜头运动（固定/推/拉/摇/移/跟/甩/环绕）
  4. light     光位（顶光/侧光/逆光/自然光/霓虹光/烛火/月光）
  5. compo     构图（三分/中心对称/引导线/浅景深/框架式/负空间）
  6. palette   色调（暖调/冷调/低饱和/高对比/单色系）

人性化层：微表情 + 生活细节 + 情绪延续，避免 AI 味的生硬摆拍感。
"""
from typing import Dict, List, Any, Optional
import re

# 景别 → 默认 6 维组合（可按情绪/题材覆盖）
_FRAME_DEFAULTS = {
    "远":  dict(angle="平拍", motion="缓慢后拉", light="自然光", compo="引导线", palette="冷调低饱和"),
    "全景": dict(angle="平拍", motion="固定", light="自然光", compo="三分", palette="自然"),
    "中景": dict(angle="平拍", motion="缓慢推近", light="侧光", compo="三分", palette="自然"),
    "近景": dict(angle="平拍", motion="缓慢推近", light="侧光", compo="浅景深", palette="暖调"),
    "特写": dict(angle="平拍", motion="急推", light="顶光", compo="浅景深中心", palette="高对比"),
}

# 情绪 → 人性化情绪层（微表情/生活细节/情绪延续），控 AI 味
_EMOTION_HUMAN = {
    "爆发": "眉尾骤然收紧、下颌绷紧，指节因用力泛白，呼吸急促到胸口明显起伏，情绪从上镜克制处瞬间破堤",
    "反转": "笑意凝固在脸上、眼神骤变，一个僵住的半拍后才反应过来，前情铺垫的错位在脸上显出裂缝",
    "悲伤": "眼眶泛红却强忍着没掉泪，垂下眼回避视线，手指无意识地摩挲衣角，把痛憋成沉默",
    "甜蜜": "嘴角自然上扬、眼神发软发亮，下意识靠近对方半步，动作放慢带着藏不住的雀跃",
    "紧张": "喉结轻动、指尖微颤，汗意渗在鬓角，视线不敢定格、频繁游移",
    "沉淀": "气息放缓、面部肌肉松下来，留白的一拍里时间变慢，情绪往静水深处收",
    "愤怒": "太阳穴青筋微凸、攥紧的拳头背在身后，克制到发白的牙关",
    "恐惧": "瞳孔骤缩、脊背僵直、下意识后退半步，呼吸屏住",
}

# 题材 → 色调/光/人性化基调（覆盖面广：不同题材自动切风格）
_TOPIC_STYLE = {
    "现实":   dict(palette="自然低饱和", light="自然光/窗光", human="生活流细节：家居杂物、日常手势、非表演化的停顿"),
    "古装":   dict(palette="水墨暖调", light="烛火/柔侧光", human="古典礼仪感：身段收敛、执礼停顿、器物入画"),
    "科幻":   dict(palette="冷蓝高对比", light="霓虹光/全息泛光", human="科技感微动作：设备交互、界面反光映脸、机械声留白"),
    "悬疑":   dict(palette="低饱和高对比", light="单侧硬光", human="不安留白：视线错位的停顿、阴影里的小动作、未说出口的话"),
    "甜宠":   dict(palette="暖粉柔调", light="柔光顶侧", human="亲密微反应：躲闪的笑、指尖轻触、凑近偷看"),
    "恐怖":   dict(palette="青绿低饱和", light="逆光/忽明忽灭", human="生理性惊悚：后颈汗毛、骤然的心跳停顿、视角落空"),
}

_TOPIC_DEFAULT = dict(palette="自然", light="自然光", human="生活流细节：日常手势、非表演化的停顿")


def _pick(framing: str) -> Dict[str, str]:
    return dict(_FRAME_DEFAULTS.get(framing, _FRAME_DEFAULTS["中景"]))


def build_shot_prompt(shot: Dict[str, Any],
                      topic: str = "现实",
                      extra_detail: str = "") -> str:
    """把一镜的镜头语言扩写成 6 维精确 + 人性化 prompt。

    shot 可带: shot_type(景别) / motion(运动) / emotion(情绪) / raw(台词) / index。
    topic: 题材（现实/古装/科幻/悬疑/甜宠/恐怖），控制色调光位基调。
    返回可直接喂视频/图生成模型的中文 prompt。
    """
    framing = shot.get("shot_type", "中景")
    dims = _pick(framing)
    topic_style = _TOPIC_STYLE.get(topic, _TOPIC_DEFAULT)

    motion = shot.get("motion") or dims["motion"]
    emotion = shot.get("emotion", "沉淀")
    human = _EMOTION_HUMAN.get(emotion, "")
    scene_detail = topic_style.get("human", "")

    parts = [
        f"{framing}（机位{dims['angle']}，镜头{motion}）",
        f"{dims['compo']}构图，{topic_style.get('light', dims['light'])}光位，{topic_style.get('palette', dims['palette'])}色调",
    ]
    raw = (shot.get("raw") or "").strip()
    if raw:
        parts.append(raw[:100])
    if human:
        parts.append(f"情绪{emotion}：{human}")
    if scene_detail:
        parts.append(f"基调：{scene_detail}")
    if extra_detail:
        parts.append(extra_detail)
    # 人性化收尾：控 AI 味
    parts.append("表演自然不造作，保留生活细节与情绪延续，面部与肢体比例真实不走形")
    return "；".join(parts) + "。"


def craft_all_shots(shots: List[Dict[str, Any]], topic: str = "现实",
                    chars: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """批量给 shots 补 6 维精确 prompt（不破坏原结构，新增 craft_prompt 字段）。

    chars 提供时同时注入角色一致性块（联动 character_consistency）。
    """
    from .character_consistency import inject_into_shots
    out = []
    for sh in shots:
        new = dict(sh)
        new["craft_prompt"] = build_shot_prompt(sh, topic=topic)
        out.append(new)
    if chars:
        out = inject_into_shots(out, chars)
        for s in out:
            # 角色块 + 6 维 craft 合并成最终可喂 prompt
            s["final_prompt"] = f"{s.get('craft_prompt','')}\n角色基准：{s.get('char_block','')}".strip()
    return out
