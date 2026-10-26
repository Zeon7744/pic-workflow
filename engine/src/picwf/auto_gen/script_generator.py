# -*- coding: utf-8 -*-
"""用 LLM（或模板兜底）从表单生成剧本 Markdown。
v0.5.15 P0: 专业编剧 prompt，按题材区分结构、爽点设计、平台规范。
"""
import json
import os
from typing import Any, Dict, List, Optional
from .form_schema import FormInput

_ENGINE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
TEMPLATE_DIR = os.path.join(_ENGINE_ROOT, "templates")

# ─── 题材专属结构化 prompt 模板 ──────────────────────────

_GENRE_GUIDANCE = {
    "职场复仇": {
        "structure": """【本集标准结构】
- 开场（3-5秒）：直接切入冲突/羞辱场景，观众瞬间入戏
- 转场（10-15秒）：铺垫+信息揭示，主角隐忍但观众知道她在蓄力
- 冲突升级（20-30秒）：反派加码，主角被推向极限
- 高潮反击（15-20秒）：主角亮出底牌/反转局面，爽感爆发
- 结尾钩子（5-10秒）：悬念/预告下集更大反转""",
        "hit_design": """【爽点设计要点】
- 爽点①（开场钩子）：反派的嚣张羞辱，让观众憋足气
- 爽点②（中段反击）：主角用专业能力/证据打脸，"你说我不会？我让你看看"
- 爽点③（结尾高潮）：更大身份/底牌曝光，"你以为我只是个助理？"
- 甜点点缀：同事暗中支持/主角内心独白""",
        "dialogue_rules": """【台词规范】
- 单句≤15字，短句为主，忌长段独白
- 反派台词要嚣张但有逻辑，不能脸谱化
- 主角台词：隐忍期少说多做，反击期字字有力
- 善用动作描写替代台词（如"冷笑""把文件甩到桌上"）""",
        "visual_guidance": """【画面提示】
- 职场场景：办公室/会议室/工位/走廊，强调空间压迫感
- 特写多用：眼神变化、手指握紧、文件特写
- 对比镜头：反派坐高位 vs 主角站低位（视觉上先压后翻）""",
    },
    "古装权谋": {
        "structure": """【本集标准结构】
- 开场（3-5秒）：宫廷氛围镜头，主角身份/处境一目了然
- 转场（10-15秒）：暗线铺垫，配角传递关键信息
- 冲突升级（20-30秒）：当面对质，话里有话，刀刀见血
- 高潮反击（15-20秒）：主角用智慧/布局反制，"你算错了一步"
- 结尾钩子（5-10秒）：密信/秘密曝光，下集更大棋局""",
        "hit_design": """【爽点设计要点】
- 爽点①（开场）：主角身处险境但面不改色，"她竟敢直视娘娘"
- 爽点②（中段）：借力打力，用反派的规则反制反派
- 爽点③（高潮）：布局揭晓，观众"原来早就设好了"
- 甜点点缀：暗线盟友的默契眼神""",
        "dialogue_rules": """【台词规范】
- 台词含两层意思：表面恭敬，暗藏锋芒
- 多用反问和留白："娘娘这话，奴婢听不懂"
- 古代称谓准确：娘娘/殿下/本宫/奴婢/奴才
- 动作描写代替情绪直述（"叩首""指尖微颤"）""",
        "visual_guidance": """【画面提示】
- 宫廷场景：红墙/烛火/屏风/宫灯，色调偏冷
- 特写多用：茶杯/信物/眼神/衣角
- 光影对比：光明处vs阴影处，暗示势力格局""",
    },
    "甜宠爱情": {
        "structure": """【本集标准结构】
- 开场（3-5秒）：暧昧场景/意外相遇，氛围感拉满
- 转场（10-15秒）：互动升温，小动作传递好感
- 冲突升级（20-30秒）：误会/第三者介入/外界阻力
- 高潮反击（15-20秒）：男主/女主主动表态，"我喜欢你"或等价表达
- 结尾钩子（5-10秒）：甜蜜时刻/新危机伏笔""",
        "hit_design": """【爽点设计要点】
- 爽点①：暧昧升温，"他记得我的名字"
- 爽点②：公开维护，"她是我的人"
- 爽点③：双向奔赴确认
- 甜点密集：肢体接触、眼神交汇、细节关怀""",
        "dialogue_rules": """【台词规范】
- 台词要甜但不腻，留白比直说更有张力
- 多用动作+短句："他没说话，只是把伞往她那边倾斜"
- 内心戏用画面表达，少用旁白""",
        "visual_guidance": """【画面提示】
- 暖色调，柔光，生活化场景
- 特写：手指触碰/对视/微笑
- 距离变化：从陌生距离到亲密距离""",
    },
    "悬疑推理": {
        "structure": """【本集标准结构】
- 开场（3-5秒）：悬念画面/异常事件，"这不对劲"
- 转场（10-15秒）：线索浮现，主角深入调查
- 冲突升级（20-30秒）：发现新证据/遇到阻碍
- 高潮反击（15-20秒）：关键突破，"凶手是……"
- 结尾钩子（5-10秒）：反转/更大的谜""",
        "hit_design": """【爽点设计要点】
- 爽点①：发现关键线索，"原来如此"
- 爽点②：智斗反派，主角比反派快一步
- 爽点③：真相逼近，观众"我知道谁是凶手了"
- 甜点点缀：队友默契配合""",
        "dialogue_rules": """【台词规范】
- 对话要暗藏信息，表面正常实则关键
- 多用疑问句引导观众思考
- 反派台词要有误导性和真实感""",
        "visual_guidance": """【画面提示】
- 冷暖对比色调，阴影多
- 特写：证据/表情变化/环境细节
- 节奏：快切制造紧张感""",
    },
    "都市幻想": {
        "structure": """【本集标准结构】
- 开场（3-5秒）：日常场景突然异常，"有什么不对劲"
- 转场（10-15秒）：能力觉醒/异象初现
- 冲突升级（20-30秒）：敌人出现/能力失控
- 高潮反击（15-20秒）：能力正式使用，"原来我真的……"
- 结尾钩子（5-10秒）：更大世界观揭示""",
        "hit_design": """【爽点设计要点】
- 爽点①：能力觉醒瞬间，视觉震撼
- 爽点②：用超能力解决日常困境
- 爽点③：身份/能力大曝光
- 甜点点缀：伙伴震惊/崇拜""",
        "dialogue_rules": """【台词规范】
- 现代口语为主，能力描述简洁有力
- 震惊反应要真实："这不可能……"
- 避免过多设定解释，用行动展示""",
        "visual_guidance": """【画面提示】
- 现代都市+超现实元素融合
- 能力特效：光/粒子/变形
- 对比：日常场景 vs 超能场景""",
    },
    "历史传奇": {
        "structure": """【本集标准结构】
- 开场（3-5秒）：时代背景镜头，历史氛围
- 转场（10-15秒）：主角处境揭示，历史洪流中的个人
- 冲突升级（20-30秒）：朝堂/战场/民间斗争
- 高潮反击（15-20秒）：历史性转折，"这一战改变了……"
- 结尾钩子（5-10秒）：历史悬念/下一段征程""",
        "hit_design": """【爽点设计要点】
- 爽点①：以弱胜强的铺垫
- 爽点②：关键时刻力挽狂澜
- 爽点③：历史节点上的个人抉择
- 甜点点缀：家国情怀/兄弟情义""",
        "dialogue_rules": """【台词规范】
- 半文半白，古意但不晦涩
- 称谓准确：陛下/将军/先生/阁下
- 金句要有历史感："自古圣贤皆寂寞"
- 行动描写替代长篇论述""",
        "visual_guidance": """【画面提示】
- 大场景+人物特写结合
- 色调：金色/红色/灰色为主
- 服装道具考据感""",
    },
}

