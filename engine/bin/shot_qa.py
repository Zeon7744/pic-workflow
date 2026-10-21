#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""镜头质检 CLI：输入镜头视频 + prompt，输出形变/质变/迁移/偏移 4 维打分。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from picwf.shot_qa import main as shot_main
if __name__ == "__main__":
    sys.exit(shot_main())
