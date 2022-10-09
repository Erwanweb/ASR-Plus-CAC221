"""
AC Aircon Smart Remote plugin using CASA.IA CAC 221 for Domoticz
Author: MrErwan,
Version:    0.0.1: alpha
Version:    0.1.1: beta
Version:    2.1.1: overheat control
"""
"""
<plugin key="AC-ASR-CAC221" name="AC Aircon Smart Remote PLUS for CAC221" author="MrErwan" version="0.1.1" externallink="https://github.com/Erwanweb/ASR-Plus-CAC221.git">
    <description>
        <h2>Aircon Smart Remote</h2><br/>
        Easily implement in Domoticz an full control of air conditoner controled by IR Remote and using CAC221<br/>
        <h3>Set-up and Configuration</h3>
    </description>
    <params>
        <param field="Username" label="CAC221 widgets idx - AC mode" width="100px" required="true" default=""/>
        <param field="Password" label="CAC221 widgets idx - AC fanspeed" width="100px" required="true" default=""/>
        <param field="Mode1" label="CAC221 widgets idx - AC Setpoint" width="100px" required="true" default=""/>
        <param field="Mode2" label="Pause sensors (csv list of idx)" width="100px" required="false" default=""/>
        <param field="Mode3" label="Presence Sensors (csv list of idx)" width="100px" required="false" default=""/>
        <param field="Mode4" label="Inside Temperature Sensors (csv list of idx)" width="100px" required="false" default="0"/>
        <param field="Mode5" label="Day/Night Activator, Pause On delay, Forced Eco Off delay (0=not timed), Presence On delay, Presence Off delay (all in minutes), reducted T(in degree), Delta max fanspeed (in in tenth of degre)" width="200px" required="true" default="0,1,1,2,45,3,10"/>
        <param field="Mode6" label="Logging Level" width="200px">
            <options>
                <option label="Normal" value="Normal"  default="true"/>
                <option label="Verbose" value="Verbose"/>
                <option label="Debug - Python Only" value="2"/>
                <option label="Debug - Basic" value="62"/>
                <option label="Debug - Basic+Messages" value="126"/>
                <option label="Debug - Connections Only" value="16"/>
                <option label="Debug - Connections+Queue" value="144"/>
                <option label="Debug - All" value="-1"/>
            </options>
        </param>
    </params>
</plugin>
"""
import Domoticz
# uniquement pour les besoins de cette appli
import getopt, sys
# pour lire le json
import json
import urllib
import urllib.parse as parse
import urllib.request as request
from datetime import datetime, timedelta
import time
import base64
import itertools


class deviceparam:

    def __init__(self, unit, nvalue, svalue):
        self.unit = unit
        self.nvalue = nvalue
        self.svalue = svalue
        self.debug = False


