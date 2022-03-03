"""
AC Aircon Smart Remote plugin using CASA.IA CAC 221 for Domoticz
Author: MrErwan,
Version:    0.0.1: alpha
Version:    0.1.1: beta
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
        <param field="Mode5" label="Day/Night Activator, Pause On delay, Pause Off delay, Presence On delay, Presence Off delay (all in minutes), reducted T(in degree), Delta max fanspeed (in in tenth of degre)" width="200px" required="true" default="0,1,1,2,45,3,5"/>
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
        self.setpoint = 21.0
        self.WACmodevalue = 0
        self.WACfanspeedvalue = 0
        self.WACsetpointvalue = 21.0
        self.WACmodevaluenew = 0
        self.WACfanspeedvaluenew = 0
        self.WACsetpointvaluenew = 21.0
        self.deltamax = 10  # allowed deltamax from setpoint for high level airfan
        self.ModeAuto = True
        self.DTpresence = []
        self.Presencemode = False
        self.Presence = False
        self.PresenceTH = False
        self.PresenceTHdelay = datetime.now()
        self.presencechangedtime = datetime.now()
        self.PresenceDetected = False
        self.DTtempo = datetime.now()
        self.presenceondelay = 2  # time between first detection and last detection before turning presence ON
        self.presenceoffdelay = 45  # time between last detection before turning presence OFF
        self.pauseondelay = 1
        self.pauseoffdelay = 1
        self.pause = False
        self.pauserequested = False
        self.pauserequestchangedtime = datetime.now()
        self.reductedsp = 3
        self.InTempSensors = []
        self.intemp = 25.0
        self.nexttemps = datetime.now()
        self.controlinfotime = datetime.now()
        self.controlsettime = datetime.now()
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
            Domoticz.Device(Name="Presence sensor", Unit=4, TypeName="Switch", Image=9).Create()
            devicecreated.append(deviceparam(4, 0, ""))  # default is Off
        if 5 not in Devices:
            Domoticz.Device(Name="Thermostat Setpoint", Unit=5, Type=242, Subtype=1, Used=1).Create()
            devicecreated.append(deviceparam(5, 0, "21"))  # default is 21 degrees
        if 6 not in Devices:
            Domoticz.Device(Name="Presence Active", Unit=6, TypeName="Switch", Image=9, Used=1).Create()
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
            self.pauseoffdelay = CheckParam("Pause Off Delay", params5[2], 1)
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
        Devices[4].Update(nValue=0, sValue=Devices[4].sValue)
        self.Presencemode = False
        self.Presence = False
        self.PresenceTH = False
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

        if (Unit == 5):  # AC Manual Fan speed
            Devices[5].Update(nValue=self.powerOn, sValue=str(Level))
            self.setpoint = float(Devices[5].sValue)

        self.onHeartbeat()

    def onHeartbeat(self):
        Domoticz.Debug("onHeartbeat called")
        # fool proof checking.... based on users feedback
        if not all(device in Devices for device in (1, 2, 3, 4, 5, 6, 7, 8)):
            Domoticz.Error(
                "one or more devices required by the plugin is/are missing, please check domoticz device creation settings and restart !")
            return

        now = datetime.now()

        # check if CAC widget are ok
        self.CAC221widgetcontrol()
        # check presence detection
        self.PresenceDetection()

        # Check if the mode, used setpoint and fan speed is ok
        if not self.powerOn:
            if not self.WACmodevalue == 0:
                for idx in self.WACmode:
                    DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level=0".format(idx))
                self.WACmodevalue = 0
        else:
            if self.ModeAuto:
                if not self.WACmodevalue == 20:
                    for idx in self.WACmode:
                        DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level=20".format(idx))
                    self.WACmodevalue = 20
                if self.PresenceTH:
                    if self.intemp < (float(Devices[5].sValue) - ((self.deltamax / 10) + (self.deltamax / 20))):
                        self.setpoint = 30.0
                        Domoticz.Debug(
                            "AUTOMode - used setpoint is Max 30 and fan speed Max because room temp is lower more than delta min from setpoint")
                        #AC setpoint = max setpoint
                        if not self.WACsetpointvalue == self.setpoint:
                            for idx in self.WACsetpoint:
                                DomoticzAPI(
                                    "type=command&param=setsetpoint&idx={}&setpoint={}".format(idx, self.setpoint))
                            self.WACsetpointvalue = self.setpoint
                        # AC Fan Speed High
                        if not Devices[3].sValue == "40":
                            Devices[3].Update(nValue=self.powerOn, sValue="40")
                        if not self.WACfanspeedvalue == 40:
                            for idx in self.WACfanspeed:
                                DomoticzAPI(
                                    "type=command&param=switchlight&idx={}&switchcmd=Set Level&level=40".format(idx))
                            self.WACfanspeedvalue = 40
                    else:
                        self.setpoint = float(Devices[5].sValue)
                        Domoticz.Debug("AUTOMode - used setpoint is normal : " + str(self.setpoint))
                        # AC setpoint = thermostat setpoint
                        if not self.WACsetpointvalue == self.setpoint:
                            for idx in self.WACsetpoint:
                                DomoticzAPI(
                                    "type=command&param=setsetpoint&idx={}&setpoint={}".format(idx, self.setpoint))
                            self.WACsetpointvalue = self.setpoint
                        if self.intemp < (float(Devices[5].sValue) - (self.deltamax / 10)):
                            # AC Fan Speed High
                            if not Devices[3].sValue == "40":
                                Devices[3].Update(nValue=self.powerOn, sValue="40")
                                Domoticz.Debug(
                                    "Fan speed high because room temp is lower more than delta min from setpoint")
                            if not self.WACfanspeedvalue == 40:
                                for idx in self.WACfanspeed:
                                    DomoticzAPI(
                                        "ype=command&param=switchlight&idx={}&switchcmd=Set Level&level=40".format(idx))
                                self.WACfanspeedvalue = 40
                        else:
                            # AC Fan Speed Auto
                            if not Devices[3].sValue == "10":
                                Devices[3].Update(nValue=self.powerOn, sValue="10")
                                Domoticz.Debug("Fan speed auto because room temp is near from setpoint")
                            if not self.WACfanspeedvalue == 10:
                                for idx in self.WACfanspeed:
                                    DomoticzAPI(
                                        "ype=command&param=switchlight&idx={}&switchcmd=Set Level&level=10".format(idx))
                                self.WACfanspeedvalue = 10

                else:
                    self.setpoint = (float(Devices[5].sValue) - self.reductedsp)
                    if self.setpoint < 17:  # Setpoint Lower than range 17 to 30
                        self.setpoint = 17.0
                    Domoticz.Debug("AUTOMode - used setpoint is reducted one : " + str(self.setpoint))
                    if not self.WACsetpointvalue == self.setpoint:
                        # AC setpoint = Thermostat setpoint reducted in limit of range
                        for idx in self.WACsetpoint:
                            DomoticzAPI("type=command&param=setsetpoint&idx={}&setpoint={}".format(idx, self.setpoint))
                        self.WACsetpointvalue = self.setpoint
                    if not Devices[3].sValue == "10":
                        Devices[3].Update(nValue=self.powerOn, sValue="10")
                        Domoticz.Debug("Fan speed auto because room temp is near from setpoint")
                    if not self.WACfanspeedvalue == 10:
                        for idx in self.WACfanspeed:
                            DomoticzAPI(
                                "type=command&param=switchlight&idx={}&switchcmd=Set Level&level=10".format(idx))
                        self.WACfanspeedvalue = 10

            else:
                Domoticz.Log("MANUAL mode")
                self.setpoint = float(Devices[5].sValue)
                # check manual asked mode
                if Devices[2].sValue == "10":
                    self.WACmodevaluenew = 10
                elif Devices[2].sValue == "20":
                    self.WACmodevaluenew = 10
                elif Devices[2].sValue == "30":
                    self.WACmodevaluenew = 20
                elif Devices[2].sValue == "40":
                    self.WACmodevaluenew = 30
                # check if wac is ok
                if not self.WACmodevaluenew == self.WACmodevalue:
                    # self.WACmodevalue = self.WACmodevaluenew
                    for idx in self.WACmode:
                        DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level={}".format(idx,self.WACmodevalue))
                    Domoticz.Debug("Manual mode - MODE = {}".format(self.WACmodevalue))
                if not Devices[3].sValue == str(self.WACfanspeedvalue):
                    # self.WACfanspeedvalue = str(Devices[3].sValue)
                    for idx in self.WACfanspeed:
                        DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level={}".format(idx,str(Devices[3].sValue)))
                    Domoticz.Debug("Manual mode - FANSPEED = {}".format(self.WACfanspeedvalue))
                if not self.WACsetpointvalue == self.setpoint:
                    # self.WACsetpointvalue = self.setpoint
                    for idx in self.WACsetpoint:
                        DomoticzAPI("type=command&param=setsetpoint&idx={}&setpoint={}".format(idx, self.setpoint))
                    Domoticz.Debug("Manual mode - SETPOINT = {}".format(self.WACsetpointvalue))

        if self.nexttemps + timedelta(minutes=2) <= now:
            self.readTemps()

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
                        Domoticz.Error(
                            "device: {}-{} is not a Temperature sensor".format(device["idx"], device["Name"]))

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

        if Parameters["Mode3"] == "":
            Domoticz.Debug("presence detection mode = NO...")
            self.Presencemode = False
            self.Presence = False
            self.PresenceTH = True
            if Devices[4].nValue == 1 or Devices[6].nValue == 1:
                Devices[4].Update(nValue=0, sValue=Devices[4].sValue)
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
                            Domoticz.Debug("DT switch {} currently is '{}'".format(idx, device["Status"]))
                            if device["Status"] == "On":
                                self.DTtempo = datetime.now()

                        else:
                            Domoticz.Error("Device with idx={} does not seem to be a DT !".format(idx))

            # fool proof checking....
            if len(PresenceDT) == 0:
                Domoticz.Error("none of the devices in the 'dt' parameter is a dt... no action !")
                self.Presencemode = False
                self.Presence = False
                self.PresenceTH = True
                self.PresenceTHdelay = datetime.now()
                Devices[4].Update(nValue=0, sValue=Devices[4].sValue)
                return

            if self.DTtempo + timedelta(seconds=30) >= now:
                self.PresenceDetected = True
                Domoticz.Debug("At mini 1 DT is ON or was ON in the past 30 seconds...")
            else:
                self.PresenceDetected = False

            if self.PresenceDetected:
                if Devices[4].nValue == 1:
                    Domoticz.Debug("presence detected but already registred...")
                else:
                    Domoticz.Debug("new presence detected...")
                    Devices[4].Update(nValue=1, sValue=Devices[4].sValue)
                    self.Presence = True
                    self.presencechangedtime = datetime.now()

            else:
                if Devices[4].nValue == 0:
                    Domoticz.Debug("No presence detected DT already OFF...")
                else:
                    Domoticz.Debug("No presence detected in the past 30 seconds...")
                    Devices[4].Update(nValue=0, sValue=Devices[4].sValue)
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
            for device in devicesAPI["result"]:  # parse the presence/motion sensors (DT) device
                idx = int(device["idx"])
                if idx in self.WACmode:
                    Domoticz.Debug("WACmode with idx '{}' Named '{}' have a Leval at '{}' ".format(idx, device["Name"], device["Level"]))
                    self.WACmodevalue = device["Level"]
                    Domoticz.Debug("Updating AC mode widget Level = {}".format(self.WACmodevalue))
                if idx in self.WACfanspeed:
                    Domoticz.Debug("WACfanspeed with idx '{}' Named '{}' have a Leval at '{}' ".format(idx, device["Name"], device["Level"]))
                    self.WACfanspeedvalue = device["Level"]
                    Domoticz.Debug("Updating AC fanspeed widget Level = {}".format(self.WACfanspeedvalue))
                if idx in self.WACsetpoint:
                    Domoticz.Debug("WACsetpoint with idx '{}' Named '{}' have a Leval at '{}' ".format(idx, device["Name"], device["SetPoint"]))

        # Check mode of CAC221s
        # url = "http://127.0.0.1:8080/json.htm?type=devices&rid=".format(self.WACmode)
        # Domoticz.Debug("Calling domoticz api for cheking cac mode : {}".format(url))
        # resultJson = json.loads(response.read().decode('utf-8'))
        # self.WACmodevalue =
        # Domoticz.Debug("AC mode widget Level = {}".format(self.WACmodevalue))
        
    # self.WACmodevalue =

    # APIjson1 = DomoticzAPI("type=devices&rid={}".format(self.WACmode))
    # if APIjson1:
    # for device in APIjson1["result"]:  # check if idx is ok
    # self.WACmodevalue = int(device["Level"])
    # Domoticz.Debug("AC mode widget Level = {}".format(self.WACmodevalue))

    # check fan
        #for idx in self.WACfanspeed:
            #devicesAPI = DomoticzAPI("type=devices&rid={}".format(idx))
            #Domoticz.Debug("WACfanspeed {} currently is '{}'".format(idx, device["Level"]))
        #Domoticz.Debug("Update WACfanspeedvalue to  = {}".format(self.WACfanspeedvalue))

        #devicesAPI = DomoticzAPI("type=devices&rid={}".format(self.WACfanspeed))
        #if devicesAPI:
            #for device in devicesAPI["result"]:  # check the level
                # self.WACfanspeedvalue = device["Level"]
                #Domoticz.Debug("AC fan widget Level from API is  = {}".format(device["Level"]))
                #Domoticz.Debug("Update WACfanspeedvalue to  = {}".format(self.WACfanspeedvalue))

                #if device["Level"] == 10 :
                    #self.WACfanspeedvalue = 10
                #if device["Level"] == 20 :
                    #self.WACfanspeedvalue = 20
                #if device["Level"] == 30 :
                    #self.WACfanspeedvalue = 30
                #if device["Level"] == 40 :
                    #self.WACfanspeedvalue = 40
    # self.WACfanspeedvalue = int(device["Level"]
    # Domoticz.Debug("AC fan widget Level = {}".format(self.WACfanspeedvalue))

    # check setpoint
    # APIjson = DomoticzAPI("type=devices&rid={}".format(self.WACsetpoint))
    # if APIjson:
    # for device in APIjson["result"]:  # check if idx is ok
    # self.WACsetpointvalue = int(device["SetPoint"])
    # str(self.WACsetpointvalue) = int(device["SetPoint"])
    # sValueNew = device["SetPoint"]
    # self.WACsetpointvalue = sValueNew
    # if (Devices[7].nValue != self.powerOn or Devices[7].sValue != sValueNew):
    # Devices[7].Update(nValue = self.powerOn,sValue = sValueNew)
    # Domoticz.Debug("AC setpoint = {}".format(self.WACsetpointvalue))

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
