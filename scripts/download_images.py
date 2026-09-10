"""Download question images referenced in a JSONL dataset into a zip archive.

Reads a JSONL file where each line has "page_id" and "page_url", downloads each
image, and streams it into a sharded zip store that survives hard interruption.

Design notes
------------
A zip file keeps its central directory only at the end of the file, so an
append-per-image scheme rewrites that directory once per image and a kill in
that window destroys the whole archive. Instead this script writes a directory
of bounded shards (part-00000.zip, ...). Each shard is closed cleanly once
full, so completed shards are permanently safe and a crash can only damage the
single shard being written -- which is then salvaged on the next run by
scanning its local file headers.

Resume state is derived from the shards themselves rather than a side-car
progress log, so the recorded progress can never disagree with the archive
contents. Shards are merged into one .zip at the end.
"""

import argparse
import logging
import queue
import shutil
import struct
import threading
import zlib
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Iterator, Optional
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

import requests
from requests.adapters import HTTPAdapter
from tqdm import tqdm
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15
DEFAULT_RETRIES = 3
DEFAULT_POOL_CONNECTIONS = 10
DEFAULT_POOL_MAXSIZE = 20
DEFAULT_SHARD_SIZE = 2000
DEFAULT_QUEUE_SIZE = 64
DEFAULT_WINDOW_FACTOR = 4

LOCAL_HEADER_SIG = b'PK\x03\x04'
LOCAL_HEADER_LEN = 30
COPY_CHUNK = 1 << 20

def create_session(pool_connections: int, pool_maxsize: int, retries: int) -> requests.Session:
    """Create a requests session with connection pooling and retry strategy.

    Args:
        pool_connections: Number of connection pools to cache.
        pool_maxsize: Maximum number of connections to save in the pool.
        retries: Number of retry attempts on failure.

    Returns:
        Configured requests Session with connection pooling.
    """
    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=['GET', 'HEAD'],
    )
    adapter = HTTPAdapter(
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize,
        max_retries=retry_strategy,
    )
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    return session


