from dataclasses import dataclass
from pympler import asizeof
from contextlib import contextmanager

@dataclass
class _MemoryValue:
    memory_use: int
    value: any

class MemoryController:
    def __init__(self, memory_size_bytes: int):
        self.memory_limit = memory_size_bytes
        self.current_memory_use = 0
        self.memory: dict[str, _MemoryValue] = {}

    #if the retrieved mutable value (like list) is modified, update_memory_use must be called
    def __getitem__(self, key: str):
        if not key in self.memory:
            raise IndexError(f"Cannot get unitializes variable '{key}'")
        return self.memory[key].value

    def __setitem__(self, key: str, value):
        if not key in self.memory:
            raise IndexError(f"Cannot set unitializes variable '{key}', use allocate_variable first")
        self.memory[key].value = value
        self.update_memory_use(key)

    def _ensure_capacity(self):
        if self.current_memory_use > self.memory_limit:
            raise MemoryError("Memory controller ran out of usable memory")

    def update_memory_use(self, key: str):
        entry = self.memory[key]
        new_size = asizeof.asizeof(entry.value)
        self.current_memory_use += new_size - entry.memory_use
        self._ensure_capacity()
        entry.memory_use = new_size

    def allocate_variable(self, key: str, value):
        if key in self.memory:
            raise IndexError(f"Cannot allocate '{key}' variable that already exists")
        size = asizeof.asizeof(value)
        self.memory[key] = _MemoryValue(size, value)
        self.current_memory_use += size + len(key)
        self._ensure_capacity()

    def allocate_empty_variables(self, *keys):
        for key in keys:
            self.allocate_variable(key, None)

    def deallocate_variable(self, key: str):
        if not key in self.memory:
            raise IndexError(f"Variable '{key}' not found")
        self.current_memory_use -= len(key) + self.memory[key].memory_use
        del self.memory[key]

    def deallocate_variables(self, *keys):
        for key in keys:
            self.deallocate_variable(key)

    #automatically deallocates the variable when the 'with' statement closes
    @contextmanager
    def auto_alloc(self, key: str, value):
        try:
            self.allocate_variable(key, value)
            yield None
        finally:
            self.deallocate_variable(key)

    #automatically allocates multiple variables defined with pairs of keys and values
    @contextmanager
    def auto_alloc_multiple(self, *pairs: tuple[str, any]):
        try:
            for key, value in pairs:
                self.allocate_variable(key, value)
            yield None
        finally:
            for key, value in pairs:
                self.deallocate_variable(key, value)

    #use 'with' statement to simulate allocation for the duration of the statement
    @contextmanager
    def temp_alloc(self, size: int):
        try:
            self.current_memory_use += size
            self._ensure_capacity()
            yield None #wait until 'with' is closed
        finally:
            self.current_memory_use -= size
