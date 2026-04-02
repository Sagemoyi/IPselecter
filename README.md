# ☁️ CloudFlare 优选 IP 订阅生成器

基于 [CloudflareSpeedTest](https://github.com/XIU2/CloudflareSpeedTest) 优选结果，自动生成 Clash.Meta / Mihomo 和 v2rayN 订阅文件的 Python 工具。支持**双线路整合**（顶级线路 + 大流量线路），内置 LAN HTTP 服务器方便局域网设备导入。

## ✨ 功能特性

- 🚀 读取 CFST 优选结果，自动生成完整的 Clash.Meta YAML 配置
- 📱 生成 Shadowrocket (Surge) 兼容的 .conf 配置（含节点、分组、规则）
- 🔗 同时生成 v2rayN 兼容的 base64 订阅文件
- ⚡ **双线路整合**：同时支持 VM（顶级线路）和 RN（CF 优选大流量）节点
- 📡 内置 HTTP 服务器，局域网设备直接导入订阅
- 🎯 22 个精细分流分组，与主流机场订阅格式一致
- 🛡️ 使用 GEOSITE/GEOIP 规则，零维护自动更新
- 💻 纯 Python 标准库实现，无第三方依赖

## 📁 项目结构

```
.
├── scripts/
│   └── generator2.py          # 核心脚本
├── cfst_windows_amd64/ (及 cfst_linux_amd64/)
│   ├── cfst.exe 或 cfst          # CloudflareSpeedTest 工具
│   ├── ip.txt                 # CFST 测速 IP 段
│   └── result.csv             # CFST 测速结果（自动生成）
├── deploy/
│   └── nginx-subscription.conf.example   # Nginx 部署示例
├── dist/                      # 输出目录（自动生成）
│   ├── subscription-clash-meta.yaml      # Clash.Meta 订阅
│   ├── subscription-shadowrocket.conf    # Shadowrocket 订阅（含规则/分组）
│   ├── subscription-v2rayn.txt           # v2rayN 订阅（base64）
│   ├── subscription-v2rayn-raw.txt       # v2rayN 订阅（原文）
│   ├── preferred-ips.txt                 # 优选 IP 列表
│   └── build-summary.txt                # 构建摘要
├── 节点订阅链接.txt             # RN vmess 节点源（需自行填写）
├── vm-nodes.yaml              # VM 节点源（可选，需自行填写）
└── README.md
```

## 🚀 快速开始

### 前置条件

- Python 3.10+（仅使用标准库，无需 pip install）
- 一个可用的 vmess 节点（来自你的 VPS / 3x-ui 面板等）
- [CloudflareSpeedTest](https://github.com/XIU2/CloudflareSpeedTest) 已完成测速

### 第一步：准备节点源

将你的 vmess:// 链接写入 `节点订阅链接.txt`：

```
vmess://eyJ2IjoiMiIsInBzIjoiTXlOb2RlIiwiYWRkIjoiMS4yLjMuNCIs...
```

### 第二步：运行 CFST 测速（如果还没有 result.csv）

```bash
# 脚本会自动调用 cfst.exe 测速
python scripts/generator2.py

# 或者手动运行 cfst.exe 后跳过测速
python scripts/generator2.py --skip-cfst
```

### 第三步：导入订阅

运行后脚本会输出 LAN 链接并询问是否启动 HTTP 服务器：

```
Generated 20 nodes [RN-only (20)]
Clash.Meta config: D:\...\dist\subscription-clash-meta.yaml
Shadowrocket config: D:\...\dist\subscription-shadowrocket.conf
v2rayN subscription: D:\...\dist\subscription-v2rayn.txt

LAN subscription links (need --serve or confirm below to activate):
  clash: http://192.168.31.81:8765/subscription-clash-meta.yaml
  shadowrocket: http://192.168.31.81:8765/subscription-shadowrocket.conf
  v2rayn: http://192.168.31.81:8765/subscription-v2rayn.txt

ℹ️  To let LAN devices import subscriptions, the HTTP server must keep running.
Start LAN HTTP server on port 8765 now? [Y/n]
```

- **Clash / Mihomo**: 导入 clash 链接
- **Shadowrocket**: 导入 shadowrocket 链接（包含完整的节点、代理分组和分流规则）
- **v2rayN**: 导入 v2rayn 链接

## ⚡ 双线路整合（VM + RN）

如果你同时拥有：
- **VM 线路**：顶级线路 VPS（低延迟，流量有限）
- **RN 线路**：通过 CF CDN 优选的大流量线路

可以合并为一份配置，实现**日常走 VM、下载走 RN** 的智能分流。

### 配置 VM 节点

**方式一：本地文件**（推荐）

将 VM 节点保存为 `vm-nodes.yaml`，格式为标准 Clash proxies：

```yaml
proxies:
  - {name: "节点1", type: vless, server: 1.2.3.4, port: 443, ...}
  - {name: "节点2", type: trojan, server: 1.2.3.4, port: 8886, ...}
```

> 如果你使用 [fscarmen/sing-box](https://github.com/fscarmen/sing-box)，可以直接访问面板的 `/proxies` 端点获取此格式。

**方式二：在线拉取**

```bash
python scripts/generator2.py --skip-cfst \
  --vm-url "http://你的VPS:端口/uuid/proxies"
```

### 合并模式的分组结构

```
🚀 节点选择        ← 主入口（默认 ⚡ VM自动）
├── ⚡ VM自动       ← url-test，自动选最快的 VM 协议
├── 📥 RN大流量     ← url-test，自动选最快的 CF 优选 IP
├── 故障转移        ← VM 挂了自动切 RN
├── DIRECT
├── [VM 各协议节点]
└── [RN 各优选节点]
```

| 分流规则 | 默认路线 | 说明 |
|---|---|---|
| YouTube / Netflix / ChatGPT | ⚡ VM (via 节点选择) | 日常流媒体走顶级线路 |
| ☁️ 谷歌云盘 (Google Drive) | 📥 RN大流量 | 大文件同步省 VM 流量 |
| Ⓜ️ 微软云盘 (OneDrive) | 📥 RN大流量 | 大文件同步省 VM 流量 |
| 哔哩哔哩 / 国内媒体 | DIRECT | 直连 |
| 漏网之鱼 | 🚀 节点选择 | 未匹配的走节点选择 |

## 📋 完整参数说明

### 节点源参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--vmess` | _(交互输入)_ | vmess:// 链接 |
| `--source` | `node-source.txt` | vmess 链接备用文件 |
| `--vm-url` | _(空)_ | VM 节点在线拉取 URL |
| `--vm-file` | `vm-nodes.yaml` | VM 节点本地文件 |
| `--vm-prefix` | `⚡VM` | VM 节点名称前缀 |

### CFST 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--csv` | *(自动检测)* | CFST 结果文件（自动识别 Windows/Linux 对应目录） |
| `--skip-cfst` | `false` | 跳过 CFST 测速 |
| `--limit` | `20` | 选取的优选 IP 数量 |
| `--quality-group-size` | `15` | 质量分组节点数 |
| `--cfst-exe` | *(自动检测)* | CFST 可执行文件路径（自动识别系统） |
| `--cfst-threads` | `200` | 测速线程数 |
| `--cfst-max-latency` | `200` | 最大延迟 (ms) |
| `--cfst-min-speed` | `0.0` | 最低速度 (MB/s) |

### 输出与服务参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--output-dir` | `dist` | 输出目录 |
| `--serve` | `false` | 直接启动 HTTP 服务 |
| `--serve-bind` | `0.0.0.0` | HTTP 绑定地址 |
| `--serve-port` | `8765` | HTTP 服务端口 |

## 🌐 部署到服务器

### 方案一：内置 HTTP 服务器（开发/临时使用）

```bash
python scripts/generator2.py --serve --serve-port 8765
```

### 方案二：Nginx 静态托管（生产推荐）

1. 将 `dist/` 目录上传到服务器
2. 参考 `deploy/nginx-subscription.conf.example` 配置 Nginx
3. 配合 FRP 内网穿透实现远程访问

```bash
# 示例：同步 dist 到远程服务器
rsync -avz dist/ user@server:/var/www/subscription/dist/
```

### 方案三：FRP 内网穿透（家庭服务器）

在 Linux 小主机上运行脚本 + 内置 HTTP 服务器，通过 FRP 暴露到公网：

```ini
# frpc.ini
[subscription]
type = tcp
local_ip = 127.0.0.1
local_port = 8765
remote_port = 8765
```

## 📝 分组列表

| 分组名 | 类型 | 默认行为 |
|---|---|---|
| 🚀 节点选择 | select | 主入口 |
| ⚡ VM自动 / 自动选择 | url-test | 自动选最快节点 |
| 📥 RN大流量 / 延迟选优 | url-test | 自动选最快节点 |
| 故障转移 | fallback | 自动故障切换 |
| 📲 Telegram | select | → 节点选择 |
| 📢 谷歌服务 | select | → 节点选择 |
| 📹 YouTube | select | → 节点选择 |
| 🎥 Netflix | select | → 节点选择 |
| 🎥 Disney+ | select | → 节点选择 |
| 🎶 ChatGPT | select | → 节点选择 |
| 😺 GitHub | select | → 节点选择 |
| 🌍 国外媒体 | select | → 节点选择 |
| ☁️ 谷歌云盘 | select | → RN大流量 / DIRECT |
| Ⓜ️ 微软云盘 | select | → RN大流量 / DIRECT |
| Ⓜ️ 微软服务 | select | → DIRECT |
| 🍎 苹果服务 | select | → 节点选择 |
| 🎮 游戏平台 | select | → 节点选择 |
| 📺 哔哩哔哩 | select | → DIRECT |
| 🌏 国内媒体 | select | → DIRECT |
| 🛑 广告拦截 | select | → REJECT |
| 🍃 应用净化 | select | → DIRECT |
| 🎯 全球直连 | select | → DIRECT |
| 🐟 漏网之鱼 | select | → 节点选择 |

## ⚠️ 注意事项

1. **防火墙**：使用 LAN 服务时，确保 Windows 防火墙允许对应端口（默认 8765）的入站连接
2. **节点安全**：`节点订阅链接.txt` 和 `vm-nodes.yaml` 包含敏感信息，请勿提交到公开仓库
3. **操作系统的智能判断**：脚本已支持自动判断系统。如果是 Linux，会自动选取 `cfst_linux_amd64/` 目录；如果是 Windows 则是 `cfst_windows_amd64/`。
4. **CFST 路径**：你只需要确保对应目录下有正确的平台的 cfst 二进制文件及 ip.txt 即可，通常无需再手动指定 `--cfst-exe` 等参数。

## 📄 License

MIT
