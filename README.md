# xiaozhi-local-voice

把 xiaozhi（小智 / xiaozhi-esp32）语音助手从「云端 + 共享大模型 + 慢主机」改成**全本地、低延迟**的语音链路，用于儿童英语陪练这类需要「像对话一样快」的场景。

一句话目标：孩子说完话到机器人开口，从 **15—20 秒压到 1—2 秒**。

## 为什么需要它

原版做法里，语音识别（ASR）跑在一台双核 Intel Celeron 的 NAS 上，大模型走局域网里共享的推理服务，语音合成走微软云端 EdgeTTS。每个环节单独看都不算错，拼在一起就是十几秒的等待，孩子早就走神了。

本项目的判断是：**这类玩具慢的通常不是模型，而是链路落在哪台机器上。**

## 架构

```
设备 (ESP32-C3, MAC 见 config)
  ├─ OTA  http://<旧服务器IP>:18003/xiaozhi/ota/      # 固件硬编码，改不了
  │        └─ 应答 ws://<Mac mini IP>:8000/xiaozhi/v1/
  └─ WebSocket → Mac mini:8000   (xiaozhi-esp32-server)
        ├─ ASR  OpenaiASR → http://127.0.0.1:8879   sherpa-onnx SenseVoice (language=en)
        ├─ LLM  LocalLLM  → http://127.0.0.1:8890   mlx_lm.server + Qwen2.5-3B-4bit
        ├─ TTS  OpenAITTS → http://127.0.0.1:8880   常驻 Piper
        └─ VAD  SileroVAD  min_silence_duration_ms=500
```

- 服务端用上游 [`xinnan-tech/xiaozhi-esp32-server`](https://github.com/xinnan-tech/xiaozhi-esp32-server)，本项目只带配置和补丁，不带厂商源码。
- 所有服务都在同一台 Apple Silicon Mac 上，凭 launchd 常驻。
- 设备固件把 OTA 地址写死成老服务器，所以那台机器上必须留一个极简 OTA 应答（`gateway/`），它不在音频链路上。

## 实测收益

| 环节 | 改造前 | 改造后 |
|---|---|---|
| ASR 语音识别 | 10—18 s（NAS Celeron） | ~0.15 s |
| LLM 首句 | 3—15 s | 0.3—1 s |
| TTS 语音合成 | 3—5 s/句 × 3 句 | 0.15—0.2 s/句 |
| 每轮合计 | **15—20 s** | **1—2 s** |

同一个 SenseVoice 小模型，NAS 上 10.7 s，Apple M4 上 0.05—0.19 s。

## 目录

```
services/
  bin/asr_service.py      OpenAI 兼容的 ASR 端点（sherpa-onnx SenseVoice）
  bin/tts_service.py      OpenAI 兼容的 TTS 端点（piper / say / kokoro）
  bin/watchdog-llm.sh     本地 LLM 健康看门狗
  bin/run-*.sh            launchd 启动包装（日志写外接卷，见「坑」）
  launchd/com.xz.*.plist  5 个常驻服务
server/
  agent-base-prompt.txt   精简系统提示词（替换上游 6326 字符版本）
  data/.config.example.yaml
gateway/
  ota.js                  极简 OTA 应答
  gateway.js              OTA 应答 + WebSocket TCP 转发
docs/
  LOG.md                  完整修复记录（逐层根因 + 回滚）
  SKILL.md                运维技能：常用命令、排查表、延迟预算
```

## 部署

1. 安装上游服务端到 `/Volumes/S/AI-Runtimes/xz/server`（或改 plist / run 脚本里的路径）。
2. 准备模型（体积大，不进仓库）：SenseVoice、Qwen2.5-3B-Instruct-4bit（MLX）、Piper `en_US-amy-medium`、SileroVAD。
3. `cp server/data/.config.example.yaml server/data/.config.yaml`，填入本机 IP、设备 MAC、自己生成的 ASR/TTS token，让 token 与 plist 里的 `XZ_ASR_TOKEN` / `XZ_TTS_TOKEN` 一致。
4. 按需修改 `services/run-*.sh` 里的路径，`launchctl bootstrap` 加载 5 个 plist。
5. 老服务器上跑 `gateway/gateway.js`（Node），或用 Docker：
   ```bash
   docker run -d --name xz-ota -p 18000:18000 -p 18003:18003 \
     -e XZ_PUBLIC_HOST=<旧服务器IP> -e XZ_UPSTREAM=<Mac mini IP>:8000 \
     -v $PWD/gateway:/app -w /app node:22-alpine node gateway.js
   ```
6. 机器人断电重启，拉一次 OTA 后应直连 Mac mini。

## 调优要点

- **ASR 换机器**：模型不用换，换算力就快约 100 倍；并把语言固定为 `en`，避免多语种自动检测把英文听成中文。
- **关思考模式**：远端 vLLM 只认 `chat_template_kwargs.enable_thinking=false`（顶层 `enable_thinking` 无效）。
- **精简提示词**：6326 字符 → 118 字符，首 token 从 1.5—1.8 s 降到 0.31 s；同时去掉模板里那句「必须用中文回答」。
- **VAD**：`min_silence_duration_ms` 默认 1000 ms，改 500 ms 省 0.5 s。
- **TTS**：常驻 Piper 0.15—0.2 s/句（每次冷启动要 0.65—0.88 s，必须常驻）；`say` ~0.7 s；Kokoro ~1.2—2.3 s 但音质最好。

## 坑

| 症状 | 真正原因 |
|---|---|
| 显示「连接中」/「我们稍后再试吧」 | 多半不是网络，而是本地 LLM 服务漂移（长时间运行后单核 100%、返回 502）；已用看门狗修 |
| `curl` 200、应用报 502 | Mac 系统代理被 httpx/openai SDK 读取，连 `127.0.0.1` 也走代理；给服务加 `NO_PROXY` |
| launchd 启动即 exit 78 | launchd 不能把日志写到外接卷；用外接卷上的 `run-*.sh` 重定向 |
| mlx_lm.server 去 HuggingFace 拉模型 | `model_name` 必须写本地路径 |
| 精简提示词后屏幕不显示表情 | emoji 指令被一起删了，自定义 prompt 要补白名单前缀 |

## 硬件限制

测试设备是白牌 `zuowei-c3-lcd` 板（ESP32-C3、8 MB flash、**无 PSRAM**、ST7789 SPI 屏），固件为上游官方固件二次编译。它只能显示静态 emoji + 文本，**跑不动官方的 EmoteDisplay 动画**；要动画需要换官方支持的 ESP32-S3（N16R8，带 PSRAM）带屏板，再改一下 config 里的设备 MAC 即可接入同一台服务器。

## 许可

MIT。服务端本体来自 `xinnan-tech/xiaozhi-esp32-server`（MIT），固件来自 `78/xiaozhi-esp32`（MIT）。
