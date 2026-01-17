# viscologic/storage/retention.py
# Retention manager: deletes old files based on retention_days (CSV logs, etc.)

from __future__ import annotations

import os
import time
import logging
from dataclasses import dataclass
from typing import Optional, List


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class RetentionReport:
    scanned_files: int = 0
    deleted_files: int = 0
    deleted_paths: Optional[List[str]] = None
    errors: int = 0


class RetentionManager:
    """
    Deletes files older than retention_days.
    - Works on a folder (non-recursive by default for safety).
    - You can enable recursive cleanup if needed.
    """

    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
        recursive: bool = False,
        dry_run: bool = False,
    ):
        self.logger = logger or logging.getLogger("viscologic.retention")
        self.recursive = bool(recursive)
        self.dry_run = bool(dry_run)

    def cleanup_folder(self, folder_path: str, retention_days: int, allowed_ext: Optional[List[str]] = None) -> RetentionReport:
        report = RetentionReport(deleted_paths=[])
        if retention_days <= 0:
            self.logger.info("Retention disabled (retention_days=%s).", retention_days)
            return report

        if not os.path.isdir(folder_path):
            self.logger.info("Retention folder not found: %s", folder_path)
            return report

        cutoff_sec = time.time() - (retention_days * 24 * 60 * 60)

        try:
            if self.recursive:
                for root, _, files in os.walk(folder_path):
                    self._process_files(root, files, cutoff_sec, allowed_ext, report)
            else:
                files = os.listdir(folder_path)
                self._process_files(folder_path, files, cutoff_sec, allowed_ext, report)
        except Exception:
            self.logger.error("Retention cleanup failed for %s", folder_path, exc_info=True)
            report.errors += 1

        return report

    def _process_files(
        self,
        root: str,
        files: List[str],
        cutoff_sec: float,
        allowed_ext: Optional[List[str]],
        report: RetentionReport,
    ) -> None:
        for name in files:
            path = os.path.join(root, name)
            if not os.path.isfile(path):
                continue

            report.scanned_files += 1

            if allowed_ext:
                _, ext = os.path.splitext(name)
                if ext.lower() not in [e.lower() for e in allowed_ext]:
                    continue

            try:
                mtime = os.path.getmtime(path)
                if mtime < cutoff_sec:
                    if self.dry_run:
                        self.logger.info("[DRY RUN] Would delete: %s", path)
                    else:
                        os.remove(path)
                        report.deleted_files += 1
                        if report.deleted_paths is not None:
                            report.deleted_paths.append(path)
            except Exception:
                report.errors += 1
                self.logger.warning("Failed to process retention file: %s", path, exc_info=True)
