#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ATemporized presence detection plugin
# Author: MrErwan,
# Version:    0.0.1: alpha...

"""
<plugin key="PresenceManagerLite" name="Ronelabs- Presence Manager Lite" author="Erwanweb" version="1.1.0">
    <params>
        <param field="Mode1" label="IDX capteurs (séparés par des virgules)" width="400px" required="true" />
        <param field="Mode2" label="IDX relais à contrôler (séparés par des virgules)" width="400px" required="true" />
        <param field="Mode3" label="Temporisation présence (min)" width="100px" required="true" default="2"/>
        <param field="Mode4" label="Temporisation absence (min)" width="100px" required="true" default="30"/>
        <param field="Mode6" label="Log Level" width="200px">
            <options>
                <option label="Normal" value="Normal" default="true"/>
                <option label="Debug" value="Debug"/>
            </options>
        </param>
    </params>
</plugin>
"""

import Domoticz
import time
import urllib.request
import json


class BasePlugin:
    def __init__(self):
        self.presence_sensors = []
        self.relay_outputs = []
        self.presence_on_delay = 120      # en secondes
        self.presence_off_delay = 600    # en secondes
        self.debug_enabled = False
        self.presence_detected = False
        self.presence_start_time = None
        self.absence_start_time = None
        self.last_relay_check_time = 0
        self.relay_check_interval = 60  # 15 minutes en secondes = 900

    def log_debug(self, msg):
        if self.debug_enabled:
            Domoticz.Log("[DEBUG] " + msg)

    def onStart(self):
        Domoticz.Log("Plugin démarré")
        self.last_relay_check_time = time.time()

        try:
            self.presence_sensors = list(map(int, Parameters["Mode1"].split(",")))
            self.relay_outputs = list(map(int, Parameters["Mode2"].split(",")))
        except Exception as e:
            Domoticz.Error("Erreur dans les IDX capteurs/relais : " + str(e))
            return

        # Conversion minutes → secondes
        try:
            self.presence_on_delay = float(Parameters["Mode3"]) * 60
            self.presence_off_delay = float(Parameters["Mode4"]) * 60
        except ValueError:
            Domoticz.Error("Erreur : temporisations invalides.")
            return

        self.debug_enabled = Parameters["Mode6"] == "Debug"

        self.log_debug(f"Capteurs = {self.presence_sensors}")
        self.log_debug(f"Relais = {self.relay_outputs}")
        self.log_debug(f"Temporisation présence = {self.presence_on_delay} s")
        self.log_debug(f"Temporisation absence = {self.presence_off_delay} s")
        self.log_debug(f"Debug activé = {self.debug_enabled}")

        # create the child devices if these do not exist yet
        if 1 not in Devices:
            Domoticz.Device(Name="Presence", Unit=1, TypeName="Switch", Image=9, Used=1).Create()
            Domoticz.Log("Device 'Présence' (Motion Sensor) créé")

        # Widget de contrôle ON/OFF du plugin (Unit=2)
        if 2 not in Devices:
            Domoticz.Device(Name="Mode Auto", Unit=2, TypeName="Switch", Image=9, Used=1).Create()
            Domoticz.Log("Device 'Gestion Présence - Activé' créé")

        # Widget Motion Sensor
        if 1 in Devices:
            value = 0 # Reset Widget Motion Sensor
            if Devices[1].nValue != value:
                Devices[1].Update(nValue=value, sValue=str(value))
                self.log_debug(f"Widget Présence → {'On' if value else 'Off'}")
        else:
            Domoticz.Error("Widget Présence non trouvé")

        Domoticz.Heartbeat(10)

    def onCommand(self, Unit, Command, Level, Color):
        self.log_debug(f"Commande reçue : Unit={Unit}, Command={Command}")

        # Gestion du widget de contrôle (Unit 2)
        if Unit == 2:
            new_value = 1 if Command.lower() == "on" else 0

            if Devices[2].nValue != new_value:
                Devices[2].Update(nValue=new_value, sValue=Command.capitalize())
                Domoticz.Log(f"Plugin {'activé' if new_value == 1 else 'désactivé'} via le widget de contrôle")

            # 🔁 Réinitialiser les temporisations
            self.presence_start_time = None
            self.absence_start_time = None
            self.log_debug("Temporisations réinitialisées (activation/désactivation plugin)")

            if new_value == 0:
                # Désactivation = on coupe tous les relais immédiatement
                for idx in self.relay_outputs:
                    self.switch_device_by_idx(idx, False)
                Domoticz.Log("Tous les relais ont été désactivés suite à l'arrêt du plugin")

    def onHeartbeat(self):

        # Si le widget de contrôle (Unit 2) est sur OFF, on ne fait rien
        if 2 in Devices and Devices[2].nValue == 0:
            self.log_debug("Plugin désactivé via le widget de contrôle (Unit 2)")
            return

        # Sinon mode auto :
        now = time.time()
        any_sensor_active = any(
            self.get_device_state_by_idx(idx) for idx in self.presence_sensors
        )

        status_list = [f"{idx}: {self.get_device_status_string_by_idx(idx)}" for idx in self.presence_sensors]
        self.log_debug(f"État capteurs : {status_list}")
        self.log_debug(f"Présence détectée ? {any_sensor_active}")

        if any_sensor_active:
            if not self.presence_detected:
                if self.presence_start_time is None:
                    self.presence_start_time = now
                    self.log_debug("Début temporisation présence")
                elif now - self.presence_start_time >= self.presence_on_delay:
                    self.setPresence(True)
                else:
                    remaining = self.presence_on_delay - (now - self.presence_start_time)
                    self.log_debug(f"Temporisation présence en cours... {remaining:.1f} s restantes")
            else:
                if self.presence_detected:
                    self.log_debug("Présence toujours active")
                self.absence_start_time = None
        else:
            if self.presence_detected:
                if self.absence_start_time is None:
                    self.absence_start_time = now
                    self.log_debug("Début temporisation absence")
                elif now - self.absence_start_time >= self.presence_off_delay:
                    self.setPresence(False)
                else:
                    remaining = self.presence_off_delay - (now - self.absence_start_time)
                    self.log_debug(f"Temporisation absence en cours... {remaining:.1f} s restantes")
            else:
                self.presence_start_time = None

        # Vérification périodique des relais toutes les x minutes selon self.relay_check_interval dans init
        if time.time() - self.last_relay_check_time >= self.relay_check_interval:
            self.log_debug("Vérification périodique des relais")
            for idx in self.relay_outputs:
                current_status = self.get_switch_status_by_idx(idx)
                if current_status is None:
                    continue  # skip si erreur

                expected_status = self.presence_detected
                if current_status != expected_status:
                    self.log_debug(
                        f"Incohérence relais {idx} : actuel={'On' if current_status else 'Off'}, attendu={'On' if expected_status else 'Off'} → correction")
                    self.switch_device_by_idx(idx, expected_status)
            self.last_relay_check_time = time.time()

    def setPresence(self, state):
        self.presence_detected = state
        action = "Présence détectée" if state else "Absence confirmée"
        Domoticz.Log(action)

        # Widget Motion Sensor
        if 1 in Devices:
            value = 1 if state else 0
            if Devices[1].nValue != value:
                Devices[1].Update(nValue=value, sValue=str(value))
                self.log_debug(f"Widget Présence → {'On' if value else 'Off'}")
        else:
            Domoticz.Error("Widget Présence non trouvé")

        # Commande relais
        for idx in self.relay_outputs:
            self.switch_device_by_idx(idx, state)


    def get_device_state_by_idx(self, idx):
        try:
            url = f"http://127.0.0.1:8080/json.htm?type=command&param=getdevices&rid={idx}"
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode())

            if 'result' not in data or not data['result']:
                Domoticz.Error(f"IDX {idx} introuvable ou vide dans la réponse JSON")
                return False

            status = data['result'][0].get('Status', '').lower()
            if status == 'on':
                return True
            elif status == 'off':
                return False
            else:
                Domoticz.Error(f"IDX {idx} : Status inconnu ou absent")
                return False

        except Exception as e:
            Domoticz.Error(f"Erreur en lisant le status de l'idx {idx} : {e}")
            return False

    def switch_device_by_idx(self, idx, turn_on):
        try:
            action = "On" if turn_on else "Off"
            url = f"http://127.0.0.1:8080/json.htm?type=command&param=switchlight&idx={idx}&switchcmd={action}"
            with urllib.request.urlopen(url) as response:
                result = json.loads(response.read().decode())
            self.log_debug(f"Relais {idx} → {action} (réponse : {result.get('status')})")
        except Exception as e:
            Domoticz.Error(f"Erreur lors du switch du relais idx {idx} : {e}")

    def get_device_status_string_by_idx(self, idx):
        try:
            url = f"http://127.0.0.1:8080/json.htm?type=command&param=getdevices&rid={idx}"
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode())

            if 'result' in data and data['result']:
                return data['result'][0].get('Status', 'Unknown')
            else:
                return "Unknown"
        except Exception as e:
            Domoticz.Error(f"Erreur lecture Status idx {idx} : {e}")
            return "Erreur"

    def get_switch_status_by_idx(self, idx):
        try:
            url = f"http://127.0.0.1:8080/json.htm?type=devices&rid={idx}"
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode())

            if 'result' in data and data['result']:
                status = data['result'][0].get('Status', '').lower()
                return status == 'on'
            else:
                Domoticz.Error(f"Erreur lecture status relais idx {idx} : Résultat vide")
                return None
        except Exception as e:
            Domoticz.Error(f"Erreur lecture relais idx {idx} : {e}")
            return None



global _plugin
_plugin = BasePlugin()

def onStart():
    _plugin.onStart()

def onHeartbeat():
    _plugin.onHeartbeat()

def onCommand(Unit, Command, Level, Color):
    _plugin.onCommand(Unit, Command, Level, Color)
