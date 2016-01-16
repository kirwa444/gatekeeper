#!/usr/bin/python

import daemon   #to deamonize this script
import serial   #serial communication
import re       #regular expressions
import logging  #hmm what could this be for?
import os       #to call external stuff
import signal  #catch kill signall
import time     #for the sleep function
import select  #for select.error
from errno import EINTR #read interrupt
import traceback #for stacktrace
import RPi.GPIO as GPIO
import requests

#setup logging
LOG_FILENAME = '/home/ovi/gatekeeper/gatekeeper.log'
FORMAT = "%(asctime)-12s: %(levelname)-8s - %(message)s"
logging.basicConfig(filename=LOG_FILENAME,level=logging.DEBUG,format=FORMAT)
log = logging.getLogger("GateKeeper")

#setup GPIO output pins
lukko = 12
valot = 16
modem_power = 17
modem_reset = 18

#setup GPIO input pins
valotieto = 5
salpa = 6

class Pin:
  #init (activate pin)
  def __init__(self):
    GPIO.cleanup()
    # use BCM chip pin numbering convention
    GPIO.setmode(GPIO.BCM)
    # Set up the GPIO channels
    GPIO.setup(lukko, GPIO.OUT)
    GPIO.output(lukko, GPIO.LOW)
    log.debug("initialized lukko, pin to low")
    GPIO.setup(valot, GPIO.OUT)
    GPIO.output(valot, GPIO.LOW)
    log.debug("initialized valot, pin to low")
    GPIO.setup(modem_power, GPIO.OUT)
    GPIO.output(modem_power, GPIO.LOW)
    log.debug("initialized modem_power, pin to low")
    GPIO.setup(modem_reset, GPIO.OUT)
    GPIO.output(modem_reset, GPIO.LOW)
    log.debug("initialized modem_reset, pin to low")

    GPIO.setup(20, GPIO.OUT)
    GPIO.output(20, GPIO.LOW)
    GPIO.setup(21, GPIO.OUT)
    GPIO.output(21, GPIO.LOW)

  
  def lukkohigh(self):
    GPIO.output(lukko, GPIO.HIGH)
    log.debug("lukko to high")

    GPIO.output(16, GPIO.HIGH)
    GPIO.output(20, GPIO.HIGH)
    GPIO.output(21, GPIO.HIGH)


  def lukkolow(self):
    GPIO.output(lukko, GPIO.LOW)
    log.debug("lukko to low")

    GPIO.output(16, GPIO.LOW)
    GPIO.output(20, GPIO.LOW)
    GPIO.output(21, GPIO.LOW)


  def valothigh(self):
    GPIO.output(valot, GPIO.HIGH)
    log.debug("valot to high")

  def valotlow(self):
    GPIO.output(valot, GPIO.LOW)
    log.debug("valot to low")

  def send_pulse_lukko(self):
    self.lukkohigh()
    #keep pulse high for 5.5 second
    time.sleep(5.5)
    self.lukkolow()
    log.debug("Pulse done")
    
