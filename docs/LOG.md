# 小知/宜星机器人 语音链路与屏幕优化 日志

更新：2026-09-20 · 执行：Air M5 opencode · 主机：Mac mini M4(192.168.31.68) + NAS(192.168.31.20) + Spark(192.168.31.225)

## 1. 目标
机器人（英文固件）升级后语音"超级慢"，并希望屏幕更生动。

## 2. 根因与修复（逐层）

### 2.1 ASR 慢（主因）
- 原：NAS Intel Celeron 3865U(2核, load≈10) 上跑 FunASR SenseVoice，rtf 5-6（1.87s 音频要 10.7s 推理，加载 94s）。
- 修复：Mac mini M4 部署 sherpa-onnx SenseVoice HTTP 服务（`OpenaiASR` 指向它），并强制 `language=en`（避免中/日误识别）。
- 实测：容器→M4 **0.15s**（原 10-18s）。

### 2.2 LLM 慢
- 原：指向被多 agent 共享的 Spark vLLM `GLM-5.3-Flash-EXL3`，未关思考，每轮多烧 ~100 reasoning token（3-15s）；且 6326 字符的"增强提示词"每轮全量 prefill。
- 修复：
  - 容器启动补丁 `patch/apply.sh`：给 Spark 关思考（`chat_template_kwargs.enable_thinking=false`，vLLM 只认这个字段）；把 `agent-base-prompt.txt` 精简为 `{{ base_prompt }}`（6326→~300 字符，同时去掉模板里默认 `language=中文` 的冲突指令）。
  - 最终改用 Mac mini M4 本地专属 LLM：`mlx_lm.server` + `Qwen2.5-3B-Instruct-4bit`（:8890），不再被抢。
- 实测：首 token **0.2-0.7s**。

### 2.3 TTS 慢
- 原：云端 EdgeTTS，每句 3-5s（每句一次握手）。
- 修复：Mac mini M4 部署本地 TTS HTTP 服务（:8880）。引擎可切：`say`（默认，~0.75-0.8s）或 Kokoro-82M。
- 实测：`say` 0.75-0.8s；Kokoro 1.1-2.3s（CPU 反而慢，CoreML 不支持）→ 已切回 `say`。

### 2.4 屏幕更生动（服务端 A 方案）
- 固件只支持 3 个显示通道：情绪表情、孩子的话(stt)、回复文本(tts)。
- 修复：提示词改为「每个回复 = 1 个情绪表情（21 选 1）+ 1 句 ≤10 词、含正在教的英文单词的短句」。
- 实测：`I like cats.` → `😄I like cats too!`；`teach me the word elephant` → `😄 The elephant is really big!`
- emoji 只走显示，TTS 前由 `check_emoji()` 剥离，不影响朗读与速度。

## 3. 服务与路径（全部在 Mac mini M4 的 S 盘）
```
/Volumes/S/AI-Runtimes/xz/
├── bin/     asr_service.py, tts_service.py, run-{asr,tts,llm}.sh
├── models/  sherpa SenseVoice + kokoro-en-v0_19 + Qwen2.5-3B-Instruct-4bit
├── venvs/   asr, llm
└── logs/
```
- launchd（用户级）：`com.xz.asr`(:8879)、`com.xz.tts`(:8880)、`com.xz.llm`(:8890)
- **坑**：launchd 无法把 StandardOutPath/StandardErrorPath 写到 /Volumes/S（noowners）→ exit 78；改用 S 上的 `run-*.sh` 包装脚本自行重定向日志。
- 本地 mlx LLM 无鉴权（仅局域网）。

## 4. xiaozhi 服务端（NAS 容器）
- 配置：`/share/Container/xiaozhi-esp32-server/data/.config.yaml`
- `selected_module`: ASR=OpenaiASR(→M4:8879) · LLM=LocalLLM(→M4:8890) · TTS=OpenAITTS(→M4:8880)
- 启动补丁：`/share/Container/xiaozhi-esp32-server/patch/apply.sh`（compose command 挂载执行）
- 设备授权 MAC：`<DEVICE_MAC>`

### 配置备份（回滚用）
- `.config.yaml.bak-20260919-en-switch`
- `.config.yaml.bak-20260920-remoteasr`
- `.config.yaml.bak-20260920-m4tts`
- `.config.yaml.bak-20260920-onesentence`
- `.config.yaml.bak-20260920-localllm`
- `.config.yaml.bak-20260920-emoji`
- `.config.yaml.bak-20260920-screenA`
- `patch/apply.sh.bak-20260920-promptmin`
- `docker-compose.yml.bak-20260920-thinking`