_DEFAULT_GUIDANCE = _GENRE_GUIDANCE.get("职场复仇", {})


def _build_prompt(form: FormInput) -> str:
    """构建专业编剧级 prompt，按题材区分结构和爽点设计。"""
    chars_desc = "\n".join(
        f"- **{c['name']}**：{c.get('role','')}，{c.get('gender','')}，{c.get('age_band','')}岁，"
        f"核心特征：{c.get('key_trait','')}。"
        for c in form.characters
    ) or "- **主角**：青年，核心特征：待定"

    scenario_map = {
        "workplace_drama": "职场复仇",
        "historical": "古装权谋",
        "romance": "甜宠爱情",
        "thriller": "悬疑推理",
        "fantasy": "都市幻想",
    }
    genre_cn = scenario_map.get(form.scenario, form.genre)
    guidance = _GENRE_GUIDANCE.get(genre_cn, _DEFAULT_GUIDANCE)

    # 根据集数推算每集应有镜头数
    ep_dur = form.episode_duration
    if ep_dur == "30秒":
        shot_count = 4
    elif ep_dur == "2分钟":
        shot_count = 10
    else:
        shot_count = 6  # 默认1分钟

    return f"""你是一位顶流短剧编剧，作品在红果/抖音/快手等平台爆款无数。
你深谙"3秒留人、15秒给爽点、结尾必留钩"的流量密码。

═══════════════════════════════════════
【本项目设定】
═══════════════════════════════════════
- 剧名：{form.title}
- 题材：{genre_cn}
- 总集数：{form.episodes}集，每集{ep_dur}
- 基调：{form.tone}
- 每集目标：{form.hit_points_per_ep}个爽点 + {form.sweet_points_per_ep}个甜点
- 输出：第1集完整剧本（含分镜）

═══════════════════════════════════════
【角色档案】
═══════════════════════════════════════
{chars_desc}
要求：为每个角色补充具体外貌描述（50字以内，可用于AI绘图prompt）

═══════════════════════════════════════
【剧情主题】
═══════════════════════════════════════
{form.theme or f'围绕{genre_cn}核心冲突展开，第1集要建立世界观+引入核心矛盾'}

═══════════════════════════════════════
【本题材编剧指南】{guidance.get("structure","")}
═══════════════════════════════════════
{guidance.get("hit_design","")}

═══════════════════════════════════════
【台词规范】{guidance.get("dialogue_rules","")}{guidance.get("visual_guidance","")}
═══════════════════════════════════════

═══════════════════════════════════════
【输出格式】严格按以下格式，不要有任何多余文字：
═══════════════════════════════════════

# 《{form.title}》第1集

**类型：** {genre_cn}
**集数：** {form.episodes}集 × {ep_dur}
**基调：** {form.tone}
**平台：** 红果短剧

---

## 角色设定

| 角色 | 定位 | 外景描述（AI绘图用） |
|------|------|----------|
| （填写） | （主角/反派/配角） | （外貌+服装+气质，50字内） |

---

## 分镜剧本

### 【开场】{scene1_loc}·{time1}·{interior_exterior}

{scene1_action}

{char1}：{dialogue1}

### 【转场】{scene2_loc}·{time2}·{interior_exterior}

{scene2_action}

{char2}：{dialogue2}
{char1}：{dialogue3}

### 【冲突】{scene3_loc}·{time3}·{interior_exterior}

{scene3_action}

{char2}：{dialogue4}
{char1}：{dialogue5}

### 【高潮】{scene4_loc}·{time4}·{interior_exterior}

{scene4_action}

{char1}：{dialogue6}
{char2}：{dialogue7}

### 【结尾钩子】{scene5_loc}·{time5}·{interior_exterior}

{scene5_action}

{char1}（自语）：{hook_line}

**【本集完】**

---

## 爽点清单
1. **爽点①（{hit1_type}）：** {hit1_desc}
2. **爽点②（{hit2_type}）：** {hit2_desc}
3. **爽点③（{hit3_type}）：** {hit3_desc}

## 甜点
- {sweet_desc}

## AI绘图提示词（每镜头）
- 镜头1：{shot1_prompt}
- 镜头2：{shot2_prompt}
- 镜头3：{shot3_prompt}
- 镜头4：{shot4_prompt}
- 镜头5：{shot5_prompt}

═══════════════════════════════════════
【创作铁律】
═══════════════════════════════════════
1. 全程禁止出现"耀/曜"任何字眼
2. 单句台词≤15字，短句为王
3. 开场3秒必须有冲突/悬念/视觉冲击
4. 每集必须有明确爽点节奏：铺垫→积累→爆发→钩子
5. 结尾必须留钩子，让观众忍不住看下一集
6. 角色要有记忆点，一句话能记住的特征
7. 画面描述具体可执行，AI绘图能直接用
"""


