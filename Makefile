.PHONY: install lint test eval contract gateway console up down

install:
	pip install -r requirements-dev.txt
lint:
	ruff check .
test:      ## unit, protocol, agent and HTTP-transport tests
	pytest -q
eval:      ## agent accuracy (5 seeds) + security suite + contract check
	python -m itsm_mcp.eval.run --gate
contract:  ## accept the current tool schemas as the published contract
	python -m itsm_mcp.eval.run --update-contract
gateway:   ## MCP gateway on http://localhost:8000/mcp
	python -m itsm_mcp.servers.gateway
console:
	streamlit run streamlit_app.py
up:
	cp -n .env.example .env || true; docker compose up --build -d
down:
	docker compose down
