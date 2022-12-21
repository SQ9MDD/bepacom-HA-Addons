#===================================================
# Importing from libraries
#=================================================== 

from threading import Thread
import uvicorn
import webAPI as api
import time
import sys
from bacpypes.debugging import bacpypes_debugging, ModuleLogger
from bacpypes.consolelogging import ConfigArgumentParser, ConsoleLogHandler
from bacpypes.core import run, deferred, stop, enable_sleeping
from bacpypes.local.device import LocalDeviceObject
from bacpypes.basetypes import PropertyReference, PropertyIdentifier, PropertyValue, RecipientProcess, Recipient, EventType, ServicesSupported
from BACnetIOHandler import BACnetIOHandler


#===================================================
# Global variables
#===================================================
webserv: str
port = 7813
extIP: str

this_application = None
devices = []
rsvp = (True, None, None)

_debug = 0
_log = ModuleLogger(globals())

#===================================================
# Threads
#=================================================== 

# Uvicorn thread
class uviThread(Thread):
    def run(self):
        uvicorn.run(api.app, host=webserv, port=port, log_level="debug")


# BACpypes thread
class BACpypesThread(Thread):
    def __init__(self):
        Thread.__init__(self)

    def run(self):
        run()

    def stop(self):
        stop()
        self.join()

        
#===================================================
# Main
#=================================================== 
def main():
    #===================================================
    # parse bacpypes.ini
    #===================================================
    args = ConfigArgumentParser(description=__doc__).parse_args()
    global webserv
    global extIP
    webserv = args.ini.webserv
    extIP = args.ini.address
    
    #===================================================
    # Uvicorn server
    #===================================================
    server = uviThread()
    server.start()

    #===================================================
    # BACnet server
    #===================================================
    global this_application
    global this_device

    # make a device object
    this_device = LocalDeviceObject(
        objectName=args.ini.objectname,
        objectIdentifier=int(args.ini.objectidentifier),
        maxApduLengthAccepted=int(args.ini.maxapdulengthaccepted),
        segmentationSupported=args.ini.segmentationsupported,
        vendorIdentifier=int(args.ini.vendoridentifier),
        description="BACnet Add-on for Home Assistant"
        )

    # provide max segments accepted if any kind of segmentation supported
    if args.ini.segmentationsupported != 'noSegmentation':
        this_device.maxSegmentsAccepted = int(args.ini.maxsegmentsaccepted)

    # make a simple application
    this_application = BACnetIOHandler(this_device, args.ini.address)
    sys.stdout.write("Starting BACnet device on " + args.ini.address + "\n")

    # Coupling of FastAPI and BACnetIOHandler
    api.BACnetDeviceDict = this_application.BACnetDeviceDict
    api.threadingUpdateEvent = this_application.updateEvent

    bacpypes_thread = BACpypesThread()
    bacpypes_thread.start()


    while True:
        time.sleep(2)


if __name__=="__main__":
    main()


