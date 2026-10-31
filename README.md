# ASR-Plus-CAC221

install :

cd ~/domoticz/plugins<br/>
git clone https://github.com/Erwanweb/ASR-Plus-CAC221.git<br/> 
ASR-Plus-CAC221<br/>
cd ASR-Plus-CAC221<br/>
sudo chmod +x plugin.py<br/>
sudo /etc/init.d/domoticz.sh restart

Upgrade :

cd ~/domoticz/plugins/ASR-Plus-CAC221<br/>
git reset --hard && git pull --force<br/> 
sudo /etc/init.d/domoticz.sh restart<br/>

Expert param :<br/> 
Day/Night Activator, <br/>
Pause On delay, <br/>
Forced Eco Off delay (in minutes, 0=not timed), <br/>
Presence On delay (in minutes), <br/>
Presence Off delay (in minutes), <br/>
reducted Temp (in degree), <br/>
Turbo level (0=no turbofan/turbopower, 1=small 0.5°C, 2=medium 1°C, 3=high 1.5°C below setpoint), <br/>
IR Repeat order (0 not activ.), <br/>
Turbofan max speed (10=Auto,20=Low,30=Mid,40=High), <br/>
Normal fan speed (10=Auto,20=Low,30=Mid,40=High), <br/>
AC setpoint offset for oversized unit (in degree, 0=none), <br/>
AC min setpoint (in degree, ex :17), <br/>
Overheat action above min setpoint (0=auto, 1=fan only, 2=stay in heat mode, 3= off) <br/>

Params (expert) : Day/Night Activator, Pause On delay, Forced Eco Off delay (0=not timed), Presence On delay, Presence Off delay (all in minutes), reducted T(in degree), Turbo level (0=no turbofan/turbopower, 1=small 0.5°C, 2=medium 1°C, 3=high 1.5°C below setpoint), IR Repeat order (0 not activ.), Turbofan max speed, Normal fan speed (10=Auto,20=Low,30=Mid,40=High), AC setpoint offset for oversized unit (in degree, 0=none), AC min setpoint (in degree, ex :17), Overheat action above min setpoint (0=auto, 1=fan only, 2=stay in heat mode, 3= off)

default= 0,1,15,1,45,4,1,30,40,10,0,17,1
