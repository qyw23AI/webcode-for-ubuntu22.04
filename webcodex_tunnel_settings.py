"""Local, private settings for the installed v0.4.6 OpenAI Tunnel profile.

The release CLI can create a profile but refuses to replace existing Tunnel
credentials. This module updates only the two credential fields in its owned
private env file, then asks the CLI to restart and verify the service. An exact
private backup is retained until the new connection is confirmed or rollback
succeeds.
"""

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


ROOT = Path("/home/qyw/WebCodex/installed/environment")
CLI = Path("/home/qyw/WebCodex/installed/bin/webcodex")
PROFILE = "chatgpt"
ENV_FILE = ROOT / "server/tunnels/chatgpt/webcodex.env"
BACKUP_FILE = ROOT / "server/tunnels/chatgpt/webcodex.env.gui-backup"
TUNNEL_ID_PATTERN = re.compile(r"tunnel_[0-9a-f]{32}\Z")


def _run_cli(*args):
    return subprocess.run(
        [str(CLI), "environment", *args, "--environment-dir", str(ROOT), "--json"],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )


def _fields(content):
    values = {}
    for line in content.decode("utf-8").splitlines():
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name in values:
            raise ValueError("Tunnel 配置包含重复字段")
        values[name] = value
    if values.get("WEBCODEX_TUNNEL_PROFILE_ID") != PROFILE:
        raise ValueError("Tunnel 配置不属于 chatgpt 连接")
    if not values.get("CONTROL_PLANE_TUNNEL_ID") or not values.get("CONTROL_PLANE_API_KEY"):
        raise ValueError("Tunnel ID 或 API key 尚未保存")
    return values


def current_credentials():
    if not ENV_FILE.exists():
        return "", ""
    if ENV_FILE.stat().st_mode & 0o077:
        raise ValueError("Tunnel 凭据文件权限过宽，请先修复")
    values = _fields(ENV_FILE.read_bytes())
    return values["CONTROL_PLANE_TUNNEL_ID"], values["CONTROL_PLANE_API_KEY"]


def status():
    result = _run_cli("tunnel-status", PROFILE)
    if result.returncode:
        return "无法读取 Tunnel 状态"
    data = json.loads(result.stdout)
    service = data.get("service_status") or {}
    if data.get("ready") and service.get("running"):
        return "本机 Tunnel 和 MCP 已就绪；ChatGPT 连接需实际调用验证"
    if service.get("running"):
        return "正在运行，等待 Tunnel 就绪"
    return "未运行"


def _validate(tunnel_id, api_key):
    if not TUNNEL_ID_PATTERN.fullmatch(tunnel_id):
        raise ValueError("Tunnel ID 格式无效，应为 tunnel_ 后接 32 位小写十六进制字符")
    if not api_key or len(api_key) > 8192 or any(c in api_key for c in '\n\r\0"\''):
        raise ValueError("API key 为空、过长或包含不支持的字符")


def _atomic_private_write(path, content):
    descriptor, temporary = tempfile.mkstemp(prefix=".webcodex-env-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _create_backup(content):
    descriptor = os.open(BACKUP_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _replace_credentials(content, tunnel_id, api_key):
    _fields(content)
    replacements = {
        "CONTROL_PLANE_TUNNEL_ID": tunnel_id,
        "CONTROL_PLANE_API_KEY": api_key,
    }
    lines = []
    for line in content.decode("utf-8").splitlines():
        name = line.split("=", 1)[0]
        lines.append(f"{name}={replacements[name]}" if name in replacements else line)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _restart_and_verify():
    restarted = _run_cli("restart", "tunnel", "--profile", PROFILE)
    if restarted.returncode:
        raise RuntimeError("Tunnel 重启或就绪检查失败")
    checked = _run_cli("tunnel-status", PROFILE)
    if checked.returncode or not json.loads(checked.stdout).get("ready"):
        raise RuntimeError("Tunnel 尚未就绪")


def recover_backup():
    if not BACKUP_FILE.exists():
        raise ValueError("没有待恢复的 Tunnel 配置")
    old_content = BACKUP_FILE.read_bytes()
    _fields(old_content)
    _atomic_private_write(ENV_FILE, old_content)
    _restart_and_verify()
    BACKUP_FILE.unlink()


def save_credentials(tunnel_id, api_key):
    _validate(tunnel_id, api_key)
    if BACKUP_FILE.exists():
        raise RuntimeError("检测到上次修改的备份，请先恢复旧配置")

    if not ENV_FILE.exists():
        descriptor, temporary = tempfile.mkstemp(prefix=".webcodex-credentials-", dir=ROOT)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"tunnel_id": tunnel_id, "api_key": api_key}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            configured = _run_cli("configure-tunnel", PROFILE, "--credentials-file", temporary)
            if configured.returncode:
                raise RuntimeError("Tunnel 配置未完成，请检查 ID、API key 和服务状态")
            return "已保存并启动 Tunnel"
        finally:
            os.unlink(temporary)

    original = ENV_FILE.read_bytes()
    values = _fields(original)
    if (values["CONTROL_PLANE_TUNNEL_ID"], values["CONTROL_PLANE_API_KEY"]) == (tunnel_id, api_key):
        return "配置没有变化"
    revised = _replace_credentials(original, tunnel_id, api_key)
    _create_backup(original)
    try:
        if ENV_FILE.read_bytes() != original:
            raise RuntimeError("Tunnel 配置被其他进程修改，尚未覆盖")
        _atomic_private_write(ENV_FILE, revised)
        _restart_and_verify()
    except Exception as error:
        if ENV_FILE.read_bytes() == revised:
            try:
                recover_backup()
            except Exception:
                raise RuntimeError("新配置未就绪，自动恢复也失败；原配置保存在私有备份中") from None
            raise RuntimeError("新配置未就绪，已恢复原 Tunnel 配置") from None
        if ENV_FILE.read_bytes() == original:
            BACKUP_FILE.unlink()
        raise error
    BACKUP_FILE.unlink()
    return "已保存，Tunnel 和本机 MCP 均就绪；请在 ChatGPT 验证调用"