class BasePlugin:

    def __init__(self):
        self.debug = False
        self.WACmode = []
        self.WACfanspeed = []
        self.WACsetpoint = []
        self.setpoint = 21
        self.pluginsetpoint = 21
        self.WACmodevalue = 0
        self.WACfanspeedvalue = 0
        self.WACsetpointvalueBrut = 21
        self.WACsetpointvalue = 21
        self.WACmodevaluenew = 0
        self.WACfanspeedvaluenew = 0
        self.WACsetpointvaluenew = 21
        self.Turbopower = False
        self.Turbofan = False
        self.deltamax = 10  # allowed deltamax from setpoint for high level airfan
        self.ModeAuto = True
        self.DTpresence = []
        self.Presencemode = False
        self.ForcedEco = False
        self.ForcedEcoTime = datetime.now()
        self.PresenceDetected = False
        self.Presence = False
        self.PresenceTH = False
        self.PresenceTHdelay = datetime.now()
        self.presencechangedtime = datetime.now()
        self.PresenceSensor = False
        self.DTtempo = datetime.now()
        self.presenceondelay = 2  # time between first detection and last detection before turning presence ON
        self.presenceoffdelay = 45  # time between last detection before turning presence OFF
        self.pauseondelay = 1
        self.ForcedECOoffdelay = 30
        self.pause = False
        self.pauserequested = False
        self.pauserequestchangedtime = datetime.now()
        self.reductedsp = 3
        self.InTempSensors = []
        self.intemp = 25.0
        self.overheat = False
        self.overheatvalue = 1
        self.setpointnew = 21
        self.setpointadjusted = 21
        self.nexttemps = datetime.now()
        self.controlinfotime = datetime.now()
        self.controlsettime = datetime.now()
        self.controloverheatvalue = datetime.now()
        self.PLUGINstarteddtime = datetime.now()
        return

    def onStart(self):
        Domoticz.Log("onStart called")
        # setup the appropriate logging level
        try:
            debuglevel = int(Parameters["Mode6"])
        except ValueError:
            debuglevel = 0
            self.loglevel = Parameters["Mode6"]
        if debuglevel != 0:
            self.debug = True
            Domoticz.Debugging(debuglevel)
            DumpConfigToLog()
            self.loglevel = "Verbose"
        else:
            self.debug = False
            Domoticz.Debugging(0)

        # create the child devices if these do not exist yet
        devicecreated = []
        if 1 not in Devices:
            Options = {"LevelActions": "||",
                       "LevelNames": "Disconnected|Off|Auto|Manual",
                       "LevelOffHidden": "true",
                       "SelectorStyle": "0"}
            Domoticz.Device(Name="Control", Unit=1, TypeName="Selector Switch", Switchtype=18, Image=9,
                            Options=Options, Used=1).Create()
            devicecreated.append(deviceparam(1, 0, "10"))  # default is Off
        if 2 not in Devices:
            Options = {"LevelActions": "||",
                       "LevelNames": "Off|Auto|Cool|Heat|Dry|Fan",
                       "LevelOffHidden": "true",
                       "SelectorStyle": "0"}
            Domoticz.Device(Name="AC Manual Mode", Unit=2, TypeName="Selector Switch", Switchtype=18, Image=15,
                            Options=Options, Used=1).Create()
            devicecreated.append(deviceparam(2, 0, "30"))  # default is Heating mode
        if 3 not in Devices:
            Options = {"LevelActions": "||",
                       "LevelNames": "Off|Auto|Low|Mid|High",
                       "LevelOffHidden": "true",
                       "SelectorStyle": "0"}
            Domoticz.Device(Name="AC Manual Fan Speed", Unit=3, TypeName="Selector Switch", Switchtype=18, Image=15,
                            Options=Options, Used=1).Create()
            devicecreated.append(deviceparam(3, 0, "10"))  # default is Auto mode
        if 4 not in Devices:
            Domoticz.Device(Name="Forced ECO", Unit=4, TypeName="Switch", Image=9).Create()
            devicecreated.append(deviceparam(4, 0, ""))  # default is Off
        if 5 not in Devices:
            Domoticz.Device(Name="Thermostat Setpoint", Unit=5, Type=242, Subtype=1, Used=1).Create()
            devicecreated.append(deviceparam(5, 0, "21"))  # default is 21 degrees
        if 6 not in Devices:
            Domoticz.Device(Name="Presence Active", Unit=6, TypeName="Switch", Image=9).Create()
            devicecreated.append(deviceparam(6, 0, ""))  # default is Off
        if 7 not in Devices:
            Domoticz.Device(Name="Room temp", Unit=7, TypeName="Temperature", Used=1).Create()
            devicecreated.append(deviceparam(7, 0, "30"))  # default is 30 degrees
        if 8 not in Devices:
            Domoticz.Device(Name="Pause requested", Unit=8, TypeName="Switch", Image=9, Used=1).Create()
            devicecreated.append(deviceparam(8, 0, ""))  # default is Off
        # if 9 not in Devices:
        # Domoticz.Device(Name = "AC Setpoint",Unit=9,Type = 242,Subtype = 1).Create()
        # devicecreated.append(deviceparam(9,0,"20"))  # default is 20 degrees

        # if any device has been created in onStart(), now is time to update its defaults
        for device in devicecreated:
            Devices[device.unit].Update(nValue=device.nvalue, sValue=device.svalue)

        # build lists of idx widget of CAC221
        # params1 = parseCSV(Parameters["Mode1"])
        # if len(params1) == 3:
        # self.WACmode = CheckParam("AC mode",params1[0],0)
        # Domoticz.Debug("AC mode widget idx = {}".format(self.WACmode))
        # self.WACfanspeed = CheckParam("AC fan speed",params1[1],0)
        # Domoticz.Debug("AC fan speed widget idx = {}".format(self.WACfanspeed))
        # self.WACsetpoint = CheckParam("AC Stepoint",params1[2],0)
        # Domoticz.Debug("AC setpoint widget idx = {}".format(self.WACsetpoint))
        # else:
        # Domoticz.Error("Error reading CAC221 widgets idx")

        # build lists of idx widget of CAC221
        self.WACmode = parseCSV(Parameters["Username"])
        Domoticz.Debug("AC mode widget idx = {}".format(self.WACmode))
        self.WACfanspeed = parseCSV(Parameters["Password"])
        Domoticz.Debug("AC fan speed widget idx = {}".format(self.WACfanspeed))
        self.WACsetpoint = parseCSV(Parameters["Mode1"])
        Domoticz.Debug("AC setpoint widget idx = {}".format(self.WACsetpoint))

        # build lists of sensors
        self.DTpresence = parseCSV(Parameters["Mode3"])
        Domoticz.Debug("DTpresence = {}".format(self.DTpresence))
        self.InTempSensors = parseCSV(Parameters["Mode4"])
        Domoticz.Debug("Inside Temperature sensors = {}".format(self.InTempSensors))

        # splits additional parameters
        params5 = parseCSV(Parameters["Mode5"])
        if len(params5) == 7:
            self.DTDayNight = CheckParam("Day/Night Activator", params5[0], 0)
            self.pauseondelay = CheckParam("Pause On Delay", params5[1], 1)
            self.ForcedECOoffdelay = CheckParam("ForcedECO Off Delay", params5[2], 30)
            self.presenceondelay = CheckParam("Presence On Delay", params5[3], 2)
            self.presenceoffdelay = CheckParam("Presence Off Delay", params5[4], 45)
            self.reductedsp = CheckParam("Reduction temp", params5[5], 3)
            self.deltamax = CheckParam("delta max fan", params5[6], 10)
        else:
            Domoticz.Error("Error reading Mode5 parameters")

        # Check if the used control mode is ok
        if (Devices[1].sValue == "20"):
            self.ModeAuto = True
            self.powerOn = 1

        elif (Devices[1].sValue == "30"):
            self.ModeAuto = False
            self.powerOn = 1

        elif (Devices[1].sValue == "10"):
            self.ModeAuto = False
            self.powerOn = 0

        # reset presence detection when starting the plugin.
        self.Presencemode = False
        self.PresenceSensor = False
        self.Presence = False
        self.PresenceTH = False
        #self.DTtempo =  (datetime.now() - timedelta(seconds=40))
        self.presencechangedtime = datetime.now()
        self.PresenceDetected = False

        # reset time info when starting the plugin.
        self.controlinfotime = datetime.now()
        self.PLUGINstarteddtime = datetime.now()

        # update temp
        self.readTemps()

        # update widget values
        # self.CAC221widgetcontrol()

    def onStop(self):
        Domoticz.Log("onStop called")
        Domoticz.Debugging(0)

    def onCommand(self, Unit, Command, Level, Color):
        Domoticz.Log(
            "onCommand called for Unit " + str(Unit) + ": Parameter '" + str(Command) + "', Level: " + str(Level))

        now = datetime.now()

        # Thermostat control
        if (Unit == 1):
            Devices[1].Update(nValue=self.powerOn, sValue=str(Level))
            if (Devices[1].sValue == "20"):  # Mode auto
                self.ModeAuto = True
                self.powerOn = 1
                Devices[2].Update(nValue=self.powerOn, sValue="30")  # AC mode Heat
                Devices[3].Update(nValue=self.powerOn, sValue="10")  # AC Fan Speed Auto

            elif (Devices[1].sValue == "30"):  # Mode manuel
                self.ModeAuto = False
                self.powerOn = 1

            elif (Devices[1].sValue == "10"):  # Arret
                self.powerOn = 0
                self.ModeAuto = False
                Devices[1].Update(nValue=0, sValue="10")
                for idx in self.WACmode:
                    DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level=0".format(idx))

            # Update devices
            Devices[1].Update(nValue=self.powerOn, sValue=Devices[1].sValue)
            Devices[2].Update(nValue=self.powerOn, sValue=Devices[2].sValue)
            Devices[3].Update(nValue=self.powerOn, sValue=Devices[3].sValue)
            self.onHeartbeat()

        if (Unit == 2):  # AC Manual mode
            Devices[2].Update(nValue=self.powerOn, sValue=str(Level))

        if (Unit == 3):  # AC Manual Fan speed
            Devices[3].Update(nValue=self.powerOn, sValue=str(Level))

        if (Unit == 4):  # Forced ECO
            if self.powerOn :
                Devices[4].Update(self.powerOn, sValue=Devices[4].sValue)
                Domoticz.Debug("Forced ECO Requested")
                self.ForcedEco = True
                self.ForcedEcoTime = datetime.now()

        if (Unit == 5):  # AC Manual Fan speed
            Devices[5].Update(nValue=self.powerOn, sValue=str(Level))
            self.setpoint = round(float(Devices[5].sValue))

        self.onHeartbeat()

    def onHeartbeat(self):
        Domoticz.Debug("onHeartbeat called")
        # fool proof checking.... based on users feedback
        if not all(device in Devices for device in (1, 2, 3, 4, 5, 6, 7, 8)):
            Domoticz.Error("one or more devices required by the plugin is/are missing, please check domoticz device creation settings and restart !")
            return

        self.pluginsetpoint = round(float(Devices[5].sValue))

        now = datetime.now()

        # check if CAC widget are ok
        self.CAC221widgetcontrol()
        # check presence detection
        self.PresenceDetection()

        if self.ForcedEco:
            #if self.ForcedECOoffdelay != 0
            if self.ForcedEcoTime + timedelta(minutes=self.ForcedECOoffdelay) <= now:
                self.ForcedEco = False
                Domoticz.Debug("Forced ECO not Request anymore")
                if Devices[4].nValue == 1:
                    Devices[4].Update(nValue=0, sValue=Devices[4].sValue)
        else:
            if Devices[4].nValue == 1:
                Devices[4].Update(nValue=0, sValue=Devices[4].sValue)


        # Check the mode, used setpoint and fan speed is ok
        if not self.powerOn:
            if not self.WACmodevalue == 0:
                for idx in self.WACmode:
                    DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level=0".format(idx))
                    Domoticz.Debug("WACmode isn't at good Level at '{}'- Updating AC mode widget Level at '0'".format(self.WACmodevalue))
                #self.WACmodevalue = 0
        else:
            if self.ModeAuto: # Auto Mode

