#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# AC Aircon Smart Remote plugin using CASA.IA CAC 221 for Domoticz
# Author: MrErwan,
# Version:    0.0.1: alpha...
# Version:    2.1.1: overheat control
# Version:    2.1.2: IR order repeat
# Version:    3.1.1: Auto Coll mode

"""
<plugin key="AC-ASR-CAC221" name="AC Aircon Smart Remote PLUS for CAC221" author="MrErwan" version="3.1.1" externallink="https://github.com/Erwanweb/ASR-Plus-CAC221.git">
    <description>
        <h2>Aircon Smart Remote V3.1.1</h2><br/>
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
        <param field="Mode5" label="Day/Night Activator, Pause On delay, Forced Eco Off delay (0=not timed), Presence On delay, Presence Off delay (all in minutes), reducted T(in degree), Delta max fanspeed (in in tenth of degre), IR Repeat order (0 not activ.)" width="200px" required="true" default="0,1,15,1,45,4,5,30"/>
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

import json
import math
import urllib
import urllib.parse as parse
import urllib.request as request
from datetime import datetime, timedelta

import Domoticz
import requests

class deviceparam:

    def __init__(self, unit, nvalue, svalue):
        self.unit = unit
        self.nvalue = nvalue
        self.svalue = svalue
        self.debug = False


class BasePlugin:

    def __init__(self):
        # Initialisation des attributs critiques pour éviter les erreurs
        self.powerOn = 0
        self.ForcedEco = False
        # Initialisation des attributs nécessaires pour éviter les erreurs si appel avant onStart
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
        self.ModeAutoHeat = True
        self.ModeAutoCool = True
        self.DTpresence = []
        self.Presencemode = False
        self.ForcedEco = False
        self.PresenceDetected = False
        self.Presence = False
        self.PresenceTH = False
        self.PresenceSensor = False
        self.presenceondelay = 2  # time between first detection and last detection before turning presence ON
        self.presenceoffdelay = 45  # time between last detection before turning presence OFF
        self.pauseondelay = 1
        self.ForcedECOoffdelay = 30
        self.pause = False
        self.pauserequested = False
        self.reductedsp = 3
        self.InTempSensors = []
        self.intemp = 25.0
        self.overheat = False
        self.overheatvalue = 1
        # Log détaillé ajouté pour traçabilité du delta et des consignes en mode Auto Heat
        #Domoticz.Debug("AUTO HEAT LOG -- Room Temp: {:.2f}, Thermostat Setpoint: {:.2f}, Initial Delta: {:.2f}, Adjusted Overheatvalue: {}, Final Setpoint: {}".format(self.intemp,float(Devices[5].sValue),self.intemp - self.setpoint,self.overheatvalue,self.setpoint))
        self.undervalue = 1
        self.setpointnew = 21
        self.setpointadjusted = 21
        self.repeatorder = 0

        now = datetime.now()
        self.ForcedEcoTime = now
        self.PresenceTHdelay = now
        self.presencechangedtime = now
        self.DTtempo = now
        self.pauserequestchangedtime = now
        self.nexttemps = now
        self.controlinfotime = now
        self.controlsettime = now
        self.controloverheatvalue = now
        self.repeatordertime = now
        self.PLUGINstarteddtime = now

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
                       "LevelNames": "Disconnected|Off|Manual|Auto Heat|Auto Cool",
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
        if len(params5) == 8:
            self.DTDayNight = CheckParam("Day/Night Activator", params5[0], 0)
            self.pauseondelay = CheckParam("Pause On Delay", params5[1], 1)
            self.ForcedECOoffdelay = CheckParam("ForcedECO Off Delay", params5[2], 30)
            self.presenceondelay = CheckParam("Presence On Delay", params5[3], 2)
            self.presenceoffdelay = CheckParam("Presence Off Delay", params5[4], 45)
            self.reductedsp = CheckParam("Reduction temp", params5[5], 3)
            self.deltamax = CheckParam("delta max fan", params5[6], 10)
            self.repeatorder = CheckParam("repeat IR Order", params5[7], 0)
        else:
            Domoticz.Error("Error reading Mode5 parameters")

        # Check if the used control mode is ok
        if (Devices[1].sValue == "20"):
            self.ModeAutoHeat = False
            self.ModeAutoCool = False
            self.powerOn = 1

        elif (Devices[1].sValue == "30"):
            self.ModeAutoHeat = True
            self.ModeAutoCool = False
            self.powerOn = 1

        elif (Devices[1].sValue == "40"):
            self.ModeAutoHeat = False
            self.ModeAutoCool = True
            self.powerOn = 1

        elif (Devices[1].sValue == "10"):
            self.ModeAutoHeat = False
            self.ModeAutoCool = False
            # Défini à 0 pour éviter l'AttributeError dans onHeartbeat si appelé avant onStart
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

        # Set domoticz heartbeat to 20 s (onheattbeat() will be called every 20 )
        Domoticz.Heartbeat(20)

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
            if (Devices[1].sValue == "20"):  # Mode manuel
                self.ModeAutoHeat = False
                self.ModeAutoCool = False
                self.Turbofan = False
                self.Turbopower = False
                self.powerOn = 1

            elif (Devices[1].sValue == "30"):  # Mode auto heat
                self.ModeAutoHeat = True
                self.ModeAutoCool = False
                self.Turbofan = False
                self.Turbopower = False
                self.powerOn = 1
                Devices[2].Update(nValue=self.powerOn, sValue="30")  # AC mode Heat
                Devices[3].Update(nValue=self.powerOn, sValue="10")  # AC Fan Speed Auto

            elif (Devices[1].sValue == "40"):  # Mode auto cool
                self.ModeAutoHeat = False
                self.ModeAutoCool = True
                self.Turbofan = False
                self.Turbopower = False
                self.powerOn = 1
                Devices[2].Update(nValue=self.powerOn, sValue="20")  # AC mode Heat
                Devices[3].Update(nValue=self.powerOn, sValue="10")  # AC Fan Speed Auto

            elif (Devices[1].sValue == "10"):  # Arret
                # Défini à 0 pour éviter l'AttributeError dans onHeartbeat si appelé avant onStart
        self.powerOn = 0
                self.ModeAutoHeat = False
                self.ModeAutoCool = False
                self.Turbofan = False
                self.Turbopower = False
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

        # REPEAT IR ORDER -----------------------------------------------------------------------------------------------------
        # Modifié : répète les ordres IR même en mode manuel ou OFF si repeatorder > 0
        if self.repeatorder > 0:  # We repeat IR order to be sure AC received and take the good one
            Domoticz.Debug("Repeating IR Order is activated")
            if self.repeatordertime + timedelta(minutes=self.repeatorder) <= now:
                if self.powerOn:
                    for idx in self.WACfanspeed:
                        DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level={}".format(idx,self.WACfanspeedvalue))
                    for idx in self.WACmode:
                        DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level={}".format(idx,self.WACmodevalue))
                    for idx in self.WACsetpoint:
                        DomoticzAPI("type=command&param=setsetpoint&idx={}&setpoint={}".format(idx, self.setpoint))
                    Domoticz.Debug("-------------> Repeating IR Order in ACTIVE mode")
                else:
                    for idx in self.WACmode:
                        DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level=0".format(idx))
                    Domoticz.Debug("-------------> Repeating IR Order in OFF mode (forcing AC OFF)")
                self.repeatordertime = datetime.now()
        else:
            Domoticz.Debug("NO Repeating IR Order - Function is deactivated")

        # CHECK FORCED ECO PERIOD

        # CHECK FORCED ECO PERIOD ----------------------------------------------------------------------------------------------
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

        # MODE CHECK  ----------------------------------------------------------------------------------------------------------
        # Check the mode, used setpoint and fan speed is ok
        if not self.powerOn:
            if not self.WACmodevalue == 0:
                for idx in self.WACmode:
                    DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level=0".format(idx))
                    Domoticz.Debug("WACmode isn't at good Level at '{}'- Updating AC mode widget Level at '0'".format(self.WACmodevalue))
                    self.repeatordertime = datetime.now()
                #self.WACmodevalue = 0
        else :

# MODE AUTO HEAT ------------------------------------------------------------------------------------
            if self.ModeAutoHeat:  # Auto Mode Heat
                # CHOOSING AC SETPOINT IN AUTO HEAT MODE ------------------------------------------------------------------------------------
                # Choose AC setpoint if presence or not and check if AC setpoint is over and need adjustment
                if self.PresenceTH:  # We use normal thermostat setpoint for confort
                    self.setpoint = round(float(Devices[5].sValue))
                else:  # No presence detected so we use reducted thermosat setpoint
                    self.setpoint = round(float(Devices[5].sValue) - self.reductedsp)
                #self.overheatvalue = round((self.intemp - self.setpoint),1)
                if self.intemp >= (self.setpoint - 0.1) :
                    if self.intemp > (self.setpoint + 1.0) :
                        self.overheatvalue = round((self.intemp - self.setpoint) +4)
                    elif self.intemp > (self.setpoint + 0.5) :
                        self.overheatvalue = math.ceil((self.intemp - self.setpoint) +3)
                    elif self.intemp > (self.setpoint + 0.3) :
                        self.overheatvalue = math.ceil((self.intemp - self.setpoint) +2)
                    elif self.intemp > self.setpoint :
                        self.overheatvalue = math.ceil((self.intemp - self.setpoint) +1)
                    else :
                        #self.overheatvalue = math.ceil(self.intemp - self.setpoint)
                        self.overheatvalue = 1
                else :
                    self.overheatvalue = round((self.intemp - self.setpoint), 1)
                self.setpointadjusted = (self.setpoint - self.overheatvalue)
                self.setpoint = round(self.setpointadjusted)
                Domoticz.Debug("Delta between Room and setpoint is '{}' - New AC Setpoint after correction is '{}'".format(self.overheatvalue, self.setpoint))

                if self.PresenceTH:
                    if self.intemp < (float(Devices[5].sValue) - 0.2):
                        self.overheat = False
                        if self.setpoint < 17:
                            self.setpoint = 17
                        Domoticz.Debug("NO Overheat - AC Setpoint is '{}'".format(self.setpoint))

                else :  # No presence detected so we use reducted thermosat setpoint
                    if self.intemp < ((float(Devices[5].sValue) - 0.2) - self.reductedsp):
                        self.overheat = False
                        if self.setpoint < 17:
                            self.setpoint = 17
                        Domoticz.Debug("NO Overheat - No Presence - AC Reducted Setpoint is '{}'".format(self.setpoint))

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
                        self.repeatordertime = datetime.now()
                    if not self.WACfanspeedvalue == 20:
                        for idx in self.WACfanspeed:
                            DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level=20".format(idx))
                        Domoticz.Debug("WACfanspeed isn't at good Level at '{}'- Updating AC fanspeed widget Level at '20'".format(self.WACfanspeedvalue))
                        self.repeatordertime = datetime.now()
                else :  # no overheating, so heating Mode and auto control
                    Domoticz.Debug("AC no present overheat - Setpoint is '{}' for Room Temp '{}'".format(self.setpoint, self.intemp))
                    if not self.WACmodevalue == 30:
                        for idx in self.WACmode:
                            DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level=30".format(idx))
                        Domoticz.Debug("WACmode isn't at good Level at '{}'- Updating AC mode widget Level at '30' for heating".format(self.WACmodevalue))
                        self.repeatordertime = datetime.now()

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
                            self.repeatordertime = datetime.now()
                            # check if turbofan still needed or not
                        if self.intemp > (float(Devices[5].sValue) - (self.deltamax / 20)):
                            self.Turbofan = False
                    else:  # Turbofan is off
                        Domoticz.Debug("AUTOMode - Turbofan OFF - Fan speed auto because room temp is near from setpoint")
                        if not Devices[3].sValue == "10":
                            Devices[3].Update(nValue=self.powerOn, sValue="10")
                        if not self.WACfanspeedvalue == 10:
                            for idx in self.WACfanspeed:
                                DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level=10".format(idx))
                            Domoticz.Debug("WACfanspeed isn't at good Level at '{}'- Updating AC fanspeed widget Level at '10'".format(self.WACfanspeedvalue))
                            self.repeatordertime = datetime.now()

                    # check if Turbopower is on
                    if self.Turbopower:  # Turbopower is on
                        self.setpoint = 30
                        Domoticz.Debug("AUTOMode - Turbopower ON - Used setpoint is Max '30' because room temp is lower more than delta min from setpoint")
                        if not self.WACsetpointvalue == self.setpoint:
                            for idx in self.WACsetpoint:
                                DomoticzAPI("type=command&param=setsetpoint&idx={}&setpoint={}".format(idx, self.setpoint))
                            Domoticz.Debug("AC Setpoint is not ok - Updating AC setpoint to : " + str(self.setpoint))
                            self.repeatordertime = datetime.now()
                            # self.WACsetpointvalue = self.setpoint
                        # check if turbopower still needed or not
                        if self.intemp > (float(Devices[5].sValue) - (self.deltamax / 10)):
                            self.Turbopower = False
                    else:  # Turbopower is off
                        Domoticz.Debug("AUTOMode - Turbopower OFF - Used setpoint is normal : " + str(self.setpoint))
                        self.setpoint = round(self.setpointadjusted)
                        if not self.WACsetpointvalue == self.setpoint:
                            for idx in self.WACsetpoint:
                                DomoticzAPI("type=command&param=setsetpoint&idx={}&setpoint={}".format(idx, self.setpoint))
                            Domoticz.Debug("AC Setpoint is not ok - Updating AC setpoint to : " + str(self.setpoint))
                            self.repeatordertime = datetime.now()

# MODE AUTO COOL ------------------------------------------------------------------------------------
            elif self.ModeAutoCool:  # Auto Mode Cool
                # CHOOSING AC SETPOINT IN AUTO MODE ------------------------------------------------------------------------------------
                # Choose AC setpoint if presence or not and check if AC setpoint is over and need adjustment
                if self.PresenceTH: # We use normal thermostat setpoint for confort
                    self.setpoint = round(float(Devices[5].sValue))
                else: # No presence detected so we use reducted thermosat setpoint
                    self.setpoint = round(float(Devices[5].sValue) + self.reductedsp)
                if self.intemp <= (self.setpoint + 0.1):
                    if self.intemp < (self.setpoint - 1.0):
                        self.undervalue = round((self.setpoint - self.intemp) + 3)
                    elif self.intemp < (self.setpoint - 0.6):
                        self.undervalue = math.ceil((self.setpoint - self.intemp) + 2)
                    elif self.intemp < (self.setpoint - 0.3):
                        self.undervalue = math.ceil((self.setpoint - self.intemp) + 1)
                    elif self.intemp < self.setpoint :
                        self.undervalue = math.ceil(self.setpoint - self.intemp)
                    else:
                        self.undervalue = -1
                else:
                    self.undervalue = round(((self.setpoint - self.intemp)-1), 1)

                self.setpointadjusted = self.setpoint + self.undervalue
                self.setpoint = round(self.setpointadjusted)
                Domoticz.Debug( "AUTO COOL LOG -- Room Temp: {:.2f}, Thermostat Setpoint: {:.2f}, Initial Delta: {:.2f}, Adjusted Undervalue: {}, Final Setpoint: {}".format(
                        self.intemp,
                        float(Devices[5].sValue),
                        self.setpoint - self.intemp,
                        self.undervalue,
                        self.setpoint
                    ))
                Domoticz.Debug("Delta between Room and setpoint is '{}' - New AC Setpoint after correction is '{}'".format(self.undervalue, self.setpoint))
                
                if self.PresenceTH:
                    if self.intemp > (float(Devices[5].sValue) + 0.2):
                        self.overheat = False
                        if self.setpoint > 30:
                            self.setpoint = 30
                        Domoticz.Debug("NO Undercool - AC Setpoint is '{}'".format(self.setpoint))

                else:  # No presence detected so we use increased thermostat setpoint
                    if self.intemp > ((float(Devices[5].sValue) + 0.2) + self.reductedsp):
                        self.overheat = False
                        if self.setpoint > 30:
                            self.setpoint = 30
                        Domoticz.Debug("NO Undercool - No Presence - AC Increased Setpoint is '{}'".format(self.setpoint))


                # UNDERCOOL ----------------------------------------------------------------------------------------------------------
                # check if undercool
                if self.setpoint > 30:
                    if not self.overheat:
                        self.overheat = True
                        self.Turbofan = False
                        self.Turbopower = False
                else:
                    self.overheat = False

                # force fan only mode if undercool
                if self.overheat:
                    Domoticz.Debug("AC present undercooling of '{}' - Setpoint is '{}' for Room Temp '{}'".format(self.undervalue,self.setpoint,self.intemp))
                    if not self.WACmodevalue == 50:
                        for idx in self.WACmode:
                            DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level=50".format(idx))
                        Domoticz.Debug("WACmode isn't at good Level at '{}'- Updating AC mode widget Level at '50' for fan only".format(self.WACmodevalue))
                        self.repeatordertime = datetime.now()
                    if not self.WACfanspeedvalue == 20:
                        for idx in self.WACfanspeed:
                            DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level=20".format(idx))
                        Domoticz.Debug("WACfanspeed isn't at good Level at '{}'- Updating AC fanspeed widget Level at '20'".format(self.WACfanspeedvalue))
                        self.repeatordertime = datetime.now()
                else:  # no undercooling, so cooling Mode and auto control
                    Domoticz.Debug("AC no present undercooling - Setpoint is '{}' for Room Temp '{}'".format(self.setpoint,self.intemp))
                    if not self.WACmodevalue == 20:
                        for idx in self.WACmode:
                            DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level=20".format(idx))
                        Domoticz.Debug("WACmode isn't at good Level at '{}'- Updating AC mode widget Level at '20' for cooling".format( self.WACmodevalue))
                        self.repeatordertime = datetime.now()
                
                    # NORMAL AUTO MODE COOL -------------------------------------------------------------------------------
                    if not self.PresenceTH:
                        self.Turbofan = False
                        self.Turbopower = False
                    else :
                        # check if turbo needed
                        if self.intemp > (float(Devices[5].sValue) + (self.deltamax / 10)):
                            self.Turbofan = True
                        if self.intemp > (float(Devices[5].sValue) + ((self.deltamax / 10) + (self.deltamax / 20))):
                            self.Turbopower = True
    
                    # Mode Cool
                    if not self.WACmodevalue == 20:
                        for idx in self.WACmode:
                            DomoticzAPI(f"type=command&param=switchlight&idx={idx}&switchcmd=Set Level&level=20")
                        Domoticz.Debug(f"WACmode isn't at good Level '{self.WACmodevalue}' - Updating AC mode to Cool (20)")
                        self.repeatordertime = datetime.now()
    
                    # Fan Speed check if Turbofan is on
                    if self.Turbofan:
                        Domoticz.Debug("AUTOMode COOL- Turbofan ON - Fan speed high because room temp is too far from delta min setpoint")
                        if not Devices[3].sValue == "40":
                            Devices[3].Update(nValue=self.powerOn, sValue="40")
                        if not self.WACfanspeedvalue == 40:
                            for idx in self.WACfanspeed:
                                DomoticzAPI(f"type=command&param=switchlight&idx={idx}&switchcmd=Set Level&level=40")
                            Domoticz.Debug(f"WACfanspeed updated to High (40)")
                            self.repeatordertime = datetime.now()
                        # check if turbofan still needed or not
                        if self.intemp < (float(Devices[5].sValue) + (self.deltamax / 20)):
                            self.Turbofan = False
                    else: # Turbofan is off
                        Domoticz.Debug("AUTOMode COOL- Turbofan OFF - Fan speed auto because room temp is near from setpoint")
                        if not Devices[3].sValue == "10":
                            Devices[3].Update(nValue=self.powerOn, sValue="10")
                        if not self.WACfanspeedvalue == 10:
                            for idx in self.WACfanspeed:
                                DomoticzAPI(f"type=command&param=switchlight&idx={idx}&switchcmd=Set Level&level=10")
                            Domoticz.Debug(f"WACfanspeed updated to Auto (10)")
                            self.repeatordertime = datetime.now()

                    # check if Turbopower is on
                    if self.Turbopower:
                        self.setpoint = 17  # forcé pour refroidissement rapide
                        Domoticz.Debug(f"AUTO COOL - TurboPower ON - Forcing setpoint to 17")
                        if not self.WACsetpointvalue == self.setpoint:
                            for idx in self.WACsetpoint:
                                DomoticzAPI(f"type=command&param=setsetpoint&idx={idx}&setpoint={self.setpoint}")
                            Domoticz.Debug(f"Setpoint updated to: {self.setpoint}")
                            self.repeatordertime = datetime.now()
                        if self.intemp > (float(Devices[5].sValue) + (self.deltamax / 10)):
                            self.Turbopower = False
                    else:  # Turbopower is off
                        Domoticz.Debug("AUTOMode - Turbopower OFF - Used setpoint is normal : " + str(self.setpoint))
                        self.setpoint = round(self.setpointadjusted)
                        if not self.WACsetpointvalue == self.setpoint:
                            for idx in self.WACsetpoint:
                                DomoticzAPI("type=command&param=setsetpoint&idx={}&setpoint={}".format(idx, self.setpoint))
                            Domoticz.Debug("AC Setpoint is not ok - Updating AC setpoint to : " + str(self.setpoint))
                            self.repeatordertime = datetime.now()

# MANUAL MODE ----------------------------------------------------------------------------------------------------------
            else:  # Manual Mode
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
                    self.repeatordertime = datetime.now()
                    Domoticz.Debug("Manual mode - MODE = {}".format(self.WACmodevaluenew))
                if not Devices[3].sValue == str(self.WACfanspeedvalue):
                    for idx in self.WACfanspeed:
                        DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd=Set Level&level={}".format(idx,str(Devices[3].sValue)))
                    self.repeatordertime = datetime.now()
                    Domoticz.Debug("Manual mode - FANSPEED = {}".format(self.WACfanspeedvalue))
                if not self.WACsetpointvalue == self.setpoint:
                    for idx in self.WACsetpoint:
                        DomoticzAPI("type=command&param=setsetpoint&idx={}&setpoint={}".format(idx, self.setpoint))
                    self.repeatordertime = datetime.now()
                    Domoticz.Debug("AC Setpoint is not ok - Updating AC setpoint to : " + str(self.setpoint))

        # READING ROOM TEMP ----------------------------------------------------------------------------------------------------
        if self.nexttemps + timedelta(seconds=30) <= now:
            self.readTemps()

        # NORMAL LOG -----------------------------------------------------------------------------------------------------------
        if self.powerOn:
            if self.ModeAutoHeat:
                Domoticz.Log("System ON - AUTO HEAT - Room Temp : {}ºC - System Setpoint : '{}' - Aircon Setpoint : '{}' ".format(self.intemp, self.pluginsetpoint, self.setpoint))
            elif self.ModeAutoCool:
                Domoticz.Log("System ON - AUTO COOL - Room Temp : {}ºC - System Setpoint : '{}' - Aircon Setpoint : '{}' ".format(self.intemp, self.pluginsetpoint, self.setpoint))
            else:
                Domoticz.Log("System ON - MANUAL - Room Temp : {}ºC - System Setpoint : '{}' - Aircon Setpoint : '{}' ".format(self.intemp, self.pluginsetpoint, self.setpoint))
        else:
            Domoticz.Log("System OFF")

    # OTHER DEF -----------------------------------------------------------------------------------------------------------
    def readTemps(self):
        Domoticz.Debug("readTemps called")
        self.nexttemps = datetime.now()
        # fetch all the devices from the API and scan for sensors
        noerror = True
        listintemps = []
        devicesAPI = DomoticzAPI("type=command&param=getdevices&filter=temp&used=true&order=Name")
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
            devicesAPI = DomoticzAPI("type=command&param=getdevices&filter=light&used=true&order=Name")
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

        devicesAPI = DomoticzAPI("type=command&param=getdevices&filter=all&used=true&order=Name")
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
        value = value.strip()
        if value == "":
            continue
        try:
            val = int(value)
            listvals.append(val)
        except ValueError:
            try:
                val = float(value)
                listvals.append(val)
            except ValueError:
                Domoticz.Error(f"Skipping non-numeric value: '{value}'")
    return listvals



def DomoticzAPI(APICall):
    resultJson = None
    url = f"http://127.0.0.1:8080/json.htm?{parse.quote(APICall, safe='&=')}"

    try:
        Domoticz.Debug(f"Domoticz API request: {url}")
        req = request.Request(url)
        response = request.urlopen(req)

        if response.status == 200:
            resultJson = json.loads(response.read().decode('utf-8'))
            if resultJson.get("status") != "OK":
                Domoticz.Error(f"Domoticz API returned an error: status = {resultJson.get('status')}")
                resultJson = None
        else:
            Domoticz.Error(f"Domoticz API: HTTP error = {response.status}")

    except urllib.error.HTTPError as e:
        Domoticz.Error(f"HTTP error calling '{url}': {e}")

    except urllib.error.URLError as e:
        Domoticz.Error(f"URL error calling '{url}': {e}")

    except json.JSONDecodeError as e:
        Domoticz.Error(f"JSON decoding error: {e}")

    except Exception as e:
        Domoticz.Error(f"Error calling '{url}': {e}")

    return resultJson



def CheckParam(name, value, default):
    try:
        param = int(value)
    except ValueError:
        param = default
        Domoticz.Error( f"Parameter '{name}' has an invalid value of '{value}' ! defaut of '{param}' is instead used.")
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
