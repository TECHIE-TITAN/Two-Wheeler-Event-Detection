SHELL := /bin/bash

# Absolute paths to your virtual environments
MY_ENV=~/Desktop/Two-Wheeler-Event-Detection/my_env
VENV=~/Desktop/Two-Wheeler-Event-Detection/.venv

# Path to Python scripts
CODE_DIR="Hardware\ Source\ Codes/"

run:
	@echo "Fixing GPS port permissions..."
	@sudo chmod 666 /dev/ttyS0
	@echo "Starting camera_utils.py (.venv) and main2.py (my_env) together..."
	@ (source $(VENV)/bin/activate && python "$(CODE_DIR)/camera_utils.py") & \
	  (source $(MY_ENV)/bin/activate && python "$(CODE_DIR)/main2.py") & \
	  wait

# Alternative: Run with CPU affinity if you have multiple cores
run-affinity:
    @echo "Fixing GPS port permissions..."
    @sudo chmod 666 /dev/ttyS0
    @echo "Starting processes with CPU affinity..."
    @ (source $(VENV)/bin/activate && taskset -c 1 python "$(CODE_DIR)/camera_utils.py") & \
      (source $(MY_ENV)/bin/activate && taskset -c 0 python "$(CODE_DIR)/main2.py") & \
      wait
