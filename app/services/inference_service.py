# services/inference_service.py

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from queue import Queue, Empty
from typing import Any, Optional

from app.intelligence.client import OllamaClient
from app.services.logger import get_logger

logger = get_logger(__name__)


@dataclass
class InferenceJob:
    session_id: str
    message_id: str
    prompt: str
    store: Any
    enqueued_at: float = field(default_factory=time.time)


class OllamaInferenceService:
    """
    Production-grade inference adapter for the FastAPI backend.

    Features:
    - FIFO job queue
    - Background worker thread
    - Status tracking (queued, running, completed, error, cancelled)
    - Queue position and ETA estimation
    - REST: enqueue + background processing
    - WebSocket: direct streaming via generate_tokens
    """

    def __init__(self, settings):
        # settings must provide ollama.base_url and ollama.model
        self.client = OllamaClient(
            base_url=settings.ollama.base_url,
            default_model=settings.ollama.model,
            timeout_seconds=settings.ollama.timeout_seconds,
        )
        self.model_loaded: bool = True

        # Job queue and worker control
        self._queue: Queue[InferenceJob] = Queue()
        self._shutdown_flag = threading.Event()
        self._avg_job_seconds: float = 5.0  # simple ETA heuristic

        # Cancellation tracking
        self._cancelled: set[str] = set()

        # Start background worker
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="ollama-inference-worker",
            daemon=True,
        )
        self._worker.start()
        logger.info("OllamaInferenceService worker started")

    # ------------------------------------------------------------
    # Queueing (REST path)
    # ------------------------------------------------------------
    def enqueue(self, *, session_id: str, message_id: str, prompt: str, store) -> bool:
        """
        Enqueue a job for background processing.
        The session store already has a message record; we only update its status.
        """
        try:
            job = InferenceJob(
                session_id=session_id,
                message_id=message_id,
                prompt=prompt,
                store=store,
            )
            self._queue.put_nowait(job)
            logger.info(
                "enqueue",
                extra={
                    "session_id": session_id,
                    "message_id": message_id,
                    "prompt_len": len(prompt),
                },
            )
            # Mark message as queued in the store (best-effort)
            self._update_message_status(store, session_id, message_id, "queued")
            return True
        except Exception as exc:
            logger.exception("enqueue failed", extra={"error": str(exc)})
            return False

    def queue_position(self, message_id: Optional[str]) -> int:
        """
        Return approximate queue position for a given message_id.
        If message_id is None, return total queue size.
        """
        try:
            items = list(self._queue.queue)
        except Exception:
            return 0

        if message_id is None:
            return len(items)

        for idx, job in enumerate(items):
            if job.message_id == message_id:
                return idx
        return 0

    def estimate_wait(self, message_id: Optional[str]) -> float:
        """
        Rough ETA based on queue position and average job time.
        """
        pos = self.queue_position(message_id)
        return float(pos) * self._avg_job_seconds

    # ------------------------------------------------------------
    # Background worker
    # ------------------------------------------------------------
    def _worker_loop(self) -> None:
        """
        Background loop that consumes jobs from the queue and calls Ollama.
        Updates message status and content in the session store.
        """
        logger.info("Inference worker loop started")
        while not self._shutdown_flag.is_set():
            try:
                job = self._queue.get(timeout=0.5)
            except Empty:
                continue

            # Check cancellation
            if job.message_id in self._cancelled:
                logger.info(
                    "job cancelled before start",
                    extra={
                        "session_id": job.session_id,
                        "message_id": job.message_id,
                    },
                )
                self._update_message_status(job.store, job.session_id, job.message_id, "cancelled")
                self._queue.task_done()
                continue

            # Mark as running
            self._update_message_status(job.store, job.session_id, job.message_id, "running")

            start = time.time()
            try:
                logger.info(
                    "job.start",
                    extra={
                        "session_id": job.session_id,
                        "message_id": job.message_id,
                    },
                )
                text = self.client.generate(job.prompt)

                # Write assistant response back into the session store
                self._update_message_content(
                    job.store,
                    job.session_id,
                    job.message_id,
                    text,
                )
                self._update_message_status(job.store, job.session_id, job.message_id, "completed")

                duration = time.time() - start
                # Simple moving average for ETA
                self._avg_job_seconds = (self._avg_job_seconds * 0.8) + (duration * 0.2)

                logger.info(
                    "job.completed",
                    extra={
                        "session_id": job.session_id,
                        "message_id": job.message_id,
                        "duration": duration,
                    },
                )
            except Exception as exc:
                logger.exception(
                    "job.failed",
                    extra={
                        "session_id": job.session_id,
                        "message_id": job.message_id,
                        "error": str(exc),
                    },
                )
                self._update_message_status(job.store, job.session_id, job.message_id, "error")
                self._update_message_meta(
                    job.store,
                    job.session_id,
                    job.message_id,
                    {"error": str(exc)},
                )
            finally:
                self._queue.task_done()

        logger.info("Inference worker loop exiting")

    # ------------------------------------------------------------
    # Store helpers (best-effort, no strict schema assumptions)
    # ------------------------------------------------------------
    def _update_message_status(self, store, session_id: str, message_id: str, status: str) -> None:
        try:
            session = store.get_session(session_id)
            if not session:
                return
            for m in session:
                if m.get("id") == message_id:
                    m["status"] = status
                    m.setdefault("meta", {})
                    m["meta"]["updated_by"] = "inference_worker"
                    break
        except Exception:
            logger.exception(
                "update_message_status failed",
                extra={"session_id": session_id, "message_id": message_id, "status": status},
            )

    def _update_message_content(self, store, session_id: str, message_id: str, content: str) -> None:
        try:
            session = store.get_session(session_id)
            if not session:
                return
            for m in session:
                if m.get("id") == message_id:
                    # Convert user message into assistant response or attach content
                    m["role"] = "assistant"
                    m["content"] = content
                    break
        except Exception:
            logger.exception(
                "update_message_content failed",
                extra={"session_id": session_id, "message_id": message_id},
            )

    def _update_message_meta(self, store, session_id: str, message_id: str, meta: dict) -> None:
        try:
            session = store.get_session(session_id)
            if not session:
                return
            for m in session:
                if m.get("id") == message_id:
                    m.setdefault("meta", {})
                    m["meta"].update(meta)
                    break
        except Exception:
            logger.exception(
                "update_message_meta failed",
                extra={"session_id": session_id, "message_id": message_id},
            )

    # ------------------------------------------------------------
    # Token generation (WebSocket path)
    # ------------------------------------------------------------
    async def generate_tokens(
        self,
        *,
        prompt: str,
        session_id: str | None,
        message_id: str,
    ):
        """
        WebSocket streaming path: call Ollama synchronously and yield tokens.
        For now, we yield the full text as a single token; later you can
        switch to Ollama's streaming API and chunk by tokens.
        """
        try:
            logger.info(
                "ws.generate_tokens.start",
                extra={"session_id": session_id, "message_id": message_id},
            )
            text = self.client.generate(prompt)
            # Simple single-token stream; you can split by sentences or tokens later.
            yield text
            logger.info(
                "ws.generate_tokens.done",
                extra={"session_id": session_id, "message_id": message_id},
            )
        except Exception as exc:
            logger.exception(
                "ws.generate_tokens.failed",
                extra={"session_id": session_id, "message_id": message_id, "error": str(exc)},
            )
            yield f"[error] {exc}"

    # ------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------
    def cancel(self, message_id: str) -> bool:
        """
        Mark a message as cancelled; worker will skip it if not yet started.
        """
        try:
            self._cancelled.add(message_id)
            logger.info("cancel", extra={"message_id": message_id})
            return True
        except Exception:
            logger.exception("cancel failed", extra={"message_id": message_id})
            return False

    # ------------------------------------------------------------
    # Token validation (stub)
    # ------------------------------------------------------------
    def validate_token(self, token: str) -> bool:
        # For now, accept any token; your require_local_token already checks "Bearer dev".
        return True

    # ------------------------------------------------------------
    # Shutdown hook
    # ------------------------------------------------------------
    async def shutdown(self):
        """
        Signal the worker to stop and wait for it to exit.
        """
        logger.info("OllamaInferenceService shutdown requested")
        self._shutdown_flag.set()
        try:
            if self._worker.is_alive():
                self._worker.join(timeout=5.0)
        except Exception:
            logger.exception("Error joining worker thread")
