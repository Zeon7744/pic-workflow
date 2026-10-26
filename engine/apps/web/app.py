# -*- coding: utf-8 -*-
"""pic-workflow Web UI - 三种出片方案一览。"""
import os
import sys
import json
import tempfile
from pathlib import Path

import streamlit as st

# 引擎路径
ENGINE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ENGINE_ROOT / "src"))

from picwf.auto_gen import FormInput, run_auto_pipeline, validate_form
from picwf.auto_gen.form_schema import FORM_SCHEMA
from picwf.cloud_api import has_key, get_key

st.set_page_config(page_title="爽点厂 · HookForge", page_icon="⚡", layout="wide")

# ─── 样式 ───────────────────────────────────────────────
st.markdown("""
<style>
.main-header {font-size: 2.2rem; font-weight: 800; color: #1a1a2e;}
.sub-header {font-size: 1.3rem; font-weight: 600; color: #16213e;}
.card {background: #f8f9fa; border-radius: 12px; padding: 1.2rem; margin: 0.5rem 0; border-left: 4px solid #4361ee;}
.card-success {border-left-color: #2ec4b6;}
.card-warn {border-left-color: #ff9f1c;}
.code-block {background: #1e1e2e; color: #cdd6f4; padding: 1rem; border-radius: 8px; font-size: 0.85rem;}
</style>
""", unsafe_allow_html=True)

# ─── 侧边栏：配置 ──────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ 配置")
    llm_api_base = st.text_input("LLM API Base", value=os.getenv("LLM_API_BASE", ""),
                                  help="OpenAI 兼容接口，如 https://api.deepseek.com")
    llm_api_key = st.text_input("LLM API Key", type="password",
                                 value=os.getenv("LLM_API_KEY", ""),
                                 help="用于剧本生成（可选，无则用模板兜底）")
    st.markdown("---")
    st.markdown("### 云端模型状态")
    for svc in ["wan", "kling", "seedream"]:
        has = has_key(svc)
        st.metric(label=svc.upper(), value="✅ 已配置" if has else "❌ 未配置")
    st.markdown("---")
    st.markdown("**v0.5.14 · HookForge**")
    st.caption("爽点厂 · 剧本工厂自动化")

# ─── 标题 ──────────────────────────────────────────────
st.markdown('<p class="main-header">⚡ 爽点厂 HookForge</p>', unsafe_allow_html=True)
st.markdown("AI 短剧自动化生产平台 · 三种出片方案，一键启动")
st.divider()

# ─── 方案选择 Tabs ─────────────────────────────────────
tab_auto, tab_form, tab_upload = st.tabs([
    "📝 方案一：自动生产（CLI）",
    "🎨 方案二：表单 → LLM → 剧本 → 引擎",
    "📂 方案三：上传剧本直接跑引擎",
])

# ═══════════════════════════════════════════════════════
# 方案一：CLI 自动生产（已有脚本）
# ═══════════════════════════════════════════════════════
with tab_auto:
    st.markdown('<p class="sub-header">方案一：CLI 一键出片</p>', unsafe_allow_html=True)
    st.markdown("""
    **适用场景**：已有剧本文件，直接跑引擎生成视频成片。
    
    这是最成熟的方案，一条命令完成 8 环节全链路。
    """)
    
    col1, col2 = st.columns([2, 1])
    with col1:
        script_path = st.text_input("剧本文件路径 (.md)",
                                     value="/Coze/Drive/简化画廊/00_项目简报/剧本_助理反击_第1集.md",
                                     key="cli_script")
    with col2:
        tier = st.selectbox("档位", ["T0", "T1", "T2", "cloud"], key="cli_tier")
    
    col3, col4, col5 = st.columns(3)
    with col3:
        style = st.selectbox("画风轨", FORM_SCHEMA["properties"]["style_key"]["enum"],
                              index=0, key="cli_style")
    with col4:
        scenario = st.selectbox("剧种场景",
                                 ["workplace_drama", "historical", "romance", "thriller", "fantasy"],
                                 key="cli_scenario")
    with col5:
        cloud_model = st.selectbox("云端模型（可选）",
                                    ["none", "wan", "kling", "seedream"],
                                    key="cli_cloud")
    
    ep_count = st.slider("集数/分镜数", 1, 30, 10, key="cli_ep")
    
    if st.button("▶ 运行引擎", type="primary", key="btn_cli"):
        with st.spinner("正在生成工作流并执行 8 环节..."):
            from picwf.pipeline_cli import run as pipeline_run
            import os as _os
            _workdir = _os.path.join(tempfile.gettempdir(), "hookforge_cli", str(hash(script_path)) % 10000)
            _kw = dict(
                script_path=script_path, tier=tier, style=style,
                scenario=scenario, ep=ep_count, workdir=_workdir,
            )
            if cloud_model != "none":
                _kw["cloud_model"] = cloud_model
            try:
                _res = pipeline_run(**_kw)
                st.success(f"✅ 完成！共 {_res.get('completed', 0)} 环节")
                st.json(_res.get("pipeline_report") or _res)
                if _res.get("final_video"):
                    st.video(_res["final_video"])
            except Exception as e:
                st.error(f"❌ 执行失败: {e}")

