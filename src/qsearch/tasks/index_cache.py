"""Process-local SearchEngine cache with idle-time eviction."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from qsearch.webui.search_engine import SearchEngine

logger = logging.getLogger(__name__)

INDEX_IDLE_TTL_SECONDS = 30 * 60


@dataclass
class _Entry:
    resources: tuple
    engines: dict[str, SearchEngine]
    last_used_at: float
    active_users: int = 0


class _SynchronizedExtractor:
    """Serialize access to a shared predictor that may not be thread-safe."""

    def __init__(self, extractor) -> None:
        self._extractor = extractor
        self._lock = threading.Lock()

    def extract(self, image_path):
        with self._lock:
            return self._extractor.extract(image_path)

    def extract_batch(self, image_paths, **kwargs):
        with self._lock:
            return self._extractor.extract_batch(image_paths, **kwargs)


class SearchEngineCache:
    """Keep loaded search indices until they have been idle for 30 minutes."""

    def __init__(
        self,
        idle_ttl_seconds: float = INDEX_IDLE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        engine_factory: Callable[..., SearchEngine] = SearchEngine,
        extractor_factory: Callable[[dict], object] | None = None,
    ) -> None:
        self.idle_ttl_seconds = float(idle_ttl_seconds)
        self._clock = clock
        self._engine_factory = engine_factory
        self._extractor_factory = extractor_factory or self._create_extractor
        self._entries: dict[str, _Entry] = {}
        # Engines own the strong references. Once all engines using a model are
        # evicted, the weak cache drops it automatically as well.
        self._extractors: weakref.WeakValueDictionary[
            str, _SynchronizedExtractor
        ] = weakref.WeakValueDictionary()
        self._lock = threading.RLock()

    @contextmanager
    def acquire(
        self,
        database_path: Path,
        config: dict,
        load_feature_extractor: bool = False,
    ) -> Iterator[SearchEngine]:
        """Lease an engine; active leases are never evicted."""
        key = self._cache_key(database_path, config)
        engine_key = self._engine_key(config, load_feature_extractor)
        now = self._clock()

        with self._lock:
            self._evict_idle_locked(now)
            shared_extractor = (
                self._get_extractor(config) if load_feature_extractor else None
            )
            entry = self._entries.get(key)
            if entry is None:
                engine = self._engine_factory(
                    Path(database_path),
                    config=config,
                    load_feature_extractor=False,
                    feature_extractor=shared_extractor,
                )
                entry = _Entry(
                    resources=engine.index_resources,
                    engines={engine_key: engine},
                    last_used_at=now,
                )
                self._entries[key] = entry
                logger.info("索引缓存未命中，已加载：%s", database_path)
            else:
                logger.info("命中索引缓存：%s", database_path)
                engine = entry.engines.get(engine_key)
                if engine is None:
                    engine = self._engine_factory(
                        Path(database_path),
                        config=config,
                        load_feature_extractor=False,
                        index_resources=entry.resources,
                        feature_extractor=shared_extractor,
                    )
                    entry.engines[engine_key] = engine
            entry.active_users += 1

        try:
            yield engine
        finally:
            with self._lock:
                entry.active_users = max(0, entry.active_users - 1)
                entry.last_used_at = self._clock()

    def evict_idle(self) -> int:
        """Release entries unused for at least the configured idle TTL."""
        with self._lock:
            return self._evict_idle_locked(self._clock())

    def close(self) -> None:
        """Release all engines during scheduler shutdown."""
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
        for entry in entries:
            self._close_entry(entry)
        self._extractors.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _evict_idle_locked(self, now: float) -> int:
        expired = [
            key
            for key, entry in self._entries.items()
            if entry.active_users == 0
            and now - entry.last_used_at >= self.idle_ttl_seconds
        ]
        for key in expired:
            entry = self._entries.pop(key)
            self._close_entry(entry)
            logger.info("索引空闲超过 30 分钟，已释放：%s", key)
        return len(expired)

    @classmethod
    def _close_entry(cls, entry: _Entry) -> None:
        for engine in entry.engines.values():
            cls._close_engine(engine)
        entry.engines.clear()
        entry.resources = ()

    @staticmethod
    def _close_engine(engine: SearchEngine) -> None:
        close = getattr(engine, "close", None)
        if callable(close):
            try:
                close()
            except Exception as exc:
                logger.warning("释放索引缓存时出错：%s", exc)

    def _get_extractor(self, config: dict) -> _SynchronizedExtractor:
        model_key = self._model_key(config)
        extractor = self._extractors.get(model_key)
        if extractor is None:
            extractor = _SynchronizedExtractor(self._extractor_factory(config))
            self._extractors[model_key] = extractor
            logger.info("模型缓存未命中，已加载：%s", model_key)
        else:
            logger.info("命中模型缓存：%s", model_key)
        return extractor

    @staticmethod
    def _create_extractor(config: dict):
        from qsearch.features.feature_extractor import FeatureExtractor

        return FeatureExtractor(config)

    @staticmethod
    def _model_key(config: dict) -> str:
        payload = {
            "text": config.get("text", {}),
            "image": config.get("image", {}),
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @staticmethod
    def _cache_key(database_path: Path, config: dict) -> str:
        resolved = Path(database_path).resolve()
        index_dir = resolved / "index"
        files = (
            "features.pkl",
            "text_index.faiss",
            "text_index_ids.pkl",
            "hash_index.pkl",
        )
        fingerprint = []
        for name in files:
            path = index_dir / name
            try:
                stat = path.stat()
                fingerprint.append((name, stat.st_mtime_ns, stat.st_size))
            except OSError:
                fingerprint.append((name, None, None))

        payload = {
            "database_path": str(resolved),
            "index_config": config.get("index", {}),
            "index_fingerprint": fingerprint,
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @staticmethod
    def _engine_key(config: dict, load_feature_extractor: bool) -> str:
        payload = {
            "config": config,
            "load_feature_extractor": load_feature_extractor,
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
