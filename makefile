SHELL := /bin/bash

# Absolute paths to your virtual environments
MY_ENV=~/Desktop/Two-Wheeler-Event-Detection/my_env
VENV=~/Desktop/Two-Wheeler-Event-Detection/.venv

# Path to Python scripts
CODE_DIR="Hardware\ Source\ Codes/"
WARNING_DIR="Warning\ Generation\ Algorithm/"

run:
	@echo "Fixing GPS port permissions..."
	@sudo chmod 666 /dev/ttyS0
	@echo "Starting camera_utils.py (.venv), main2.py (my_env), and Warning_Generate.py (my_env) together..."
	@ (source $(VENV)/bin/activate && python "$(CODE_DIR)/camera_utils.py") & \
	  (source $(MY_ENV)/bin/activate && python "$(CODE_DIR)/main2.py") & \
	  (source $(MY_ENV)/bin/activate && python "$(WARNING_DIR)/Warning_Generate.py") & \
	  wait

