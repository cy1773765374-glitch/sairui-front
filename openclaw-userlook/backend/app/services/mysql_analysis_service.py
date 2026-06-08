from __future__ import annotations

import calendar
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.models.agent import Agent


MYSQL_ANALYSIS_TASK_TYPE = "mysql_analysis_report"
MYSQL_ANALYSIS_RUNNER_NAME = "mysql_analysis_job"
MYSQL_ANALYSIS_AGENT_ALIASES = {
    "mysql_analysis",
    "mysql-analysis",
    "mysql",
    "huizong_ceshi",
    "huizong-ceshi",
    "mysql分析",
    "mysql 分析",
    "汇总测试",
}
MYSQL_ANALYSIS_WORKSPACE_CANDIDATES = [
    "/home/cy/.openclaw/workspace-huizong-ceshi",
    "/home/cy/.openclaw/workspace-mysql-analysis",
    "/home/ubuntu/.openclaw/workspace-mysql-analysis",
]
MYSQL_ANALYSIS_DEFAULT_OUTPUT_ROOTS = [
    "/data/share/yaq/test",
    "/data/share/test",
]
MYSQL_ANALYSIS_SCRIPT_REL = "scripts/run_supplier_shipment_report.py"

MYSQL_ANALYSIS_REPORT_KEYWORDS = (
    "统计",
    "汇总",
    "分析",
    "报表",
    "excel",
    "xlsx",
    "csv",
    "图表",
    "top10",
    "供应商",
    "出货",
    "采购金额",
    "开船日期",
    "unionid",
    "union_id",
    "子公司",
    "工厂",
    "厂商",
    "采购员",
    "mysql 查询结果",
    "生成文件",
    "导出",
)
MYSQL_ANALYSIS_HELP_MARKERS = (
    "你是谁",
    "你能做什么",
    "怎么提问",
    "需要哪些参数",
    "使用说明",
    "示例",
    "支持哪些报表",
    "当前支持哪些字段",
)
MYSQL_ANALYSIS_DATE_REQUIRED_MESSAGE = (
    "这个统计需要开始日期和结束日期，例如：统计 2026-05-01 到 2026-05-31 的供应商出货采购金额。"
)

_NUMERIC_DATE_RE = r"\d{4}-\d{1,2}-\d{1,2}"
_CHINESE_DATE_RE = r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*[日号]?"
_DATE_RANGE_SEPARATORS = r"(?:到|至|~|－|—|–|--)"
_SENSITIVE_VALUE_RE = re.compile(
    r"(?i)\b(mysql_password|password|passwd|pwd|token|secret|app_secret|access_token)\b\s*([=:])\s*([^\s,;]+)"
)
_MYSQL_URL_PASSWORD_RE = re.compile(r"(?i)(mysql(?:\+\w+)?://[^:\s/@]+:)([^@\s]+)(@)")


@dataclass(frozen=True)
class ParsedDateRange:
    start_date: str
    end_date: str
    source: str
    default_year: int | None = None


@dataclass(frozen=True)
class ParsedMysqlAnalysisRequest:
    start_date: str
    end_date: str
    union_id: str | None = None
    default_year: int | None = None
    date_source: str = ""

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "date_source": self.date_source,
        }
        if self.union_id:
            payload["union_id"] = self.union_id
        if self.default_year:
            payload["default_year"] = self.default_year
        return payload


def _normalize_agent_token(value: str | None) -> str:
    return (value or "").strip().lower()


def _shanghai_now() -> datetime:
    try:
        return datetime.now(ZoneInfo("Asia/Shanghai"))
    except Exception:
        return datetime.now(timezone(timedelta(hours=8)))


def is_mysql_analysis_agent(agent: Agent | None) -> bool:
    if agent is None:
        return False
    candidates = {
        _normalize_agent_token(agent.code),
        _normalize_agent_token(agent.openclaw_agent_id),
        _normalize_agent_token(agent.name),
    }
    expanded: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        expanded.add(candidate)
        expanded.add(candidate.replace("_", "-"))
        expanded.add(candidate.replace("-", "_"))
        expanded.add(candidate.replace(" ", ""))
    return bool(expanded & MYSQL_ANALYSIS_AGENT_ALIASES) or any("mysql" in item and "分析" in item for item in expanded)


def is_mysql_help_intent(text: str | None) -> bool:
    value = (text or "").strip().lower()
    if not value:
        return False
    return any(marker.lower() in value for marker in MYSQL_ANALYSIS_HELP_MARKERS)