# CHOOSING AC SETPOINT IN AUTO MODE ------------------------------------------------------------------------------------

                # Choose AC setpoint if presence or not and check if AC setpoint is over and need adjustment
                if self.PresenceTH: # We use normal thermostat setpoint for confort
                    self.setpoint = round(float(Devices[5].sValue))
                else:  # No presence detected so we use reducted thermosat setpoint
                    self.setpoint = round(float(Devices[5].sValue) - self.reductedsp)
                self.overheatvalue = (self.intemp - self.setpoint)
                self.setpointadjusted = (self.setpoint - self.overheatvalue)
                self.setpoint = round(self.setpointadjusted)
                Domoticz.Debug("Overheat value is '{}' - New AC Setpoint after correction is '{}'".format(self.overheatvalue, self.setpoint))

                if self.PresenceTH:
                    if self.intemp < (float(Devices[5].sValue)):
                        self.overheat = False
                        if self.setpointadjusted < 17:
                            self.setpointadjusted = 17
                            self.setpoint = 17
                        Domoticz.Debug("NO Overheat - AC Setpoint without correction is '{}'".format(self.setpoint))

                else : # No presence detected so we use reducted thermosat setpoint
                    if self.intemp < (float(Devices[5].sValue)- self.reductedsp):
                        self.overheat = False
                        if self.setpointadjusted < 17:
                            self.setpointadjusted = 17
                            self.setpoint = 17
                        Domoticz.Debug("NO Overheat - AC Setpoint without correction is '{}'".format(self.setpoint))

