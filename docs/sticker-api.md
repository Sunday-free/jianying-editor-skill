# 剪映「贴纸」接口文档

> 通过 mitmproxy 抓包剪映专业版（Mac，v10.4.0）贴纸库整理。
> 抓包时间：2026-10-07 / 2026-10-08

域名统一为 **`lv-api-sinfonlinea.ulikecam.com`**（注意：与「智能划重点」的 `lv-pc-api-sinfonlinea.ulikecam.com` **不是同一个域**），全部为 `POST`。

## 接口概览

| 分类 | 接口 | 状态 | 作用 |
|------|------|------|------|
| 面板 | `POST /artist/v1/panel/get_panel_info` | ✅ 已验证 | 贴纸面板**分类列表**（43 个） |
| 浏览 | `POST /artist/v1/effect/get_resources_by_category_id` | ✅ 已验证 | 某分类下的**资源分页** |
| 搜索①  | `POST /artist/v1/effect/get_search_words` | ✅ 已验证 | **热词 / 默认词** |
| 搜索②  | `POST /artist/v1/effect/get_suggest_words` | ✅ 已验证 | **联想词** |
| 搜索③  | `POST /artist/v1/effect/search` | ✅ 已验证 | **搜索结果**（核心） |
| AI | `POST /artist/v1/aigc_effect/random_prompt` 等 | — | AI 贴纸相关 |

> ✅ 验证方式：直接本地伪造请求调用（`scripts/sticker_search.py`），不经过剪映客户端。

> **⚠️ 浏览 vs 搜索是两条不同的路**：
> - 按分类浏览 → `get_resources_by_category_id`（参数 `category_id`）
> - 按关键词搜索 → `effect/search`（参数 `query`）
>
> 只抓浏览接口会漏掉搜索；这是排查「抓不到搜索接口」时的关键。

---

## 公共 URL query 参数

每次请求都会带上环境/设备信息（query string）：

| 参数 | 示例值 | 说明 |
|------|--------|------|
| `aid` | `3704` | 剪映 App ID |
| `biz_id` | `2` | 业务线 |
| `effect_sdk_version` | `21.1.0` | 特效 SDK 版本 |
| `version_name` / `version_code` | `10.4.0` / `10.4.0` | 客户端版本 |
| `device_platform` | `mac` | 平台 |
| `language` | `zh-Hans` | 界面语言 |
| `region` | `CN` | 区域 |
| `device_id` | `2285265576813817` | 设备 ID |
| `device_info` | `{"cpu":"Apple M2 Pro",...}` | 设备详情（JSON 串） |
| `channel` | `App Store` | 渠道 |

> **实测这些 query 参数不是必需的**：即使 query 全空，接口仍正常返回（见「鉴权结论」）。

---

## 鉴权与本地调用（实测结论）

重放 + 最小化实验（`effect/search` 与 `get_search_words`）表明——**这个域的鉴权比 highlight 更宽松**：

| 请求头 | 是否必需 | 说明 |
|--------|---------|------|
| `content-type: application/json` | ✅ **必需** | 缺失 → `ret=2008 effect search error` |
| `user-agent` | ❌ | **无需伪装**，`Python-urllib` / `curl` 均可 |
| `x-ss-stub` | ❌ | 可省略（真实值 = MD5(body)，但服务端不校验） |
| `cookie`（登录态） | ❌ | 无需登录 |
| `x-ss-dp` / `x-helios` / `x-medusa` / `tdid` | ❌ | 均可省略 |
| 所有 URL query 参数 | ❌ | 可省略 |

**最小可用请求** = `content-type: application/json` + 正确的 JSON body。

实测：`--no-query`（URL 完全不带任何 query 参数）时 `effect/search` 依然正常返回 10 条命中结果。

> **⚠️ 鉴权宽松 ≠ 入参可以乱填**：所有接口的**业务必填字段**仍需正确。
> 典型翻车点：`panel/get_panel_info` 缺 `panel`/`panel_source` 会返回 `ret=1000 invalid parameter`，
> 看起来像鉴权问题，其实是**业务参数缺失**。排查时先怀疑 body，再怀疑鉴权。

