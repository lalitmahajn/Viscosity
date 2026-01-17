# viscologic/core/event_bus.py
# Thread-safe EventBus for ViscoLogic (frames + commands + status)

from __future__ import annotations

import time
import queue
import threading
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, List


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Command:
    """
    Unified command model (UI/PLC दोनों इसी format में push करेंगे)
    cmd_type examples:
      START, STOP, PAUSE, RESET_ALARMS, SET_MODE, SET_CONTROL_SOURCE, SET_REMOTE_ENABLE, SET_PROFILE
    """
    source: str                 # "LOCAL" | "PLC"
    cmd_type: str               # e.g., "START"
    payload: Dict[str, Any]     # extra parameters (mode, profile_id, etc.)
    seq_id: int = 0             # PLC handshake support (0 ok for local)
    timestamp_ms: int = 0

    def __post_init__(self):
        if not self.timestamp_ms:
            self.timestamp_ms = now_ms()


class EventBus:
    """
    Responsibilities:
      1) MeasurementFrame publish करना (latest_frame store + optional callbacks)
      2) Command queue maintain करना (UI/PLC -> Orchestrator)
      3) Status snapshot publish (optional)
      4) Thread-safe stop flag
    """

    def __init__(self, logger: Optional[logging.Logger] = None, command_queue_max: int = 200):
        self.logger = logger or logging.getLogger("viscologic.event_bus")

        # Latest measurement frame (dict)
        self._frame_lock = threading.Lock()
        self._latest_frame: Dict[str, Any] = {
            "timestamp_ms": now_ms(),
            "viscosity_cp": 0.0,
            "temp_c": 25.0,
            "freq_hz": 0.0,
            "health_pct": 0,
            "status_word": 0,
            "alarm_word": 0,
        }

        # Optional status snapshot (dict)
        self._status_lock = threading.Lock()
        self._latest_status: Dict[str, Any] = {
            "timestamp_ms": now_ms(),
            "state": "BOOTING",
            "message": "Starting",
        }

        # Command queue
        self._cmd_q: "queue.Queue[Command]" = queue.Queue(maxsize=command_queue_max)

        # Subscribers (callbacks)
        self._subs_lock = threading.Lock()
        self._frame_subs: List[Callable[[Dict[str, Any]], None]] = []
        self._status_subs: List[Callable[[Dict[str, Any]], None]] = []
        
        # Generic topic-based subscriptions (for backward compatibility)
        self._topic_subs: Dict[str, List[Callable[[Any], None]]] = {}

        # Stop control
        self._stop_event = threading.Event()

    # -----------------------
    # Stop / Health
    # -----------------------

    def stop(self) -> None:
        """Signal all threads to stop."""
        self._stop_event.set()

    def is_stopped(self) -> bool:
        return self._stop_event.is_set()

    # -----------------------
    # Measurement Frame APIs
    # -----------------------

    def publish_frame(self, frame: Dict[str, Any]) -> None:
        """
        Store latest measurement frame and notify subscribers.
        Frame is expected to include at least:
          timestamp_ms, viscosity_cp, temp_c, freq_hz, health_pct, status_word, alarm_word
        """
        if "timestamp_ms" not in frame:
            frame["timestamp_ms"] = now_ms()

        with self._frame_lock:
            self._latest_frame = dict(frame)
            snapshot = self._latest_frame

        # Notify subscribers (non-blocking best-effort)
        subs = self._copy_frame_subs()
        for cb in subs:
            try:
                cb(snapshot)
            except Exception:
                # Never crash bus due to a bad subscriber
                self.logger.debug("Frame subscriber error (ignored)", exc_info=True)

    def get_latest_frame(self) -> Dict[str, Any]:
        with self._frame_lock:
            return dict(self._latest_frame)

    def subscribe_frames(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        with self._subs_lock:
            self._frame_subs.append(callback)

    def unsubscribe_frames(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        with self._subs_lock:
            self._frame_subs = [cb for cb in self._frame_subs if cb != callback]

    def _copy_frame_subs(self) -> List[Callable[[Dict[str, Any]], None]]:
        with self._subs_lock:
            return list(self._frame_subs)

    # -----------------------
    # Status APIs (optional)
    # -----------------------

    def publish_status(self, status: Dict[str, Any]) -> None:
        """
        Useful for UI banners: e.g., Self-check fail reasons, lock state, etc.
        """
        if "timestamp_ms" not in status:
            status["timestamp_ms"] = now_ms()

        with self._status_lock:
            self._latest_status = dict(status)

        subs = self._copy_status_subs()
        for cb in subs:
            try:
                cb(self._latest_status)
            except Exception:
                self.logger.debug("Status subscriber error (ignored)", exc_info=True)

    def get_latest_status(self) -> Dict[str, Any]:
        with self._status_lock:
            return dict(self._latest_status)

    def subscribe_status(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        with self._subs_lock:
            self._status_subs.append(callback)

    def unsubscribe_status(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        with self._subs_lock:
            self._status_subs = [cb for cb in self._status_subs if cb != callback]

    def _copy_status_subs(self) -> List[Callable[[Dict[str, Any]], None]]:
        with self._subs_lock:
            return list(self._status_subs)

    # -----------------------
    # Command Queue APIs
    # -----------------------

    def push_command(
        self,
        source: str,
        cmd_type: str,
        payload: Optional[Dict[str, Any]] = None,
        seq_id: int = 0
    ) -> bool:
        """
        Push a command into queue (UI/PLC call this).
        Returns True if enqueued, False if dropped due to full queue.
        """
        payload = payload or {}
        cmd = Command(source=source, cmd_type=cmd_type, payload=payload, seq_id=seq_id)

        try:
            self._cmd_q.put_nowait(cmd)
            return True
        except queue.Full:
            # Drop newest command to avoid blocking UI/PLC threads
            self.logger.warning("Command queue full, dropping cmd=%s source=%s", cmd_type, source)
            return False

    def pop_command(self, timeout_s: float = 0.0) -> Optional[Command]:
        """
        Orchestrator calls this to get commands.
        timeout_s=0 => non-blocking
        """
        if self.is_stopped():
            return None
        try:
            if timeout_s and timeout_s > 0:
                return self._cmd_q.get(timeout=timeout_s)
            return self._cmd_q.get_nowait()
        except queue.Empty:
            return None

    def drain_commands(self, max_items: int = 100) -> List[Command]:
        """
        Fetch up to max_items commands at once (useful for batch processing).
        """
        items: List[Command] = []
        for _ in range(max_items):
            cmd = self.pop_command(timeout_s=0.0)
            if cmd is None:
                break
            items.append(cmd)
        return items

    # -----------------------
    # Generic Topic-Based API (for backward compatibility)
    # -----------------------

    def subscribe(self, topic: str, callback: Callable[[Any], None]) -> None:
        """
        Generic topic-based subscription (backward compatibility).
        Topics like "frame", "ui.frame", "ui.command", "ui/start", etc.
        
        Special handling:
        - "frame" and "ui.frame" topics also trigger frame subscribers
        - Other topics use generic topic-based routing
        """
        if not topic or not callable(callback):
            return
        
        with self._subs_lock:
            # Special case: frame topics also register as frame subscribers
            if topic in ("frame", "ui.frame"):
                if callback not in self._frame_subs:
                    self._frame_subs.append(callback)
            else:
                # Generic topic-based subscription
                if topic not in self._topic_subs:
                    self._topic_subs[topic] = []
                if callback not in self._topic_subs[topic]:
                    self._topic_subs[topic].append(callback)

    def publish(self, topic: str, payload: Any = None) -> None:
        """
        Generic topic-based publish (backward compatibility).
        Publishes to topic subscribers and handles special topics.
        
        Special handling:
        - "frame" and "ui.frame" topics also trigger publish_frame()
        - Other topics notify only topic subscribers
        """
        if not topic:
            return
        
        # Special case: frame topics also use publish_frame
        if topic in ("frame", "ui.frame") and isinstance(payload, dict):
            self.publish_frame(payload)
            return
        
        # Notify topic subscribers
        with self._subs_lock:
            callbacks = list(self._topic_subs.get(topic, []))
        
        # Call callbacks (non-blocking best-effort)
        for cb in callbacks:
            try:
                cb(payload)
            except Exception:
                self.logger.debug("Topic subscriber error (ignored)", exc_info=True)
