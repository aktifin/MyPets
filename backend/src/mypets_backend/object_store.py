"""Filesystem object storage used for development and test asset publishing."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


class FileObjectStore:
    """Store immutable package objects below one configured root."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if candidate == self.root or self.root not in candidate.parents:
            raise ValueError("对象存储键越界")
        return candidate

    def write(self, key: str, data: bytes, *, replace: bool = False) -> Path:
        target = self._path(key)
        if target.exists() and not replace:
            raise FileExistsError(f"对象已存在：{key}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target)
        return target

    def promote(self, source_key: str, target_key: str) -> Path:
        source = self._path(source_key)
        if not source.is_file():
            raise FileNotFoundError(f"暂存对象不存在：{source_key}")
        target = self._path(target_key)
        if target.exists():
            raise FileExistsError(f"发布对象已存在：{target_key}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        shutil.copy2(source, temporary)
        temporary.replace(target)
        return target

    def path(self, key: str) -> Path:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(f"对象不存在：{key}")
        return path