---

## 客户端脚本 `scripts/sticker_search.py`

纯标准库实现，**不需要登录、不需要 cookie、不需要 UA 伪装**。

```bash
cd jianying-editor-skill/scripts

# 按关键词搜索（核心）
python3 sticker_search.py 中秋
python3 sticker_search.py 中秋 --count 20 --limit 10      # 每页 20，打印 10 条
python3 sticker_search.py 中秋 --count 20 --pages 3       # 自动翻页 3 页 → 60 条
python3 sticker_search.py 中秋 --json                     # 输出原始 JSON
python3 sticker_search.py 中秋 --no-query                 # 不带任何 URL query 参数

# 热词 / 联想词
python3 sticker_search.py --hot-words
python3 sticker_search.py --suggest 中秋

# 面板分类列表（43 个）
python3 sticker_search.py --categories
python3 sticker_search.py --categories --limit 10 --json

# 分类浏览（category_id 或中文名都行）
python3 sticker_search.py --browse 10515 --count 5
python3 sticker_search.py --browse 中秋 --count 5

# 导出成 config/sticker.json 兼容结构（按 sticker_id 去重合并）
python3 sticker_search.py 中秋 --count 50 --save-config ../config/sticker.json
```

Python 内调用：

```python
from sticker_search import (
    search_stickers, search_all, hot_words, suggest_words,
    panel_categories, browse_category, browse_by_name, dump_config,
)

r = search_stickers("中秋", count=50)
print(r.ok, len(r.items), r.has_more, r.search_id)
for s in r.items:
    print(s.id, s.title, s.best_url())      # best_url() = 优先 hd 1920

# 分类导航
p = panel_categories()                       # 43 个分类
print(p.names()[:5])                         # ['热门', '🥮中秋', ...]
cat = p.find("中秋")                          # 按名称模糊找 → category_id=5914050

# 按分类名直接拉资源
r = browse_by_name("卡皮巴拉", count=50)

# 搜索翻页 + 落 config
r = search_all("中秋", limit=120)             # 自动翻页
entries = r.config_entries()                 # 直接可写入 config/sticker.json
dump_config(r.items, "../config/sticker.json")
```

### 实测结果（不经过剪映客户端）

| 调用 | 结果 |
|------|------|
| `search_stickers("中秋", count=10)` | ✅ `ret=0`，命中 10 条，`next_offset=10`，`has_more=True` |
| `--no-query` | ✅ 同样命中 10 条（query 参数确认可省） |
| `--count 20 --pages 3` | ✅ 累计 60 条，`next_offset=60` |
| `hot_words()` | ✅ `default_word=大家都在搜「箭头」`，recommend 7 个词 |
| `suggest_words("中秋")` | ✅ `['中秋','中秋节','中秋佳节','中秋快乐','中秋佳节灯笼']` |
| `panel_categories()` | ✅ `ret=0`，**43 个分类**，`version_code=1132-`，顺序与客户端面板一致 |
| `browse_category(category_id=10515)` | ✅ 返回「油画春日露营元素太阳」等，结构与搜索一致 |
| `browse_by_name("中秋")` | ✅ 先查面板表 → `category_id=5914050` → 返回「柿子 / 共赴美好」等 |
| `dump_config()` | ✅ 导出的 JSON 字段与现有 `config/sticker.json` 完全一致（`sticker`/`sticker_id`/`title`） |

> 全部为本地伪造请求直接调用，**未经过剪映客户端、未使用任何登录态**。

---

## 1. 搜索主接口 `effect/search`

### 请求

**抓包原文（剪映 Mac v10.4.0 原样复刻，字段一个不少）**：

