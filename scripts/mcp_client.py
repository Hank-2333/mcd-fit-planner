#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦当劳中国 MCP Server 客户端（Streamable HTTP，零依赖）

接入地址：https://mcp.mcd.cn
鉴权：Authorization: Bearer <MCD_MCP_TOKEN>

用法：
    export MCD_MCP_TOKEN=xxxxx
    python scripts/mcp_client.py list-tools
    python scripts/mcp_client.py call list-nutrition-foods
    python scripts/mcp_client.py call query-nearby-stores '{"address":"上海市徐汇区漕溪北路"}'
    python scripts/mcp_client.py save list-nutrition-foods data/mcp_nutrition_raw.json

说明：
    - Token 从环境变量读取，不要写进代码或提交到仓库。
    - 服务端限流 600 次/分钟，脚本每次调用间隔 0.2s。
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

MCP_URL = os.environ.get("MCD_MCP_URL", "https://mcp.mcd.cn")
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "mcd-fit-planner", "version": "1.0.0"}


def load_token():
    """Token 优先级：环境变量 MCD_MCP_TOKEN > 本地文件（均不在仓库内）。"""
    tok = (os.environ.get("MCD_MCP_TOKEN") or "").strip()
    if tok:
        return tok
    for path in (
        os.path.expanduser("~/.workbuddy/mcd-mcp.token"),
        os.path.expanduser("~/.mcd_mcp_token"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".mcd_mcp_token"),
    ):
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                return fh.read().strip()
    return ""


class McpError(RuntimeError):
    pass


class McpClient:
    def __init__(self, token=None, url=MCP_URL, timeout=30):
        self.token = token or load_token()
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.session_id = None
        self._id = 0

    # ---- 底层 HTTP ----
    def _post(self, payload):
        if not self.token:
            raise McpError(
                "缺少 MCP Token。请先到 https://open.mcd.cn/mcp 申请，"
                "然后设置环境变量 MCD_MCP_TOKEN，或写入 ~/.workbuddy/mcd-mcp.token。"
            )
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": "Bearer " + self.token,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
                if sid:
                    self.session_id = sid
                ctype = (resp.headers.get("Content-Type") or "").lower()
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            if exc.code == 401:
                raise McpError("401：MCP Token 无效、过期或未提供。") from exc
            if exc.code == 429:
                raise McpError("429：触发限流（600 次/分钟），请降低频率。") from exc
            raise McpError("HTTP %s：%s" % (exc.code, detail)) from exc
        except urllib.error.URLError as exc:
            raise McpError("网络错误：%s" % exc.reason) from exc

        if "text/event-stream" in ctype:
            return self._parse_sse(raw)
        if not raw.strip():
            return None
        return json.loads(raw)

    @staticmethod
    def _parse_sse(raw):
        """从 SSE 流里取出最后一条 JSON-RPC 响应。"""
        last = None
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if not chunk or chunk == "[DONE]":
                continue
            try:
                last = json.loads(chunk)
            except json.JSONDecodeError:
                continue
        return last

    def _rpc(self, method, params=None, notify=False):
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notify:
            self._id += 1
            payload["id"] = self._id
        resp = self._post(payload)
        if notify:
            return None
        if resp is None:
            raise McpError("%s：服务端返回空响应" % method)
        if "error" in resp:
            raise McpError("%s 失败：%s" % (method, json.dumps(resp["error"], ensure_ascii=False)))
        return resp.get("result")

    # ---- MCP 协议 ----
    def initialize(self):
        result = self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        self._rpc("notifications/initialized", {}, notify=True)
        return result

    def list_tools(self):
        return self._rpc("tools/list", {}).get("tools", [])

    def call_tool(self, name, arguments=None):
        return self._rpc("tools/call", {"name": name, "arguments": arguments or {}})


def flatten(result):
    """把 tools/call 结果里的 content 数组拼成纯文本。"""
    if result is None:
        return ""
    parts = []
    for block in result.get("content", []):
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
        else:
            parts.append(json.dumps(block, ensure_ascii=False))
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser(description="麦当劳中国 MCP Server 命令行客户端")
    ap.add_argument("command", choices=["list-tools", "call", "save", "ping"])
    ap.add_argument("tool", nargs="?", help="工具名，例如 list-nutrition-foods")
    ap.add_argument("payload", nargs="?", default="{}", help="JSON 参数，默认 {}")
    ap.add_argument("out", nargs="?", help="save 命令的输出路径")
    args = ap.parse_args()

    client = McpClient()
    try:
        info = client.initialize()
        server = (info or {}).get("serverInfo", {})
        if args.command == "ping":
            print("已连接 %s（%s）" % (server.get("name", "mcd-mcp"), server.get("version", "?")))
            return

        if args.command == "list-tools":
            for t in client.list_tools():
                print("- %-26s %s" % (t.get("name"), (t.get("description") or "").split("\n")[0][:70]))
            return

        if not args.tool:
            ap.error("call / save 需要指定工具名")

        time.sleep(0.2)
        try:
            arguments = json.loads(args.payload)
        except json.JSONDecodeError:
            ap.error("payload 必须是合法 JSON")

        result = client.call_tool(args.tool, arguments)
        text = flatten(result)

        if args.command == "save":
            path = args.out or ("data/%s.json" % args.tool)
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            print("已保存到 %s（%d 字节）" % (path, len(text)))
        else:
            print(text)
    except McpError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
