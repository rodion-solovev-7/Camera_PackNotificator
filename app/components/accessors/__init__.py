"""
Обёртки, предоставляющие доступ к актуальным данным:
например, режиму работы, регулярно получаемому с сервера.
"""

from ._accessors import *

__all__ = [
    'BaseAccessor',
    'BackendAccessor',
    'ImmutableAccessor',
]
