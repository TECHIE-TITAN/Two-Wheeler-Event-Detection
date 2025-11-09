#!/bin/bash

API_KEY="rRFoNCvmMJDVJrriVS1o"

detect_hazards() {
    local image_path="$1"

    if [ -z "$image_path" ]; then
        echo "Error: No image path provided to detect_hazards function." >&2
        return 255
    fi

    local pothole_model="pothole-xjwqu/3"
    local speedbump_model="speed-bumps-detection-61eef/7"
    local pipeline_command="| grep '^{' | sed \"s/'/\\\"/g\" | jq '.predictions | length > 0'"

    echo "Checking '$image_path' for potholes..."
    local pothole_command="inference infer -i \"$image_path\" -m \"$pothole_model\" --api-key \"$API_KEY\" $pipeline_command"
    local has_pothole=$(eval "$pothole_command")

    echo "Checking '$image_path' for speedbumps..."
    local speedbump_command="inference infer -i \"$image_path\" -m \"$speedbump_model\" --api-key \"$API_KEY\" $pipeline_command"
    local has_speedbump=$(eval "$speedbump_command")

    if [ "$has_pothole" = "true" ] && [ "$has_speedbump" = "true" ]; then
        return 3
    elif [ "$has_pothole" = "true" ]; then
        return 2
    elif [ "$has_speedbump" = "true" ]; then
        return 1
    else
        return 0
    fi
}


IMAGE_TO_TEST="/home/samarth-singla/Desktop/yolo lelo/pothole images/pothle.jpeg"
detect_hazards "$IMAGE_TO_TEST"
detection_result=$?


case $detection_result in
    0)
        echo "Result Code: 0"
        echo "Result: Neither a pothole nor a speedbump was detected."
        ;;
    1)
        echo "Result Code: 1"
        echo "Result: Speedbump detected!"
        ;;
    2)
        echo "Result Code: 2"
        echo "Result: Pothole detected!"
        ;;
    3)
        echo "Result Code: 3"
        echo "Result: BOTH a pothole AND a speedbump were detected!"
        ;;
    255)
        echo "Result Code: 255"
        echo "Error: The detection function failed. (Was an image path provided?)"
        ;;
    *)
        echo "Result Code: $detection_result"
        echo "Error: An unknown return code was received."
        ;;
esac


# general output format-
# Running inference on /home/samarth-singla/Desktop/yolo lelo/pothole images/pothle.jpeg, using model: pothole-xjwqu/3, and host: http://localhost:9001
# {'inference_id': '0cd8bdf3-bc62-44da-b6e5-33eaa463897b', 'time': 0.21424480699988635, 'image': {'width': 294, 'height': 172}, 'predictions': [{'x': 135.0, 'y': 132.0, 'width': 62.0, 'height': 34.0, 'confidence': 0.856471598148346, 'class': 'potholes', 'class_id': 0, 'detection_id': '30b5532c-8995-498e-96dd-e2f0ce08f801'}, {'x': 240.5, 'y': 101.5, 'width': 45.0, 'height': 15.0, 'confidence': 0.8071173429489136, 'class': 'potholes', 'class_id': 0, 'detection_id': '68b7202d-6d0c-47db-a4db-cbba5c6b6972'}]}