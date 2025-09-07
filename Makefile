# Aurora P3-E & P4 Build Automation Makefile
# Comprehensive build, test, and deployment targets

.PHONY: help install test lint format clean build docker-build docker-push deploy dev up down logs

# Default target
help: ## Show this help message
	@echo "Aurora P3-E & P4 Build System"
	@echo ""
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

# Development environment setup
install: ## Install Python dependencies
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

dev-install: ## Install development dependencies only
	pip install -r requirements-dev.txt

# Testing targets
test: ## Run all tests
	pytest tests/ -v --cov=core --cov=skalp_bot --cov=tools --cov-report=html

test-unit: ## Run unit tests only
	pytest tests/unit/ -v

test-integration: ## Run integration tests only
	pytest tests/integration/ -v

test-smoke: ## Run smoke tests
	pytest tests/smoke/ -v

test-performance: ## Run performance tests
	pytest tests/performance/ -v

# Code quality targets
lint: ## Run linting checks
	flake8 core skalp_bot tools --count --select=E9,F63,F7,F82 --show-source --statistics
	black --check core skalp_bot tools
	isort --check-only core skalp_bot tools
	mypy core skalp_bot tools

format: ## Format code with black and isort
	black core skalp_bot tools
	isort core skalp_bot tools

security-scan: ## Run security vulnerability scan
	safety check
	bandit -r core skalp_bot tools

# Build targets
build: clean ## Build the application
	python -m pip install -e .

build-dist: ## Build distribution packages
	python setup.py sdist bdist_wheel

# Docker targets
docker-build: ## Build all Docker images
	docker build -f Dockerfile.runner -t aurora-runner:latest .
	docker build -f Dockerfile.live_feed -t aurora-live-feed:latest .
	docker build -f Dockerfile.dashboard -t aurora-dashboard:latest .

docker-build-runner: ## Build runner Docker image
	docker build -f Dockerfile.runner -t aurora-runner:latest .

docker-build-live-feed: ## Build live-feed Docker image
	docker build -f Dockerfile.live_feed -t aurora-live-feed:latest .

docker-build-dashboard: ## Build dashboard Docker image
	docker build -f Dockerfile.dashboard -t aurora-dashboard:latest .

docker-push: ## Push Docker images to registry
	docker tag aurora-runner:latest $(REGISTRY)/aurora-runner:$(TAG)
	docker tag aurora-live-feed:latest $(REGISTRY)/aurora-live-feed:$(TAG)
	docker tag aurora-dashboard:latest $(REGISTRY)/aurora-dashboard:$(TAG)
	docker push $(REGISTRY)/aurora-runner:$(TAG)
	docker push $(REGISTRY)/aurora-live-feed:$(TAG)
	docker push $(REGISTRY)/aurora-dashboard:$(TAG)

# Development environment with Docker Compose
dev: ## Start development environment
	docker-compose up -d

dev-build: ## Build and start development environment
	docker-compose up --build -d

dev-logs: ## Show development environment logs
	docker-compose logs -f

dev-stop: ## Stop development environment
	docker-compose down

dev-clean: ## Clean development environment
	docker-compose down -v --remove-orphans

# Kubernetes/Helm deployment targets
helm-template: ## Show Helm templates
	helm template aurora deploy/helm/aurora

helm-install: ## Install Helm chart
	helm upgrade --install aurora deploy/helm/aurora

helm-upgrade: ## Upgrade Helm release
	helm upgrade aurora deploy/helm/aurora

helm-uninstall: ## Uninstall Helm release
	helm uninstall aurora

helm-test: ## Test Helm release
	helm test aurora

# CI/CD targets
ci: lint test security-scan ## Run full CI pipeline

cd-deploy-staging: ## Deploy to staging environment
	helm upgrade --install aurora-staging deploy/helm/aurora \
		--namespace aurora-staging \
		--create-namespace \
		--values deploy/helm/aurora/values-staging.yaml

cd-deploy-production: ## Deploy to production environment
	helm upgrade --install aurora deploy/helm/aurora \
		--namespace aurora \
		--create-namespace \
		--values deploy/helm/aurora/values-production.yaml

# Monitoring and observability
prometheus-test: ## Test Prometheus configuration
	promtool check config deploy/prometheus.yml

alerts-test: ## Test alert rules
	promtool check rules deploy/alerts.yml

# Log management
logs-rotate: ## Rotate application logs
	logrotate -f /etc/logrotate.d/aurora

logs-cleanup: ## Clean up old log archives
	find logs/ -name "*.log.*.gz" -mtime +30 -delete

# Database targets (if applicable)
db-migrate: ## Run database migrations
	alembic upgrade head

db-reset: ## Reset database (dangerous!)
	alembic downgrade base

# Utility targets
clean: ## Clean build artifacts
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -delete
	find . -type f -name ".coverage" -delete
	rm -rf build/ dist/ htmlcov/ .pytest_cache/

clean-all: clean ## Clean all artifacts including Docker
	docker system prune -f
	docker volume prune -f

# Environment setup
setup-dev: ## Setup development environment
	python -m venv venv
	source venv/bin/activate && make install
	pre-commit install

setup-pre-commit: ## Setup pre-commit hooks
	pre-commit install
	pre-commit run --all-files

# Documentation
docs-build: ## Build documentation
	mkdocs build

docs-serve: ## Serve documentation locally
	mkdocs serve

# Performance profiling
profile: ## Run performance profiling
	python -m cProfile -s time tools/auroractl.py profile

# Health checks
health-check: ## Run health checks
	curl -f http://localhost:8000/health || exit 1
	curl -f http://localhost:8001/health || exit 1
	curl -f http://localhost:8002/health || exit 1

# Backup and restore
backup-config: ## Backup configuration files
	tar -czf backup/config-$(date +%Y%m%d-%H%M%S).tar.gz configs/

backup-logs: ## Backup log files
	tar -czf backup/logs-$(date +%Y%m%d-%H%M%S).tar.gz logs/

# Emergency targets
emergency-stop: ## Emergency stop all services
	docker-compose down
	kubectl delete deployment aurora-runner aurora-live-feed aurora-dashboard
	systemctl stop aurora-live-feed

emergency-restart: ## Emergency restart services
	systemctl restart aurora-live-feed
	kubectl rollout restart deployment aurora-runner
	kubectl rollout restart deployment aurora-live-feed
	kubectl rollout restart deployment aurora-dashboard

# Information targets
info: ## Show system information
	@echo "=== Aurora System Information ==="
	@echo "Python version: $(python --version)"
	@echo "Docker version: $(docker --version)"
	@echo "Kubernetes context: $(kubectl config current-context)"
	@echo "Helm version: $(helm version --short)"
	@echo "Git branch: $(git branch --show-current)"
	@echo "Git commit: $(git rev-parse --short HEAD)"

version: ## Show version information
	@python -c "import aurora; print(aurora.__version__)"