## 5. 设备/板子识别（esptool 只读，8MB flash）
| 项 | 值 |
|---|---|
| 品牌 | 宜星（固件内标识 `zuowei`，配网热点 `zuowei-B1E9`） |
| 板型名 | `zuowei-c3-lcd`（官方 xiaozhi-esp32 二次编译，v1.4.7） |
| 主控 | ESP32-C3 QFN32 rev v0.4，单核 160MHz，**无 PSRAM** |
| Flash | 8MB（分区 nvs/otadata/phy_init/model/ota_0/ota_1） |
| 屏 | **ST7789 SPI**（标准 LCD 显示类，无 EmoteDisplay/动画） |
| 音频 | I2S 自定义 codec（`VbAudioCodec`），非 ES8311 |
| MAC | <DEVICE_MAC> |

**结论**：C3 无 PSRAM，官方动画表情（EmoteDisplay）跑不动；厂商板级源码不公开（GitHub/Gitee/淘宝/1688 均查无 `zuowei-c3-lcd`）。要真动画需换官方支持的 ESP32-S3 带屏板（N16R8）。
屏规格待定：厂商网盘"1.54寸TFT"含 8/10/12/15/16 针多版本，需按实物针数确认（8 针蓝板模块最通用）。

## 6. 性能对比
| 阶段 | 最初 | 现在 |
|---|---|---|
| ASR | 10-18s（NAS Celeron） | 0.15s（M4 sherpa，强制英文） |
| LLM 首 token | 3-15s（Spark 被抢/思考） | 0.2-0.7s（M4 本地 Qwen2.5-3B） |
| TTS | 3-5s/句 ×3 句（EdgeTTS） | 0.75-0.8s ×1 句（`say`） |
| 整轮到出声 | ~15-20s | **~1.5s** |

## 7. 待办/未决
- 机器人重启后需确认建连（多次重启容器后设备偶发"连接中"，断电重启可恢复）。
- 屏模块针数/型号待用户确认（发照片可用本机视觉模型识别）。
- 百度网盘厂商资料需登录+验证码，命令行无法访问；需用户下载到本机。
- 本地候选入库：NAS Brain `aec-645a75554b87c0e3e8f0`（语音链路提速 playbook）。

---

## 8. 2026-09-20 晚：服务端从 NAS 搬到 Mac mini M4（按 owner 要求）

### 变更
- **xiaozhi-esp32-server 全部搬到 M4**：源码 `/Volumes/S/AI-Runtimes/xz/server`，uv Python 3.10.20，venv `venvs/server`（不含 torch/funasr，ASR 走远端）。
- launchd `com.xz.server` 常驻，监听 8000(ws)/8003(ota)。
- 配置 `server/data/.config.yaml`：ASR/LLM/TTS 全部指向 `127.0.0.1`；`server.websocket = ws://192.168.31.68:8000/xiaozhi/v1/`。
- **NAS 旧容器 `xiaozhi-esp32-server` 已停**；NAS 只留极简 OTA 应答容器 `xz-ota`（node:22-alpine，端口 18003，脚本 `/share/Container/xz-ota/ota.js`）——因为**设备固件把 OTA 硬编码为 `http://192.168.31.20:18003/xiaozhi/ota/`**（配置门户只能改 WiFi），必须由 NAS 把设备引向 M4。
- M4 缺的依赖已补：ffmpeg（`imageio-ffmpeg` 静态二进制，软链到 `bin/ffmpeg`）、SileroVAD 模型（从 NAS 容器拷 `models/snakers4_silero-vad`）、mcp==1.22.0、cryptography、portalocker、aioconsole、numpy 等。
- **资源层登记**：`registry_register /Volumes/S/AI-Runtimes/xz "..." resource` 已完成（audit-log 留痕）。

### 迁移后链路
```
机器人 → OTA 192.168.31.20:18003 (NAS xz-ota) → 返回 ws://192.168.31.68:8000
      → WebSocket 直连 M4:8000 (com.xz.server)
          ASR 127.0.0.1:8879 / LLM 127.0.0.1:8890 / TTS 127.0.0.1:8880
```