# OVERHEAT ----------------------------------------------------------------------------------------------------------

                # check if overheat
                if self.setpoint < 17:
                    if not self.overheat:
                        self.overheat = True
                        self.Turbofan = False
                        self.Turbopower = False
                else:
                    self.overheat = False
                    #self.setpoint = self.septpointadjusted

                # force heating mode or fan if overheat
                if self.overheat :
                    Domoticz.Debug("AC present overheating of '{}' - Setpoint is '{}' for Room Temp '{}'".format(self.overheatvalue, self.setpoint, self.intemp))
                    if not self.WACmodevalue == 50:
                        for idx in self.WACmode:
                            DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level=50".format(idx))
                        Domoticz.Debug("WACmode isn't at good Level at '{}'- Updating AC mode widget Level at '50' for fan only".format(self.WACmodevalue))
                    if not self.WACfanspeedvalue == 20:
                        for idx in self.WACfanspeed:
                            DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level=20".format(idx))
                        Domoticz.Debug("WACfanspeed isn't at good Level at '{}'- Updating AC fanspeed widget Level at '20'".format(self.WACfanspeedvalue))
                else : # no overheating, so heating Mode and auto control
                    Domoticz.Debug("AC no present overheat - Setpoint is '{}' for Room Temp '{}'".format(self.setpoint, self.intemp))
                    if not self.WACmodevalue == 30:
                        for idx in self.WACmode:
                            DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level=30".format(idx))
                        Domoticz.Debug("WACmode isn't at good Level at '{}'- Updating AC mode widget Level at '30' for heating".format(self.WACmodevalue))