def iter_entries(json_path: Path) -> Iterator[dict]:
    """Yield page_id/page_url entries from a JSONL file one at a time.

    Streaming keeps peak memory independent of the input size, which matters for
    inputs in the hundreds of thousands of lines.

    Args:
        json_path: Path to the JSONL file.

    Yields:
        Parsed entry dicts, skipping blank and malformed lines.
    """
    import json as _json

    with open(json_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield _json.loads(line)
            except ValueError as e:
                logger.warning(f"Skipping malformed JSON on line {line_num}: {e}")


def get_extension(url: str) -> str:
    """Derive a file extension from the URL, defaulting to .jpg."""
    suffix = Path(url).suffix
    return suffix if suffix else '.jpg'


def salvage_shard(shard_path: Path) -> int:
    """Rebuild a shard whose central directory is missing or truncated.

    Walks the local file headers, which are written immediately before each
    entry's data, and keeps every entry whose compressed payload is complete and
    passes its stored CRC. The shard is replaced atomically so an interruption
    during salvage leaves the original intact.

    Args:
        shard_path: Path to the damaged shard.

    Returns:
        Number of entries recovered into the rewritten shard.
    """
    raw = shard_path.read_bytes()
    recovered: list[tuple[str, bytes]] = []
    offset = 0

    while True:
        offset = raw.find(LOCAL_HEADER_SIG, offset)
        if offset < 0 or offset + LOCAL_HEADER_LEN > len(raw):
            break

        header = raw[offset:offset + LOCAL_HEADER_LEN]
        flags, method, _, _, crc, comp_size, _, name_len, extra_len = struct.unpack(
            '<HHHHIIIHH', header[6:30]
        )
        name_start = offset + LOCAL_HEADER_LEN
        data_start = name_start + name_len + extra_len

        # A streamed entry defers its sizes to a trailing data descriptor, so the
        # header length is unusable. This writer never streams, so skip those.
        if flags & 0x08 or comp_size == 0 or data_start + comp_size > len(raw):
            offset += 4
            continue

        name = raw[name_start:name_start + name_len].decode('utf-8', 'replace')
        payload = raw[data_start:data_start + comp_size]

        try:
            data = zlib.decompress(payload, -15) if method == ZIP_DEFLATED else payload
        except zlib.error:
            offset = data_start
            continue

        if zlib.crc32(data) & 0xFFFFFFFF == crc:
            recovered.append((name, data))

        offset = data_start + comp_size

    temp_path = shard_path.with_suffix('.salvage')
    with ZipFile(temp_path, 'w', compression=ZIP_DEFLATED) as zf:
        for name, data in recovered:
            zf.writestr(name, data)
    temp_path.replace(shard_path)
    return len(recovered)


def scan_store(store_dir: Path) -> tuple[set[str], int]:
    """Read completed page_ids from the shard store, repairing the last shard.

    The shard contents are the single source of truth for resume state. Only the
    most recent shard can be damaged, since every earlier one was closed cleanly
    before the next was opened.

    Args:
        store_dir: Directory holding part-*.zip shards.

    Returns:
        Tuple of (set of completed page_ids, next shard index to write).
    """
    if not store_dir.exists():
        return set(), 0

    shards = sorted(store_dir.glob('part-*.zip'))
    for stale in store_dir.glob('part-*.salvage'):
        stale.unlink()

    done: set[str] = set()
    for shard in shards:
        try:
            with ZipFile(shard) as zf:
                names = zf.namelist()
        except (BadZipFile, OSError):
            logger.warning(f"Shard {shard.name} is damaged, salvaging entries")
            count = salvage_shard(shard)
            logger.info(f"Recovered {count} entries from {shard.name}")
            with ZipFile(shard) as zf:
                names = zf.namelist()
        done.update(Path(name).stem for name in names)

    next_index = int(shards[-1].stem.split('-')[1]) + 1 if shards else 0
    return done, next_index

class ShardWriter:
    """Single-threaded writer that appends entries to bounded, rolling shards.

    One thread owns the open zip handle for a shard's whole lifetime, so the
    central directory is written exactly once per shard instead of once per
    image. Work arrives over a bounded queue, which caps how many downloaded
    payloads can be in flight regardless of how many images remain.
    """

    def __init__(self, store_dir: Path, start_index: int, shard_size: int, queue_size: int):
        self._store_dir = store_dir
        self._shard_size = shard_size
        self._index = start_index
        self._queue: queue.Queue[Optional[tuple[str, bytes]]] = queue.Queue(maxsize=queue_size)
        self._zf: Optional[ZipFile] = None
        self._in_shard = 0
        self._written = 0
        self._error: Optional[BaseException] = None
        self._thread = threading.Thread(target=self._run, name='shard-writer', daemon=True)

    @property
    def written(self) -> int:
        """Number of entries committed to shards."""
        return self._written

    def start(self) -> None:
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._thread.start()

    def submit(self, name: str, data: bytes) -> None:
        """Hand an entry to the writer, blocking while the queue is full.

        Blocking is the backpressure mechanism: downloads cannot outrun the
        writer and accumulate in memory.
        """
        if self._error:
            raise self._error
        self._queue.put((name, data))

    def close(self) -> None:
        """Drain the queue, close the open shard, and surface writer errors."""
        self._queue.put(None)
        self._thread.join()
        if self._error:
            raise self._error

    def _run(self) -> None:
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    break
                self._write(*item)
        except BaseException as e:  # noqa: BLE001 - re-raised on the main thread
            self._error = e
        finally:
            self._close_shard()

    def _write(self, name: str, data: bytes) -> None:
        if self._zf is None:
            path = self._store_dir / f"part-{self._index:05d}.zip"
            self._zf = ZipFile(path, 'w', compression=ZIP_DEFLATED)
            self._in_shard = 0
        self._zf.writestr(name, data)
        self._in_shard += 1
        self._written += 1
        if self._in_shard >= self._shard_size:
            self._close_shard()
            self._index += 1

    def _close_shard(self) -> None:
        if self._zf is not None:
            self._zf.close()
            self._zf = None


def download_image(
    entry: dict,
    session: requests.Session,
    timeout: int,
) -> tuple[str, Optional[bytes], str]:
    """Download a single image into memory.

    Args:
        entry: Dict with "page_id" and "page_url".
        session: Requests session with connection pooling.
        timeout: Per-request timeout in seconds.

    Returns:
        Tuple of (name, image_bytes_or_None, message). The name carries the
        extension so the writer needs no knowledge of the source URL.
    """
    page_id = entry.get('page_id')
    page_url = entry.get('page_url')

    if not page_id or not page_url:
        return str(page_id or '<unknown>'), None, 'Missing page_id or page_url'

    name = f"{page_id}{get_extension(page_url)}"
    try:
        response = session.get(page_url, timeout=timeout)
        response.raise_for_status()
        return name, response.content, 'Downloaded'
    except requests.exceptions.RequestException as e:
        return name, None, str(e)

def run_downloads(
    entries: Iterator[dict],
    session: requests.Session,
    writer: ShardWriter,
    workers: int,
    timeout: int,
    window: int,
    pbar: tqdm,
) -> list[tuple[str, str]]:
    """Download entries with a sliding submission window.

    Only `window` tasks are ever pending, so neither the executor queue nor the
    set of completed-but-unconsumed futures grows with the input size.

    Args:
        entries: Iterator of pending entry dicts.
        session: Requests session with connection pooling.
        writer: Shard writer receiving successful payloads.
        workers: Number of concurrent download threads.
        timeout: Per-request timeout in seconds.
        window: Maximum number of in-flight download tasks.
        pbar: Progress bar advanced once per finished entry.

    Returns:
        List of (name, error_message) for entries that failed.
    """
    failed: list[tuple[str, str]] = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending: set = set()
        exhausted = False

        while True:
            while not exhausted and len(pending) < window:
                entry = next(entries, None)
                if entry is None:
                    exhausted = True
                    break
                pending.add(executor.submit(download_image, entry, session, timeout))

            if not pending:
                break

            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                name, data, message = future.result()
                if data is None:
                    failed.append((name, message))
                else:
                    writer.submit(name, data)
                pbar.update(1)

    return failed


def merge_shards(store_dir: Path, output_zip: Path) -> int:
    """Merge every shard into a single zip archive.

    Entries are copied compressed-as-is, so merging neither re-compresses nor
    holds more than one entry in memory. The archive is built beside the target
    and moved into place, so an interrupted merge cannot leave a partial file at
    the output path.

    Args:
        store_dir: Directory holding part-*.zip shards.
        output_zip: Destination archive path.

    Returns:
        Number of entries written to the merged archive.
    """
    shards = sorted(store_dir.glob('part-*.zip'))
    if not shards:
        return 0

    temp_path = output_zip.with_suffix('.merging')
    seen: set[str] = set()
    total = 0

    with ZipFile(temp_path, 'w', compression=ZIP_DEFLATED) as out:
        for shard in tqdm(shards, desc='Merging shards', unit='shard'):
            with ZipFile(shard) as src:
                for info in src.infolist():
                    if info.filename in seen:
                        continue
                    seen.add(info.filename)
                    with src.open(info) as reader, out.open(info, 'w') as target:
                        shutil.copyfileobj(reader, target, COPY_CHUNK)
                    total += 1

    temp_path.replace(output_zip)
    return total

def main():
    parser = argparse.ArgumentParser(
        description='Download images from a JSONL dataset into a resumable zip archive'
    )
    parser.add_argument('--input', type=str, default='data/test.json', help='Path to input JSONL file')
    parser.add_argument('--output-zip', type=str, default='data/images.zip', help='Path to output zip file')
    parser.add_argument('--workers', type=int, default=8, help='Number of concurrent download workers')
    parser.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT, help='Per-request timeout in seconds')
    parser.add_argument('--retries', type=int, default=DEFAULT_RETRIES, help='Retry attempts per image')
    parser.add_argument('--pool-connections', type=int, default=DEFAULT_POOL_CONNECTIONS,
                        help='Number of connection pools to cache')
    parser.add_argument('--pool-maxsize', type=int, default=DEFAULT_POOL_MAXSIZE,
                        help='Maximum connections per pool')
    parser.add_argument('--shard-size', type=int, default=DEFAULT_SHARD_SIZE,
                        help='Images per shard; a crash can only affect the open shard')
    parser.add_argument('--queue-size', type=int, default=DEFAULT_QUEUE_SIZE,
                        help='Max downloaded images buffered for the writer (caps memory)')
    parser.add_argument('--restart', action='store_true',
                        help='Discard the existing shard store and start over')
    parser.add_argument('--merge', action='store_true',
                        help='Merge shards into the output zip and exit without downloading')
    parser.add_argument('--no-merge', action='store_true',
                        help='Leave shards unmerged after downloading')

    args = parser.parse_args()

    input_path = Path(args.input)
    output_zip = Path(args.output_zip)
    store_dir = Path(f"{output_zip}.d")

    if args.merge:
        total = merge_shards(store_dir, output_zip)
        if total:
            logger.info(f"Merged {total} images into {output_zip}")
        else:
            logger.warning(f"No shards found in {store_dir}")
        return

    if args.restart and store_dir.exists():
        logger.info(f"Discarding shard store {store_dir}")
        shutil.rmtree(store_dir)

    # Retire the pre-shard progress log; shard contents are now authoritative.
    legacy_progress = output_zip.with_suffix('.progress')
    if legacy_progress.exists():
        legacy_progress.unlink()

    done, next_index = scan_store(store_dir)
    if done:
        logger.info(f"Resuming with {len(done)} images already stored")

    total_entries = 0
    pending: list[dict] = []
    for entry in iter_entries(input_path):
        total_entries += 1
        if str(entry.get('page_id')) not in done:
            pending.append(entry)

    logger.info(f"{total_entries} entries in {input_path}, {len(pending)} left to download")
    if not pending:
        if not args.no_merge:
            total = merge_shards(store_dir, output_zip)
            logger.info(f"Merged {total} images into {output_zip}")
        return

    session = create_session(args.pool_connections, args.pool_maxsize, args.retries)
    writer = ShardWriter(store_dir, next_index, args.shard_size, args.queue_size)
    writer.start()
    window = max(args.workers * DEFAULT_WINDOW_FACTOR, args.workers + 1)

    failed: list[tuple[str, str]] = []
    interrupted = False
    try:
        with tqdm(total=len(pending), desc='Downloading', unit='img') as pbar:
            failed = run_downloads(
                iter(pending), session, writer, args.workers, args.timeout, window, pbar
            )
    except KeyboardInterrupt:
        interrupted = True
        logger.warning('Interrupted; closing the open shard')
    finally:
        writer.close()
        session.close()

    logger.info(f"Stored {writer.written} images this run, {len(failed)} failed")
    for name, message in failed[:20]:
        logger.error(f"Failed {name}: {message}")
    if len(failed) > 20:
        logger.error(f"...and {len(failed) - 20} more failures")

    if interrupted:
        logger.info('Re-run the same command to resume')
        return

    if not args.no_merge:
        total = merge_shards(store_dir, output_zip)
        logger.info(f"Merged {total} images into {output_zip}")


if __name__ == '__main__':
    main()
