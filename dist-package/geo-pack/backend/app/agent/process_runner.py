import multiprocessing as mp
import time
from queue import Empty
from typing import Any, Callable

from app.core.config import Settings


class ChildProcessCancelled(RuntimeError):
    pass


class ChildProcessFailed(RuntimeError):
    pass


def run_worker_process(
    worker_name: str,
    payload: dict[str, Any],
    settings: Settings,
    *,
    cancel_requested: Callable[[], bool],
    on_progress: Callable[[str], None] | None = None,
) -> Any:
    ctx = mp.get_context("spawn")
    result_queue = ctx.Queue()
    progress_queue = ctx.Queue()
    process = ctx.Process(target=_worker_entry, args=(worker_name, payload, result_queue, progress_queue))
    process.start()

    started_at = time.monotonic()
    poll_interval = max(float(settings.job_cancel_poll_interval_seconds), 0.05)
    timeout = max(float(settings.job_child_process_timeout_seconds), 0)

    try:
        while process.is_alive():
            _drain_progress(progress_queue, on_progress)
            if cancel_requested():
                _terminate_process(process, settings)
                _drain_progress(progress_queue, on_progress)
                raise ChildProcessCancelled("任务已停止。")
            if timeout and time.monotonic() - started_at > timeout:
                _terminate_process(process, settings)
                raise ChildProcessFailed(f"子进程执行超过 {timeout:g} 秒，已终止。")
            process.join(poll_interval)

        _drain_progress(progress_queue, on_progress)
        if cancel_requested():
            raise ChildProcessCancelled("任务已停止，结果未保存。")

        try:
            message = result_queue.get(timeout=1)
        except Empty as exc:
            raise ChildProcessFailed(f"子进程异常退出，退出码：{process.exitcode}") from exc
        if not isinstance(message, dict):
            raise ChildProcessFailed("子进程返回格式无效。")
        if message.get("ok"):
            return message.get("result")
        error = str(message.get("error") or "子进程执行失败。")
        raise ChildProcessFailed(error)
    finally:
        if process.is_alive():
            _terminate_process(process, settings)
        process.join(timeout=0.1)
        _close_queue(progress_queue)
        _close_queue(result_queue)


def _worker_entry(worker_name: str, payload: dict[str, Any], result_queue: Any, progress_queue: Any) -> None:
    try:
        from app.agent.process_workers import run_named_worker

        result = run_named_worker(worker_name, payload, progress_queue)
        result_queue.put({"ok": True, "result": result})
    except BaseException as exc:  # noqa: BLE001 - child must return a serializable error
        result_queue.put({"ok": False, "error": str(exc), "error_type": exc.__class__.__name__})


def _terminate_process(process: mp.Process, settings: Settings) -> None:
    if not process.is_alive():
        return
    process.terminate()
    process.join(timeout=max(float(settings.job_terminate_grace_seconds), 0))
    if process.is_alive() and hasattr(process, "kill"):
        process.kill()
        process.join(timeout=0.2)


def _drain_progress(progress_queue: Any, on_progress: Callable[[str], None] | None) -> None:
    if not on_progress:
        return
    while True:
        try:
            message = progress_queue.get_nowait()
        except Empty:
            return
        if isinstance(message, dict):
            text = str(message.get("message") or "")
        else:
            text = str(message or "")
        if text:
            on_progress(text)


def _close_queue(queue: Any) -> None:
    close = getattr(queue, "close", None)
    if callable(close):
        close()
    join_thread = getattr(queue, "join_thread", None)
    if callable(join_thread):
        join_thread()