def has_mysql_report_intent(text: str | None) -> bool:
    value = (text or "").strip().lower()
    if not value:
        return False
    return any(keyword.lower() in value for keyword in MYSQL_ANALYSIS_REPORT_KEYWORDS)


def _format_date(year: int, month: int, day: int) -> str:
    parsed = datetime(year, month, day)
    return parsed.strftime("%Y-%m-%d")


def _month_range(year: int, month: int) -> tuple[str, str]:
    last_day = calendar.monthrange(year, month)[1]
    return _format_date(year, month, 1), _format_date(year, month, last_day)


def _parse_numeric_date(value: str) -> str | None:
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", value.strip())
    if not match:
        return None
    try:
        return _format_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _parse_chinese_date(value: str) -> str | None:
    match = re.fullmatch(
        r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?",
        value.strip(),
    )
    if not match:
        return None
    try:
        return _format_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def parse_mysql_date_range(text: str | None, *, now: datetime | None = None) -> ParsedDateRange | None:
    value = (text or "").strip()
    if not value:
        return None

    numeric_range = re.search(
        rf"(?P<start>{_NUMERIC_DATE_RE})\s*{_DATE_RANGE_SEPARATORS}\s*(?P<end>{_NUMERIC_DATE_RE})",
        value,
    )
    if numeric_range:
        start_date = _parse_numeric_date(numeric_range.group("start"))
        end_date = _parse_numeric_date(numeric_range.group("end"))
        if start_date and end_date and start_date <= end_date:
            return ParsedDateRange(start_date=start_date, end_date=end_date, source="explicit_date_range")

    chinese_range = re.search(
        rf"(?P<start>{_CHINESE_DATE_RE})\s*{_DATE_RANGE_SEPARATORS}\s*(?P<end>{_CHINESE_DATE_RE})",
        value,
    )
    if chinese_range:
        start_date = _parse_chinese_date(chinese_range.group("start"))
        end_date = _parse_chinese_date(chinese_range.group("end"))
        if start_date and end_date and start_date <= end_date:
            return ParsedDateRange(start_date=start_date, end_date=end_date, source="explicit_chinese_date_range")

    full_month = re.search(r"(?<!\d)(\d{4})\s*年\s*(1[0-2]|0?[1-9])\s*月(?:份)?", value)
    if full_month:
        try:
            start_date, end_date = _month_range(int(full_month.group(1)), int(full_month.group(2)))
        except ValueError:
            return None
        return ParsedDateRange(start_date=start_date, end_date=end_date, source="explicit_month")

    current_year_month = re.search(r"今年\s*(1[0-2]|0?[1-9])\s*月(?:份)?", value)
    if current_year_month:
        current = now or _shanghai_now()
        month = int(current_year_month.group(1))
        start_date, end_date = _month_range(current.year, month)
        return ParsedDateRange(
            start_date=start_date,
            end_date=end_date,
            source="current_year_month",
            default_year=current.year,
        )

    month_only = re.search(r"(?<![\d年-])(1[0-2]|0?[1-9])\s*月(?:份)?", value)
    if month_only:
        current = now or _shanghai_now()
        month = int(month_only.group(1))
        start_date, end_date = _month_range(current.year, month)
        return ParsedDateRange(
            start_date=start_date,
            end_date=end_date,
            source="month_only_default_year",
            default_year=current.year,
        )

    return None


def parse_mysql_union_id(text: str | None) -> str | None:
    value = (text or "").strip()
    if not value:
        return None
    patterns = (
        r"(?i)\bunion[_\s-]*id\s*[=:：为]?\s*([A-Za-z0-9_-]+)",
        r"子公司\s*([A-Za-z0-9_-]+)",
        r"([A-Za-z0-9_-]+)\s*子公司",
    )
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            union_id = match.group(1).strip()
            if union_id:
                return union_id
    return None


def parse_mysql_analysis_request(text: str | None, *, now: datetime | None = None) -> ParsedMysqlAnalysisRequest | None:
    date_range = parse_mysql_date_range(text, now=now)
    if date_range is None:
        return None
    return ParsedMysqlAnalysisRequest(
        start_date=date_range.start_date,
        end_date=date_range.end_date,
        union_id=parse_mysql_union_id(text),
        default_year=date_range.default_year,
        date_source=date_range.source,
    )


def mysql_python_executable(workspace: Path) -> str:
    venv_python = workspace / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    windows_venv_python = workspace / ".venv" / "Scripts" / "python.exe"
    if windows_venv_python.exists():
        return str(windows_venv_python)
    return "python3" if os.name != "nt" else "python"