# NORMAL AUTO MODE -----------------------------------------------------------------------------------------------------
                    if not self.PresenceTH:
                        self.Turbofan = False
                        self.Turbopower = False
                    else :
                    # check if turbo needed
                        if self.intemp < (float(Devices[5].sValue) - (self.deltamax / 10)):
                            self.Turbofan = True
                        if self.intemp < (float(Devices[5].sValue) - ((self.deltamax / 10) + (self.deltamax / 20))):
                            self.Turbopower = True

                    # check if Turbofan is on
                    if self.Turbofan:  # Turbofan is on
                        Domoticz.Debug("AUTOMode - Turbofan ON - Fan speed high because room temp is too far from delta min setpoint")
                        if not Devices[3].sValue == "40":
                            Devices[3].Update(nValue=self.powerOn, sValue="40")
                        if not self.WACfanspeedvalue == 40:
                            for idx in self.WACfanspeed:
                                DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level=40".format(idx))
                                Domoticz.Debug("WACfanspeed isn't at good Level at '{}'- Updating AC fanspeed widget Level at '40'".format(self.WACfanspeedvalue))
                            # check if turbofan still needed or not
                            if self.intemp > (float(Devices[5].sValue) - (self.deltamax / 100)):
                                self.Turbofan = False
                    else:  # Turbofan is off
                        Domoticz.Debug("AUTOMode - Turbofan OFF - Fan speed auto because room temp is near from setpoint")
                        if not Devices[3].sValue == "10":
                            Devices[3].Update(nValue=self.powerOn, sValue="10")
                        if not self.WACfanspeedvalue == 10:
                            for idx in self.WACfanspeed:
                                DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level=10".format(idx))
                            Domoticz.Debug("WACfanspeed isn't at good Level at '{}'- Updating AC fanspeed widget Level at '10'".format(self.WACfanspeedvalue))

                    # check if Turbopower is on
                    if self.Turbopower:  # Turbopower is on
                        self.setpoint = 30
                        Domoticz.Debug("AUTOMode - Turbopower ON - Used setpoint is Max '30' because room temp is lower more than delta min from setpoint")
                        if not self.WACsetpointvalue == self.setpoint:
                            for idx in self.WACsetpoint:
                                DomoticzAPI("type=command&param=setsetpoint&idx={}&setpoint={}".format(idx, self.setpoint))
                            Domoticz.Debug("AC Setpoint is not ok - Updating AC setpoint to : " + str(self.setpoint))
                                # self.WACsetpointvalue = self.setpoint
                        # check if turbopower still needed or not
                            if self.intemp > (float(Devices[5].sValue) - (self.deltamax / 20)):
                                self.Turbopower = False
                    else:  # Turbopower is off
                        Domoticz.Debug("AUTOMode - Turbopower OFF - Used setpoint is normal : " + str(self.setpoint))
                        self.setpoint = round(self.setpointadjusted)
                        if not self.WACsetpointvalue == self.setpoint:
                            for idx in self.WACsetpoint:
                                DomoticzAPI("type=command&param=setsetpoint&idx={}&setpoint={}".format(idx, self.setpoint))
                            Domoticz.Debug("AC Setpoint is not ok - Updating AC setpoint to : " + str(self.setpoint))


