# Absolute paths to your virtual environments
MY_ENV=~/Desktop/Two-Wheeler-Event-Detection/my_env
VENV=~/Desktop/Two-Wheeler-Event-Detection/.venv

run:
	@echo "Starting camera_utils.py (.venv) and main.py (my_env) together..."
	@(source $(VENV)/bin/activate && python camera_utils.py) & \
	 (source $(MY_ENV)/bin/activate && python main.py) & \
	 wait