def _venv_bin_dir(workspace: Path) -> Path | None:
    venv_bin = workspace / ".venv" / "bin"
    if venv_bin.exists():
        return venv_bin
    windows_venv_bin = workspace / ".venv" / "Scripts"
    if windows_venv_bin.exists():
        return windows_venv_bin
    return None


def read_workspace_env_value(workspace: Path, key: str) -> str | None:
    env_path = workspace / ".env"
    if not env_path.is_file():
        return None
    key_pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(key)}\s*=\s*(.*?)\s*$")
    try:
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = key_pattern.match(line)
            if not match:
                continue
            raw_value = match.group(1).strip()
            if (raw_value.startswith('"') and raw_value.endswith('"')) or (raw_value.startswith("'") and raw_value.endswith("'")):
                raw_value = raw_value[1:-1]
            return raw_value.strip() or None
    except OSError:
        return None
    return None


def resolve_mysql_analysis_output_root(workspace: Path, *, profile_output_root: str | None = None) -> str:
    candidates = [
        profile_output_root,
        read_workspace_env_value(workspace, "OUTPUT_ROOT"),
        os.getenv("MYSQL_ANALYSIS_OUTPUT_ROOT"),
        get_settings().mysql_analysis_output_root,
        *MYSQL_ANALYSIS_DEFAULT_OUTPUT_ROOTS,
    ]
    for candidate in candidates:
        value = (candidate or "").strip()
        if value:
            return str(Path(value).expanduser())
    return MYSQL_ANALYSIS_DEFAULT_OUTPUT_ROOTS[0]


