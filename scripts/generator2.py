#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import csv
import ipaddress
import json
import re
import socket
import subprocess
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

GROUP_PROXY = "\U0001f680 \u8282\u70b9\u9009\u62e9"
GROUP_AUTO = "\u81ea\u52a8\u9009\u62e9"
GROUP_LATENCY = "\u5ef6\u8fdf\u9009\u4f18"
GROUP_FAILOVER = "\u6545\u969c\u8f6c\u79fb"
GROUP_DIRECT = "\U0001f3af \u5168\u7403\u76f4\u8fde"
GROUP_ADS = "\U0001f6d1 \u5e7f\u544a\u62e6\u622a"
GROUP_PURIFY = "\U0001f343 \u5e94\u7528\u51c0\u5316"
GROUP_FINAL = "\U0001f41f \u6f0f\u7f51\u4e4b\u9c7c"
GROUP_GOOGLE = "\U0001f4e2 \u8c37\u6b4c\u670d\u52a1"
GROUP_GOOGLE_DRIVE = "\u2601\ufe0f \u8c37\u6b4c\u4e91\u76d8"
GROUP_YOUTUBE = "\U0001f4f9 YouTube"
GROUP_NETFLIX = "\U0001f3a5 Netflix"
GROUP_DISNEY = "\U0001f3a5 Disney+"
GROUP_CHATGPT = "\U0001f3b6 ChatGPT"
GROUP_GITHUB = "\U0001f63a GitHub"
GROUP_TELEGRAM = "\U0001f4f2 Telegram"
GROUP_ONEDRIVE = "\u24c2\ufe0f \u5fae\u8f6f\u4e91\u76d8"
GROUP_MICROSOFT = "\u24c2\ufe0f \u5fae\u8f6f\u670d\u52a1"
GROUP_APPLE = "\U0001f34e \u82f9\u679c\u670d\u52a1"
GROUP_GAMES = "\U0001f3ae \u6e38\u620f\u5e73\u53f0"
GROUP_BILIBILI = "\U0001f4fa \u54d4\u54e9\u54d4\u54e9"
GROUP_FOREIGN_MEDIA = "\U0001f30d \u56fd\u5916\u5a92\u4f53"
GROUP_DOMESTIC_MEDIA = "\U0001f30f \u56fd\u5185\u5a92\u4f53"
GROUP_VM_AUTO = "\u26a1 VM\u81ea\u52a8"
GROUP_RN_AUTO = "\U0001f4e5 RN\u5927\u6d41\u91cf"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read existing CFST result.csv and build Clash.Meta / v2rayN subscriptions")
    parser.add_argument("--vmess", default="", help="Original vmess:// node. If omitted, the script prompts for it.")
    parser.add_argument("--source", default="node-source.txt", help="Fallback source file when vmess is not provided interactively.")

    is_linux = sys.platform.startswith("linux")
    default_cfst_dir = "cfst_linux_amd64" if is_linux else "cfst_windows_amd64"
    default_exe_name = "cfst" if is_linux else "cfst.exe"

    parser.add_argument("--csv", default=f"{default_cfst_dir}/result.csv")
    parser.add_argument("--output-dir", default="dist")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--selection-mode", choices=["file"], default="file")
    parser.add_argument("--skip-cfst", action="store_true")
    parser.add_argument("--cfst-exe", default=f"{default_cfst_dir}/{default_exe_name}")
    parser.add_argument("--cfst-ip-file", default=f"{default_cfst_dir}/ip.txt")
    parser.add_argument("--cfst-url", default="https://speed.cloudflare.com/__down?bytes=5000000")
    parser.add_argument("--cfst-threads", type=int, default=200)
    parser.add_argument("--cfst-times", type=int, default=4)
    parser.add_argument("--cfst-download-count", type=int, default=15)
    parser.add_argument("--cfst-download-time", type=int, default=10)
    parser.add_argument("--cfst-port", type=int, default=443)
    parser.add_argument("--cfst-max-latency", type=int, default=200)
    parser.add_argument("--cfst-packet-loss", type=float, default=0.0)
    parser.add_argument("--cfst-min-speed", type=float, default=0.0)
    parser.add_argument("--cfst-cfcolo", default="")
    parser.add_argument("--quality-group-size", type=int, default=15)
    parser.add_argument("--serve", action="store_true", help="Serve dist/ on the LAN after generation.")
    parser.add_argument("--serve-bind", default="0.0.0.0")
    parser.add_argument("--serve-port", type=int, default=8765)
    parser.add_argument("--vm-url", default="", help="URL to fetch VM proxies (Clash proxies YAML format)")
    parser.add_argument("--vm-file", default="vm-nodes.yaml", help="Local file with VM proxies")
    parser.add_argument("--vm-prefix", default="\u26a1VM", help="Prefix for VM node names")
    return parser.parse_args()


def b64pad(raw: str) -> str:
    return raw + "=" * (-len(raw) % 4)


def resolve_path(root: Path, configured: str, patterns: list[str]) -> Path:
    candidate = (root / configured).resolve()
    if candidate.exists():
        return candidate
    for pattern in patterns:
        matches = sorted(root.glob(pattern))
        if matches:
            return matches[0].resolve()
    return candidate


def parse_vmess_uri(uri: str) -> dict[str, object]:
    payload = uri.split("://", 1)[1]
    data = json.loads(base64.b64decode(b64pad(payload)).decode("utf-8"))
    data["host"] = str(data.get("host") or data.get("sni") or "").strip()
    data["sni"] = str(data.get("sni") or data["host"]).strip()
    data["path"] = str(data.get("path") or "/").strip() or "/"
    data["net"] = str(data.get("net") or "tcp").strip().lower()
    data["tls_enabled"] = str(data.get("tls") or "").strip().lower() in {"tls", "xtls", "true", "1"}
    data["alpn_list"] = [x.strip() for x in str(data.get("alpn") or "").split(",") if x.strip()]
    if not data["host"]:
        raise ValueError("vmess host/sni is missing")
    return data


def read_vmess_from_file(path: Path) -> dict[str, object]:
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line.startswith("vmess://"):
            return parse_vmess_uri(line)
    raise ValueError(f"could not find a vmess:// link in {path}")


def get_source_node(args: argparse.Namespace, root: Path) -> tuple[dict[str, object], str]:
    if args.vmess.strip():
        return parse_vmess_uri(args.vmess.strip()), "cli"

    if sys.stdin.isatty():
        try:
            raw = input("Paste the original vmess:// link and press Enter (leave blank to auto-detect local files): ").strip()
        except EOFError:
            raw = ""
        if raw:
            return parse_vmess_uri(raw), "prompt"

    source = resolve_path(root, args.source, ["*????*.txt", "*????*", "*.txt"])
    candidates = [source, *sorted(root.glob("*.txt"))]
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        try:
            return read_vmess_from_file(resolved), str(resolved)
        except ValueError:
            continue
    raise ValueError("could not find any vmess source file in the workspace")