```json
{
  "app_id": 3704,
  "count": 50,
  "effect_type": 2,
  "filter_optional": {
    "filter_paid_type": [], "filter_uncommercial": false,
    "no_copyrighted": false, "no_tuchong_order": false,
    "only_enterprise_commercial": false
  },
  "need_recommend": false,
  "offset": 0,
  "pack_optional": {
    "fav_scene": null, "image_pack_param": null, "large_image_formats": [],
    "need_collection_id": false, "need_contract": true, "need_favorite_info": false,
    "need_operation_tag": false, "need_parent_tag": false, "need_tag": false,
    "need_thumb": false, "only_commercial": false, "tag_one_level": null
  },
  "query": "中秋",
  "replicate_sdk_version": "",
  "search_id": "",
  "search_option": {
    "aspect_ratio": "", "category_list": [], "effect_segment_type": null,
    "filter_uncommercial": false, "scene": "", "sticker_type": 0
  },
  "statistics_optional": {
    "need_add_count": false, "need_favorite_count": false, "need_usage_count": false
  }
}
```

> 实测：只保留 `app_id` / `effect_type` / `query` / `count` / `offset` / `search_option` 也能正常返回；
> 上面这一坨主要是保证与客户端行为 100% 对齐。

| 关键字段 | 说明 |
|----------|------|
| `query` | **搜索关键词** |
| `effect_type` | `2` = 贴纸 |
| `count` | 每页数量（本次 50） |
| `offset` | 翻页偏移（0 → 50 → 100…） |
| `search_id` | 首页传空；翻页时回填上次返回的 `search_id` |
| `search_option.sticker_type` | 贴纸类型筛选，`0` = 不限 |
| `effect_type` 换成其它值 | 同一套接口可搜其它特效类型 |

### 响应

```json
{
  "ret": "0",
  "errmsg": "success",
  "data": {
    "next_offset": 50,
    "has_more": true,
    "search_id": "20261008004154AB8B46E3E7E17044300D",
    "is_search_result": true,
    "max_rel_score": 3.228163,
    "effect_type": 2,
    "related_words": [],
    "effect_item_list": [ /* 50 条贴纸 */ ]
  }
}
```

### 单条贴纸结构（`effect_item_list[i]`）

顶层 3 个字段：`common_attr`、`author`、`sticker`。

**`common_attr`（22 字段）**：

| 字段 | 示例 | 说明 |
|------|------|------|
| `id` / `effect_id` | `7409910548755647798` | **贴纸资源 ID**（两者相同） |
| `title` | `国风手写-中秋快乐` | 贴纸名称 |
| `description` | 同上 | 描述 |
| `cover_url.small` / `.static_img` | `https://p3-heycan-jy-sign.byteimg.com/...` | 封面图（带签名，有时效） |
| `item_urls` | `["https://lf26-faceu-file-sign.bytecdn.com/..."]` | **贴纸资源下载地址** |
| `download_info.url` / `.format` | `...resize:1920:1920.png` / `png` | 高清下载地址（1920） |
| `md5` | `1ffb5ddf...` | 资源校验 |
| `aspect_ratio` | `1` | 宽高比 |
| `source` / `status` / `is_original` | `1` / `102` / `true` | 来源 / 状态 / 是否原创 |
| `statistics` | `{"favorite_count": 0}` | 统计 |
| `review_info` | `{"review_status": 1, ...}` | 审核信息 |
| `publish_source` / `is_business` / `business_info` | — | 商用 / 发布信息 |
| `category_ids` | `[...]` | 分类 ID 列表 |

**`author`**：`{name, avatar_url, source, uid}`

**`sticker`**（贴纸专有）：
```json
{
  "preview_cover": "",
  "track_thumbnail": "https://...resize:120:120.png",
  "sticker_type": 1,
  "sticker_package": {"width_per_frame": 540, "height_per_frame": 540, "size": 165782},
  "large_image": {"image_url": "https://..."}
}
```

---

## 2. 热词接口 `effect/get_search_words`

搜索框为空时拉取「大家都在搜」+ 热词。

**入参**：`{"app_id": 3704, "effect_type": 2}`

