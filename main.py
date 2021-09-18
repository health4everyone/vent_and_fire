#!/usr/bin/env python
#
# Copyright (c) 2020, Pycom Limited.
#
# This software is licensed under the GNU GPL version 3 or any
# later version, with permitted additional terms. For more information
# see the Pycom Licence v1.0 document supplied with this file, or
# available at https://www.pycom.io/opensource/licensing
#

# See https://docs.pycom.io for more information regarding library specifics

import time
import pycom
import machine
import utime
import ujson
import ubinascii
import urequest
from machine import RTC
from SI7006A20 import SI7006A20
from LTR329ALS01 import LTR329ALS01
from MPL3115A2 import MPL3115A2,ALTITUDE,PRESSURE
from DFRobot_SGP40 import DFRobot_SGP40
from DFRobot_Oxygen import *
from machine import PWM
from _pybytes_config import PybytesConfig

#VOC index over 200 means you need to ventilate room
#since it may spike we used a counter to set in in alarm only after 5 checks
VOC_LIMIT=200
VOC_COUNT=5
#Oxygen over 23% means something is leaking so you need to ventilate
#Check also oxygen sources
OXYGEN_LIMIT=23.0

health4everyoneURL="http://patientmonitor.health4everyone.org"
collectTimestamp=""
rtc = machine.RTC()

def send_health4everyone(uuid,key,data,timestamp):
    url = health4everyoneURL
    postData = {}
    pdata=""
    pdata=pdata+"device="+str(uuid)
    pdata=pdata+"&key="+str(key)
    if(isinstance(data,int) or isinstance(data,float)):
        pdata=pdata+"&value="+str(data);
        url=url+"/device/postNumeric"
    if(isinstance(data,str)):
        pdata=pdata+"&value="+str(data);
        url=url+"/device/postString"
    if(isinstance(data,bytearray)):
        pdata=pdata+"&value="+str(data);
        url=url+"/device/postBinary"
    pdata=pdata+"&timestamp="+timestamp
    print(url+" "+pdata)
    res = urequest.post(url, headers={'Content-Type':'application/x-www-form-urlencoded '},data=pdata)
    print(res.text)
    return res

def check_health4everyone(uuid):
    url = health4everyoneURL+"/device/check?device="+uuid
    print(url)
    res = urequest.request("GET",url)
    print(res.text)
    return res

def register_health4everyone(uuid,name,model,serial):

    url = health4everyoneURL+"/device/register?uuid="+str(uuid)+"&name="+name+"&model="+model+"&serial="+serial
    print(url)
    res = urequest.request("GET",url)
    print(res.text)
    return res

COLLECT_NUMBER   = 10              # collect number, the collection range is 1-100
IIC_MODE         = 0x01            # default use IIC1

rtc.ntp_sync("pool.ntp.org")
while not rtc.synced():
    machine.idle()

print("RTC synced with NTP time")
#adjust your local timezone, by default, NTP time will be GMT
time.timezone(3*60**2) #we are located at GMT+2, thus 2*60*60

wmac = str(ubinascii.hexlify(machine.unique_id()))

pycom.heartbeat(False)
pycom.rgbled(0x0A0A08) # white

mp = MPL3115A2(mode=ALTITUDE) # Returns height in meters. Mode may also be set to PRESSURE, returning a value in Pascals
mpp = MPL3115A2(mode=PRESSURE) # Returns pressure in Pa. Mode may also be set to ALTITUDE, returning a value in meters
si = SI7006A20()
lt = LTR329ALS01()
voc = DFRobot_SGP40()
oxygen = DFRobot_Oxygen_IIC(0x73)
alarmPWM = PWM(0, frequency=2000)


conf = PybytesConfig().read_config()
uuid = conf['device_id']

print("Device UUID:"+str(uuid))


#checking if device is registered
check = check_health4everyone(uuid)
#if not registered we register the device using pybytes uuid
if( check.text=="false" ):
    print("Device not registered")
    register = register_health4everyone(uuid,"Pybytes%20"+uuid,"Vent%26Fire%20Monitor",uuid);
    register.close()
check.close()

reportInterval = 60
lastTime = time.time()-reportInterval
initialTime = lastTime
counter = 0
alarm = 0
alarmVal = 0

while True:
  currentTime = time.time()
  temperature = si.temperature()
  humidity = si.humidity()
  voc.set_envparams(humidity,temperature)
  voc_data = voc.get_voc_index()
  oxygen_data = oxygen.get_oxygen_data(COLLECT_NUMBER);
  alarm = 0
  if oxygen_data>OXYGEN_LIMIT: #oxygen alarm
      alarm = alarm+1
      print("Oxygen in alarm")
  if voc_data>VOC_LIMIT and voc_count>VOC_COUNT: #voc alarm
      alarm = alarm+66
      print("VOC in alarm")
      voc_count=voc_count+1
  elif voc_data>VOC_LIMIT:
      voc_count=voc_count+1
  else:
      voc_count=0;

  if alarm==1 or alarm==3:
      alarmVal = 1 #full buzz
  elif alarm==2:
      alarmVal = 0.1 #partial buz
  else:
      alarmVal = 0

  alarmPWM.channel(0, pin='P9', duty_cycle=alarmVal)

  if currentTime-lastTime>=reportInterval:
      counter=counter+1
      lastTime = initialTime+counter*reportInterval
      print("Start collecting data...")
      st = utime.ticks_ms()
      pressure = mpp.pressure()
      temp_2nd = mp.temperature()
      light = lt.lux()
      temperature = si.temperature()
      humidity = si.humidity()
      voc.set_envparams(humidity,temperature)
      voc_data = voc.get_voc_index()
      oxygen_data = oxygen.get_oxygen_data(COLLECT_NUMBER);
      year, month, day, hour, minute, seconds, usecond, pp = rtc.now()
      collectTimestamp="{:04d}-{:02d}-{:02d}%20{:02d}%3A{:02d}%3A{:02d}".format(year, month, day, hour, minute, seconds)

      r=send_health4everyone(uuid,"temperature", temperature, collectTimestamp)
      r.close();
      r=send_health4everyone(uuid,"humidity", humidity, collectTimestamp)
      r.close();
      r=send_health4everyone(uuid,"pressure", pressure, collectTimestamp)
      r.close();
      r=send_health4everyone(uuid,"light", light, collectTimestamp)
      r.close();
      r=send_health4everyone(uuid,"temp_2nd", temp_2nd, collectTimestamp)
      r.close();
      r=send_health4everyone(uuid,"VOC", voc_data, collectTimestamp)
      r.close();
      r=send_health4everyone(uuid,"oxygen", oxygen_data, collectTimestamp)
      r.close();

      en = utime.ticks_ms()
      print("Data sent in:"+str(en-st)+" milliseconds")
  time.sleep(.1)