### 回滚
- 起回 NAS 容器：`docker start xiaozhi-esp32-server`（其 compose 仍在 `/share/Container/xiaozhi-esp32-server/`）。
- 停 NAS OTA 应答：`docker rm -f xz-ota`。
- 停 M4 服务端：`launchctl bootout gui/$(id -u)/com.xz.server`。

---

## 9. 2026-09-20 晚：设备"我们稍后再试吧"根因 + LLM 看门狗

### 症状
设备显示/播报「主人，小智现在有点忙 / 我们稍后再试吧」，看着像连不上。

### 定位过程（关键证据）
- NAS 抓包：设备 `192.168.31.199` 与 `NAS:18000` 持续收发 → 设备其实**已连上**，NAS 转发到 M4:8000。
- M4 `server.out.log`：设备 conn 正常、收到 hello、ASR 也识别出文本；但紧接着
  `ERROR LLM stream processing error: Connection error / Error code: 502`，然后走兜底话术。
- M4 本地 LLM 实测：一次请求 **10.8s**、`mlx_lm.server` 单核 100%（跑了两小时后漂移）。
- 结论：**不是连接问题，是本地 LLM 服务漂移**导致服务端 LLM 调用失败。

### 修复
- 重启 `com.xz.llm` → 延迟回到 0.75–1.4s。
- 新增看门狗 `com.xz.watchdog`（StartInterval 180s）：探测 :8890，非 200 或 >6s 就
  `launchctl kickstart -k com.xz.llm`；脚本 `bin/watchdog-llm.sh`，日志 `logs/watchdog.log`。

### 备注
- NAS 侧 `xz-ota` 网关：18003 应答 OTA（返回 `ws://192.168.31.20:18000/xiaozhi/v1/`）、
  18000 纯 TCP 转发到 M4:8000。设备固件要求 OTA 与 websocket 同主机（192.168.31.20），故保留。

---

## 10. 2026-09-20 晚：设备仍报「有点忙/稍后再试」的真正根因 = 系统代理

- 症状：设备连得上、ASR 正常，但 LLM 调用报 `Error code: 502`，播兜底话术。
- 定位：M4 上 **curl 访问 127.0.0.1:8890 正常(200)**，但 **openai SDK / httpx 得 502** 且 mlx 无请求日志。
- 根因：M4 开了**系统代理**（192.168.31.20:7897，给 Codex 用），`urllib.getproxies()` 返回它，httpx/openai
  读取后把 `127.0.0.1` 也走代理 → 代理侧 127.0.0.1 是自己 → 502。
- 修复：`com.xz.server` plist 增加
  `NO_PROXY`/`no_proxy=localhost,127.0.0.1,::1,192.168.31.0/24,192.168.0.0/16,10.0.0.0/8`，重载。
  验证：`NO_PROXY=... python -c "httpx.post(...)"` → 200；openai SDK → 200。
- 特征记忆：**curl 正常但应用报 502** → 先查系统代理/NO_PROXY。

---

## 11. 2026-09-20 晚：延迟预算与 VAD 调优

- 单轮到出声 = VAD静音 + ASR + LLM首句 + TTS。
- **VAD 默认 min_silence_duration_ms=1000ms**（孩子说完要等满 1 秒），已在 `data/.config.yaml` 设 **500ms**。
- 组件隔离实测：LLM 首句 0.23-0.41s、TTS(`say`) 0.70-0.77s、ASR ~0.15s。
- 剩余空间：① TTS 换 Piper（~0.15s，省 ~0.5s，音质中等）；② VAD 再降到 400ms（省 0.1s，可能打断）。
- LLM/ASR 已接近下限。

---

## 12. 2026-09-20 晚：TTS 换常驻 Piper（再省 ~0.5s）

- Piper 独立二进制缺 dylib（libespeak-ng/libonnxruntime），改用 pip 版 `piper-tts`：
  venv `/Volumes/S/AI-Runtimes/xz/venvs/piper`，音色 `/Volumes/S/AI-Runtimes/xz/piper/en_US-amy-medium.onnx`。
- `tts_service.py` 支持 engine=piper|say|kokoro，**piper 模型常驻**（load 0.37s 一次性）。
- 实测：Piper 稳态 **0.15-0.20s/句**（`say` 0.70-0.77s）；服务 `com.xz.tts` 改用 piper venv，engine=piper，失败回退 say。
- 最终延迟预算：VAD 500ms + ASR ~0.15s + LLM 首句 ~0.3-1s + TTS ~0.15s ≈ **~1-2s 到出声**。