# MANUAL MODE ----------------------------------------------------------------------------------------------------------
            else: # Manual Mode
                self.setpoint = round(float(Devices[5].sValue))
                # check manual asked mode
                if Devices[2].sValue == "10":
                    self.WACmodevaluenew = 10
                elif Devices[2].sValue == "20":
                    self.WACmodevaluenew = 20
                elif Devices[2].sValue == "30":
                    self.WACmodevaluenew = 30
                elif Devices[2].sValue == "40":
                    self.WACmodevaluenew = 40
                elif Devices[2].sValue == "50":
                    self.WACmodevaluenew = 50
                # check if wac is ok
                if not self.WACmodevaluenew == self.WACmodevalue:
                    for idx in self.WACmode:
                        DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level={}".format(idx,self.WACmodevaluenew))
                    Domoticz.Debug("Manual mode - MODE = {}".format(self.WACmodevaluenew))
                if not Devices[3].sValue == str(self.WACfanspeedvalue):
                    for idx in self.WACfanspeed:
                        DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level={}".format(idx,str(Devices[3].sValue)))
                    Domoticz.Debug("Manual mode - FANSPEED = {}".format(self.WACfanspeedvalue))
                if not self.WACsetpointvalue == self.setpoint:
                    for idx in self.WACsetpoint:
                        DomoticzAPI("type=command&param=setsetpoint&idx={}&setpoint={}".format(idx, self.setpoint))
                    Domoticz.Debug("AC Setpoint is not ok - Updating AC setpoint to : " + str(self.setpoint))

# READING ROOM TEMP ----------------------------------------------------------------------------------------------------
        if self.nexttemps + timedelta(minutes=2) <= now:
            self.readTemps()

