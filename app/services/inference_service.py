# services/inference_service.py

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from queue import Empty, Queue
from typing import Any
from uuid import uuid4

from app.intelligence.client import OllamaClient
from app.intelligence.prompt_builders import (
    build_chat_messages,
    build_system_prompt,
    load_voice_configs,
)
from app.intelligence.tool_handler import detect_tool
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

    def __init__(self, settings, tool_service=None):
        # settings must provide ollama.base_url and ollama.model
        self.client = OllamaClient(
            base_url=settings.ollama.base_url,
            default_model=settings.ollama.model,
            timeout_seconds=settings.ollama.timeout_seconds,
        )
        self.model_loaded: bool = True
        # Slash dispatch (SPEC-0007 WP-7); None disables it and every message uses the chat path.
        self._tool_service = tool_service

        # Prompt pipeline (SPEC-0006): voice configs and prompt limits are read once, here.
        self._system_prompt = build_system_prompt(settings.prompts, load_voice_configs())
        self._max_turns = settings.app.max_turns
        self._max_field_len = settings.app.max_field_len

        # Job queue and worker control
        self._queue: Queue[InferenceJob] = Queue()
        self._shutdown_flag = threading.Event()
        # Serializes every Ollama chat call: the worker's chat and generate (ADR-0004).
        # Non-reentrant; never held around store writes or status updates.
        self._ollama_lock = threading.Lock()
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
            # Mark message as queued before the job is visible to the worker (no race with running)
            self._update_message_status(store, session_id, message_id, "queued")
            self._queue.put_nowait(job)
            logger.info(
                "enqueue",
                extra={
                    "session_id": session_id,
                    "message_id": message_id,
                    "prompt_len": len(prompt),
                },
            )
            return True
        except Exception as exc:
            logger.exception("enqueue failed", extra={"error": str(exc)})
            return False

    def queue_position(self, message_id: str | None) -> int:
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

    def estimate_wait(self, message_id: str | None) -> float:
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
        Updates message status and appends the reply as a new assistant message.
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
                name, args = (
                    detect_tool(job.prompt) if self._tool_service is not None else (None, None)
                )
                if name is not None:
                    # Slash job (PAT-ARCH-004): run the tool here, outside _ollama_lock (narrate
                    # calls generate, which takes it). No chat builder and no client.chat.
                    logger.info(
                        "tool.dispatch",
                        extra={
                            "session_id": job.session_id,
                            "message_id": job.message_id,
                            "tool": name,
                        },
                    )
                    result = self._tool_service.invoke(
                        name,
                        args or "",
                        {
                            "store": job.store,
                            "session_id": job.session_id,
                            "message_id": job.message_id,
                        },
                    )
                    self._append_reply(
                        job.store,
                        job.session_id,
                        job.message_id,
                        result["text"],
                        meta={**result["meta"], "tool": name},
                    )
                else:
                    history = job.store.list_messages(job.session_id)
                    messages = build_chat_messages(
                        self._system_prompt,
                        history,
                        job.message_id,
                        job.prompt,
                        max_turns=self._max_turns,
                        max_field_len=self._max_field_len,
                    )
                    logger.info(
                        "prompt.built",
                        extra={
                            "session_id": job.session_id,
                            "message_id": job.message_id,
                            "history_count": len(messages) - 2,
                            "message_count": len(messages),
                        },
                    )
                    with self._ollama_lock:
                        text = self.client.chat(messages)

                    # Append the reply as a new assistant message; the user message is untouched
                    self._append_reply(job.store, job.session_id, job.message_id, text)
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
                self._update_message_status(
                    job.store,
                    job.session_id,
                    job.message_id,
                    "error",
                    {"error": str(exc)},
                )
            finally:
                self._queue.task_done()

        logger.info("Inference worker loop exiting")

    # ------------------------------------------------------------
    # Store helpers (best-effort, no strict schema assumptions)
    # ------------------------------------------------------------
    def _update_message_status(
        self, store, session_id: str, message_id: str, status: str, meta: dict | None = None
    ) -> None:
        try:
            store.update_message_status(
                session_id,
                message_id,
                status,
                meta={"updated_by": "inference_worker", **(meta or {})},
            )
        except Exception:
            logger.exception(
                "update_message_status failed",
                extra={"session_id": session_id, "message_id": message_id, "status": status},
            )

    def _append_reply(
        self,
        store,
        session_id: str,
        user_message_id: str,
        text: str,
        meta: dict | None = None,
    ) -> str:
        """Append the reply as a new assistant message linked by meta.reply_to; exceptions propagate so the worker marks the job as error."""
        reply_id = str(uuid4())
        store.create_message(
            session_id,
            reply_id,
            {
                "role": "assistant",
                "content": text,
                "meta": {**(meta or {}), "reply_to": user_message_id},
            },
        )
        store.update_message_status(session_id, reply_id, "completed")
        logger.info(
            "reply.appended",
            extra={"session_id": session_id, "message_id": user_message_id, "reply_id": reply_id},
        )
        return reply_id

    # ------------------------------------------------------------
    # Single-prompt generation (tools, e.g. narrate)
    # ------------------------------------------------------------
    def generate(self, prompt: str) -> str:
        """Run one prompt through Ollama under the shared lock and return the reply text."""
        with self._ollama_lock:
            return self.client.generate(prompt)

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