**返回**：
```json
{
  "ret": "0",
  "data": {
    "default_word": "大家都在搜「箭头」",
    "recommend_words": ["春天", "箭头", "马赛克", "问号", "爱心", "点赞", "花"],
    "hot_words": [{"word": "春天", "word_source": 1, "query_id": 0}, ...],
    "grey_words": [{"word": "箭头", "word_source": 1, "query_id": 0}],
    "task_id": "20261008004151EB01BB490FEA8DF57C4D"
  }
}
```

## 3. 联想词接口 `effect/get_suggest_words`

**入参**：
```json
{"app_id": 3704, "count": 5, "effect_type": 2, "query": "中秋",
 "search_option": {"sticker_type": 0}}
```

**返回**：
```json
{
  "ret": "0",
  "data": {
    "sug_words": [
      {"words": "中秋", "group_id": "", "highlight": [{"start": 0, "end": 1}]},
      {"words": "中秋节", "group_id": "", "highlight": [{"start": 0, "end": 1}]},
      {"words": "中秋佳节", ...},
      {"words": "中秋快乐", ...}
    ]
  }
}
```
`highlight[].start/end` = 命中片段的字符下标，用于联想词的红色高亮。

---

## 4. 面板分类 `panel/get_panel_info` ✅

**入参（最小可用）**：

```json
{"app_id": 3704, "effect_type": 2, "panel": "default", "panel_source": "heycan"}
```

> **⚠️ 踩坑记录（重要）**：这个接口的必填字段是 **`panel` + `panel_source`**，
> 缺任一个就返回 `ret=1000 errmsg=invalid parameter`。
> 当时试了 25 种组合（`panel_key` / `panel_id` / `panel_type` / `material_type` /
> `sdk_version` / `category_id` / `need_category` / `resource_type` / `category_type` …
> 连域名都换了）全部失败，**唯独没想到 `panel` 这个「看起来像选择器、其实必填」的字段**。
>
> 突破口：重新抓包拿到 `get_resources_by_category_id` 的**完整原文**，
> 发现里面带了 `"panel":"default"` 和 `"panel_source":"heycan"`，
> 把这两个字段喂给 `get_panel_info` 立刻 `ret=0`。

**返回**：`data.categories[]`（**43 个**）+ `data.version_code`（`1132-`）+ `data.panel_source`。

每项字段：`category_id` / `category_key` / `category_name` / `category_is_top` /
`category_is_vip` / `category_source` / `category_icon` / `category_selected_icon` /
`sub_categories` / `category_extra`。

### 43 个分类全景（2026-10-08 实测，与客户端面板顺序一致）

| # | category_id | category_key | 名称 |
|---|------------|--------------|------|
| 0 | 10515 | `10515` | 热门（`is_top`） |
| 1 | 5914050 | `zhongqiu` | 🥮中秋 |
| 2 | 10586 | `guoqing` | 🇨🇳国庆 |
| 3 | 5915097 | `hajimi` | 🐱hajimi |
| 4 | 5914954 | `shuitun` | 🍊水豚噜噜 |
| 5 | 5914728 | `gou` | 🐶线条小狗 |
| 6 | 10523 | `hudong` | 👍互动 |
| 7 | 10517 | `zhedang` | 😷遮挡 |
| 8 | 5914747 | `tuzi` | 🐰粉红兔子 |
| 9 | 11669 | `11669` | 📸vlog |
| 10 | 5914752 | `shu` | 🐭奶茶鼠 |
| 11 | 10522 | `qingxu` | 😄情绪 |
| 12 | 5914412 | `xiari` | 🍉夏日 |
| 13 | 5914499 | `qiuri` | 🍁秋日 |
| 14 | 5914351 | `jieri` | 🎉节日 |
| 15 | 10742 | `shopping` | 🛍️电商 |
| 16 | 5914743 | `lipu` | 🥕暹罗厘普 |
| 17 | 5914727 | `xiong` | 🐻黄油小熊 |
| 18 | 11670 | `yundong` | 🏃运动 |
| 19 | 5914754 | `lan` | 🥏小蓝 |
| 20 | 10530 | `biankuang` | 🖼️边框 |
| 21 | 11128 | `lvxing` | ✈️旅行 |
| 22 | 5914739 | `shouxie` | ✍️手写字 |
| 23 | 11722 | `langman` | 💝浪漫 |
| 24 | 11859 | `makeup` | 💄美妆 |
| 25 | 5914418 | `yanbiaoqing` | 😊颜表情 |
| 26 | 10518 | `zhishi` | ➡️指示 |
| 27 | 5914410 | `kapi` | 🦦卡皮巴拉 |
| 28 | 11578 | `regeng` | 🗣️热梗 |
| 29 | 11714 | `11714` | 🎈可爱 |
| 30 | 11304 | `meishi` | 🍰美食 |
| 31 | 11856 | `11856` | ☀️假日 |
| 32 | 10519 | `aixin` | 🩷爱心 |
| 33 | 10520 | `shanshan` | ✨闪闪 |
| 34 | 10521 | `jijie` | 🌸季节 |
| 35 | 10527 | `zhakai` | 🎆炸开 |
| 36 | 11443 | `hudie` | 🦋蝴蝶 |
| 37 | 10529 | `jiemian` | 📆界面元素 |
| 38 | 10531 | `youxi` | 🎲游戏元素 |
| 39 | 10524 | `ziran` | 🍃自然元素 |
| 40 | 11291 | `fugu` | 👜复古 |
| 41 | 11307 | `mengchong` | 🐾萌宠 |
| 42 | 11320 | `keji` | 🔭科技 |

