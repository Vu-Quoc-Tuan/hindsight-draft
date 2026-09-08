# ==============================================================================
# Hindsight Project Makefile
# ==============================================================================
# Convenient workflows for development, production (Docker), UI, and testing.
# ==============================================================================

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

# --- Terminal Styling ---
BOLD   := \033[1m
DIM    := \033[2m
CYAN   := \033[36m
GREEN  := \033[32m
YELLOW := \033[33m
BLUE   := \033[34m
MAGENTA:= \033[35m
RED    := \033[31m
RESET  := \033[0m

# --- Configuration & Ports ---
API_PORT    ?= 8000
WEB_PORT    ?= 5173
MOCK_PORT   ?= 8085
COMPOSE_FILE := nocpro-chain-explain/docker-compose.yml

.PHONY: help dev dev-api dev-web dev-mock ui prod product prod-down down prod-logs logs prod-status status test test-fast test-full test-backend test-mock test-ui test-web lint install clean

# ==============================================================================
# 1. Help / Command Dashboard
# ==============================================================================
help:
	@echo ""
	@echo -e "$(BOLD)$(CYAN)  ██╗  ██╗██╗███╗   ██╗██████╗ ███████╗██╗ ██████╗ ██╗  ██╗████████╗$(RESET)"
	@echo -e "$(BOLD)$(CYAN)  ██║  ██║██║████╗  ██║██╔══██╗██╔════╝██║██╔════╝ ██║  ██║╚══██╔══╝$(RESET)"
	@echo -e "$(BOLD)$(CYAN)  ███████║██║██╔██╗ ██║██║  ██║███████╗██║██║  ███╗███████║   ██║   $(RESET)"
	@echo -e "$(BOLD)$(CYAN)  ██╔══██║██║██║╚██╗██║██║  ██║╚════██║██║██║   ██║██╔══██║   ██║   $(RESET)"
	@echo -e "$(BOLD)$(CYAN)  ██║  ██║██║██║ ╚████║██████╔╝███████║██║╚██████╔╝██║  ██║   ██║   $(RESET)"
	@echo -e "$(DIM)  See the bigger picture behind alarm chains · Quick Commands$(RESET)"
	@echo ""
	@echo -e "$(BOLD)$(YELLOW)DEVELOPMENT (No Kafka - Fast Local Dev):$(RESET)"
	@echo -e "  $(GREEN)make dev$(RESET)          $(DIM)→$(RESET) Run full local stack (API + Web + Mock UI) without Kafka"
	@echo -e "  $(GREEN)make dev-api$(RESET)      $(DIM)→$(RESET) Run FastAPI backend only (port $(API_PORT), auto-reload, no Kafka)"
	@echo -e "  $(GREEN)make dev-web$(RESET)      $(DIM)→$(RESET) Run Vite Web frontend only (port $(WEB_PORT))"
	@echo -e "  $(GREEN)make dev-mock$(RESET)     $(DIM)→$(RESET) Run NocPro Mock server only (port $(MOCK_PORT))"
	@echo -e "  $(GREEN)make ui$(RESET)           $(DIM)→$(RESET) Alias for 'make dev-web'"
	@echo ""
	@echo -e "$(BOLD)$(YELLOW)PRODUCTION (Full Stack with Docker Compose & Kafka):$(RESET)"
	@echo -e "  $(GREEN)make prod$(RESET)         $(DIM)→$(RESET) Build & start full Docker stack (Kafka, Postgres, API, Web, etc.)"
	@echo -e "  $(GREEN)make product$(RESET)      $(DIM)→$(RESET) Alias for 'make prod'"
	@echo -e "  $(GREEN)make down$(RESET)         $(DIM)→$(RESET) Stop and remove Docker containers"
	@echo -e "  $(GREEN)make logs$(RESET)         $(DIM)→$(RESET) Follow logs from running Docker containers"
	@echo -e "  $(GREEN)make status$(RESET)       $(DIM)→$(RESET) Check Docker container statuses"
	@echo ""
	@echo -e "$(BOLD)$(YELLOW)TESTING (Fast & Visual):$(RESET)"
	@echo -e "  $(GREEN)make test$(RESET)         $(DIM)→$(RESET) Run mixed fast test suite (Backend + Mock UI + Web Vitest)"
	@echo -e "  $(GREEN)make test-backend$(RESET) $(DIM)→$(RESET) Run Backend pytest (Explain API & Assistant)"
	@echo -e "  $(GREEN)make test-mock$(RESET)    $(DIM)→$(RESET) Run Mock server pytest"
	@echo -e "  $(GREEN)make test-ui$(RESET)      $(DIM)→$(RESET) Run Web frontend Vitest"
	@echo -e "  $(GREEN)make test-full$(RESET)    $(DIM)→$(RESET) Run all comprehensive tests (including long replay fixtures)"
	@echo ""
	@echo -e "$(BOLD)$(YELLOW)SETUP & MAINTENANCE:$(RESET)"
	@echo -e "  $(GREEN)make install$(RESET)      $(DIM)→$(RESET) Install all Python (uv) and Node (pnpm) dependencies"
	@echo -e "  $(GREEN)make clean$(RESET)        $(DIM)→$(RESET) Clean up python bytecode, cache directories, and test artifacts"
	@echo ""

# ==============================================================================
# 2. Development Mode (No Kafka)
# ==============================================================================

# Run all 3 local dev servers concurrently with a single command.
# Pressing Ctrl+C cleanly stops all 3 servers via trap.
dev:
	@echo -e "$(BOLD)$(CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@echo -e "$(BOLD)$(GREEN)🚀 Starting Hindsight in DEV mode (No Kafka)...$(RESET)"
	@echo -e "   $(CYAN)• Web UI:     $(RESET)http://127.0.0.1:$(WEB_PORT)"
	@echo -e "   $(CYAN)• Backend API:$(RESET)http://127.0.0.1:$(API_PORT)"
	@echo -e "   $(CYAN)• Mock Server:$(RESET)http://127.0.0.1:$(MOCK_PORT)"
	@echo -e "   $(DIM)Mode: Local in-memory / presets enabled, Kafka disabled.$(RESET)"
	@echo -e "   $(YELLOW)Press [Ctrl+C] to stop all services simultaneously.$(RESET)"
	@echo -e "$(BOLD)$(CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@bash -c '\
		trap "echo -e \"\n$(YELLOW)Shutting down all dev services...$(RESET)\"; kill \$$(jobs -p) 2>/dev/null; exit 0" EXIT SIGINT SIGTERM; \
		(cd nocpro-mock && uv run python -m nocpro_mock.cli ui --port $(MOCK_PORT) 2>&1 | sed "s/^/[MOCK-$(MOCK_PORT)] /") & \
		(cd nocpro-chain-explain && PYTHONPATH=.:services/analysis-worker:services/api:../nocpro-mock/src KAFKA_ENABLED=false AUTO_SEED_DEFAULT_SNAPSHOT=true uv run uvicorn nocpro_api.app:app --app-dir services/api --host 127.0.0.1 --port $(API_PORT) --reload 2>&1 | sed "s/^/[API-$(API_PORT)] /") & \
		(cd nocpro-chain-explain/services/web && pnpm dev --port $(WEB_PORT) 2>&1 | sed "s/^/[WEB-$(WEB_PORT)] /") & \
		wait'

# Run only the FastAPI backend (Fast iteration on Python API)
dev-api:
	@echo -e "$(BOLD)$(GREEN)⚡ Starting Backend API (no Kafka) on http://127.0.0.1:$(API_PORT)...$(RESET)"
	@cd nocpro-chain-explain && \
		PYTHONPATH=.:services/analysis-worker:services/api:../nocpro-mock/src \
		KAFKA_ENABLED=false \
		AUTO_SEED_DEFAULT_SNAPSHOT=true \
		uv run uvicorn nocpro_api.app:app --app-dir services/api --host 127.0.0.1 --port $(API_PORT) --reload

# Run only the Vite Web Frontend
dev-web:
	@echo -e "$(BOLD)$(GREEN)🌐 Starting Web Frontend on http://127.0.0.1:$(WEB_PORT)...$(RESET)"
	@cd nocpro-chain-explain/services/web && pnpm dev --port $(WEB_PORT)

ui: dev-web

# Run only the Mock Server
dev-mock:
	@echo -e "$(BOLD)$(GREEN)📦 Starting Mock Server on http://127.0.0.1:$(MOCK_PORT)...$(RESET)"
	@cd nocpro-mock && uv run python -m nocpro_mock.cli ui --port $(MOCK_PORT)

# ==============================================================================
# 3. Production Mode (Full Docker Compose Stack)
# ==============================================================================

prod:
	@echo -e "$(BOLD)$(CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@echo -e "$(BOLD)$(GREEN)🐳 Starting Full Hindsight Production Stack (Docker)...$(RESET)"
	@echo -e "   Includes: PostgreSQL, Kafka, Migration, Explain API, Web (Nginx)"
	@echo -e "$(BOLD)$(CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	docker compose -f $(COMPOSE_FILE) up --build -d
	@echo ""
	@echo -e "$(BOLD)$(GREEN)✓ Production stack is running!$(RESET)"
	@echo -e "  → Web App:  http://localhost:3000"
	@echo -e "  → API:      http://localhost:8000"
	@echo -e "  → Kafka:    localhost:9092"
	@echo -e "  → Postgres: localhost:5432"
	@echo ""
	@echo -e "Use $(YELLOW)make logs$(RESET) to view logs, or $(YELLOW)make down$(RESET) to stop."

product: prod

prod-down:
	@echo -e "$(BOLD)$(YELLOW)Stopping Docker Compose stack...$(RESET)"
	docker compose -f $(COMPOSE_FILE) down

down: prod-down

prod-logs:
	docker compose -f $(COMPOSE_FILE) logs -f

logs: prod-logs

prod-status:
	docker compose -f $(COMPOSE_FILE) ps

status: prod-status

# ==============================================================================
# 4. Testing ("Mix" - Fast & Visual Dev Output)
# ==============================================================================

# Mixed fast test suite: Runs essential unit tests across Backend, Mock, and Frontend
test:
	@echo -e "$(BOLD)$(CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@echo -e "$(BOLD)$(MAGENTA)🧪 Running Mixed Developer Test Suite$(RESET)"
	@echo -e "$(BOLD)$(CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@echo ""
	@echo -e "$(BOLD)$(BLUE)[1/3] Backend Tests (Explain API, Grounded LLM & Assistant)...$(RESET)"
	@cd nocpro-chain-explain && \
		PYTHONPATH=../nocpro-mock/src:services/api:services/analysis-worker:src \
		uv run pytest -q --tb=short \
			tests/test_assistant_knowledge.py \
			tests/test_assistant_tool_calling.py \
			tests/test_grounded_llm.py \
			tests/test_ai_advisor.py \
			tests/test_analysis_config.py
	@echo ""
	@echo -e "$(BOLD)$(BLUE)[2/3] Mock Server Tests (UI, Slicer & Kafka Dispatcher)...$(RESET)"
	@cd nocpro-mock && \
		uv run pytest -q --tb=short \
			tests/test_ui.py
	@echo ""
	@echo -e "$(BOLD)$(BLUE)[3/3] Web Frontend Component & Data Truth Tests (Vitest)...$(RESET)"
	@cd nocpro-chain-explain/services/web && \
		pnpm test
	@echo ""
	@echo -e "$(BOLD)$(GREEN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@echo -e "$(BOLD)$(GREEN)🎉 ALL MIXED TESTS PASSED! Everything is green and healthy.$(RESET)"
	@echo -e "$(BOLD)$(GREEN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"

test-fast: test

test-backend:
	@echo -e "$(BOLD)$(BLUE)Testing Backend (Explain API)...$(RESET)"
	@cd nocpro-chain-explain && \
		PYTHONPATH=../nocpro-mock/src:services/api:services/analysis-worker:src \
		uv run pytest tests/test_assistant_knowledge.py tests/test_assistant_tool_calling.py tests/test_grounded_llm.py tests/test_ai_advisor.py tests/test_analysis_config.py

test-mock:
	@echo -e "$(BOLD)$(BLUE)Testing NocPro Mock Server...$(RESET)"
	@cd nocpro-mock && uv run pytest tests/test_ui.py

test-ui:
	@echo -e "$(BOLD)$(BLUE)Testing Web Frontend...$(RESET)"
	@cd nocpro-chain-explain/services/web && pnpm test

test-web: test-ui

# Full comprehensive test run (including all 225 mock fixtures)
test-full:
	@echo -e "$(BOLD)$(MAGENTA)Running FULL Test Suite (Comprehensive)...$(RESET)"
	@echo -e "$(BLUE)1. Mock Full Suite...$(RESET)"
	@cd nocpro-mock && uv run pytest -q
	@echo -e "$(BLUE)2. Explain Full Suite...$(RESET)"
	@cd nocpro-chain-explain && PYTHONPATH=../nocpro-mock/src:services/api:services/analysis-worker:src uv run pytest -q
	@echo -e "$(BLUE)3. Web Frontend...$(RESET)"
	@cd nocpro-chain-explain/services/web && pnpm test
	@echo -e "$(BOLD)$(GREEN)✓ Full test suite passed!$(RESET)"

# Run linter on web frontend
lint:
	@echo -e "$(BOLD)$(CYAN)Running linter...$(RESET)"
	@cd nocpro-chain-explain/services/web && pnpm lint

# ==============================================================================
# 5. Dependency Installation & Cleanup
# ==============================================================================

install:
	@echo -e "$(BOLD)$(CYAN)Installing all dependencies...$(RESET)"
	@echo -e "$(BLUE)1. Syncing nocpro-mock (uv)...$(RESET)"
	@cd nocpro-mock && uv sync
	@echo -e "$(BLUE)2. Syncing nocpro-chain-explain (uv)...$(RESET)"
	@cd nocpro-chain-explain && uv sync
	@echo -e "$(BLUE)3. Installing web packages (pnpm)...$(RESET)"
	@cd nocpro-chain-explain/services/web && pnpm install
	@echo -e "$(BOLD)$(GREEN)✓ All dependencies installed successfully!$(RESET)"

clean:
	@echo -e "$(BOLD)$(YELLOW)Cleaning caches and temporary files...$(RESET)"
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.py[cod]" -delete 2>/dev/null || true
	@rm -rf nocpro-chain-explain/services/web/dist 2>/dev/null || true
	@rm -rf playwright-report test-results 2>/dev/null || true
	@rm -rf nocpro-mock/docs/examples/synthetic/test_ui_evolution_seq 2>/dev/null || true
	@echo -e "$(BOLD)$(GREEN)✓ Cleanup complete!$(RESET)"