class GateKeeper:
  def __init__(self):
    self.pin = Pin()
    self.read_whitelist()
    self.modem_power_on()    
    self.enable_caller_id()
    self.data_channel = serial.Serial(port='/dev/ttyAMA0',baudrate=115200,parity=serial.PARITY_ODD,stopbits=serial.STOPBITS_ONE,bytesize=serial.EIGHTBITS,xonxoff=True)

  def url_log(self, name, number):
    try:
      r = requests.get('http://mikeful.kapsi.fi/vaasahacklab/log/' + number + '/' + name)
    except:
      log.debug('failed url')

  def dingdong(self):
    try:
      r = requests.get('http://musicbox.lan:8080')
    except:
      log.debug('failed url for doorbell')

  def read_whitelist(self):
    self.whitelist = {}
    file = open('/home/ovi/gatekeeper/whitelist','r')
    entry_pattern = re.compile('([0-9][0-9]+?) (.*)')
    line = file.readline()
    while line:
      entry_match = entry_pattern.match(line)
      if entry_match:
        number = entry_match.group(1)
        name = entry_match.group(2)
        self.whitelist[number] = name
      line = file.readline()
    file.close()
    log.debug("Whitelist " + str(self.whitelist))

  def enable_caller_id(self):
    command_channel = serial.Serial(port='/dev/ttyAMA0',baudrate=115200,parity=serial.PARITY_ODD,stopbits=serial.STOPBITS_ONE,bytesize=serial.EIGHTBITS,xonxoff=True)
    command_channel.isOpen()
    command_channel.write("AT+CLIP=1" + "\r\n")
    command_channel.close()
    log.debug("Enabled caller ID")

  def hangup(self):
    command_channel = serial.Serial(port='/dev/ttyAMA0',baudrate=115200,parity=serial.PARITY_ODD,stopbits=serial.STOPBITS_ONE,bytesize=serial.EIGHTBITS,xonxoff=True)
    command_channel.isOpen()
    command_channel.write("AT+HVOIC" + "\r\n") #Disconnect only voice call (instead W/ data)
    command_channel.close()
    log.debug("Hung up")

  def start(self):
    try: 
      self.wait_for_call()
    except select.error, v:
      if v[0] == EINTR:
        log.debug("Interrupt while waiting for call, cleanup should be done.")
      else:
        raise
    else:
      log.warning("Unexpected exception, shutting down!")
  
  def modem_power_on(self):
    command_channel = serial.Serial(port='/dev/ttyAMA0',baudrate=115200,parity=serial.PARITY_ODD,stopbits=serial.STOPBITS_ONE,bytesize=serial.EIGHTBITS,xonxoff=True,timeout=0.2)
    command_channel.isOpen()
    command_channel.write("AT"+"\r\n")
    command_channel.readline()
    buffer = command_channel.readline(command_channel.inWaiting())
    log.debug(buffer)
    if not buffer:
      log.debug("Powering on modem")
      GPIO.output(modem_power, GPIO.HIGH)
      time.sleep(1.2)
      GPIO.output(modem_power, GPIO.LOW)
      time.sleep(2)
    else:
      log.debug("Modem already powered")

  def modem_power_off(self):
    command_channel = serial.Serial(port='/dev/ttyAMA0',baudrate=115200,parity=serial.PARITY_ODD,stopbits=serial.STOPBITS_ONE,bytesize=serial.EIGHTBITS,xonxoff=True,timeout=0.2)
    command_channel.isOpen()
    command_channel.write("AT"+"\r\n")
    command_channel.readline()
    buffer = command_channel.readline(command_channel.inWaiting())
    log.debug(buffer)
    if not buffer:
      log.debug("Modem already powered off")
    else:
      log.debug("Powering off modem")
      GPIO.output(modem_power, GPIO.HIGH)
      time.sleep(1.2)
      GPIO.output(modem_power, GPIO.LOW)

  def wait_for_call(self):
    self.data_channel.isOpen()
    call_id_pattern = re.compile('.*CLIP.*"([0-9]+)",.*')
    while True:
      time.sleep(0.1) # Sleep for a 100 millseconds, no need to consume all CPU
      buffer = self.data_channel.readline(self.data_channel.inWaiting())
      call_id_match = call_id_pattern.match(buffer)
##
#      log.debug("Data from data channel: " +buffer.strip())
##
      if call_id_match:
        print call_id_match.groups()
        number = call_id_match.group(1)
        self.handle_call(number)
  
  def handle_call(self,number):
    log.debug(number)
    if number in self.whitelist:
      self.hangup()
      self.pin.send_pulse_lukko()
      log.info("Opened the gate for " + self.whitelist[number] + " (" + number + ").")
      self.url_log(self.whitelist[number],number)
    else:
      log.info("Did not open the gate for "  + number + ", number  is not kown.")
      self.dingdong()
      self.url_log("DENIED",number)
      
  def stop_gatekeeping(self):
    self.data_channel.close()
    #set pin to default state?
    self.pin.lukkolow()
    self.pin.valotlow()
    self.modem_power_off()
    time.sleep(0.5)
    GPIO.cleanup()
    log.debug("Cleanup finished.") 
    

#make this process a deamon
#daemon.daemonize("/tmp/gatekeeper.pid")

logging.info("Started GateKeeper.")

gatekeeper = GateKeeper()

def shutdown_handler(signum, frame):
    gatekeeper.stop_gatekeeping()
    log.info("Stopping GateKeeper.") 

signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM,shutdown_handler)

gatekeeper.start()