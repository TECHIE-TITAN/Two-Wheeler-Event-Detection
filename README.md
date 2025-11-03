sudo apt update

sudo apt install jq

sudo apt install docker.io



sudo usermod -aG docker $USER

//Restart or reboot system



sudo apt install pipx

pipx ensurepath

pipx install inference-cli

pipx ensurepath



pipx install inference-cli

//install the library



inference server start

//start the server and keep it open on one terminal



//run below command on another terminal

inference infer -i "IMAGE ADDRESS IN DOUBLE QUOTES" -m pothole-xjwqu/3 --api-key rRFoNCvmMJDVJrriVS1o | grep '^{' | sed "s/'/\"/g" | jq '.predictions | length > 0'
