.PHONY: help up down logs ps build rebuild seed catalog offers catalog-offers migrate test test-backend test-frontend typecheck fmt clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

up: ## Start the whole stack (postgres + backend + frontend)
	docker compose up -d

down: ## Stop the stack
	docker compose down

logs: ## Tail all logs
	docker compose logs -f

ps: ## Show service status
	docker compose ps

build: ## Build images
	docker compose build

rebuild: ## Rebuild images from scratch
	docker compose build --no-cache

migrate: ## Apply alembic migrations
	cd backend && alembic upgrade head

seed: ## Load the deterministic demo dataset
	cd backend && python -m app.seed.run

catalog: ## Build the curated product list from data/raw (read-only)
	python3 scripts/build_catalog.py

offers: ## Attach seller offers from data/product-pages to the catalogue
	python3 scripts/add_offers.py

test: test-backend test-frontend ## Run all tests

test-backend: ## Backend tests (pytest)
	cd backend && pytest -q

test-frontend: ## Frontend tests (vitest)
	cd frontend && npm run test:run

typecheck: ## Frontend type check
	cd frontend && npm run typecheck

catalog-offers: ## Rebuild the catalogue and attach seller offers
	$(MAKE) catalog offers

clean: ## Remove build artefacts
	rm -rf frontend/dist frontend/node_modules/.vite backend/.pytest_cache