def _load_template(genre: str) -> str:
    template_map = {
        "职场复仇": "workplace_drama.md",
        "古装权谋": "historical.md",
        "甜宠爱情": "romance.md",
        "悬疑推理": "workplace_drama.md",
        "都市幻想": "workplace_drama.md",
        "历史传奇": "historical.md",
    }
    fname = template_map.get(genre, "workplace_drama.md")
    path = os.path.join(TEMPLATE_DIR, fname)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return ""


def generate_script_from_form(
    form: FormInput,
    llm_api_base: Optional[str] = None,
    llm_api_key: Optional[str] = None,
    llm_model: str = "deepseek-chat",
    use_llm: bool = True,
) -> str:
    """生成剧本文本，三层降级：LLM → 模板填充 → 最小可用。"""
    if use_llm and llm_api_base and llm_api_key:
        try:
            import urllib.request
            payload = json.dumps({
                "model": llm_model,
                "messages": [{"role": "user", "content": _build_prompt(form)}],
                "temperature": 0.8,
                "max_tokens": 4000,
            }).encode()
            req = urllib.request.Request(
                f"{llm_api_base.rstrip('/')}/v1/chat/completions",
                data=payload,
                headers={
                    "Authorization": f"Bearer {llm_api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode())
            content = result["choices"][0]["message"]["content"]
            if content and len(content.strip()) > 200:
                return content
        except Exception as e:
            print(f"[auto_gen] LLM调用失败，回退模板: {e}")

    # 模板兜底：加载 + 填充占位符
    template = _load_template(form.genre)
    if template:
        chars = form.characters or [
            {"name": "主角", "role": "主角", "gender": "女", "age_band": "青年", "key_trait": "待定"},
            {"name": "反派", "role": "反派", "gender": "男", "age_band": "中年", "key_trait": "阴狠"},
            {"name": "配角", "role": "配角", "gender": "女", "age_band": "青年", "key_trait": "善意"},
        ]
        c1, c2, c3 = chars[0], chars[1] if len(chars) > 1 else chars[0], chars[2] if len(chars) > 2 else chars[0]
        filled = template
        # 基础替换
        filled = filled.replace("{{TITLE}}", form.title)
        filled = filled.replace("{{GENRE}}", form.genre)
        filled = filled.replace("{{EPISODES}}", str(form.episodes))
        filled = filled.replace("{{TONE}}", form.tone)
        filled = filled.replace("{{EP}}", str(form.episodes))
        filled = filled.replace("{{DURATION}}", form.episode_duration.replace("分钟", "").replace("秒", ""))
        # 角色占位符替换
        filled = filled.replace("{{CHAR1_NAME}}", c1.get("name", "主角"))
        filled = filled.replace("{{CHAR1_ROLE}}", c1.get("role", "主角"))
        filled = filled.replace("{{CHAR1_AGE}}", c1.get("age_band", "青年"))
        filled = filled.replace("{{CHAR1_DESC}}", c1.get("key_trait", "待定"))
        filled = filled.replace("{{CHAR2_NAME}}", c2.get("name", "反派"))
        filled = filled.replace("{{CHAR2_ROLE}}", c2.get("role", "反派"))
        filled = filled.replace("{{CHAR2_AGE}}", c2.get("age_band", "中年"))
        filled = filled.replace("{{CHAR2_DESC}}", c2.get("key_trait", "阴狠"))
        filled = filled.replace("{{CHAR3_NAME}}", c3.get("name", "配角"))
        filled = filled.replace("{{CHAR3_ROLE}}", c3.get("role", "配角"))
        filled = filled.replace("{{CHAR3_AGE}}", c3.get("age_band", "青年"))
        filled = filled.replace("{{CHAR3_DESC}}", c3.get("key_trait", "善意"))
        # 场景占位符保留，标注待填
        return filled

    # 最终兜底：生成最小可用剧本
    safe_title = form.title
    c1 = form.characters[0] if form.characters else {"name": "主角", "role": "主角"}
    genre_cn = form.genre
    return f"""# 《{safe_title}》第1集

**类型：** {genre_cn}
**集数：** {form.episodes}集 × {form.episode_duration}
**基调：** {form.tone}
**平台：** 红果短剧

---

## 角色设定

| 角色 | 定位 | 外景描述 |
|------|------|----------|
| {c1.get('name','主角')} | {c1.get('role','主角')} | {c1.get('key_trait','')} |

---

## 分镜剧本

### 【开场】场景A·日·内

主角出场，氛围营造。

{c1.get('name','主角')}：（第一句台词）

### 【转场】场景B·夜·内

冲突铺垫。

配角：（过渡台词）
{c1.get('name','主角')}：（回应）

### 【冲突】场景C·日·内

矛盾升级。

反派：（挑衅台词）
{c1.get('name','主角')}：（隐忍/反击）

### 【高潮】场景D·夜·内

爽点爆发。

{c1.get('name','主角')}：（核心反击台词）
反派：（震惊/不甘）

### 【结尾钩子】场景E·夜·内

悬念留钩。

{c1.get('name','主角')}（自语）：（钩子台词）

**【本集完】**

---

## 爽点清单
1. **爽点①：** 开场冲突引入
2. **爽点②：** 中段反击打脸
3. **爽点③：** 高潮底牌曝光

## 甜点
- 配角暗中支持/主角内心独白

## AI绘图提示词
- 镜头1：{genre_cn}风格，{c1.get('name','主角')}出场，场景A
- 镜头2：对话场景，场景B
- 镜头3：冲突对峙，场景C
- 镜头4：高潮反击，场景D
- 镜头5：结尾悬念，场景E
"""
