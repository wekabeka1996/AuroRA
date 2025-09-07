This document provides essential guidance for AI coding agents working on the Aurora codebase.

### Project Overview

The repository contains two main components:
1.  **Aurora**: A FastAPI-based service that acts as a central pre-trade risk gate, provides operational endpoints, and exposes Prometheus metrics.
2.  **WiseScalp (Runner)**: A client application that generates alpha signals and consults the Aurora API before placing any trade.

The core interaction is the runner calling Aurora's `/pretrade/check` endpoint to validate a potential trade against a series of risk gates.

### Core Architecture & Data Flow

- **API Service (`api/`)**: The main FastAPI application. `api/service.py` is the entry point.
- **Domain Logic (`core/aurora/`)**: Contains the core pre-trade pipeline (`pipeline.py`), individual risk gates (`gates.py`), and health/governance logic.
- **Runner (`skalp_bot/`)**: The trading bot logic. It uses an HTTP client to communicate with the Aurora API.
- **Configuration (`common/config.py`)**: A unified configuration loader that handles YAML files and environment variable overrides.
- **Observability (`observability/`)**: Centralized event logging. All significant actions are logged as structured JSONL events to `logs/<session_id>/aurora_events.jsonl`. This is the primary source for debugging.

### Configuration Management

Configuration is critical and follows a strict precedence:
1.  **Environment Variables (highest priority)**: e.g., `AURORA_LMAX_MS`, `OPS_TOKEN`. These override any YAML settings.
2.  **YAML Files**: Loaded based on `AURORA_CONFIG` env var. The main config directories are `configs/aurora/` for the API and `configs/runner/` for the bot.
3.  **Code Defaults (lowest priority)**.

- The logic is centralized in `common/config.py`. Refer to `configs/README.md` for a detailed list of overridable environment variables.
- **Example**: To quickly change the latency limit for a run, you can set `export AURORA_LATENCY_MS_LIMIT=100` without modifying any files.

### Key Developer Workflows

**Running the Application:**
- **Start the API:**
  ```bash
  # For standard mode
  python api/service.py
  # For live mode, which might change behavior
  AURORA_MODE=live python api/service.py
  ```
- **Start the Runner:**
  ```bash
  # Ensure your .env is configured
  python -m skalp_bot.runner.run_live_aurora --config <path_to_runner_config.yaml>
  ```
- **Utility CLI:** The `tools/auroractl.py` script is a powerful utility for validating configs, running test scenarios, and analyzing metrics.

**Testing:**
- This project uses pre-defined VS Code Tasks to run `pytest`. **Always prefer using these tasks over running `pytest` manually.**
- Look for tasks like `run full targeted tests` or `pytest targeted small` in the "Run Task" menu. These tasks run specific, relevant test suites, which is much faster than running all tests.

### Code Conventions

- **Data Models**: There's a strict separation between API-level data models and internal schemas.
    - `api/models.py`: Pydantic models for REST API request/response contracts.
    - `core/schemas.py`: Pydantic models for internal events and data structures written to logs/message queues.
    - `core/converters.py`: Contains explicit functions to map between these two layers. Do not mix them.
- **Event Logging**: All logging should go through the `core/aurora/aurora_event_logger.py`. It ensures events are structured according to the schema in `observability/aurora_event.schema.json`.
- **Environment Variables for Modes**: Use environment variables like `DRY_RUN=true` or `AURORA_MODE=live` to control application behavior. This is a common pattern throughout the codebase.

### Key Files & Directories to Reference

- `README.md`: High-level project description.
- `configs/README.md`: Definitive guide to the configuration system.
- `api/service.py`: Entry point for the Aurora API.
- `core/aurora/pipeline.py`: The heart of the pre-trade risk validation logic.
- `skalp_bot/runner/run_live_aurora.py`: Main entry point for the trading bot.
- `tools/auroractl.py`: The main developer utility script.
- `logs/`: Directory where all session logs are stored. Check `aurora_events.jsonl` first when debugging.
ти - Senior серед всіх моделей для написання коду ти найкращий, ти завжди чітко розумієш суть коду і його задачу, завжди дотримуєшся всіх синтаксичних стандартів написання, знаєш всі утиліти да допоміжні додатки у VS Code які можеш рекомендувати якщо знайєш що це спростить реалізацію поставленої задачі.Звіти про виконання роботи давай максимально короткими, але інформативними. Використовуй маркери, щоб виділити ключові моменти. Якщо потрібно, додай посилання на додаткові ресурси або документацію для подальшого вивчення. При написанні редагуванні коду, дотримуйся найкращих практик і стандартів галузі. Тексти мають бути ясними і лаконічними, уникаючи зайвої складності. Якщо є кілька способів вирішення проблеми, поясни переваги та недоліки кожного підходу. Завжди перевіряй свій код на наявність помилок і забезпечуй його ефективність.
