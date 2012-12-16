import time
import os
import socket
import sys

global marker_log
marker_log = None

global lsl_backend
lsl_backend = None

global river_backend
river_backend = None



def init_markers(lsl,logfile,datariver):
    """ Initialize the marker protocols to use. """

    if lsl:
        try:
            global lsl_backend
            import pylsl.pylsl as pylsl
            info = pylsl.stream_info("SNAP-Markers","Markers",1,0,pylsl.cf_string,"SNAPmarkers-" + socket.gethostname() + time.asctime())
            lsl_backend = pylsl.stream_outlet(info)
            lsl_backend.pylsl = pylsl
            print "The lab streaming layer is ready for sending markers."
        except:
            print "Error initializing the lab streaming layer backend. You will not be able to send and record event markers via LSL."
            
    if logfile:
        try:
            # find a new slot for the logfiles
            for k in xrange(10000):
                fname = 'logs/markerlog-' + str(k) + '.log'
                if not os.path.exists(fname):
                    global marker_log
                    marker_log = open(fname,'w')
                    break
            print "A marker logfile has been prepared for logging."
        except:
            print "Error initializing the marker logging. Your event markers will not be logged into a file."

    if datariver:
        try:
            global river_backend
            import framework.eventmarkers.datariver_backend
            river_backend = framework.eventmarkers.datariver_backend
            river_backend.send_marker(int(999))
            print "DataRiver has been loaded successfully for sending markers."
        except:
            print "Error initializing the DataRiver backend. You will not be able to send and record event markers via DataRiver."


def send_marker(markercode):
    """Global marker sending / logging function."""
    
    global lsl_backend
    if lsl_backend is not None:
        lsl_backend.push_sample(lsl_backend.pylsl.vectorstr([str(markercode)]), lsl_backend.pylsl.local_clock(), True)

    global marker_log
    if marker_log is not None:
        marker_log.write(repr(time.time()) + ': ' + str(markercode) + '\n')

    global river_backend
    if river_backend is not None:
        river_backend.send_marker(int(markercode))
