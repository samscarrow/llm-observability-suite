# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2025-09-20

Breaking changes:
- Default `service` name changed from `story-engine` to `llm-app` when `SERVICE_NAME` is not set. If your dashboards/alerts depend on the old value, set `SERVICE_NAME=story-engine` or pass `service=` to `get_logger`.
- Default log file path changed from `story_engine.log` to `app.log` when `LOG_DEST=file` and `LOG_FILE_PATH` is not provided.

Added:
- Test suite for structured logging, metrics via logs, and DB logging helpers.
- Expanded README with quick start, metrics usage, environment variables, DB examples, SQLite schema, and redaction guidance.

Changed:
- Minor docstrings/generalization (removed story-engine specific wording where applicable).

## [0.1.0] - 2025-09-20
- Initial release with core logging, metrics helpers, and DB logging shims.
