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
	@echo "Starting main2.py first to initialize shared memory..."
	@ (source $(MY_ENV)/bin/activate && python "$(CODE_DIR)/main2.py") & \
	  echo "Starting Warning_Generate.py and live_detect.py..." && \
	  (source $(MY_ENV)/bin/activate && python "$(WARNING_DIR)/Warning_Generate.py") & \
	  (source $(VENV)/bin/activate && python "$(WARNING_DIR)/live_detect.py") & \
	  wait