> 注意：部分分类的 `category_key` 就是 id 字符串（如热门 `"10515"`、vlog `"11669"`），
> 不是所有分类都有语义化 key —— 所以**能用 `category_id` 就别依赖 `category_key`**。

> 另注：本次抓包中客户端**并没有发这个请求**（面板打开时也没发），
> 说明分类列表在客户端侧有缓存、按过期策略才拉。所以「抓不到它」是正常的，
> 靠伪造请求反而更快。

## 5. 分类浏览 `effect/get_resources_by_category_id` ✅

**入参（抓包原文，Mac v10.4.0）**：

```json
{
  "app_id": 3704,
  "category_id": 5915097,
  "category_key": "hajimi",
  "count": 50,
  "filter_optional": {
    "filter_paid_type": [], "filter_uncommercial": false,
    "no_copyrighted": false, "no_tuchong_order": false,
    "only_enterprise_commercial": false
  },
  "full_count": false,
  "offset": 0,
  "pack_optional": {
    "fav_scene": null, "image_pack_param": null, "large_image_formats": [],
    "need_collection_id": false, "need_contract": false, "need_favorite_info": true,
    "need_operation_tag": false, "need_parent_tag": false, "need_tag": false,
    "need_thumb": false, "only_commercial": false, "tag_one_level": null
  },
  "panel": "default",
  "panel_source": "heycan",
  "replicate_sdk_version": "",
  "request_id": "",
  "statistics_optional": {
    "need_add_count": false, "need_favorite_count": false, "need_usage_count": false
  }
}
```

**返回**：`data.effect_item_list[]`，单条结构与上面 `effect/search` 的贴纸条目**完全一致**。

> 实测「热门」`category_id=10515`、「hajimi」`5915097`、「奶茶鼠」`5914752` 均可正常拉取，
> 翻页 `offset` 0/50/100/150。
> 注意：**分类浏览 ≠ 关键词搜索**，走的是两条不同接口（见开头提醒）。

## 6. AI 贴纸 `aigc_effect/*`

`random_prompt` / `get_history` / `user_aigc_list` — AI 生成贴纸的提示词与历史记录。

---

## 用法建议

- **按关键词找贴纸**：调 `effect/search` 翻页，取 `effect_item_list`；用 `item_urls`（原图）或 `download_info.url`（1920）下载素材。
- 三个搜索接口都带 `effect_type: 2`（贴纸）；同一套 `/artist/v1/effect/` 前缀也服务其它特效类型，改 `effect_type` 即可复用。
- `cover_url` / `item_urls` / `download_info` 均为**带签名的 CDN 地址，有时效**（`x-expires`），需即时下载。
