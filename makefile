.PHONY: run

run:
	@echo "Running orchestrator..."
	@source ~/Desktop/Two-Wheeler-Event-Detection/my_env/bin/activate && \
	python3 ~/Desktop/Two-Wheeler-Event-Detection/Hardware_code/orchestrator.py
