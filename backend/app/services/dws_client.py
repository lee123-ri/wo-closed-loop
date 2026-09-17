"""dws CLI 统一封装：子进程调用 + 就绪状态检查。

dws（dingtalk-workspace-cli）是钉盘 / AI表格数据的唯一读取通道。
本地开发：宿主机已装；容器部署：镜像内置 + 启动时导入凭证包（dws-auth.tar.gz）。

注意：dws 凭证 refresh token 约 30 天过期，过期后需重新导出凭证包
（见 docs/DEPLOYMENT.md「dws 凭证轮换」）。
"""
import json
import shutil
import subprocess


def dws_available() -> bool:
    """dws 可执行文件是否在 PATH 中"""
    return shutil.which("dws") is not None


def dws_authed() -> tuple[bool, str]:
    """检查 dws 登录态。返回 (是否已认证, 说明信息)。"""
    if not dws_available():
        return False, "dws CLI 未安装（镜像需内置 dingtalk-workspace-cli）"
    try:
        r = subprocess.run(
            ["dws", "auth", "status", "-f", "json"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(r.stdout) if r.stdout.strip() else {}
        msg = data.get("message") or data.get("hint") or ""
        return bool(data.get("authenticated")), msg
    except Exception as e:
        return False, f"dws auth status 调用失败: {e}"


def dws_status() -> dict:
    """供 API 暴露的就绪状态摘要"""
    available = dws_available()
    if not available:
        return {"available": False, "authenticated": False,
                "message": "dws CLI 未安装，钉盘/AI表格同步不可用"}
    authed, msg = dws_authed()
    return {"available": True, "authenticated": authed,
            "message": msg if not authed else ""}


def run_dws(*args: str, timeout: int = 180, parse_json: bool = True) -> dict | str:
    """执行 dws 子命令。默认解析 JSON 输出；下载等输出非 JSON 的命令传 parse_json=False。
    失败抛 RuntimeError（带可读原因）。"""
    if not dws_available():
        raise RuntimeError("dws CLI 未安装：钉盘/AI表格数据同步不可用（容器需内置 dws + 凭证包）")
    r = subprocess.run(["dws", *args, "--format", "json"],
                       capture_output=True, text=True, timeout=timeout)
    out = r.stdout.strip()
    if not out and r.returncode != 0:
        stderr = r.stderr[:300]
        if "TOKEN_VERIFIED_FAILED" in stderr or "TOKEN_VERIFIED_FAILED" in out:
            raise RuntimeError("dws 凭证无效或组织未开 CLI 数据访问权限（TOKEN_VERIFIED_FAILED）")
        if "auth" in stderr.lower() or "login" in stderr.lower():
            raise RuntimeError(f"dws 未登录或凭证已过期，请重新导出凭证包: {stderr[:120]}")
        raise RuntimeError(f"dws 执行失败: {stderr or '无错误信息'}")
    if not parse_json:
        return out
    if not out:
        raise RuntimeError("dws 空输出（期望 JSON）")
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"dws 输出不是合法 JSON（前120字符: {out[:120]!r}）: {e}")
