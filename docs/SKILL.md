---
name: xiaozhi-robot-voice-ops
description: >
  小知/小智/宜星机器人的语音链路运维与提速。整条链路（xiaozhi 服务端 + ASR/LLM/TTS）已全部
  搬到 Mac mini M4（/Volumes/S/AI-Runtimes/xz，S 盘）；NAS 只留一个极简 OTA 应答把设备引向 M4
  （设备固件把 OTA 硬编码成 192.168.31.20:18003）。含屏幕 emoji 上屏、提示词与思考开关、
  故障排查（变慢/连不上/中文回复）。Use when 小智/小知/宜星机器人语音变慢、连不上、屏幕不生动、
  要换 ASR/LLM/TTS、或要改提示词。
---

# 小知/小智机器人 语音链路运维（xiaozhi-robot-voice-ops）

## 架构与端口（2026-09-20 起：全部在 M4）
```
机器人(ESP32-C3, MAC <DEVICE_MAC>)
  ├─ OTA: http://192.168.31.20:18003/xiaozhi/ota/   ← 固件硬编码，NAS 极简应答（node:22-alpine, 容器 xz-ota）
  │       └─ 返回 ws://192.168.31.68:8000/xiaozhi/v1/  → 设备直连 M4
  └─ WebSocket → Mac mini M4 192.168.31.68:8000  (xiaozhi-esp32-server, launchd com.xz.server)
        ├─ ASR  OpenaiASR → http://127.0.0.1:8879  (sherpa SenseVoice, lang=en)
        ├─ LLM  LocalLLM  → http://127.0.0.1:8890  (mlx_lm.server Qwen2.5-3B-4bit)
        ├─ TTS  OpenAITTS → http://127.0.0.1:8880  (macOS say)
        └─ HTTP/OTA → M4:8003
```
- 全部在 Mac mini **S 盘** `/Volumes/S/AI-Runtimes/xz/`（APFS，已登记资源层 registry）：
  `server/`(服务端源码+data/.config.yaml) `models/` `venvs/{asr,llm,server}` `bin/`(含 ffmpeg 静态二进制) `logs/` `LOG.md`
- launchd（M4 用户级）：`com.xz.asr`(8879) `com.xz.tts`(8880) `com.xz.llm`(8890) `com.xz.server`(8000/8003)
- Python：uv 安装的 3.10.20；服务端 venv `venvs/server`（不含 torch/funasr，因为 ASR 走远端）。

## 关键路径
- 服务端配置：M4 `/Volumes/S/AI-Runtimes/xz/server/data/.config.yaml`
- 服务脚本：M4 `/Volumes/S/AI-Runtimes/xz/bin/{asr_service.py,tts_service.py,watchdog-llm.sh,run-*.sh}`
- TTS 音色/venv：`/Volumes/S/AI-Runtimes/xz/piper/en_US-amy-medium.onnx`、`venvs/piper`
- 启动包装：`run-server.sh`（导出 PATH 含 ffmpeg，exec python app.py）
- NAS OTA 应答：容器 `xz-ota`（node:22-alpine，脚本 `/share/Container/xz-ota/ota.js`）
- 旧 NAS 服务端容器 `xiaozhi-esp32-server` 已停（保留可回滚）

## 常用操作
```bash
# 健康检查
ssh mac-mini 'for p in 8879 8880 8890; do curl -s -o /dev/null -w "$p=%{http_code}\n" http://127.0.0.1:$p/health; done; lsof -nP -iTCP -sTCP:LISTEN | grep -E ":8000|:8003"'
# 重启某服务
ssh mac-mini 'launchctl kickstart -k gui/$(id -u)/com.xz.server'
# 改配置：编辑 M4 server/data/.config.yaml 后重启 com.xz.server
# 切 TTS 引擎（piper 默认最快 ~0.15s / say / kokoro 音质最好但慢）：改 com.xz.tts 的 XZ_TTS_ENGINE
# NAS OTA 应答：docker restart xz-ota
```

## 提速要点（Root Cause → Fix → Verify）
1. **ASR**：NAS Celeron FunASR rtf 5-6 → M4 sherpa SenseVoice(`language=en`) ~0.15s。
2. **LLM**：共享 Spark 未关思考 3-15s + 6326 字符增强提示词 → M4 `mlx_lm.server`+Qwen2.5-3B；首 token 0.2-0.7s。（vLLM 关思考只认 `chat_template_kwargs.enable_thinking=false`；精简 `agent-base-prompt.txt` 为 `{{ base_prompt }}`。）
3. **TTS**：EdgeTTS 每句 3-5s → M4 `say` ~0.8s（Kokoro 在 M4 CPU 反而 1.1-2.3s）。
4. **服务端主机**：原在 NAS 2 核 Celeron（load 12+）→ 搬到 M4，服务端自身 opus/websocket/句子切分不再被拖。
5. **屏幕**：固件只有 情绪表情/stt/tts 三通道 → 提示词让回复以 1 个情绪 emoji 开头 + 1 句含目标单词的短句；emoji 由 `check_emoji()` 在 TTS 前剥离。

