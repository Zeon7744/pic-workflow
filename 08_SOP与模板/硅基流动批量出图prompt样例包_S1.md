# 硅基流动批量出图 Prompt 样例包（S1 画风 · 沈临/苏雪晴）

> 版本：v1.0 ｜ 编制：视频导演 ｜ 用途：硅基流动 `Tongyi-MAI/Z-Image-Turbo` 接口联调画风基准样本
> 对齐：《LoRA训练素材组织规范》§四 + `character_consistency.build_character_block(lang="en")`
> 目标：红剑按 §四 流程跑 10 张主力样本，验证画风对齐度与角色一致性

---

## 一、固定基底（每张 prompt 都必须逐字复用）

### 1. S1 画风统一前缀（英文版，Z-Image 主力）

```text
Japanese 2D anime illustration style, clean and crisp linework, high-saturation clean color palette (cyan-blue primary with warm orange accents), flat colors with light cel shading, soft volumetric lighting in Makoto Shinkai style, medium-fine detail density, cinematic shallow depth of field, emotion-driven atmosphere.
```

> 对应画风总纲_S1_anime_jp §四 `[统一前缀-S1]` 的英文投影。中文原版见 §四备注，两版画风语义完全一致。

### 2. 角色外观锁定 Block（英文版，逐字复用）

**沈临（男主，P0）：**

```text
Shen Lin (male lead): male character, 25-32 years old, dark blue-black short jagged hair, deep blue trench coat with white shirt, cold and restrained demeanor, notable feature: silver earring on left ear. Keep facial structure, proportions, hairstyle and outfit color consistent across all shots.
```

**苏雪晴（女主，P0）：**

```text
Su Xueqing (female lead): female character, 22-28 years old, warm brown waist-length wavy hair, cream knit cardigan with light orange dress, gentle and sweet demeanor, notable feature: sakura hair clip on the side. Keep facial structure, proportions, hairstyle and outfit color consistent across all shots.
```

### 3. 统一负向提示词（推荐）

```text
blurry, low quality, deformed hands, extra fingers, watermark, text, logo, realistic photo, 3D render, live action, multiple people, different character, costume change, hairstyle change
```

---

## 二、10 张基准样本（覆盖变化轴）

> 变化轴：角度（正面/3-4侧/侧背/全身）/ 表情（中性/冷峻/喜/哀/乐）/ 场景（棚拍/剧内主场景）。样本编号即建议的 `{name}_train_01..10.jpg`。

### 沈临 5 张（编号 shen_lin_train_01-05）

| # | 变化轴 | 场景/状态 | 附加变化词（接在 block 后） |
|---|---|---|---|
| 01 | 正面半身 | 纯色棚拍，中性表情 | `front half-body portrait, neutral expression, plain light-grey studio background, soft key light` |
| 02 | 3/4 侧脸 | 棚拍，冷峻凝视 | `three-quarter side view, close-up portrait, cold sharp gaze, plain light-grey studio background` |
| 03 | 正面特写 | 棚拍，微喜 | `close-up portrait, slight confident smile, plain light-grey studio background` |
| 04 | 侧/背全身 | 棚拍，站姿 | `side and back three-quarter view, full body standing pose, plain light-grey studio background` |
| 05 | 主场景 | 都市天台夜景 | `full body, standing on urban rooftop at night, city lights bokeh background, cyan-blue night atmosphere with warm orange city glow` |

### 苏雪晴 5 张（编号 su_xueqing_train_06-10）

| # | 变化轴 | 场景/状态 | 附加变化词（接在 block 后） |
|---|---|---|---|
| 06 | 正面半身 | 纯色棚拍，甜笑 | `front half-body portrait, warm sweet smile, plain light-grey studio background, soft key light` |
| 07 | 3/4 侧脸 | 棚拍，俏皮 | `three-quarter side view, close-up portrait, playful expression, plain light-grey studio background` |
| 08 | 正面特写 | 棚拍，落泪 | `close-up portrait, teary eyes with gentle sadness, plain light-grey studio background` |
| 09 | 全身 | 暖阳街景 | `full body, standing on sunlit street, warm afternoon sunlight, soft shadows, pastel urban background` |
| 10 | 主场景 | 咖啡店窗边 | `half-body, sitting by cafe window, warm interior light, cozy atmosphere, bokeh background` |

### 完整 prompt 拼接公式（每张）

```text
{S1 画风前缀英文} + {角色外观 block 英文} + {该行附加变化词}
```

示例（沈临 01）：
```text
Japanese 2D anime illustration style, clean and crisp linework, high-saturation clean color palette (cyan-blue primary with warm orange accents), flat colors with light cel shading, soft volumetric lighting in Makoto Shinkai style, medium-fine detail density, cinematic shallow depth of field, emotion-driven atmosphere. Shen Lin (male lead): male character, 25-32 years old, dark blue-black short jagged hair, deep blue trench coat with white shirt, cold and restrained demeanor, notable feature: silver earring on left ear. Keep facial structure, proportions, hairstyle and outfit color consistent across all shots. Front half-body portrait, neutral expression, plain light-grey studio background, soft key light.
```

---

## 三、批量调用参数建议

| 参数 | 建议值 | 说明 |
|---|---|---|
| 模型 | `Tongyi-MAI/Z-Image-Turbo` | ¥0.10/张主力 |
| 单张分辨率 | 1024×1024（或 832×1216 竖版） | LoRA 训练档 1024p 兼容；训练集以方图/近方图为主 |
| seed | 固定每组合一个 seed 先试跑 5 张 | 画风不稳时便于定位 prompt 而非随机性 |
| 每批 | 先 5 张 → 质检 → 再扩批 | 按规范§四质量控制 |
| 参考图 | 可选：`02_图像/角色卡/出图测试_沈临_动漫三视图.png` 等 | Z-Image 若支持参考图则挂三视图锚点，能进一步提升一致性 |
| caption | 用本包角色 block 同源 | 落 train/ 目录 + captions.json |

## 四、中文版 S1 前缀（备用，若联调需中英对照）

```text
日本动画风格动漫插画，干净利落线条，高饱和干净色板（主色青蓝+暖橙点缀），平涂加少量阴影动画作画质感，柔和体积光新海诚式光影，中等偏精致细节密度，电影感浅景深，情绪导向氛围。
```

---

## 五、验收标准（红剑联调后反馈我）

- 10 张全部 S1 画风对齐（无写实/3D 泄漏、色板统一青蓝+暖橙）
- 沈临/苏雪晴脸、发型、服装跨张一致（目检 + 有需要挂 `face_similarity_gate` 阈值 0.65）
- 每张无文字水印、无多人混入
- 不合格样本按组合重抽，不整批重跑

> 通过后我这边可直接把这 10 张作为 S1 首批 LoRA 训练集基准，补足到 20 张标准档即开训男主/女主。