def build_cfst_command(args: argparse.Namespace, csv_path: Path, ip_file_path: Path) -> list[str]:
    cmd = [
        str(Path(args.cfst_exe).resolve()),
        "-n", str(args.cfst_threads),
        "-t", str(args.cfst_times),
        "-dn", str(max(args.cfst_download_count, 10)),
        "-dt", str(args.cfst_download_time),
        "-tp", str(args.cfst_port),
        "-url", args.cfst_url,
        "-tl", str(args.cfst_max_latency),
        "-tlr", f"{args.cfst_packet_loss:.2f}",
        "-p", str(args.limit),
        "-f", str(ip_file_path),
        "-o", str(csv_path),
    ]
    if args.cfst_min_speed > 0:
        cmd += ["-sl", f"{args.cfst_min_speed:.2f}"]
    if args.cfst_cfcolo:
        cmd += ["-cfcolo", args.cfst_cfcolo]
    return cmd


def run_cfst(args: argparse.Namespace, root: Path, csv_path: Path) -> list[str]:
    exe = (root / args.cfst_exe).resolve()
    ip_file = (root / args.cfst_ip_file).resolve()
    cmd = build_cfst_command(args, csv_path, ip_file)
    print("Running CFST. Make sure test traffic is not going through a proxy.")
    print(" ".join(cmd))
    subprocess.run(cmd, cwd=str(exe.parent), check=True)
    return cmd


def score_row(row: dict[str, object]) -> float:
    return float(row["speed_mb"]) * 100.0 - float(row["latency_ms"]) * 2.0


def load_rows(csv_path: Path, mode: str, limit: int) -> tuple[list[dict[str, object]], int]:
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)
        for raw in reader:
            if len(raw) < 7:
                continue
            ip = raw[0].strip()
            try:
                ipaddress.ip_address(ip)
                latency = float(raw[4])
                speed = float(raw[5])
            except ValueError:
                continue
            if ip in seen:
                continue
            seen.add(ip)
            rows.append({"ip": ip, "latency_ms": latency, "speed_mb": speed, "colo": raw[6].strip() or "N/A"})
    measured = sum(1 for row in rows if float(row["speed_mb"]) > 0)
    return rows[:limit], measured


