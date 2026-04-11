"""ProjectIndex — unified access to a project's cache, FTS, symbols, and graph."""

from libs.project_index.index import ProjectIndex, ProjectNotIndexedError

__all__ = ["ProjectIndex", "ProjectNotIndexedError"]
