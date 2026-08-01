"""
Sistema de rastreamento de memória por módulo/componente
"""
import psutil
import time
import functools
import threading
from collections import defaultdict, deque
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class MemoryTracker:
    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.module_stats = defaultdict(lambda: {
            'calls': 0,
            'total_memory_before': 0,
            'total_memory_after': 0,
            'avg_memory_increase': 0,
            'max_memory_increase': 0,
            'history': deque(maxlen=max_history)
        })
        self.lock = threading.Lock()
        self.process = psutil.Process()

    def get_current_memory(self) -> float:
        """Retorna uso atual de memória em MB"""
        return self.process.memory_info().rss / 1024 / 1024

    def track_module(self, module_name: str):
        """Decorator para rastrear uso de memória de um módulo"""
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                memory_before = self.get_current_memory()
                start_time = time.time()

                try:
                    result = func(*args, **kwargs)
                    return result
                finally:
                    memory_after = self.get_current_memory()
                    execution_time = time.time() - start_time
                    memory_diff = memory_after - memory_before

                    with self.lock:
                        stats = self.module_stats[module_name]
                        stats['calls'] += 1
                        stats['total_memory_before'] += memory_before
                        stats['total_memory_after'] += memory_after

                        # Atualizar média
                        stats['avg_memory_increase'] = (
                            (stats['avg_memory_increase'] * (stats['calls'] - 1) + memory_diff) /
                            stats['calls']
                        )

                        # Atualizar máximo
                        if memory_diff > stats['max_memory_increase']:
                            stats['max_memory_increase'] = memory_diff

                        # Adicionar ao histórico
                        stats['history'].append({
                            'timestamp': time.time(),
                            'memory_before': memory_before,
                            'memory_after': memory_after,
                            'memory_diff': memory_diff,
                            'execution_time': execution_time
                        })

                        # Log se houver crescimento significativo
                        if memory_diff > 10:  # > 10MB
                            logger.warning(
                                f"[MemoryTracker] {module_name}: Crescimento de {memory_diff:.2f}MB "
                                f"({memory_before:.2f} -> {memory_after:.2f}MB)"
                            )

            return wrapper
        return decorator

    def get_module_stats(self, module_name: Optional[str] = None) -> Dict:
        """Retorna estatísticas de memória"""
        with self.lock:
            if module_name:
                return dict(self.module_stats.get(module_name, {}))
            else:
                return {name: dict(stats) for name, stats in self.module_stats.items()}

    def get_top_consumers(self, limit: int = 10) -> List[Dict]:
        """Retorna os módulos que mais consomem memória"""
        with self.lock:
            modules = []
            for name, stats in self.module_stats.items():
                if stats['calls'] > 0:
                    modules.append({
                        'module': name,
                        'avg_increase': stats['avg_memory_increase'],
                        'max_increase': stats['max_memory_increase'],
                        'total_calls': stats['calls'],
                        'total_memory_consumed': stats['avg_memory_increase'] * stats['calls']
                    })

            return sorted(modules, key=lambda x: x['total_memory_consumed'], reverse=True)[:limit]

    def reset_stats(self, module_name: Optional[str] = None):
        """Reseta estatísticas"""
        with self.lock:
            if module_name:
                if module_name in self.module_stats:
                    del self.module_stats[module_name]
            else:
                self.module_stats.clear()

# Instância global
memory_tracker = MemoryTracker()

# Decorators convenientes
def track_llm_memory(func):
    """Decorator para rastrear memória do LLM"""
    return memory_tracker.track_module('llm')(func)

def track_websocket_memory(func):
    """Decorator para rastrear memória do WebSocket"""
    return memory_tracker.track_module('websocket')(func)

def track_database_memory(func):
    """Decorator para rastrear memória do banco"""
    return memory_tracker.track_module('database')(func)

def track_worker_memory(func):
    """Decorator para rastrear memória dos workers"""
    return memory_tracker.track_module('worker')(func)