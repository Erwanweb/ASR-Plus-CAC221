# ASR-Plus-CAC221

install :

cd ~/domoticz/plugins

mkdir ASR-Plus-CAC221

sudo apt-get update

sudo apt-get install git

git clone https://github.com/Erwanweb/ASR-Plus-CAC221.git ASR-Plus-CAC221

cd ASR-Plus-CAC221

sudo chmod +x plugin.py

sudo /etc/init.d/domoticz.sh restart

Upgrade :

cd ~/domoticz/plugins/ASR-Plus-CAC221

git reset --hard && git pull --force