# NORMAL LOG -----------------------------------------------------------------------------------------------------------
        if self.powerOn:
            if self.ModeAuto:
                Domoticz.Log("System ON - AUTO - Room Temp : {}ºC - System Setpoint : '{}' - Aircon Setpoint : '{}' ".format(self.intemp, self.pluginsetpoint, self.setpoint))
            else:
                Domoticz.Log("System ON - MANUAL - Room Temp : {}ºC - System Setpoint : '{}' - Aircon Setpoint : '{}' ".format(self.intemp, self.pluginsetpoint, self.setpoint))
        else:
            Domoticz.Log("System OFF")


    def readTemps(self):
        Domoticz.Debug("readTemps called")
        self.nexttemps = datetime.now()
        # fetch all the devices from the API and scan for sensors
        noerror = True
        listintemps = []
        devicesAPI = DomoticzAPI("type=devices&filter=temp&used=true&order=Name")
        if devicesAPI:
            for device in devicesAPI["result"]:  # parse the devices for temperature sensors
                idx = int(device["idx"])
                if idx in self.InTempSensors:
                    if "Temp" in device:
                        Domoticz.Debug("device: {}-{} = {}".format(device["idx"], device["Name"], device["Temp"]))
                        listintemps.append(device["Temp"])
                    else:
                        Domoticz.Error("device: {}-{} is not a Temperature sensor".format(device["idx"], device["Name"]))

        # calculate the average inside temperature
        nbtemps = len(listintemps)
        if nbtemps > 0:
            self.intemp = round(sum(listintemps) / nbtemps, 1)
            Devices[7].Update(nValue=0,
                              sValue=str(self.intemp))  # update the dummy device showing the current thermostat temp
        else:
            Domoticz.Debug("No Inside Temperature found... ")
            noerror = False

        self.WriteLog("Inside Temperature = {}".format(self.intemp), "Verbose")
        return noerror

    def PresenceDetection(self):

        Domoticz.Debug("PresenceDetection called")

        now = datetime.now()

        if self.ForcedEco or Parameters["Mode3"] == "":
            if self.ForcedEco :
                Domoticz.Debug("Forced ECO active...")
                self.PresenceTH = False
            if Parameters["Mode3"] == "":
                Domoticz.Debug("Presence detection mode = NO...")
                self.PresenceTH = True
            self.Presencemode = False
            self.Presence = False
            self.PresenceSensor = False
            if Devices[6].nValue == 1:
                Devices[6].Update(nValue=0, sValue=Devices[6].sValue)

        else:
            self.Presencemode = True
            Domoticz.Debug("presence detection mode = YES...")

            # Build list of DT switches, with their current status
            PresenceDT = {}
            devicesAPI = DomoticzAPI("type=devices&filter=light&used=true&order=Name")
            if devicesAPI:
                for device in devicesAPI["result"]:  # parse the presence/motion sensors (DT) device
                    idx = int(device["idx"])
                    if idx in self.DTpresence:  # this is one of our DT
                        if "Status" in device:
                            PresenceDT[idx] = True if device["Status"] == "On" else False
                            Domoticz.Debug("DT switch idx '{}' - '{}' currently is '{}'".format(idx, device["Name"], device["Status"]))
                            if device["Status"] == "On":
                                self.DTtempo = datetime.now()

                        else:
                            Domoticz.Error("Device with idx '{}' and named '{}' does not seem to be a DT !".format(idx, device["Name"]))

            # fool proof checking....
            if len(PresenceDT) == 0:
                Domoticz.Error("none of the devices in the 'dt' parameter is a dt... no action !")
                self.Presencemode = False
                self.Presence = False
                self.PresenceTH = True
                self.PresenceTHdelay = datetime.now()
                self.PresenceSensor = False
                return

            if self.DTtempo + timedelta(seconds=30) >= now:
                self.PresenceDetected = True
                Domoticz.Debug("At mini 1 DT is ON or was ON in the past 30 seconds...")
            else:
                self.PresenceDetected = False

            if self.PresenceDetected:
                if self.PresenceSensor:
                    Domoticz.Debug("presence detected but already registred...")
                else:
                    Domoticz.Debug("new presence detected...")
                    self.PresenceSensor = True
                    self.Presence = True
                    self.presencechangedtime = datetime.now()

            else:
                if not self.PresenceSensor:
                    Domoticz.Debug("No presence detected DT already OFF...")
                else:
                    Domoticz.Debug("No presence detected in the past 30 seconds...")
                    self.PresenceSensor = False
                    self.Presence = False
                    self.presencechangedtime = datetime.now()

            if self.Presence:
                if not self.PresenceTH:
                    if self.presencechangedtime + timedelta(minutes=self.presenceondelay) <= now:
                        Domoticz.Debug("Presence is now ACTIVE !")
                        self.PresenceTH = True
                        self.PresenceTHdelay = datetime.now()
                        Devices[6].Update(nValue=1, sValue=Devices[6].sValue)

                    else:
                        Domoticz.Debug("Presence is INACTIVE but in timer ON period !")
                elif self.PresenceTH:
                    Domoticz.Debug("Presence is ACTIVE !")
            else:
                if self.PresenceTH:
                    if self.presencechangedtime + timedelta(minutes=self.presenceoffdelay) <= now:
                        Domoticz.Debug("Presence is now INACTIVE because no DT since more than X minutes !")
                        self.PresenceTH = False

                    else:
                        Domoticz.Debug("Presence is ACTIVE but in timer OFF period !")
                else:
                    Domoticz.Debug("Presence is INACTIVE !")
                    if Devices[6].nValue == 1:
                        Devices[6].Update(nValue=0, sValue=Devices[6].sValue)

    def CAC221widgetcontrol(self):

        Domoticz.Debug("CAC221widgetcontrol called")

        devicesAPI = DomoticzAPI("type=devices&filter=all&used=true&order=Name")
        if devicesAPI:
            for device in devicesAPI["result"]:  # parse the device for finding widget of the cac
                idx = int(device["idx"])
                if idx in self.WACmode:
                    Domoticz.Debug("WACmode - idx '{}' - '{}' - Level is '{}' ".format(idx, device["Name"], device["Level"]))
                    self.WACmodevalue = device["Level"]
                    #Domoticz.Debug("Updating AC mode widget Level at '{}'".format(self.WACmodevalue))
                if idx in self.WACfanspeed:
                    Domoticz.Debug("WACfanspeed - idx '{}' - '{}' - Level is '{}' ".format(idx, device["Name"], device["Level"]))
                    self.WACfanspeedvalue = device["Level"]
                    #Domoticz.Debug("Updating AC fanspeed widget Level at '{}'".format(self.WACfanspeedvalue))
                if idx in self.WACsetpoint:
                    self.WACsetpointvalueBrut = device["SetPoint"]
                    self.WACsetpointvalue = round(float(self.WACsetpointvalueBrut))
                    Domoticz.Debug("WACsetpoint -  idx '{}' - '{}' -  Setpoint is '{}' ".format(idx, device["Name"], device["SetPoint"]))
                    Domoticz.Debug("CAC SETPOINT IS = {}".format(self.WACsetpointvalue))

    def WriteLog(self, message, level="Normal"):

        if self.loglevel == "Verbose" and level == "Verbose":
            Domoticz.Log(message)
        elif level == "Normal":
            Domoticz.Log(message)


