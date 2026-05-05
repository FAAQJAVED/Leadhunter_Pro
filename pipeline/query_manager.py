"""
pipeline.query_manager — Query loading, deduplication, and progress tracking.
"""

from __future__ import annotations

import csv
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from config import CHECKPOINT_FILE, CHECKPOINT_DIR, CHECKPOINT_EVERY

logger = logging.getLogger('lead_engine.query_manager')


class QueryManager:
    """
    Loads queries from:
      1. A plain-text file  (one query per line)
      2. A CSV column       (specify column name or index)
      3. A --query CLI arg  (single query injected at runtime)

    Tracks completed queries and emits only pending ones.
    Persists state to the checkpoint system (via CheckpointStore).
    """

    def __init__(self, checkpoint: 'CheckpointStore') -> None:
        self._checkpoint = checkpoint
        self._all_queries: list[str] = []

    def load_from_file(self, filepath: str) -> None:
        """Load queries from a plain-text file (one per line)."""
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Query file not found: {filepath}")
        lines = path.read_text(encoding='utf-8').splitlines()
        queries = [ln.strip() for ln in lines if ln.strip()
                   and not ln.strip().startswith('#')]
        logger.info("Loaded %d queries from %s", len(queries), filepath)
        self._add(queries)

    def load_from_csv(self, filepath: str, column: str | int = 0) -> None:
        """
        Load queries from a CSV file.

        :param filepath: path to the CSV
        :param column:   column header name (str) or 0-based index (int)
        """
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {filepath}")
        queries: list[str] = []
        with open(path, encoding='utf-8-sig', newline='') as fh:
            reader = csv.DictReader(fh)
            if isinstance(column, int):
                fieldnames = reader.fieldnames or []
                if column >= len(fieldnames):
                    raise ValueError(f"CSV has no column at index {column}")
                col_name = fieldnames[column]
            else:
                col_name = column
            for row in reader:
                val = row.get(col_name, '').strip()
                if val:
                    queries.append(val)
        logger.info("Loaded %d queries from CSV column '%s'", len(queries), col_name)
        self._add(queries)

    def add_single(self, query: str) -> None:
        """Add a single query (from --query CLI arg)."""
        q = query.strip()
        if q:
            self._add([q])
            logger.info("Single query added: '%s'", q)

    def pending(self) -> list[str]:
        """Return queries not yet completed."""
        done = self._checkpoint.completed_queries
        return [q for q in self._all_queries if q not in done]

    def total(self) -> int:
        return len(self._all_queries)

    def done_count(self) -> int:
        return len(self._checkpoint.completed_queries)

    def mark_done(self, query: str) -> None:
        """Record a query as completed in the checkpoint."""
        self._checkpoint.completed_queries.add(query)

    def report(self) -> str:
        """Human-readable progress string."""
        done  = self.done_count()
        total = self.total()
        pct   = (done / total * 100) if total else 0
        return f"{done}/{total} queries done ({pct:.1f}%)"

    def _add(self, queries: list[str]) -> None:
        seen = set(self._all_queries)
        for q in queries:
            if q not in seen:
                self._all_queries.append(q)
                seen.add(q)


class CheckpointStore:
    """
    Persists scraper progress to a JSON file.

    Structure:
    {
        "completed_queries": [...],
        "collected_domains": [...],
        "record_count": 123,
        "last_saved": "2024-01-01T14:32:00Z"
    }

    Writes are atomic: temp file → rename.
    """

    def __init__(self) -> None:
        os.makedirs(CHECKPOINT_DIR, exist_ok=True)
        self.filepath = Path(CHECKPOINT_FILE)
        self.completed_queries: set[str] = set()
        self.collected_domains: set[str] = set()
        self.record_count: int = 0
        self._records_since_save: int = 0

    def load(self) -> bool:
        """Load checkpoint from disk. Returns True if checkpoint existed."""
        if not self.filepath.exists():
            return False
        try:
            data = json.loads(self.filepath.read_text(encoding='utf-8'))
            self.completed_queries = set(data.get('completed_queries', []))
            self.collected_domains = set(data.get('collected_domains', []))
            self.record_count = int(data.get('record_count', 0))
            logger.info("Checkpoint loaded: %d queries done, %d domains, "
                        "%d records", len(self.completed_queries),
                        len(self.collected_domains), self.record_count)
            return True
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.error("Checkpoint corrupt: %s — starting fresh", exc)
            return False

    def save(self) -> None:
        """Atomically write checkpoint to disk."""
        data = {
            'completed_queries': sorted(self.completed_queries),
            'collected_domains': sorted(self.collected_domains),
            'record_count': self.record_count,
            'last_saved': datetime.now(timezone.utc).isoformat(),
        }
        tmp = self.filepath.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                       encoding='utf-8')
        tmp.replace(self.filepath)
        logger.debug("Checkpoint saved (%d records)", self.record_count)

    def on_records_added(self, count: int = 1) -> None:
        """Call after adding records. Auto-saves every CHECKPOINT_EVERY."""
        self.record_count += count
        self._records_since_save += count
        if self._records_since_save >= CHECKPOINT_EVERY:
            self.save()
            self._records_since_save = 0

    def domain_seen(self, domain: str) -> bool:
        return domain in self.collected_domains

    def add_domain(self, domain: str) -> None:
        self.collected_domains.add(domain)

    def ask_resume(self) -> bool:
        """
        Prompt the user to resume or start fresh.
        Returns True = resume, False = start fresh.
        """
        print("\n" + "=" * 60)
        print("  ⚠  CHECKPOINT FOUND")
        print(f"     Queries done : {len(self.completed_queries)}")
        print(f"     Domains found: {len(self.collected_domains)}")
        print(f"     Records      : {self.record_count}")
        print("=" * 60)
        while True:
            ans = input("  Resume from checkpoint? (Y/N): ").strip().upper()
            if ans in ('Y', 'N'):
                return ans == 'Y'
            print("  Please enter Y or N.")

    def reset(self) -> None:
        """Clear all state and delete checkpoint file."""
        self.completed_queries.clear()
        self.collected_domains.clear()
        self.record_count = 0
        self._records_since_save = 0
        if self.filepath.exists():
            self.filepath.unlink()
        logger.info("Checkpoint cleared — starting fresh")
