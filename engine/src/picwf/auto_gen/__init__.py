# -*- coding: utf-8 -*-
"""自动剧本生成链路：表单 → LLM → 剧本 → 引擎出片。"""
from .form_schema import FORM_SCHEMA, validate_form, FormInput
from .script_generator import generate_script_from_form
from .chain import run_auto_pipeline