# ═══════════════════════════════════════════════════════
# 方案二：表单 → LLM → 剧本 → 引擎
# ═══════════════════════════════════════════════════════
with tab_form:
    st.markdown('<p class="sub-header">方案二：表单自动生成剧本 + 出片</p>', unsafe_allow_html=True)
    st.markdown("填写基本信息，LLM 自动生成剧本，再调用引擎出片。")
    
    col1, col2 = st.columns(2)
    with col1:
        form_title = st.text_input("剧名", value="我的短剧", key="form_title")
        form_genre = st.selectbox("题材", FORM_SCHEMA["properties"]["genre"]["enum"], key="form_genre")
        form_episodes = st.number_input("总集数", 1, 50, 10, key="form_eps")
    with col2:
        form_tone = st.selectbox("基调", FORM_SCHEMA["properties"]["tone"]["enum"], key="form_tone")
        form_duration = st.selectbox("每集时长", ["30秒", "1分钟", "2分钟"], key="form_dur")
        form_hit = st.slider("每集爽点数", 1, 5, 3, key="form_hits")
    
    st.markdown("### 👥 角色设定")
    chars_col = st.columns(4)
    characters = []
    for i in range(3):
        with chars_col[i % 3]:
            name = st.text_input(f"角色{i+1} 名字", value="" if i == 0 else f"配角{i}", key=f"char_name_{i}")
            role = st.selectbox(f"角色{i+1} 定位", ["主角", "反派", "配角", "助手"], key=f"char_role_{i}",
                                 index=["主角", "反派", "配角", "助手"].index("主角") if i == 0 else 2)
            gender = st.selectbox(f"角色{i+1} 性别", ["男", "女"], key=f"char_gender_{i}")
        if i < 2:
            st.text_input("", key=f"spacer_{i}")
    
    if all(chars_col[i].children[0].value.strip() for i in range(min(3, st.session_state.get("form_title", "x") != "x"))):
        pass
    
    # 手动构建角色列表
    characters = []
    for i in range(3):
        n = st.session_state.get(f"char_name_{i}", "")
        r = st.session_state.get(f"char_role_{i}", "配角")
        g = st.session_state.get(f"char_gender_{i}", "女")
        if n:
            characters.append({"name": n, "role": r, "gender": g, "age_band": "青年", "key_trait": ""})
    
    form_theme = st.text_input("剧情主题/一句话简介",
                                placeholder="例：被陷害离职的女职员，三年后以投资人身份强势回归...",
                                key="form_theme")
    
    form_style = st.selectbox("画风轨", FORM_SCHEMA["properties"]["style_key"]["enum"],
                               index=0, key="form_style")
    form_tier = st.selectbox("出片档位", ["T0", "T1", "T2", "cloud"], key="form_tier")
    form_cloud = st.selectbox("云端模型", ["none", "wan", "kling", "seedream"], key="form_cloud")
    
    use_llm = st.checkbox("使用 LLM 生成剧本（需配置 API Key）", value=bool(llm_api_base and llm_api_key),
                           key="form_use_llm")
    
    if st.button("🚀 生成剧本并出片", type="primary", key="btn_form"):
        if not form_title.strip():
            st.error("请填写剧名")
        else:
            form = FormInput(
                title=form_title,
                genre=form_genre,
                episodes=form_episodes,
                episode_duration=form_duration,
                theme=form_theme,
                tone=form_tone,
                characters=characters,
                style_key=form_style,
                tier=form_tier,
                cloud_model=form_cloud if form_cloud != "none" else None,
            )
            with st.spinner("正在生成剧本..."):
                res = run_auto_pipeline(
                    form,
                    workdir=tempfile.mkdtemp(prefix="hookforge_form_"),
                    llm_api_base=llm_api_base or None,
                    llm_api_key=llm_api_key or None,
                    use_llm=use_llm,
                )
            if not res["form_valid"]:
                st.error(f"表单校验失败: {res['form_errors']}")
            else:
                st.success("✅ 剧本生成成功")
                st.markdown("### 📄 生成的剧本预览")
                st.code(res["script_text"][:2000], language="markdown")
                if res.get("script_path"):
                    st.markdown(f"**保存路径：** `{res['script_path']}`")
                if res.get("pipeline_report"):
                    pr = res["pipeline_report"]
                    if isinstance(pr, dict) and pr.get("completed"):
                        st.success(f"引擎完成 {pr['completed']}/{pr.get('total', 0)} 环节")
                    elif isinstance(pr, dict) and pr.get("error"):
                        st.warning(f"引擎执行警告: {pr['error']}")
                st.json(res)

