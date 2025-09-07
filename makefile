SHELL := /bin/bash

MY_ENV=~/Desktop/Two-Wheeler-Event-Detection/my_env
VENV=~/Desktop/Two-Wheeler-Event-Detection/.venv
CODE_DIR=Hardware\ Source\ Codes/

run:
	@echo "Running orchestrator..."
	@(. $(MY_ENV)/bin/activate && python $(CODE_DIR)/orchestrator.py)
