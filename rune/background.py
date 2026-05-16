"""In-process background task manager for Rune."""

from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class BackgroundTask:
    id: str
    command: str
    cwd: str
    process: subprocess.Popen
    started_at: float
    stdout: List[str] = field(default_factory=list)
    stderr: List[str] = field(default_factory=list)

    @property
    def running(self) -> bool:
        return self.process.poll() is None

    @property
    def returncode(self) -> Optional[int]:
        return self.process.poll()

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.started_at


class BackgroundTaskManager:
    """Starts shell commands and keeps their output available for later turns."""

    def __init__(self) -> None:
        self._tasks: Dict[str, BackgroundTask] = {}
        self._lock = threading.Lock()

    def start(self, command: str, working_directory: str = "") -> BackgroundTask:
        cwd = os.path.abspath(os.path.expanduser(working_directory or os.getcwd()))
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        task = BackgroundTask(
            id=uuid.uuid4().hex[:8],
            command=command,
            cwd=cwd,
            process=process,
            started_at=time.time(),
        )
        with self._lock:
            self._tasks[task.id] = task

        threading.Thread(target=self._read_stream, args=(task, process.stdout, task.stdout), daemon=True).start()
        threading.Thread(target=self._read_stream, args=(task, process.stderr, task.stderr), daemon=True).start()
        return task

    def list(self) -> List[BackgroundTask]:
        with self._lock:
            return list(self._tasks.values())

    def get(self, task_id: str) -> Optional[BackgroundTask]:
        with self._lock:
            return self._tasks.get(task_id)

    def stop(self, task_id: str) -> bool:
        task = self.get(task_id)
        if not task:
            return False
        if task.running:
            task.process.terminate()
            try:
                task.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                task.process.kill()
        return True

    @staticmethod
    def _read_stream(task: BackgroundTask, stream, bucket: List[str]) -> None:
        if stream is None:
            return
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                bucket.append(line)
        finally:
            stream.close()


manager = BackgroundTaskManager()