def y(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return json.dumps("" if value is None else str(value), ensure_ascii=False)


def add_list(lines: list[str], key: str, values: list[object], indent: int) -> None:
    prefix = " " * indent
    lines.append(f"{prefix}{key}:")
    for item in values:
        lines.append(f"{prefix}  - {y(item)}")


def proxy_name(base: str, idx: int, row: dict[str, object]) -> str:
    parts = [part for part in str(base).split("-") if part]
    prefix = "-".join(parts[:2]) if len(parts) >= 2 else str(base)
    return f"{prefix}-\u4f18\u9009{idx}"


def _split_top_level(s: str, sep: str = ",") -> list[str]:
    """Split string by separator, respecting nested braces and quotes."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    in_quote: str | None = None
    for ch in s:
        if in_quote:
            current.append(ch)
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ('"', "'"):
            in_quote = ch
            current.append(ch)
            continue
        if ch == "{":
            depth += 1
            current.append(ch)
        elif ch == "}":
            depth -= 1
            current.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    rest = "".join(current).strip()
    if rest:
        parts.append(rest)
    return parts


def parse_clash_inline_dict(text: str) -> dict[str, object]:
    """Parse a Clash inline YAML dict string into a Python dict."""
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1].strip()
    result: dict[str, object] = {}
    for part in _split_top_level(text):
        colon_idx = part.find(":")
        if colon_idx < 0:
            continue
        key = part[:colon_idx].strip()
        val = part[colon_idx + 1:].strip()
        if not val:
            result[key] = ""
        elif (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            result[key] = val[1:-1]
        elif val.startswith("{"):
            result[key] = parse_clash_inline_dict(val)
        elif val.lower() == "true":
            result[key] = True
        elif val.lower() == "false":
            result[key] = False
        else:
            try:
                result[key] = int(val)
            except ValueError:
                result[key] = val
    return result


def load_vm_proxies(text: str, prefix: str = "\u26a1VM") -> tuple[list[str], list[str], list[dict[str, object]]]:
    """Parse Clash proxies YAML text and return (proxy_lines, clean_names, parsed_dicts)."""
    proxy_lines: list[str] = []
    names: list[str] = []
    parsed: list[dict[str, object]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- {") and not stripped.startswith("- name:"):
            continue
        if "name:" not in stripped:
            continue
        m = re.search(r'name:\s*"([^"]*)"', stripped)
        if not m:
            m = re.search(r"name:\s*'([^']*)'", stripped)
        if not m:
            continue
        original_name = m.group(1)
        parts = re.split(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', original_name)
        protocol = parts[-1].strip() if len(parts) > 1 and parts[-1].strip() else original_name
        clean_name = f"{prefix} {protocol}"
        new_line = stripped.replace(f'name: "{original_name}"', f'name: "{clean_name}"')
        proxy_lines.append(f"  {new_line}")
        names.append(clean_name)
        dict_text = stripped[2:] if stripped.startswith("- ") else stripped
        proxy_dict = parse_clash_inline_dict(dict_text)
        proxy_dict["_clean_name"] = clean_name
        parsed.append(proxy_dict)
    return proxy_lines, names, parsed


def fetch_vm_nodes(args: argparse.Namespace, root: Path) -> tuple[list[str], list[str], list[dict[str, object]]]:
    """Try to load VM nodes from URL or local file. Returns (proxy_lines, names, parsed_dicts)."""
    if args.vm_url:
        try:
            print(f"Fetching VM nodes from {args.vm_url} ...")
            with urlopen(args.vm_url, timeout=15) as resp:
                text = resp.read().decode("utf-8")
            vm_lines, vm_names, vm_parsed = load_vm_proxies(text, args.vm_prefix)
            if vm_names:
                print(f"  Loaded {len(vm_names)} VM nodes: {', '.join(vm_names)}")
                return vm_lines, vm_names, vm_parsed
        except Exception as e:
            print(f"  Warning: could not fetch VM nodes: {e}")
    vm_file = (root / args.vm_file).resolve()
    if vm_file.exists():
        text = vm_file.read_text(encoding="utf-8")
        vm_lines, vm_names, vm_parsed = load_vm_proxies(text, args.vm_prefix)
        if vm_names:
            print(f"Loaded {len(vm_names)} VM nodes from {vm_file}")
            return vm_lines, vm_names, vm_parsed
    return [], [], []


def render_clash(node: dict[str, object], rows: list[dict[str, object]], quality_size: int,
                 vm_proxy_lines: list[str] | None = None, vm_names: list[str] | None = None) -> str:
    has_vm = bool(vm_names)
    rn_names = [proxy_name(str(node["ps"]), i, row) for i, row in enumerate(rows, start=1)]
    rn_quality = rn_names[: max(1, min(quality_size, len(rn_names)))]
    rules = [
        f"DOMAIN-SUFFIX,localhost,{GROUP_DIRECT}",
        f"DOMAIN-SUFFIX,local,{GROUP_DIRECT}",
        f"DOMAIN,dl.google.com,{GROUP_GOOGLE}",
        f"DOMAIN,services.googleapis.cn,{GROUP_GOOGLE}",
        f"DOMAIN-SUFFIX,xn--ngstr-lra8j.com,{GROUP_GOOGLE}",
        f"DOMAIN,copilot.microsoft.com,{GROUP_CHATGPT}",
        f"IP-CIDR,10.0.0.0/8,{GROUP_DIRECT},no-resolve",
        f"IP-CIDR,100.64.0.0/10,{GROUP_DIRECT},no-resolve",
        f"IP-CIDR,127.0.0.0/8,{GROUP_DIRECT},no-resolve",
        f"IP-CIDR,172.16.0.0/12,{GROUP_DIRECT},no-resolve",
        f"IP-CIDR,192.168.0.0/16,{GROUP_DIRECT},no-resolve",
        f"IP-CIDR,198.18.0.0/16,{GROUP_DIRECT},no-resolve",
        f"IP-CIDR6,::1/128,{GROUP_DIRECT},no-resolve",
        f"IP-CIDR6,fc00::/7,{GROUP_DIRECT},no-resolve",
        f"IP-CIDR6,fe80::/10,{GROUP_DIRECT},no-resolve",
        f"IP-CIDR6,fd00::/8,{GROUP_DIRECT},no-resolve",
        f"GEOSITE,category-ads-all,{GROUP_ADS}",
        f"GEOSITE,private,{GROUP_DIRECT}",
        f"GEOSITE,microsoft@cn,{GROUP_DIRECT}",
        f"GEOSITE,apple-cn,{GROUP_DIRECT}",
        f"GEOSITE,steam@cn,{GROUP_DIRECT}",
        f"GEOSITE,category-games@cn,{GROUP_DIRECT}",
        f"GEOSITE,bilibili,{GROUP_BILIBILI}",
        f"GEOSITE,openai,{GROUP_CHATGPT}",
        f"GEOSITE,telegram,{GROUP_TELEGRAM}",
        f"DOMAIN-SUFFIX,drive.google.com,{GROUP_GOOGLE_DRIVE}",
        f"DOMAIN-SUFFIX,googledrive.com,{GROUP_GOOGLE_DRIVE}",
        f"DOMAIN-SUFFIX,drive.usercontent.google.com,{GROUP_GOOGLE_DRIVE}",
        f"DOMAIN-SUFFIX,docs.google.com,{GROUP_GOOGLE_DRIVE}",
        f"DOMAIN-SUFFIX,googleapis.com,{GROUP_GOOGLE_DRIVE}",
        f"DOMAIN-SUFFIX,googleusercontent.com,{GROUP_GOOGLE_DRIVE}",
        f"GEOSITE,google,{GROUP_GOOGLE}",
        f"GEOSITE,youtube,{GROUP_YOUTUBE}",
        f"GEOSITE,netflix,{GROUP_NETFLIX}",
        f"GEOSITE,disney,{GROUP_DISNEY}",
        f"GEOSITE,github,{GROUP_GITHUB}",
        f"GEOSITE,onedrive,{GROUP_ONEDRIVE}",
        f"GEOSITE,microsoft,{GROUP_MICROSOFT}",
        f"GEOSITE,apple,{GROUP_APPLE}",
        f"GEOSITE,steam,{GROUP_GAMES}",
        f"GEOSITE,category-games,{GROUP_GAMES}",
        f"GEOSITE,geolocation-!cn,{GROUP_FOREIGN_MEDIA}",
        f"GEOSITE,cn,{GROUP_DIRECT}",
        f"GEOIP,CN,{GROUP_DIRECT},no-resolve",
        f"MATCH,{GROUP_FINAL}",
    ]
    lines = [
        "mixed-port: 7890",
        "socks-port: 7891",
        "allow-lan: true",
        'bind-address: "*"',
        'mode: "rule"',
        'log-level: "info"',
        "ipv6: false",
        'external-controller: "127.0.0.1:9090"',
        "unified-delay: true",
        "tcp-concurrent: true",
        "sniffer:",
        "  enable: true",
        "  sniff:",
        "    TLS:",
        "      ports:",
        '        - "1-65535"',
        "      override-destination: true",
        "    HTTP:",
        "      ports:",
        '        - "1-65535"',
        "      override-destination: true",
        "  skip-domain:",
        '    - "Mijia Cloud"',
        '    - "dlg.io.mi.com"',
        "  parse-pure-ip: true",
        "  override-destination: true",
        "dns:",
        "  enable: true",
        "  ipv6: false",
        "  respect-rules: true",
        '  enhanced-mode: "fake-ip"',
        '  fake-ip-range: "198.18.0.1/16"',
        "  use-hosts: true",
    ]
    add_list(lines, "fake-ip-filter", ["geosite:cn"], 2)
    add_list(lines, "default-nameserver", ["223.5.5.5", "119.29.29.29"], 2)
    add_list(lines, "proxy-server-nameserver", ["223.5.5.5", "https://223.5.5.5/dns-query", "https://223.6.6.6/dns-query", "https://dns.alidns.com/dns-query"], 2)
    add_list(lines, "nameserver", ["223.5.5.5", "https://223.5.5.5/dns-query", "https://223.6.6.6/dns-query", "https://dns.alidns.com/dns-query"], 2)
    add_list(lines, "fallback", ["1.1.1.1", "8.8.8.8"], 2)
    lines += [
        "  nameserver-policy:",
        '    "geosite:cn":',
        '      - "https://223.5.5.5/dns-query"',
        '      - "223.5.5.5"',
        '      - "119.29.29.29"',
        "  fallback-filter:",
        "    geoip: true",
        '    geoip-code: "CN"',
        "    geosite:",
        '      - "gfw"',
        "    ipcidr:",
        '      - "240.0.0.0/4"',
        "proxies:",
    ]
    # VM proxies (raw Clash YAML lines, already formatted)
    if vm_proxy_lines:
        for vl in vm_proxy_lines:
            lines.append(vl)
    # RN proxies (generated from vmess + CF optimized IPs)
    for idx, row in enumerate(rows, start=1):
        lines += [
            f"  - name: {y(proxy_name(str(node['ps']), idx, row))}",
            '    type: "vmess"',
            f"    server: {y(row['ip'])}",
            f"    port: {int(node['port'])}",
            f"    uuid: {y(node['id'])}",
            "    alterId: 0",
            f"    cipher: {y(node.get('scy') or 'auto')}",
            "    udp: true",
            f"    network: {y(node['net'])}",
            f"    tls: {y(bool(node['tls_enabled']))}",
            f"    servername: {y(node['sni'])}",
            "    skip-cert-verify: false",
        ]
        if node.get("fp"):
            lines.append(f"    client-fingerprint: {y(node['fp'])}")
        if node.get("alpn_list"):
            lines.append("    alpn:")
            for item in node["alpn_list"]:
                lines.append(f"      - {y(item)}")
        if node["net"] == "ws":
            lines += ["    ws-opts:", f"      path: {y(node['path'])}", "      headers:", f"        Host: {y(node['host'])}"]
    # ---- proxy-groups ----
    lines.append("proxy-groups:")
    if has_vm:
        _vm = vm_names or []
        # Main select: choose between VM auto, RN auto, failover, direct, or individual nodes
        lines += [f'  - name: "{GROUP_PROXY}"', '    type: "select"']
        add_list(lines, "proxies", [GROUP_VM_AUTO, GROUP_RN_AUTO, GROUP_FAILOVER, "DIRECT", *_vm, *rn_names], 4)
        # VM auto: url-test across all VM protocols
        lines += [f'  - name: "{GROUP_VM_AUTO}"', '    type: "url-test"',
                  '    url: "https://www.gstatic.com/generate_204"', "    interval: 300", "    tolerance: 50"]
        add_list(lines, "proxies", _vm, 4)
        # RN auto: url-test across top CF-optimized IPs
        lines += [f'  - name: "{GROUP_RN_AUTO}"', '    type: "url-test"',
                  '    url: "https://www.gstatic.com/generate_204"', "    interval: 300", "    tolerance: 50"]
        add_list(lines, "proxies", rn_quality, 4)
        # Failover: VM first, then RN
        lines += [f'  - name: "{GROUP_FAILOVER}"', '    type: "fallback"',
                  '    url: "https://www.gstatic.com/generate_204"', "    interval: 300"]
        add_list(lines, "proxies", [GROUP_VM_AUTO, GROUP_RN_AUTO], 4)
        # Service groups: proxy-first (daily traffic → VM via 节点选择)
        proxy_defaults = [GROUP_PROXY, GROUP_VM_AUTO, GROUP_RN_AUTO, GROUP_FAILOVER, "DIRECT"]
        for gn in [GROUP_TELEGRAM, GROUP_GOOGLE, GROUP_YOUTUBE, GROUP_NETFLIX, GROUP_DISNEY, GROUP_CHATGPT, GROUP_GITHUB, GROUP_FOREIGN_MEDIA]:
            lines += [f'  - name: "{gn}"', '    type: "select"']
            add_list(lines, "proxies", proxy_defaults, 4)
        # Google Drive & OneDrive: RN first (large file sync saves VM bandwidth)
        for gn in [GROUP_GOOGLE_DRIVE, GROUP_ONEDRIVE]:
            lines += [f'  - name: "{gn}"', '    type: "select"']
            add_list(lines, "proxies", [GROUP_RN_AUTO, GROUP_PROXY, GROUP_VM_AUTO, GROUP_FAILOVER, "DIRECT"], 4)
        # Services: DIRECT first
        for gn in [GROUP_MICROSOFT, GROUP_APPLE, GROUP_GAMES]:
            lines += [f'  - name: "{gn}"', '    type: "select"']
            add_list(lines, "proxies", ["DIRECT", GROUP_PROXY, GROUP_VM_AUTO, GROUP_RN_AUTO, GROUP_FAILOVER], 4)
    else:
        # ---- RN-only mode (no VM nodes) ----
        lines += [f'  - name: "{GROUP_PROXY}"', '    type: "select"']
        add_list(lines, "proxies", [GROUP_AUTO, GROUP_LATENCY, GROUP_FAILOVER, "DIRECT", *rn_names], 4)
        group_defs = [
            (GROUP_AUTO, "url-test", rn_quality),
            (GROUP_LATENCY, "url-test", rn_names),
            (GROUP_FAILOVER, "fallback", rn_names),
        ]
        for group_name, group_type, plist in group_defs:
            lines += [f'  - name: "{group_name}"', f'    type: "{group_type}"', '    url: "https://www.gstatic.com/generate_204"', "    interval: 300"]
            if group_type == "url-test":
                lines += ["    tolerance: 50" if group_name == GROUP_AUTO else "    tolerance: 30"]
            add_list(lines, "proxies", plist, 4)
        for gn in [GROUP_TELEGRAM, GROUP_GOOGLE, GROUP_YOUTUBE, GROUP_NETFLIX, GROUP_DISNEY, GROUP_CHATGPT, GROUP_GITHUB, GROUP_FOREIGN_MEDIA]:
            lines += [f'  - name: "{gn}"', '    type: "select"']
            add_list(lines, "proxies", [GROUP_PROXY, GROUP_AUTO, GROUP_LATENCY, GROUP_FAILOVER, "DIRECT"], 4)
        for gn in [GROUP_GOOGLE_DRIVE, GROUP_ONEDRIVE, GROUP_MICROSOFT, GROUP_APPLE, GROUP_GAMES]:
            lines += [f'  - name: "{gn}"', '    type: "select"']
            add_list(lines, "proxies", ["DIRECT", GROUP_PROXY, GROUP_AUTO, GROUP_LATENCY, GROUP_FAILOVER], 4)
    # ---- Shared groups (both modes) ----
    for gn in [GROUP_BILIBILI, GROUP_DOMESTIC_MEDIA]:
        lines += [f'  - name: "{gn}"', '    type: "select"']
        add_list(lines, "proxies", ["DIRECT", GROUP_PROXY] + ([GROUP_VM_AUTO, GROUP_RN_AUTO] if has_vm else [GROUP_AUTO, GROUP_LATENCY]), 4)
    lines += [f'  - name: "{GROUP_ADS}"', '    type: "select"']
    add_list(lines, "proxies", ["REJECT", "DIRECT"], 4)
    lines += [f'  - name: "{GROUP_PURIFY}"', '    type: "select"']
    add_list(lines, "proxies", ["DIRECT", "REJECT"], 4)
    lines += [f'  - name: "{GROUP_DIRECT}"', '    type: "select"']
    add_list(lines, "proxies", ["DIRECT", GROUP_PROXY], 4)
    lines += [f'  - name: "{GROUP_FINAL}"', '    type: "select"']
    add_list(lines, "proxies", [GROUP_PROXY] + ([GROUP_VM_AUTO, GROUP_RN_AUTO] if has_vm else [GROUP_AUTO]) + [GROUP_FAILOVER, "DIRECT"], 4)
    lines.append("rules:")
    for rule in rules:
        lines.append(f"  - {y(rule)}")
    return "\n".join(lines) + "\n"

def build_vmess(node: dict[str, object], row: dict[str, object], idx: int) -> str:
    payload = {
        "v": "2",
        "ps": proxy_name(str(node["ps"]), idx, row),
        "add": row["ip"],
        "port": int(node["port"]),
        "id": node["id"],
        "aid": "0",
        "scy": node.get("scy") or "auto",
        "net": node["net"],
        "type": "none",
        "host": node["host"],
        "path": node["path"],
        "tls": "tls" if node["tls_enabled"] else "",
        "sni": node["sni"],
    }
    if node.get("fp"):
        payload["fp"] = node["fp"]
    if node.get("alpn_list"):
        payload["alpn"] = ",".join(node["alpn_list"])
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "vmess://" + base64.b64encode(raw).decode("ascii")


def clash_proxy_to_surge(proxy: dict[str, object], clean_name: str) -> str | None:
    """Convert a parsed Clash proxy dict to a Surge/Shadowrocket [Proxy] line."""
    ptype = str(proxy.get("type", "")).lower()
    server = str(proxy.get("server", ""))
    port = int(proxy.get("port", 0))

    if ptype == "vmess":
        uuid = str(proxy.get("uuid", ""))
        parts = [f"{clean_name} = vmess, {server}, {port}, username={uuid}"]
        network = str(proxy.get("network", "tcp")).lower()
        if network == "ws":
            parts.append("ws=true")
            ws_opts = proxy.get("ws-opts", {})
            if isinstance(ws_opts, dict):
                path = ws_opts.get("path", "/")
                if path:
                    parts.append(f"ws-path={path}")
                headers = ws_opts.get("headers", {})
                if isinstance(headers, dict) and headers.get("Host"):
                    parts.append(f"ws-headers=Host:{headers['Host']}")
        if proxy.get("tls"):
            parts.append("tls=true")
            sni = proxy.get("servername") or proxy.get("sni") or ""
            if sni:
                parts.append(f"sni={sni}")
        return ", ".join(parts)

    elif ptype == "vless":
        uuid = str(proxy.get("uuid", ""))
        parts = [f"{clean_name} = vless, {server}, {port}, username={uuid}"]
        flow = proxy.get("flow", "")
        if flow:
            parts.append(f"flow={flow}")
        network = str(proxy.get("network", "tcp")).lower()
        if network == "ws":
            parts.append("ws=true")
            ws_opts = proxy.get("ws-opts", {})
            if isinstance(ws_opts, dict):
                path = ws_opts.get("path", "/")
                if path:
                    parts.append(f"ws-path={path}")
                headers = ws_opts.get("headers", {})
                if isinstance(headers, dict) and headers.get("Host"):
                    parts.append(f"ws-headers=Host:{headers['Host']}")
        if proxy.get("tls"):
            parts.append("tls=true")
            sni = proxy.get("servername") or proxy.get("sni") or ""
            if sni:
                parts.append(f"sni={sni}")
        if proxy.get("skip-cert-verify"):
            parts.append("skip-cert-verify=true")
        return ", ".join(parts)

    elif ptype == "trojan":
        password = str(proxy.get("password", ""))
        parts = [f"{clean_name} = trojan, {server}, {port}, password={password}"]
        sni = proxy.get("sni") or proxy.get("servername") or ""
        if sni:
            parts.append(f"sni={sni}")
        if proxy.get("skip-cert-verify"):
            parts.append("skip-cert-verify=true")
        return ", ".join(parts)

    elif ptype == "ss":
        cipher = str(proxy.get("cipher", ""))
        password = str(proxy.get("password", ""))
        parts = [f"{clean_name} = ss, {server}, {port}, encrypt-method={cipher}, password={password}"]
        if proxy.get("plugin") == "shadow-tls":
            plugin_opts = proxy.get("plugin-opts", {})
            if isinstance(plugin_opts, dict):
                stls_pwd = plugin_opts.get("password", "")
                stls_host = plugin_opts.get("host", "")
                stls_ver = plugin_opts.get("version", 3)
                if stls_pwd:
                    parts.append(f"shadow-tls-password={stls_pwd}")
                if stls_host:
                    parts.append(f"shadow-tls-sni={stls_host}")
                if stls_ver:
                    parts.append(f"shadow-tls-version={stls_ver}")
        return ", ".join(parts)

    elif ptype == "anytls":
        password = str(proxy.get("password", ""))
        parts = [f"{clean_name} = anytls, {server}, {port}, password={password}"]
        sni = proxy.get("sni") or proxy.get("servername") or ""
        if sni:
            parts.append(f"sni={sni}")
        if proxy.get("skip-cert-verify"):
            parts.append("skip-cert-verify=true")
        return ", ".join(parts)

    return None


def render_shadowrocket(node: dict[str, object], rows: list[dict[str, object]], quality_size: int,
                        vm_parsed: list[dict[str, object]] | None = None,
                        vm_names: list[str] | None = None) -> str:
    """Generate a Surge/Shadowrocket-compatible .conf config."""
    has_vm = bool(vm_names)
    rn_names = [proxy_name(str(node["ps"]), i, row) for i, row in enumerate(rows, start=1)]
    rn_quality = rn_names[: max(1, min(quality_size, len(rn_names)))]
    test_url = "http://www.gstatic.com/generate_204"
    lines: list[str] = []

    # ---- [General] ----
    lines += [
        "[General]",
        "bypass-system = true",
        "skip-proxy = 192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12, localhost, *.local",
        "bypass-tun = 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, "
        "192.0.0.0/24, 192.168.0.0/16, 198.18.0.0/15, 224.0.0.0/4, 255.255.255.255/32",
        "dns-server = https://doh.pub/dns-query, https://dns.alidns.com/dns-query, 223.5.5.5, 119.29.29.29",
        "ipv6 = false",
        "",
    ]

    # ---- [Proxy] ----
    lines.append("[Proxy]")
    vm_surge_names: list[str] = []
    if has_vm and vm_parsed:
        for proxy_dict in vm_parsed:
            clean = str(proxy_dict.get("_clean_name", ""))
            surge_line = clash_proxy_to_surge(proxy_dict, clean)
            if surge_line:
                lines.append(surge_line)
                vm_surge_names.append(clean)
            else:
                print(f"  Shadowrocket: skipping VM node '{clean}' ({proxy_dict.get('type')}) - unsupported type")

    for idx, row in enumerate(rows, start=1):
        name = proxy_name(str(node["ps"]), idx, row)
        parts = [f"{name} = vmess, {row['ip']}, {int(node['port'])}, username={node['id']}"]
        if str(node["net"]).lower() == "ws":
            parts.append("ws=true")
            parts.append(f"ws-path={node['path']}")
            parts.append(f"ws-headers=Host:{node['host']}")
        if node["tls_enabled"]:
            parts.append("tls=true")
            parts.append(f"sni={node['sni']}")
        lines.append(", ".join(parts))
    lines.append("")

    # ---- [Proxy Group] ----
    lines.append("[Proxy Group]")
    if has_vm and vm_surge_names:
        main_choices = [GROUP_VM_AUTO, GROUP_RN_AUTO, GROUP_FAILOVER, "DIRECT"] + vm_surge_names + rn_names
        lines.append(f"{GROUP_PROXY} = select, " + ", ".join(main_choices))
        lines.append(f"{GROUP_VM_AUTO} = url-test, " + ", ".join(vm_surge_names) + f", url={test_url}, interval=300, tolerance=50")
        lines.append(f"{GROUP_RN_AUTO} = url-test, " + ", ".join(rn_quality) + f", url={test_url}, interval=300, tolerance=50")
        lines.append(f"{GROUP_FAILOVER} = fallback, {GROUP_VM_AUTO}, {GROUP_RN_AUTO}, url={test_url}, interval=300")
        proxy_defaults = [GROUP_PROXY, GROUP_VM_AUTO, GROUP_RN_AUTO, GROUP_FAILOVER, "DIRECT"]
        for gn in [GROUP_TELEGRAM, GROUP_GOOGLE, GROUP_YOUTUBE, GROUP_NETFLIX, GROUP_DISNEY,
                    GROUP_CHATGPT, GROUP_GITHUB, GROUP_FOREIGN_MEDIA]:
            lines.append(f"{gn} = select, " + ", ".join(proxy_defaults))
        for gn in [GROUP_GOOGLE_DRIVE, GROUP_ONEDRIVE]:
            lines.append(f"{gn} = select, {GROUP_RN_AUTO}, {GROUP_PROXY}, {GROUP_VM_AUTO}, {GROUP_FAILOVER}, DIRECT")
        for gn in [GROUP_MICROSOFT, GROUP_APPLE, GROUP_GAMES]:
            lines.append(f"{gn} = select, DIRECT, {GROUP_PROXY}, {GROUP_VM_AUTO}, {GROUP_RN_AUTO}, {GROUP_FAILOVER}")
    else:
        main_choices = [GROUP_AUTO, GROUP_LATENCY, GROUP_FAILOVER, "DIRECT"] + rn_names
        lines.append(f"{GROUP_PROXY} = select, " + ", ".join(main_choices))
        lines.append(f"{GROUP_AUTO} = url-test, " + ", ".join(rn_quality) + f", url={test_url}, interval=300, tolerance=50")
        lines.append(f"{GROUP_LATENCY} = url-test, " + ", ".join(rn_names) + f", url={test_url}, interval=300, tolerance=30")
        lines.append(f"{GROUP_FAILOVER} = fallback, " + ", ".join(rn_names) + f", url={test_url}, interval=300")
        for gn in [GROUP_TELEGRAM, GROUP_GOOGLE, GROUP_YOUTUBE, GROUP_NETFLIX, GROUP_DISNEY,
                    GROUP_CHATGPT, GROUP_GITHUB, GROUP_FOREIGN_MEDIA]:
            lines.append(f"{gn} = select, {GROUP_PROXY}, {GROUP_AUTO}, {GROUP_LATENCY}, {GROUP_FAILOVER}, DIRECT")
        for gn in [GROUP_GOOGLE_DRIVE, GROUP_ONEDRIVE, GROUP_MICROSOFT, GROUP_APPLE, GROUP_GAMES]:
            lines.append(f"{gn} = select, DIRECT, {GROUP_PROXY}, {GROUP_AUTO}, {GROUP_LATENCY}, {GROUP_FAILOVER}")

    bilibili_ch = ["DIRECT", GROUP_PROXY] + ([GROUP_VM_AUTO, GROUP_RN_AUTO] if has_vm else [GROUP_AUTO, GROUP_LATENCY])
    for gn in [GROUP_BILIBILI, GROUP_DOMESTIC_MEDIA]:
        lines.append(f"{gn} = select, " + ", ".join(bilibili_ch))
    lines.append(f"{GROUP_ADS} = select, REJECT, DIRECT")
    lines.append(f"{GROUP_DIRECT} = select, DIRECT, {GROUP_PROXY}")
    final_ch = [GROUP_PROXY] + ([GROUP_VM_AUTO, GROUP_RN_AUTO] if has_vm else [GROUP_AUTO]) + [GROUP_FAILOVER, "DIRECT"]
    lines.append(f"{GROUP_FINAL} = select, " + ", ".join(final_ch))
    lines.append("")

    # ---- [Rule] ----
    lines.append("[Rule]")
    rules = [
        f"DOMAIN-SUFFIX,local,{GROUP_DIRECT}",
        f"DOMAIN-SUFFIX,localhost,{GROUP_DIRECT}",
        f"IP-CIDR,10.0.0.0/8,{GROUP_DIRECT},no-resolve",
        f"IP-CIDR,100.64.0.0/10,{GROUP_DIRECT},no-resolve",
        f"IP-CIDR,127.0.0.0/8,{GROUP_DIRECT},no-resolve",
        f"IP-CIDR,172.16.0.0/12,{GROUP_DIRECT},no-resolve",
        f"IP-CIDR,192.168.0.0/16,{GROUP_DIRECT},no-resolve",
        f"IP-CIDR,198.18.0.0/16,{GROUP_DIRECT},no-resolve",
        # Ads
        f"DOMAIN-KEYWORD,adservice,{GROUP_ADS}",
        f"DOMAIN-SUFFIX,doubleclick.net,{GROUP_ADS}",
        f"DOMAIN-SUFFIX,googleadservices.com,{GROUP_ADS}",
        f"DOMAIN-SUFFIX,googlesyndication.com,{GROUP_ADS}",
        # ChatGPT
        f"DOMAIN-SUFFIX,openai.com,{GROUP_CHATGPT}",
        f"DOMAIN-SUFFIX,oaiusercontent.com,{GROUP_CHATGPT}",
        f"DOMAIN-SUFFIX,chatgpt.com,{GROUP_CHATGPT}",
        f"DOMAIN-SUFFIX,ai.com,{GROUP_CHATGPT}",
        f"DOMAIN,copilot.microsoft.com,{GROUP_CHATGPT}",
        # Telegram
        f"DOMAIN-SUFFIX,telegram.org,{GROUP_TELEGRAM}",
        f"DOMAIN-SUFFIX,t.me,{GROUP_TELEGRAM}",
        f"DOMAIN-SUFFIX,telegra.ph,{GROUP_TELEGRAM}",
        f"DOMAIN-SUFFIX,telesco.pe,{GROUP_TELEGRAM}",
        f"IP-CIDR,91.108.0.0/16,{GROUP_TELEGRAM},no-resolve",
        f"IP-CIDR,149.154.0.0/16,{GROUP_TELEGRAM},no-resolve",
        # YouTube
        f"DOMAIN-SUFFIX,youtube.com,{GROUP_YOUTUBE}",
        f"DOMAIN-SUFFIX,ytimg.com,{GROUP_YOUTUBE}",
        f"DOMAIN-SUFFIX,youtu.be,{GROUP_YOUTUBE}",
        f"DOMAIN-SUFFIX,googlevideo.com,{GROUP_YOUTUBE}",
        f"DOMAIN-SUFFIX,yt.be,{GROUP_YOUTUBE}",
        f"DOMAIN-SUFFIX,youtube-nocookie.com,{GROUP_YOUTUBE}",
        # Google Drive
        f"DOMAIN-SUFFIX,drive.google.com,{GROUP_GOOGLE_DRIVE}",
        f"DOMAIN-SUFFIX,googledrive.com,{GROUP_GOOGLE_DRIVE}",
        f"DOMAIN-SUFFIX,drive.usercontent.google.com,{GROUP_GOOGLE_DRIVE}",
        f"DOMAIN-SUFFIX,docs.google.com,{GROUP_GOOGLE_DRIVE}",
        f"DOMAIN-SUFFIX,googleapis.com,{GROUP_GOOGLE_DRIVE}",
        f"DOMAIN-SUFFIX,googleusercontent.com,{GROUP_GOOGLE_DRIVE}",
        # Google
        f"DOMAIN,dl.google.com,{GROUP_GOOGLE}",
        f"DOMAIN-SUFFIX,google.com,{GROUP_GOOGLE}",
        f"DOMAIN-SUFFIX,googleapis.cn,{GROUP_GOOGLE}",
        f"DOMAIN-SUFFIX,gstatic.com,{GROUP_GOOGLE}",
        f"DOMAIN-SUFFIX,ggpht.com,{GROUP_GOOGLE}",
        f"DOMAIN-SUFFIX,xn--ngstr-lra8j.com,{GROUP_GOOGLE}",
        f"DOMAIN-SUFFIX,google.cn,{GROUP_GOOGLE}",
        # Netflix
        f"DOMAIN-SUFFIX,netflix.com,{GROUP_NETFLIX}",
        f"DOMAIN-SUFFIX,netflix.net,{GROUP_NETFLIX}",
        f"DOMAIN-SUFFIX,nflxext.com,{GROUP_NETFLIX}",
        f"DOMAIN-SUFFIX,nflximg.com,{GROUP_NETFLIX}",
        f"DOMAIN-SUFFIX,nflximg.net,{GROUP_NETFLIX}",
        f"DOMAIN-SUFFIX,nflxvideo.net,{GROUP_NETFLIX}",
        f"DOMAIN-SUFFIX,nflxso.net,{GROUP_NETFLIX}",
        # Disney+
        f"DOMAIN-SUFFIX,disney.com,{GROUP_DISNEY}",
        f"DOMAIN-SUFFIX,disneyplus.com,{GROUP_DISNEY}",
        f"DOMAIN-SUFFIX,dssott.com,{GROUP_DISNEY}",
        f"DOMAIN-SUFFIX,bamgrid.com,{GROUP_DISNEY}",
        # GitHub
        f"DOMAIN-SUFFIX,github.com,{GROUP_GITHUB}",
        f"DOMAIN-SUFFIX,github.io,{GROUP_GITHUB}",
        f"DOMAIN-SUFFIX,githubusercontent.com,{GROUP_GITHUB}",
        f"DOMAIN-SUFFIX,githubassets.com,{GROUP_GITHUB}",
        # OneDrive
        f"DOMAIN-SUFFIX,onedrive.com,{GROUP_ONEDRIVE}",
        f"DOMAIN-SUFFIX,onedrive.live.com,{GROUP_ONEDRIVE}",
        f"DOMAIN-SUFFIX,sharepoint.com,{GROUP_ONEDRIVE}",
        # Microsoft
        f"DOMAIN-SUFFIX,microsoft.com,{GROUP_MICROSOFT}",
        f"DOMAIN-SUFFIX,microsoftonline.com,{GROUP_MICROSOFT}",
        f"DOMAIN-SUFFIX,msn.com,{GROUP_MICROSOFT}",
        f"DOMAIN-SUFFIX,office.com,{GROUP_MICROSOFT}",
        f"DOMAIN-SUFFIX,office365.com,{GROUP_MICROSOFT}",
        f"DOMAIN-SUFFIX,windows.com,{GROUP_MICROSOFT}",
        f"DOMAIN-SUFFIX,windows.net,{GROUP_MICROSOFT}",
        f"DOMAIN-SUFFIX,live.com,{GROUP_MICROSOFT}",
        # Apple
        f"DOMAIN-SUFFIX,apple.com,{GROUP_APPLE}",
        f"DOMAIN-SUFFIX,icloud.com,{GROUP_APPLE}",
        f"DOMAIN-SUFFIX,itunes.com,{GROUP_APPLE}",
        f"DOMAIN-SUFFIX,mzstatic.com,{GROUP_APPLE}",
        f"DOMAIN-SUFFIX,cdn-apple.com,{GROUP_APPLE}",
        # Games
        f"DOMAIN-SUFFIX,steampowered.com,{GROUP_GAMES}",
        f"DOMAIN-SUFFIX,steamcommunity.com,{GROUP_GAMES}",
        f"DOMAIN-SUFFIX,steamstatic.com,{GROUP_GAMES}",
        f"DOMAIN-SUFFIX,epicgames.com,{GROUP_GAMES}",
        f"DOMAIN-KEYWORD,steam,{GROUP_GAMES}",
        # Bilibili
        f"DOMAIN-SUFFIX,bilibili.com,{GROUP_BILIBILI}",
        f"DOMAIN-SUFFIX,bilivideo.com,{GROUP_BILIBILI}",
        f"DOMAIN-SUFFIX,biliapi.com,{GROUP_BILIBILI}",
        f"DOMAIN-SUFFIX,biliapi.net,{GROUP_BILIBILI}",
        f"DOMAIN-SUFFIX,hdslb.com,{GROUP_BILIBILI}",
        f"DOMAIN-SUFFIX,b23.tv,{GROUP_BILIBILI}",
        # China direct
        f"GEOIP,CN,{GROUP_DIRECT}",
        # Final
        f"FINAL,{GROUP_FINAL}",
    ]
    for rule in rules:
        lines.append(rule)
    return "\n".join(lines) + "\n"


def is_private_lan_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if ip.is_loopback or ip.is_link_local:
        return False
    if value.startswith("255.") or value.startswith("0."):
        return False
    if value.startswith("198.18.") or value.startswith("198.19."):
        return False
    return value.startswith("192.168.") or value.startswith("10.") or ip.is_private


def detect_lan_ip() -> str:
    candidates: list[str] = []
    try:
        output = subprocess.check_output(["ipconfig"], text=True, encoding="gbk", errors="ignore")
        for token in output.replace("\r", "").split():
            token = token.strip().strip(":")
            if token.count(".") == 3 and is_private_lan_ip(token):
                candidates.append(token)
    except (OSError, subprocess.SubprocessError):
        pass
    if candidates:
        return candidates[0]
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            candidate = sock.getsockname()[0]
            if is_private_lan_ip(candidate):
                return candidate
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidate = info[4][0]
            if is_private_lan_ip(candidate):
                return candidate
    except OSError:
        pass
    return "127.0.0.1"


def build_lan_links(ip: str, port: int) -> dict[str, str]:
    base = f"http://{ip}:{port}"
    return {
        "web_index": f"{base}/lan-index.txt",
        "clash_mihomo": f"{base}/subscription-clash-meta.yaml",
        "v2rayn": f"{base}/subscription-v2rayn.txt",
        "shadowrocket": f"{base}/subscription-shadowrocket.conf",
        "raw_vmess": f"{base}/subscription-v2rayn-raw.txt",
        "socks5": f"socks5://{ip}:7891",
        "mixed": f"http://{ip}:7890",
    }


def write_lan_files(out_dir: Path, links: dict[str, str]) -> None:
    lines = [
        "LAN import links",
        f"Clash / Mihomo / Clash Verge / Meta for Android: {links['clash_mihomo']}",
        f"v2rayN: {links['v2rayn']}",
        f"Shadowrocket (config with rules): {links['shadowrocket']}",
        f"Raw vmess list: {links['raw_vmess']}",
        f"SOCKS5 proxy: {links['socks5']}",
        f"Mixed HTTP/SOCKS proxy: {links['mixed']}",
    ]
    text = "\n".join(lines) + "\n"
    (out_dir / "lan-links.txt").write_text(text, encoding="utf-8")
    (out_dir / "lan-index.txt").write_text(text, encoding="utf-8")


def serve_directory(out_dir: Path, bind: str, port: int) -> None:
    handler = partial(SimpleHTTPRequestHandler, directory=str(out_dir))
    server = ThreadingHTTPServer((bind, port), handler)
    print(f"Serving {out_dir} on http://{bind}:{port}/ . Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    args = parse_args()
    root = Path.cwd()
    csv_path = resolve_path(root, args.csv, [args.csv, "**/result.csv"])
    out_dir = (root / args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    node, source_desc = get_source_node(args, root)
    rows, measured = load_rows(csv_path, args.selection_mode, args.limit)
    if not rows:
        raise ValueError(f"could not load usable IP rows from {csv_path}")
    chosen_measured = sum(1 for row in rows if float(row["speed_mb"]) > 0)
    if measured == 0:
        print("Warning: result.csv does not contain download-speed rows.")

    vm_proxy_lines, vm_names, vm_parsed = fetch_vm_nodes(args, root)
    clash = render_clash(node, rows, args.quality_group_size, vm_proxy_lines, vm_names)
    sr_conf = render_shadowrocket(node, rows, args.quality_group_size, vm_parsed, vm_names)
    vmess_lines = [build_vmess(node, row, i) for i, row in enumerate(rows, start=1)]
    vmess_raw = "\n".join(vmess_lines) + "\n"
    (out_dir / "subscription-clash-meta.yaml").write_text(clash, encoding="utf-8")
    (out_dir / "subscription-shadowrocket.conf").write_text(sr_conf, encoding="utf-8")
    (out_dir / "subscription-v2rayn-raw.txt").write_text(vmess_raw, encoding="utf-8")
    (out_dir / "subscription-v2rayn.txt").write_text(base64.b64encode(vmess_raw.encode("utf-8")).decode("ascii"), encoding="utf-8")
    (out_dir / "preferred-ips.txt").write_text("\n".join(str(row["ip"]) for row in rows) + "\n", encoding="utf-8")

    lan_ip = detect_lan_ip()
    links = build_lan_links(lan_ip, args.serve_port)
    write_lan_files(out_dir, links)

    summary = [
        "Build summary",
        f"Source node: {node['ps']}",
        f"Source input: {source_desc}",
        f"Host: {node['host']}",
        f"Port: {node['port']}",
        f"Written preferred IPs: {len(rows)}",
        f"Rows with download speed in CSV: {measured}",
        f"Rows with download speed in chosen set: {chosen_measured}",
        f"Selection mode: {args.selection_mode}",
        "CSV order preserved: true",
        "",
    ]
    summary += ["Top 10 IPs:"]
    for i, row in enumerate(rows[:10], start=1):
        summary.append(f"{i:02d}. {row['ip']} | {float(row['speed_mb']):.2f}MB/s | {float(row['latency_ms']):.2f}ms | {row['colo']}")
    summary += ["", "LAN links:"]
    for key, value in links.items():
        summary.append(f"{key}: {value}")
    (out_dir / "build-summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")

    vm_count = len(vm_names) if vm_names else 0
    mode_str = f"merged ({vm_count} VM + {len(rows)} RN)" if vm_count else f"RN-only ({len(rows)})"
    print(f"\nGenerated {vm_count + len(rows)} nodes [{mode_str}]")
    print(f"Clash.Meta config: {out_dir / 'subscription-clash-meta.yaml'}")
    print(f"Shadowrocket config: {out_dir / 'subscription-shadowrocket.conf'}")
    print(f"v2rayN subscription: {out_dir / 'subscription-v2rayn.txt'}")
    print(f"\nLAN subscription links (need --serve or confirm below to activate):")
    for key, value in links.items():
        print(f"  {key}: {value}")

    should_serve = args.serve
    if not should_serve and sys.stdin.isatty():
        print(f"\n\u2139\ufe0f  To let LAN devices import subscriptions, the HTTP server must keep running.")
        print(f"   Tip: If other devices cannot connect, check your Windows firewall for port {args.serve_port}.")
        try:
            answer = input(f"Start LAN HTTP server on port {args.serve_port} now? [Y/n] ").strip().lower()
        except EOFError:
            answer = "n"
        should_serve = answer in ("", "y", "yes")

    if should_serve:
        serve_directory(out_dir, args.serve_bind, args.serve_port)


if __name__ == "__main__":
    main()