# ═══════════════════════════════════════════════════════
# 方案三：上传剧本直接跑引擎
# ═══════════════════════════════════════════════════════
with tab_upload:
    st.markdown('<p class="sub-header">方案三：上传剧本直接出片</p>', unsafe_allow_html=True)
    st.markdown("上传 Markdown 剧本文件，选择参数，直接调用引擎。")
    
    uploaded = st.file_uploader("上传剧本 (.md)", type=["md"], key="upload_md")
    if uploaded:
        st.text_area("剧本预览", uploaded.getvalue().decode()[:800], height=200, disabled=True)
    
    col_u1, col_u2 = st.columns(2)
    with col_u1:
        u_tier = st.selectbox("档位", ["T0", "T1", "T2", "cloud"], key="u_tier")
        u_style = st.selectbox("画风轨", FORM_SCHEMA["properties"]["style_key"]["enum"], index=0, key="u_style")
    with col_u2:
        u_scenario = st.selectbox("剧种场景",
                                   ["workplace_drama", "historical", "romance", "thriller", "fantasy"],
                                   key="u_scenario")
        u_ep = st.slider("集数", 1, 30, 10, key="u_ep")
    
    if st.button("▶ 运行引擎", key="btn_upload"):
        if uploaded:
            _tmp = os.path.join(tempfile.gettempdir(), "uploaded_script.md")
            with open(_tmp, "wb") as f:
                f.write(uploaded.getvalue())
            with st.spinner("正在执行..."):
                from picwf.pipeline_cli import run as pipeline_run
                _wd = tempfile.mkdtemp(prefix="hookforge_upload_")
                _kw = dict(script_path=_tmp, tier=u_tier, style=u_style,
                           scenario=u_scenario, ep=u_ep, workdir=_wd)
                try:
                    _res = pipeline_run(**_kw)
                    st.success(f"✅ 完成 {_res.get('completed', 0)} 环节")
                    st.json(_res)
                except Exception as e:
                    st.error(str(e))
        else:
            st.warning("请先上传剧本文件")

# ─── 底部：三方案对比 ──────────────────────────────────
st.divider()
st.markdown("### 📊 三套方案对比")

col_a, col_b, col_c = st.columns(3)
with col_a:
    st.markdown("""
    **📝 方案一：CLI 自动生产**
    - 输入：剧本 .md 文件
    - 操作：一条命令
    - 优点：最稳定，已有完整链路
    - 缺点：需手动准备剧本
    - 适用：已有剧本，快速出片
    """)
with col_b:
    st.markdown("""
    **🎨 方案二：表单 → LLM → 引擎**
    - 输入：剧名/题材/角色等表单
    - 操作：填表 → 一键生成
    - 优点：从零开始，无需写剧本
    - 缺点：依赖 LLM 质量
    - 适用：创意阶段，快速验证
    """)
with col_c:
    st.markdown("""
    **📂 方案三：上传剧本**
    - 输入：上传 .md 文件
    - 操作：选参数 → 运行
    - 优点：灵活，支持任意剧本
    - 缺点：每次都要上传
    - 适用：临时测试，快速迭代
    """)
