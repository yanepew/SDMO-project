from dataclasses import dataclass
from pympler import asizeof
from contextlib import contextmanager

@dataclass
class _MemoryValue:
    memory_use: int
    value: any

class MemoryController:
    def __init__(self, memory_size_bytes: int, count_labels: bool):
        self._memory_limit = memory_size_bytes
        self._count_labels = count_labels
        self._current_memory_use = 0
        self._max_memory_use_so_far = 0
        self._memory: dict[str, _MemoryValue] = {}

    #if the retrieved mutable value (like list) is modified, update_memory_use must be called
    def __getitem__(self, key: str):
        if not key in self._memory:
            raise IndexError(f"Cannot get unitializes variable '{key}'")
        return self._memory[key].value

    def __setitem__(self, key: str, value):
        if not key in self._memory:
            raise IndexError(f"Cannot set unitializes variable '{key}', use allocate_variable first")
        self._memory[key].value = value
        self.update_memory_use(key)

    def get_max_memory_use_thus_far(self):
        return self._max_memory_use_so_far

    def _ensure_capacity(self):
        if self._current_memory_use > self._max_memory_use_so_far:
            self._max_memory_use_so_far = self._current_memory_use
        if self._current_memory_use > self._memory_limit:
            raise MemoryError("Memory controller ran out of usable memory")

    def update_memory_use(self, key: str):
        entry = self._memory[key]
        new_size = asizeof.asizeof(entry.value)
        self._current_memory_use += new_size - entry.memory_use
        self._ensure_capacity()
        entry.memory_use = new_size

    def alloc_var(self, key: str, value):
        if key in self._memory:
            raise IndexError(f"Cannot allocate '{key}' variable that already exists")
        size = asizeof.asizeof(value)
        self._memory[key] = _MemoryValue(size, value)
        self._current_memory_use += size + (len(key) if self._count_labels else 0)
        self._ensure_capacity()

    def alloc_empty_vars(self, *keys):
        for key in keys:
            self.alloc_var(key, None)

    def dealloc_var(self, key: str):
        if not key in self._memory:
            raise IndexError(f"Variable '{key}' not found")
        self._current_memory_use -= (len(key) if self._count_labels else 0) + self._memory[key].memory_use
        del self._memory[key]

    def dealloc_vars(self, *keys):
        for key in keys:
            self.dealloc_var(key)

    #automatically deallocates the variable when the 'with' statement closes
    @contextmanager
    def auto_alloc(self, key: str, value):
        try:
            self.alloc_var(key, value)
            yield None
        finally:
            self.dealloc_var(key)

    #automatically allocates multiple variables defined with pairs of keys and values and deallocates after 'with'
    @contextmanager
    def auto_alloc_vars(self, *pairs: tuple[str, any]):
        try:
            for key, value in pairs:
                self.alloc_var(key, value)
            yield None
        finally:
            for key, _ in pairs:
                self.dealloc_var(key)

    #automatically allocates multiple empty variables and deallocates after 'with'
    @contextmanager
    def auto_alloc_empty_vars(self, *keys):
        try:
            self.alloc_empty_vars(*keys)
            yield None
        finally:
            self.dealloc_vars(*keys)

    #use 'with' statement to simulate allocation for the duration of the statement
    @contextmanager
    def temp_alloc(self, size: int):
        try:
            self._current_memory_use += size
            self._ensure_capacity()
            yield None #wait until 'with' is closed
        finally:
            self._current_memory_use -= size
