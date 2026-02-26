#!/usr/bin/env python3

import json
import os
import re
import socket
import statistics
import sys
import time
from datetime import datetime, timezone
from typing import Optional
from urllib import error, request

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None


README_RESULT_START = "<!-- OPENAI_BENCHMARK_RESULTS_START -->"
README_RESULT_END = "<!-- OPENAI_BENCHMARK_RESULTS_END -->"


def env_str(name: str, default: Optional[str] = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and (value is None or value == ""):
        raise ValueError(f"Missing required environment variable: {name}")
    return "" if value is None else value


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got: {value}") from exc


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got: {value}") from exc


def now_iso_strings():
    utc_now = datetime.now(timezone.utc)
    if ZoneInfo is None:
        beijing_now = utc_now
    else:
        beijing_now = utc_now.astimezone(ZoneInfo("Asia/Shanghai"))
    return utc_now.isoformat(), beijing_now.isoformat()


def safe_markdown_text(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def parse_sse_stream(response) -> str:
    full_text = []
    while True:
        line = response.readline()
        if not line:
            break

        decoded = line.decode("utf-8", errors="replace").strip()
        if not decoded.startswith("data:"):
            continue

        data = decoded[5:].strip()
        if data == "[DONE]":
            break

        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue

        choices = payload.get("choices", [])
        if not choices:
            continue

        delta = choices[0].get("delta", {})
        token = delta.get("content")
        if isinstance(token, str) and token:
            print(token, end="", flush=True)
            full_text.append(token)

    return "".join(full_text)


def run_single_request(
    idx: int,
    total: int,
    api_url: str,
    api_key: str,
    model: str,
    prompt: str,
    timeout_seconds: int,
    max_tokens: int,
    temperature: float,
):
    print(f"\n===== Request {idx}/{total} started =====")

    body = {
        "model": model,
        "stream": True,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    req = request.Request(
        api_url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    started_at = time.perf_counter()
    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            status_code = getattr(resp, "status", resp.getcode())
            if status_code != 200:
                err_body = resp.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"HTTP {status_code}: {err_body}")

            response_text = parse_sse_stream(resp)
            duration = time.perf_counter() - started_at
            print(f"\n===== Request {idx}/{total} finished in {duration:.3f}s =====")
            return {
                "index": idx,
                "ok": True,
                "duration": duration,
                "chars": len(response_text),
                "error": "",
            }
    except error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        duration = time.perf_counter() - started_at
        message = f"HTTPError {exc.code}: {err_body}"
    except (error.URLError, socket.timeout, TimeoutError) as exc:
        duration = time.perf_counter() - started_at
        message = f"Network/Timeout error: {exc}"
    except Exception as exc:  # noqa: BLE001
        duration = time.perf_counter() - started_at
        message = f"Unexpected error: {exc}"

    print(f"\n===== Request {idx}/{total} failed in {duration:.3f}s =====")
    print(message)
    return {
        "index": idx,
        "ok": False,
        "duration": duration,
        "chars": 0,
        "error": message,
    }


def write_github_summary(lines):
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")


def update_readme_tail(readme_path: str, report_lines):
    if os.path.exists(readme_path):
        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = "# OpenAI API Availability Monitor\n\n"

    block = (
        f"{README_RESULT_START}\n"
        + "\n".join(report_lines).strip()
        + f"\n{README_RESULT_END}\n"
    )

    pattern = re.compile(
        rf"{re.escape(README_RESULT_START)}.*?{re.escape(README_RESULT_END)}\n?",
        re.DOTALL,
    )
    content_without_old = re.sub(pattern, "", content).rstrip()
    new_content = f"{content_without_old}\n\n{block}"

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(new_content)


def build_report_lines(
    api_url: str,
    model: str,
    prompt: str,
    request_count: int,
    timeout_seconds: int,
    max_runtime_seconds: int,
    max_tokens: int,
    temperature: float,
    pause_seconds: float,
    attempted: int,
    success_count: int,
    failure_count: int,
    availability: float,
    total_runtime: float,
    avg_duration,
    fastest,
    slowest,
    results,
    status: str,
    error_message: str,
):
    utc_now, beijing_now = now_iso_strings()
    lines = [
        "## 最新脚本运行结果",
        "",
        f"- 运行状态: **{status}**",
        f"- 运行时间(UTC): `{utc_now}`",
        f"- 运行时间(Asia/Shanghai): `{beijing_now}`",
        f"- API URL: `{api_url}`",
        f"- Model: `{model}`",
        f"- Prompt: `{prompt}`",
        f"- 计划请求次数: `{request_count}`",
        f"- 实际请求次数: `{attempted}`",
        f"- 单次超时(s): `{timeout_seconds}`",
        f"- 总运行时长上限(s): `{max_runtime_seconds}`",
        f"- Max Tokens: `{max_tokens}`",
        f"- Temperature: `{temperature}`",
        f"- 请求间隔(s): `{pause_seconds}`",
        f"- 成功次数: `{success_count}`",
        f"- 失败次数: `{failure_count}`",
        f"- 模型可用性: `{availability:.2f}%`",
        f"- 总耗时(s): `{total_runtime:.3f}`",
        f"- 平均耗时(s): `{f'{avg_duration:.3f}' if avg_duration is not None else 'N/A'}`",
        f"- 最快耗时(s): `{f'{fastest:.3f}' if fastest is not None else 'N/A'}`",
        f"- 最慢耗时(s): `{f'{slowest:.3f}' if slowest is not None else 'N/A'}`",
    ]

    if error_message:
        lines.append(f"- 错误信息: `{safe_markdown_text(error_message)}`")

    lines.extend(
        [
            "",
            "### 请求明细",
            "",
            "| 请求序号 | 状态 | 耗时(s) | 输出字符数 | 错误信息 |",
            "|---|---|---:|---:|---|",
        ]
    )

    if not results:
        lines.append("| - | - | - | - | 无请求执行 |")
        return lines

    for item in results:
        state = "SUCCESS" if item["ok"] else "FAILED"
        err_text = safe_markdown_text(item["error"]) if item["error"] else "-"
        lines.append(
            f"| {item['index']} | {state} | {item['duration']:.3f} | "
            f"{item['chars']} | {err_text} |"
        )
    return lines


def main() -> int:
    readme_path = env_str("OPENAI_README_PATH", "README.md")
    api_url = "https://api.openai.com/v1/chat/completions"
    api_key = ""
    model = "gpt-4o-mini"
    prompt = "请简单回复：服务可用。"
    request_count = 5
    timeout_seconds = 120
    max_runtime_seconds = 0
    max_tokens = 128
    pause_seconds = 0.0
    temperature = 0.1
    results = []
    attempted = 0
    success_count = 0
    failure_count = 0
    availability = 0.0
    total_runtime = 0.0
    avg_duration = None
    fastest = None
    slowest = None
    status = "FAILED"
    error_message = ""
    exit_code = 1

    try:
        api_url = env_str("OPENAI_API_URL", "https://api.openai.com/v1/chat/completions")
        api_key = env_str("OPENAI_API_KEY", required=True)
        model = env_str("OPENAI_MODEL", "gpt-4o-mini")
        prompt = env_str("OPENAI_PROMPT", "请简单回复：服务可用。")
        request_count = env_int("OPENAI_REQUEST_COUNT", 5)
        timeout_seconds = env_int("OPENAI_REQUEST_TIMEOUT_SECONDS", 120)
        max_runtime_seconds = env_int("OPENAI_MAX_RUNTIME_SECONDS", 0)
        max_tokens = env_int("OPENAI_MAX_TOKENS", 128)
        pause_seconds = env_float("OPENAI_REQUEST_PAUSE_SECONDS", 0.0)
        temperature = env_float("OPENAI_TEMPERATURE", 0.1)

        if request_count <= 0:
            raise ValueError("OPENAI_REQUEST_COUNT must be > 0")
        if timeout_seconds <= 0:
            raise ValueError("OPENAI_REQUEST_TIMEOUT_SECONDS must be > 0")
        if max_tokens <= 0:
            raise ValueError("OPENAI_MAX_TOKENS must be > 0")
        if max_runtime_seconds < 0:
            raise ValueError("OPENAI_MAX_RUNTIME_SECONDS must be >= 0")
        if pause_seconds < 0:
            raise ValueError("OPENAI_REQUEST_PAUSE_SECONDS must be >= 0")

        print("=== OpenAI streaming sequential benchmark ===")
        print(f"API URL: {api_url}")
        print(f"Model: {model}")
        print(f"Planned requests: {request_count}")
        print(f"Per-request timeout (s): {timeout_seconds}")
        print(f"Max runtime (s, 0 means unlimited): {max_runtime_seconds}")
        print(f"Pause between requests (s): {pause_seconds}")
        print(f"README path: {readme_path}")
        print("Running requests sequentially...")

        suite_start = time.perf_counter()

        for idx in range(1, request_count + 1):
            elapsed = time.perf_counter() - suite_start
            if max_runtime_seconds > 0 and elapsed >= max_runtime_seconds:
                print(
                    f"Reached max runtime limit ({max_runtime_seconds}s). "
                    f"Stopping early at request {idx}."
                )
                break

            result = run_single_request(
                idx=idx,
                total=request_count,
                api_url=api_url,
                api_key=api_key,
                model=model,
                prompt=prompt,
                timeout_seconds=timeout_seconds,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            results.append(result)

            if pause_seconds > 0 and idx != request_count:
                time.sleep(pause_seconds)

        total_runtime = time.perf_counter() - suite_start
        attempted = len(results)
        success_durations = [item["duration"] for item in results if item["ok"]]
        success_count = len(success_durations)
        failure_count = attempted - success_count
        availability = (success_count / attempted * 100.0) if attempted else 0.0
        avg_duration = statistics.mean(success_durations) if success_durations else None
        fastest = min(success_durations) if success_durations else None
        slowest = max(success_durations) if success_durations else None

        print("\n=== Summary ===")
        print(f"Planned requests: {request_count}")
        print(f"Attempted requests: {attempted}")
        print(f"Successful requests: {success_count}")
        print(f"Failed requests: {failure_count}")
        print(f"Model availability: {availability:.2f}%")
        print(f"Total runtime: {total_runtime:.3f}s")
        if avg_duration is not None:
            print(f"Average duration: {avg_duration:.3f}s")
            print(f"Fastest duration: {fastest:.3f}s")
            print(f"Slowest duration: {slowest:.3f}s")
        else:
            print("Average duration: N/A")
            print("Fastest duration: N/A")
            print("Slowest duration: N/A")

        if attempted == 0:
            status = "FAILED"
            error_message = "No request attempted."
            exit_code = 1
        elif success_count == 0:
            status = "FAILED"
            error_message = "All requests failed."
            exit_code = 1
        elif failure_count > 0:
            status = "PARTIAL_SUCCESS"
            exit_code = 0
        else:
            status = "SUCCESS"
            exit_code = 0
    except ValueError as exc:
        error_message = str(exc)
        print(f"Configuration error: {error_message}")
        status = "CONFIG_ERROR"
        exit_code = 2
    except Exception as exc:  # noqa: BLE001
        error_message = f"Unexpected runtime error: {exc}"
        print(error_message)
        status = "RUNTIME_ERROR"
        exit_code = 1

    report_lines = build_report_lines(
        api_url=api_url,
        model=model,
        prompt=prompt,
        request_count=request_count,
        timeout_seconds=timeout_seconds,
        max_runtime_seconds=max_runtime_seconds,
        max_tokens=max_tokens,
        temperature=temperature,
        pause_seconds=pause_seconds,
        attempted=attempted,
        success_count=success_count,
        failure_count=failure_count,
        availability=availability,
        total_runtime=total_runtime,
        avg_duration=avg_duration,
        fastest=fastest,
        slowest=slowest,
        results=results,
        status=status,
        error_message=error_message,
    )
    update_readme_tail(readme_path, report_lines)

    summary_lines = ["## OpenAI Availability Summary", ""]
    detail_header = "### 请求明细"
    if detail_header in report_lines:
        detail_start = report_lines.index(detail_header)
        summary_lines.extend(report_lines[2:detail_start])
    else:
        summary_lines.extend(report_lines[2:])
    if failure_count > 0:
        summary_lines.append("")
        summary_lines.append("### Failed request details")
        for item in [x for x in results if not x["ok"]]:
            summary_lines.append(
                f"- Request {item['index']}: {safe_markdown_text(item['error'])}"
            )
    write_github_summary(summary_lines)
    print(f"README updated: {readme_path}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