## 故障排查
| 症状 | 先查 | 结论 |
|---|---|---|
| 变慢 | M4 `uptime`/load + 各服务 health | 服务空闲很快；多为 M4 被其它任务占用 |
| 显示"连接中" | M4 `com.xz.server` 日志有没有 `conn -` | 没有 = 设备侧，**断电重启机器人** |
| 设备连到 NAS | NAS OTA 应答是否返回 M4 | `curl -X POST http://192.168.31.20:18003/xiaozhi/ota/` |
| 回复中文 | 模型是否跟随英文提示词 | Qwen2.5-3B 对中文输入会跑偏；降 max_tokens / 换模型 |
| launchd exit 78 | 日志路径是否在 /Volumes/S | 用 S 上 `run-*.sh` 重定向（launchd 不能写 noowners 卷） |
| 服务端启动失败 | `server.out.log` | 缺依赖用 `uv pip install`；缺 ffmpeg 用 `bin/ffmpeg`（imageio-ffmpeg 静态二进制） |


## LLM 漂移看门狗
- `mlx_lm.server` 长时间运行会漂移（单核 100%、一次请求 ~10s、返回 502），xiaozhi 服务端随即报
  `LLM stream processing error` 并播兜底话术「主人，小智现在有点忙 / 我们稍后再试吧」。
- 已部署 `com.xz.watchdog`（每 180s 用 curl 探测 :8890，>6s 或非 200 就 `launchctl kickstart -k com.xz.llm`），
  脚本 `bin/watchdog-llm.sh`，日志 `logs/watchdog.log`（仅记录重启动作）。
- 手动应急：`ssh mac-mini 'launchctl kickstart -k gui/$(id -u)/com.xz.llm'`。



## 延迟预算与调优（M4 本地）
单轮到出声 ≈ VAD静音 + ASR + LLM首句 + TTS：
- **VAD 静音**：`VAD.SileroVAD.min_silence_duration_ms`，默认 **1000ms**（很大），已设 **500ms**（config：`server/data/.config.yaml`）。
- **ASR**：M4 sherpa SenseVoice ~0.15s（+ 上传/落盘 ~0.5s）。
- **LLM 首句**：Qwen2.5-3B 隔离实测 0.23-0.41s（生产 1-3s，取决于历史长度/机器负载）。
- **TTS**：已切 **常驻 Piper**（`en_US-amy-medium`，模型常驻）~0.15-0.20s/句（原 `say` 0.70-0.77s）。
  venv `venvs/piper`（piper-tts），服务 `bin/tts_service.py`（engine=piper，失败回退 say）。
- 已到瓶颈：LLM/ASR 很快；TTS 已换 Piper；VAD 可再降到 400ms（省 0.1s，风险是打断说话）。

## 系统代理坑（重要）
- Mac mini M4 开了**系统代理**（192.168.31.20:7897，给 Codex/OpenAI 用）。httpx/openai SDK 会读取它，
  导致服务端访问 `127.0.0.1:8890`（本地 LLM）也走代理 → 代理把 127.0.0.1 当自己 → 返回 **502** →
  xiaozhi 报 `LLM stream processing error: Error code: 502` → 播「主人，小智现在有点忙 / 我们稍后再试吧」。
- 修复：给 `com.xz.server` 的 plist 加
  `NO_PROXY`/`no_proxy = localhost,127.0.0.1,::1,192.168.31.0/24,192.168.0.0/16,10.0.0.0/8`。
- 排查口令：`NO_PROXY=127.0.0.1,localhost <venv>/bin/python -c "import httpx;print(httpx.post('http://127.0.0.1:8890/v1/chat/completions',json={'model':'<模型路径>','max_tokens':5,'messages':[{'role':'user','content':'hi'}]}).status_code)"`
  （无 NO_PROXY 得 502，加 NO_PROXY 得 200 即命中本坑）。
- 注意：curl 不读系统代理，所以「curl 正常但服务端 502」是本坑的典型特征。

## 设备/板子
- 板型 `zuowei-c3-lcd`（宜星白牌），ESP32-C3，8MB flash，**无 PSRAM**，ST7789 SPI 小屏，官方 xiaozhi-esp32 二次编译（v1.4.7），无 EmoteDisplay → **只能静态 emoji+文本，动画需换 ESP32-S3 带屏板**。
- 固件把 OTA/ws 硬编码为 192.168.31.20（配置门户只能改 WiFi），故 NAS 必须留 OTA 应答。
- 只读识别：`esptool --port /dev/cu.usbmodem* chip_id / flash_id / read_flash 0 0x800000`。

## 坑
- launchd 不能把 StandardOut/ErrorPath 写到 /Volumes/S（noowners）→ exit 78。
- mlx_lm.server 的 model 名要用**本地路径**（用 repo id 会去 HF 拉取）。
- 精简提示词会连 emoji 指令一起删掉，需在自定义 prompt 里补 emoji 白名单前缀。
- 服务端在 macOS 需 ffmpeg（可用 `imageio-ffmpeg` 自带静态二进制）与 libopus（`opuslib_next` 自带）。
- 百度网盘分享需登录+验证码，命令行不可访问。
