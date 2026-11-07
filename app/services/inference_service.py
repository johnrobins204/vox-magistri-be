# services/inference_service.py

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from queue import Empty, Full, Queue
from typing import Any
from uuid import uuid4

from app.intelligence.client import OllamaClient
from app.intelligence.prompt_builders import (
    build_character_section,
    build_chat_messages,
    build_system_prompt,
    build_world_section,
    load_voice_configs,
    select_world_entities,
)
from app.intelligence.tool_handler import detect_tool
from app.reference.species import Species
from app.services.logger import get_logger

logger = get_logger(__name__)
MAX_QUEUE_SIZE = 20


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

    def __init__(
        self,
        settings,
        tool_service=None,
        species: list[Species] | None = None,
        world_store=None,
    ):
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
        # Character species lookup (SPEC-0013 D2): built once here, never per job.
        self._species_by_id: dict[str, Species] = {s.id: s for s in (species or [])}
        # Canon world entities for the narrator (SPEC-0015 WP-6); None or budget 0 disables it.
        self._world_store = world_store
        self._world_budget: int = settings.world.entity_budget_chars

        # Job queue and worker control
        self._queue: Queue[InferenceJob] = Queue(maxsize=MAX_QUEUE_SIZE)
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
        job = InferenceJob(
            session_id=session_id,
            message_id=message_id,
            prompt=prompt,
            store=store,
        )
        try:
            # Mark queued before the job is visible to the worker (no race with running)
            self._update_message_status(store, session_id, message_id, "queued")
            self._queue.put_nowait(job)
        except Full:
            logger.warning("enqueue.queue_full", extra={"session_id": session_id})
            self._update_message_status(
                store, session_id, message_id, "error", {"error": "inference queue full"}
            )
            return False
        except Exception as exc:
            logger.exception("enqueue failed", extra={"error": str(exc)})
            return False

        logger.info(
            "enqueue",
            extra={
                "session_id": session_id,
                "message_id": message_id,
                "prompt_len": len(prompt),
            },
        )
        return True

    def queue_position(self, message_id: str | None) -> int | None:
        """
        Position of a queued message (0 = next up), or None if it is not waiting in the queue.
        If message_id is None, return the number of waiting jobs.
        """
        items = list(self._queue.queue)
        if message_id is None:
            return len(items)
        for idx, job in enumerate(items):
            if job.message_id == message_id:
                return idx
        return None

    def estimate_wait(self, message_id: str | None) -> float | None:
        """Rough ETA from queue position and average job time; None if not waiting."""
        pos = self.queue_position(message_id)
        if pos is None:
            return None
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
                self._cancelled.discard(job.message_id)
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
                    character = job.store.get_character(job.session_id)
                    system = self._system_prompt
                    species_resolved = False
                    if character is not None:
                        species = self._species_by_id.get(character.get("species_id") or "")
                        species_resolved = species is not None
                        section = build_character_section(
                            character,
                            species.name if species else None,
                            species.character_creation_implications if species else None,
                            max_field_len=self._max_field_len,
                        )
                        system = system + "\n\n" + section
                    messages = build_chat_messages(
                        system,
                        history,
                        job.message_id,
                        job.prompt,
                        max_turns=self._max_turns,
                        max_field_len=self._max_field_len,
                    )
                    if self._world_store is not None and self._world_budget > 0:
                        messages = self._inject_world(messages, job)
                    logger.info(
                        "prompt.built",
                        extra={
                            "session_id": job.session_id,
                            "message_id": job.message_id,
                            "history_count": len(messages) - 2,
                            "message_count": len(messages),
                            "character": character is not None,
                            "species_resolved": species_resolved,
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

    def _inject_world(
        self, messages: list[dict[str, str]], job: InferenceJob
    ) -> list[dict[str, str]]:
        """Append the canon world section to the system message (SPEC-0015 WP-6). Fail-soft."""
        try:
            entities = self._world_store.list_entities(job.session_id)
        except Exception:
            logger.warning(
                "world.unavailable",
                extra={"session_id": job.session_id, "message_id": job.message_id},
            )
            entities = []
        selected = select_world_entities(
            entities, [m["content"] for m in messages[1:]], self._world_budget
        )
        section = build_world_section(selected)
        if not section:
            return messages
        messages[0] = {"role": "system", "content": messages[0]["content"] + "\n\n" + section}
        logger.info(
            "world.injected",
            extra={
                "session_id": job.session_id,
                "message_id": job.message_id,
                "candidates": len(entities),
                "selected": len(selected),
            },
        )
        return messages

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
            status="completed",
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
