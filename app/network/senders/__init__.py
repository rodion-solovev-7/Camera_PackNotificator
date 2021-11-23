"""
Обёртки для отправки данных в различные источники
"""

from ._senders import *

__all__ = [
    'BaseApi',
    'EmptyLoggingApi',
    'ApiWithoutSpawnAndConfiscation',
]
