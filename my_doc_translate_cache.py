#!/usr/bin/env python3


import sqlitedict
import threading
import lzma
import pickle
import hashlib
import time


# Constants for database and table names
DB_FILE = "db/translate_cache.db"
TABLE_NAME = "translations"
MAX_SIZE = 100


class TextCache:
    def __init__(self, file_path: str = DB_FILE, max_size: int = MAX_SIZE):
        """
        Initialize the text cache using sqlitedict with lzma compression.
        :param file_path: Path to the SQLite database file.
        :param max_size: Maximum number of cache entries.
        """
        self.file_path: str = file_path
        self.max_size: int = max_size
        self.lock: threading.Lock = threading.Lock()
        # Use a custom encode/decode function for lzma compression
        self.db: sqlitedict.SqliteDict = sqlitedict.SqliteDict(
            self.file_path,
            tablename=TABLE_NAME,
            autocommit=True,
            encode=self._encode,
            decode=self._decode
        )

    def _encode(self, obj: dict) -> bytes:
        """
        Encode the object using pickle and compress it with lzma.

        Args:
          obj: The object to encode.

        Returns:
          The compressed byte string.
        """
        return lzma.compress(pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL), preset=lzma.PRESET_EXTREME)

    def _decode(self, data: bytes) -> dict:
        """
        Decompress the data with lzma and decode it using pickle.

        Args:
          data: The compressed byte string.

        Returns:
          The decoded object.
        """
        return pickle.loads(lzma.decompress(data))

    def _text_hash(self, text: str) -> str:
        """
        Generate a SHA-256 hash of the given text.

        Args:
          text: The text to hash.

        Returns:
          The hexadecimal representation of the SHA-256 hash.
        """
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def __len__(self) -> int:
        """Return the number of items in the cache."""
        with self.lock:
            return len(self.db)

    def __contains__(self, text: str) -> bool:
        """Check if a text translation exists in the cache using 'in' operator."""
        text_hash: str = self._text_hash(text)
        with self.lock:
            return text_hash in self.db

    def __getitem__(self, text: str) -> str:
        """Retrieve a translation using dictionary-style access."""
        text_hash: str = self._text_hash(text)
        with self.lock:
            return self.db.get(text_hash, {}).get("translation", "")

    def __setitem__(self, text: str, value: tuple[str, str]) -> None:
        """Add or update a text translation using dictionary-style assignment."""
        owner, translation = value
        self.add(owner, text, translation)

    def __delitem__(self, text: str) -> None:
        """Remove a text translation from the cache using 'del'."""
        text_hash: str = self._text_hash(text)
        with self.lock:
            if text_hash in self.db:
                del self.db[text_hash]

    def add(self, owner: str, text: str, translation: str) -> None:
        """Add or update a text translation in the cache."""
        text_hash: str = self._text_hash(text)
        timestamp: int = time.perf_counter_ns()
        with self.lock:
            if len(self.db) >= self.max_size:
                # Remove the oldest entries
                oldest_keys = sorted(self.db, key=lambda k: self.db[k].get("timestamp", 0))
                for key in oldest_keys[:len(self.db) - self.max_size + 1]:
                    del self.db[key]

            self.db[text_hash] = {"translation": translation, "owner": owner, "timestamp": timestamp}

    def exists(self, text: str) -> bool:
        """Check if a text translation exists in the cache."""
        text_hash: str = self._text_hash(text)
        with self.lock:
            return text_hash in self.db

    def remove_by_owner(self, owner: str) -> None:
        """Remove all translations associated with a specific owner."""
        with self.lock:
            keys_to_remove = [k for k, v in self.db.items() if v.get("owner") == owner]
            for key in keys_to_remove:
                del self.db[key]


if __name__ == "__main__":
    cache = TextCache(max_size=3)
    cache.add("user1", "hello", "привет")
    cache.add("user1", "world", "мир")
    cache.add("user1", "dog", "собака")
    # Now the cache is full, adding a new entry should remove the oldest one ("hello")
    cache.add("user1", "cat", "кошка")

    assert not cache.exists("hello")  # "hello" should be removed
    assert cache.exists("world")
    assert cache.exists("dog")
    assert cache.exists("cat")

    #add general tests
    cache = TextCache()
    cache.add("user1", "hello", "привет")
    assert cache.exists("hello")
    assert cache["hello"] == "привет"
    cache["hello"] = ("user2", "здравствуйте")
    assert cache["hello"] == "здравствуйте"
    del cache["hello"]
    assert not cache.exists("hello")
    cache.add("user3", "bye", "пока")
    cache.remove_by_owner("user3")
    assert not cache.exists("bye")
    print("All tests passed.")
