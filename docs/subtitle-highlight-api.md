# 剪映「智能划重点」接口文档

> 通过 mitmproxy 抓包剪映专业版（Mac，v10.4.0）字幕识别流程整理。
> 抓包时间：2026-10-07

## 结论：智能划重点 = `audio_subtitle/highlight`

「智能划重点」不是识别（ASR）本身，而是在字幕文本产出后，**再调一次关键词提取接口**得到重点词及位置。完整链路为 3 段式：

| 步骤 | 接口 | 作用 |
|------|------|------|
| 1 | `POST /lv/v1/common_task/new` | 提交 ASR 识别任务（`enter_from: "asr_llm"`） |
| 2 | `POST /lv/v1/common_task/query` | 轮询任务进度（`processing` → `succeed`） |
| 3 | `POST /lv/v1/audio_subtitle/highlight` | **智能划重点**：输入字幕文本，返回关键词 |

域名：`lv-pc-api-sinfonlinea.ulikecam.com`（`content-type: application/json`）

---

## 3. 智能划重点接口

### 请求

```
POST https://lv-pc-api-sinfonlinea.ulikecam.com/lv/v1/audio_subtitle/highlight
Content-Type: application/json
```

**入参**（只有 4 个字段）：

```json
{
  "draft_id": "91E08AC5-22FB-47e2-9AA0-7DC300FAEA2B",
  "language": "zh",
  "scene": "common",
  "subtitle_list": [
    "半年时间翻了30倍",
    "你没有听错的啊",
    "靠的不是内幕",
    "也不是什么神秘的消息",
    "..."
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `draft_id` | string | 草稿 ID |
| `language` | string | 语言，实际固定传 `zh`。**实测该字段不影响结果**（见下方「language 实测」） |
| `scene` | string | 场景，固定 `common` |
| `subtitle_list` | string[] | **字幕文本数组**（每句一条，本次 123 条） |

### 响应

```json
{
  "ret": "0",
  "errmsg": "success",
  "svr_time": 1791357284,
  "log_id": "20261007151442595F5D66BAFE75BA1805",
  "systime": "1791357284",
  "response": "",
  "sign": "",
  "Data": {
    "keyword": [
      [{"keyword": "翻了30倍", "start_index": 4, "end_index": 9}],
      [{"keyword": "没有听错", "start_index": 1, "end_index": 5}],
      [{"keyword": "内幕", "start_index": 4, "end_index": 6}],
      [{"keyword": "神秘的消息", "start_index": 5, "end_index": 10}],
      [],
      []
    ],
    "task_id": "3ae86c38-57a5-4fe6-b439-788402f9b365"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `ret` | string | `"0"` 表示成功 |
| `Data.keyword` | array[][] | **二维数组，与入参 `subtitle_list` 一一对应**（同长度） |
| `Data.keyword[i]` | object[] | 第 i 句的关键词列表；无关键词时为 `[]` |
| `…[].keyword` | string | 关键词文本 |
| `…[].start_index` / `end_index` | int | 关键词在该句文本中的**字符起止下标**（左闭右开） |
| `Data.task_id` | string | 本次划重点任务 ID |

本次样本：123 组 keyword（对应 123 句字幕），共提取 93 个关键词。

---

## 1. ASR 任务提交 `common_task/new`（前置步骤）

**入参**：
```json
{
  "bind_id": "91E08AC5-22FB-47e2-9AA0-7DC300FAEA2B",
  "can_queue": true,
  "enter_from": "asr_llm",
  "tasks": [
    {
      "context": "cd830f23-3df6-4e33-bee0-48eb6aeb2f83",
      "payload": "{\"enable_punc\":true,\"utterances\":[{\"start_time\":90,\"end_time\":59960,\"text\":\"...\",\"words\":[{\"text\":\"半\",\"start_time\":90,\"end_time\":250}, ...]}]}"
    }
  ]
}
```

**返回**：
```json
{"ret":"0","errmsg":"success","data":{"tasks":[{"id":"6ac5f1612b8b5c01940cb3a6_8_2","bind_id":"...","status":"processing","token":"328c77ace59dbb26e0319391e8479712","req_key":"asr_llm","estimated_time":433}]}}
```

## 2. 任务轮询 `common_task/query`

**入参**：
```json
{"tasks":[{"id":"6ac5f1612b8b5c01940cb3a6_8_2","req_key":"asr_llm","task_version":"v3","token":"328c77ace59dbb26e0319391e8479712"}]}
```

**返回（进行中）**：
```json
{"data":{"tasks":[{"status":"processing","progress":90,"duration":56,"estimated_time":43,"failed_node_key":"asr_llm"}]}}
```

**返回（完成）**：`status: "succeed"`，`payload` 内含带时间轴与逐字 `words` 的完整 `utterances`。

---

---

## 无需登录态：本地直接调用

客户端脚本：`scripts/subtitle_highlight.py`（参考 `universal_tts.py` 的伪造调用方式）。

**鉴权结论（重放实验）**：

| 请求头 | 是否必需 | 说明 |
|--------|---------|------|
| `content-type: application/json` | ✅ | — |
| `user-agent` | ✅ | **必须为剪映客户端 UA**（`Cronet/TTNetVersion:…`）。脚本类 UA（`python-requests`、urllib 默认）会被拒，返回 `ret=1014 system busy` |
| `x-ss-stub` | ✅ | 值 = **MD5(body)**，可自行计算 |
| `sign` / `sign-ver` | ❌ | 可省略 |
| `cookie`（登录态） | ❌ | 可省略 |
| `tdid`（设备 ID） | ❌ | 可省略 |
| `draft_id` | — | 可任意填写，不参与鉴权 |

调用示例：

```python
from subtitle_highlight import highlight

r = highlight(["半年时间翻了30倍", "靠的不是内幕"])
print(r.ok, r.plain())          # True [['翻了30倍'], ['内幕']]
for group in r.keywords:        # 带下标
    print([(k.keyword, k.start_index, k.end_index) for k in group])
```

CLI：

```bash
python subtitle_highlight.py "半年时间翻了30倍" "靠的不是内幕" --json
```

异步调用：`await highlight_async(subtitle_list)`。

---

## 备注

- `subtitle_list` 直接来源于 ASR 结果的分句文本；`highlight` 的返回下标是针对该句的字符位置，可直接用于字幕高亮/花字标注。
- 该接口与「智能去水词」是同级开关，二者都会在 ASR 完成后追加处理请求。
- **调用时机**：客户端在 `common_task/new` 提交 ASR 任务后约 **1.7s**（ASR 完成）立即调用 highlight；ASR 完成前会先发一次 `subtitle_list=[]` 的**空预检**。

## language 实测（2026-10-07 补测）

用一段**粤语**口播字幕（29 句，含「嘅/嗱/佢系响/唔应该/我哋」）作输入，结论：

| language 传入值 | 结果 |
|---|---|
| `zh` / `zh-hk` / `zh-HK` / `zh-yue` / `zh-hant` / `cantonese` / `en` / `ja` / `zh-cn` / `zh_CN` / `ZH` / `yue` | 全部 `ret=0`，返回**完全相同**的关键词 |
| 逐字对比 `zh` vs `zh-hk` vs `cantonese` | **29/29 句完全一致** |

**结论**：服务端**忽略 `language` 取值**，只按字幕文本本身提取关键词。
- 粤语内容**不需要**传 `zh-hk`，用 `zh` 即可，结果一模一样。
- 剪映客户端实测对粤语草稿也**仍旧传 `zh`**。
- 偶发的 `ret=1035 highlight subtitle failed` 是**限流/网络抖动**，与 language 取值无关（复测即恢复）。