# Plugin functions ---------------------------------------------------

global _plugin
_plugin = BasePlugin()


def onStart():
    global _plugin
    _plugin.onStart()


def onStop():
    global _plugin
    _plugin.onStop()


def onCommand(Unit, Command, Level, Color):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Color)


def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()


# Plugin utility functions ---------------------------------------------------


def parseCSV(strCSV):
    listvals = []
    for value in strCSV.split(","):
        try:
            val = int(value)
        except:
            pass
        else:
            listvals.append(val)
    return listvals


def DomoticzAPI(APICall):
    resultJson = None
    url = "http://127.0.0.1:8080/json.htm?{}".format(parse.quote(APICall, safe="&="))
    Domoticz.Debug("Calling domoticz API: {}".format(url))
    try:
        req = request.Request(url)
        # if Parameters["Username"] != "":
        #     Domoticz.Debug("Add authentification for user {}".format(Parameters["Username"]))
        #     credentials = ('%s:%s' % (Parameters["Username"], Parameters["Password"]))
        #     encoded_credentials = base64.b64encode(credentials.encode('ascii'))
        #     req.add_header('Authorization', 'Basic %s' % encoded_credentials.decode("ascii"))

        response = request.urlopen(req)
        if response.status == 200:
            resultJson = json.loads(response.read().decode('utf-8'))
            if resultJson["status"] != "OK":
                Domoticz.Error("Domoticz API returned an error: status = {}".format(resultJson["status"]))
                resultJson = None
        else:
            Domoticz.Error("Domoticz API: http error = {}".format(response.status))
    except:
        Domoticz.Error("Error calling '{}'".format(url))
    return resultJson


def CheckParam(name, value, default):
    try:
        param = int(value)
    except ValueError:
        param = default
        Domoticz.Error(
            "Parameter '{}' has an invalid value of '{}' ! defaut of '{}' is instead used.".format(name, value,
                                                                                                   default))
    return param


# Generic helper functions
def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug("'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Debug("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Debug("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Debug("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Debug("Device nValue:    " + str(Devices[x].nValue))
        Domoticz.Debug("Device sValue:   '" + Devices[x].sValue + "'")
        Domoticz.Debug("Device LastLevel: " + str(Devices[x].LastLevel))
    return
