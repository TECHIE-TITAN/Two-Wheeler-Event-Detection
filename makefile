SHELL := /bin/bash

# Absolute paths to your virtual environments
MY_ENV=~/Desktop/Two-Wheeler-Event-Detection/my_env
VENV=~/Desktop/Two-Wheeler-Event-Detection/.venv

# Path to Python scripts
CODE_DIR=Hardware\ Source\ Codes/

run:
	@echo "Starting camera_utils.py (.venv) and main.py (my_env) together..."
	@(source $(VENV)/bin/activate && python $(CODE_DIR)/camera_utils.py) & \
	 (source $(MY_ENV)/bin/activate && python $(CODE_DIR)/main.py) & \
	 wait