def build_mysql_analysis_env(
    workspace: Path,
    *,
    output_root: str,
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    env = dict(base_env or os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["OUTPUT_ROOT"] = output_root
    env["MYSQL_ANALYSIS_OUTPUT_ROOT"] = output_root
    env.pop("PYTHONHOME", None)

    venv_bin = _venv_bin_dir(workspace)
    if venv_bin is not None:
        existing_path = env.get("PATH", "")
        env["PATH"] = str(venv_bin) + (os.pathsep + existing_path if existing_path else "")
        env["VIRTUAL_ENV"] = str(workspace / ".venv")
    return env


def build_mysql_analysis_command(
    *,
    workspace: Path,
    start_date: str,
    end_date: str,
    asker: str,
    question: str,
    union_id: str | None = None,
) -> list[str]:
    command = [
        mysql_python_executable(workspace),
        MYSQL_ANALYSIS_SCRIPT_REL,
        "--start-date",
        start_date,
        "--end-date",
        end_date,
        "--asker",
        asker,
        "--question",
        question,
    ]
    if union_id:
        command.extend(["--union-id", union_id])
    return command


def sanitize_mysql_analysis_text(value: str | None, *, max_length: int = 4000) -> str:
    text = value or ""
    text = _MYSQL_URL_PASSWORD_RE.sub(r"\1***\3", text)
    text = _SENSITIVE_VALUE_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}***", text)
    if len(text) <= max_length:
        return text
    return text[-max_length:]


def sanitize_mysql_analysis_command(command: list[str]) -> list[str]:
    return [sanitize_mysql_analysis_text(item, max_length=1000) for item in command]


def sanitize_mysql_analysis_payload(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_mysql_analysis_text(value)
    if isinstance(value, list):
        return [sanitize_mysql_analysis_payload(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): sanitize_mysql_analysis_payload(item)
            for key, item in value.items()
        }
    return value


def extract_json_object(stdout: str) -> dict[str, Any] | None:
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    last_object: dict[str, Any] | None = None
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            data, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            last_object = data
    return last_object


def load_json_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _path_from_value(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value.strip()).expanduser()


def find_mysql_output_dir(
    *,
    stdout_json: dict[str, Any] | None,
    output_root: str,
) -> Path | None:
    candidate_values: list[object] = []
    if stdout_json:
        candidate_values.extend(
            stdout_json.get(key)
            for key in (
                "output_dir",
                "run_dir",
                "result_dir",
                "report_dir",
                "output_path",
                "reply_text",
                "windows_path",
                "pptx_path",
            )
        )
        files_value = stdout_json.get("files")
        if isinstance(files_value, dict):
            candidate_values.extend(files_value.values())
        elif isinstance(files_value, list):
            candidate_values.extend(files_value)

    for value in candidate_values:
        path = _path_from_value(value)
        if path is None:
            continue
        if path.is_dir():
            return path
        if path.is_file():
            return path.parent

    root = Path(output_root).expanduser()
    if not root.is_dir():
        return None
    marker_paths = list(root.rglob("run_meta.json")) + list(root.rglob("report_summary.md"))
    if marker_paths:
        return max(marker_paths, key=lambda item: item.stat().st_mtime).parent
    subdirs = [path for path in root.iterdir() if path.is_dir()]
    if subdirs:
        return max(subdirs, key=lambda item: item.stat().st_mtime)
    return root


def mysql_output_files(output_dir: Path | None) -> list[str]:
    if output_dir is None or not output_dir.is_dir():
        return []
    preferred = [
        "report_summary.md",
        "supplier_shipment_summary.xlsx",
        "supplier_shipment_result.csv",
        "supplier_shipment_top10.csv",
        "supplier_shipment_top10.png",
        "query.sql",
        "run_meta.json",
    ]
    files = [name for name in preferred if (output_dir / name).is_file()]
    if files:
        return files
    return [path.name for path in sorted(output_dir.iterdir()) if path.is_file()]


def load_mysql_report_summary(output_dir: Path | None) -> str:
    if output_dir is None:
        return ""
    summary_path = output_dir / "report_summary.md"
    if not summary_path.is_file():
        return ""
    try:
        return sanitize_mysql_analysis_text(summary_path.read_text(encoding="utf-8"), max_length=3000).strip()
    except OSError:
        return ""


def load_mysql_run_meta(output_dir: Path | None) -> dict[str, Any] | None:
    if output_dir is None:
        return None
    return load_json_file(output_dir / "run_meta.json")


def _first_meta_value(meta: dict[str, Any] | None, keys: tuple[str, ...]) -> object | None:
    if not meta:
        return None
    for key in keys:
        value = meta.get(key)
        if value not in (None, ""):
            return value
    return None


def build_mysql_success_text(
    *,
    parsed_request: ParsedMysqlAnalysisRequest,
    output_dir: Path | None,
    report_summary: str = "",
    run_meta: dict[str, Any] | None = None,
) -> str:
    scope = f"unionId={parsed_request.union_id}" if parsed_request.union_id else "全部子公司"
    lines = [
        "供应商出货统计完成。",
        "",
        f"统计周期：{parsed_request.start_date} 至 {parsed_request.end_date}",
        f"统计范围：{scope}",
    ]
    supplier_count = _first_meta_value(
        run_meta,
        ("supplier_factory_count", "supplier_count", "factory_count", "row_count"),
    )
    if supplier_count is not None:
        lines.append(f"供应商/工厂数量：{supplier_count}")
    total_amount = _first_meta_value(
        run_meta,
        ("total_purchase_amount", "purchase_amount_total", "total_amount", "total_money"),
    )
    if total_amount is not None:
        lines.append(f"出货采购总金额：{total_amount} 元")
    if parsed_request.default_year:
        month = int(parsed_request.start_date[5:7])
        lines.append(f"日期说明：已按 {parsed_request.default_year} 年 {month} 月处理")
    if output_dir is not None:
        lines.extend(["", "结果目录：", str(output_dir)])
        files = mysql_output_files(output_dir)
        if files:
            lines.extend(["", "主要文件："])
            descriptions = {
                "report_summary.md": "统计摘要",
                "supplier_shipment_summary.xlsx": "Excel 汇总表",
                "supplier_shipment_result.csv": "完整 CSV 结果",
                "supplier_shipment_top10.csv": "Top10 图表数据",
                "supplier_shipment_top10.png": "Top10 图表",
                "query.sql": "本次 SQL",
                "run_meta.json": "运行元数据",
            }
            lines.extend(f"- {name}：{descriptions.get(name, '输出文件')}" for name in files)
    if report_summary:
        lines.extend(["", "统计摘要：", report_summary])
    return "\n".join(lines).strip()


def build_mysql_failure_text(*, phase: str, error_message: str) -> str:
    return (
        "MySQL 分析任务执行失败。\n\n"
        f"失败阶段：{phase}\n"
        "错误摘要：\n"
        f"{sanitize_mysql_analysis_text(error_message, max_length=1200)}\n\n"
        "排查建议：\n"
        "1. 检查 workspace/.env 是否配置 MYSQL_PASSWORD。\n"
        "2. 检查 MySQL 白名单和网络连通性。\n"
        "3. 检查 /data/share/yaq/test 是否有写入权限。\n"
        "4. 检查 scripts/run_supplier_shipment_report.py 是否存在。\n"
        "5. 检查 .venv 依赖是否安装。"
    )
