'''
The SNAP experiment launcher program. To be run on the subject's PC.

* Installation notes: see INSTALLATION NOTES.TXT

* This program can launch experiment modules that are specified in the modules directory
  (one at a time).

* The module to be launched (and various other options) can be specified at the command line; here is a complete listing of all possible config options and their defaults:
  launcher.py --module Sample1 --studypath studies/Sample1 --autolaunch 1 --developer 1 --engineconfig defaultsettings.prc --datariver 0 --labstreaming 1 --fullscreen 0 --windowsize 800x600 --windoworigin 50/50 --noborder 0 --nomousecursor 0 --timecompensation 1
    
* If in developer mode, several key bindings are enabled:
   Esc: exit program
   F1: start module
   F2: cancel module
  
* In addition to modules, there are "study configuration files" (aka study configs),
  which are in in the studies directory. These specify the module to launch in the first line
  and assignments to member variables of the module instance in the remaining lines (all Python syntax allowed).
  
  A config can be specified in the command line just by passing the appropriate .cfg file name, as in the following example.
  In addition, the directory where to look for the .cfg file can be specified as the studypath.
  launcher.py --module=test1.cfg --studypath=studies/DAS
  
* The program can be remote-controlled via a simple TCP text-format network protocol (on port 7899) supporting the following messages:
  start                  --> start the current module
  cancel                 --> cancel execution of the current module
  load modulename        --> load the module named modulename
  config configname.cfg  --> load a config named configname.cfg (make sure that the studypath is set correctly so that it's found)
  setup name=value       --> assign a value to a member variable in the current module instance
                             can also involve multiple assignments separated by semicolons, full Python syntax allowed.
   
* The underlying Panda3d engine can be configured via a custom .prc file (specified as --engineconfig=filename.prc), see
  http://www.panda3d.org/manual/index.php/Configuring_Panda3D
  
* For quick-and-dirty testing you may also override the launch options below under "Default Launcher Configuration", but note that you cannot check these changes back into the main source repository of SNAP.  
    
'''
import optparse, sys, os, fnmatch, traceback

SNAP_VERSION = '1.01'


# -----------------------------------------------------------------------------------------
# --- Default Launcher Configuration (selectively overridden by command-line arguments) ---
# -----------------------------------------------------------------------------------------


# If non-empty, this is the module that will be initially loaded if nothing
# else is specified. Can also be a .cfg file of a study.
LOAD_MODULE = "Sample1"

# If true, the selected module will be launched automatically; otherwise it will
# only be (pre-)loaded; the user needs to press F1 (or issue the "start" command remotely) to start the module 
AUTO_LAUNCH = True

# The directory in which to look for .cfg files, if passed as module or via
# remote control messages.
STUDYPATH = "studies\SampleStudy" 

# The default engine configuration.
ENGINE_CONFIG = "defaultsettings.prc"

# Set this to True or False to override the settings in the engineconfig file (.prc)
FULLSCREEN = None

# Set this to a resolution like "1024x768" (with quotes) to override the settings in the engineconfig file
WINDOWSIZE = None

# Set this to a pixel offset from left top corner, e.g. "50/50" (with quotes) to override the window location in the engineconfig file
WINDOWORIGIN = None

# Set this to True or False to override the window border setting in the engineconfig file
NOBORDER = None

# Set this to True or False to override the mouse cursor setting in the engineconfig file
NOMOUSECURSOR = None

# Enable DataRiver support for marker sending.
DATA_RIVER = False

# Enable lab streaming layer support for marker sending.
LAB_STREAMING = True

# This is the default port on which the launcher listens for remote control 
# commands (e.g. launching an experiment module)
SERVER_PORT = 7897

# Whether the Launcher starts in developer mode; if true, modules can be loaded,
# started and cancelled via keyboard shortcuts (not recommended for production 
# experiments)
DEVELOPER_MODE = True

# Whether lost time (e.g., to processing or jitter) is compensated for by making the next sleep() slightly shorter
COMPENSATE_LOST_TIME = True

# Which serial port to use (0=disabled)
COM_PORT = 0


# ------------------------------
# --- Startup Initialization ---
# ------------------------------

print 'This is SNAP version ' + SNAP_VERSION + "\n\n"

# --- Parse console arguments ---

print 'Reading command-line options...'
parser = optparse.OptionParser()
parser.add_option("-m", "--module", dest="module", default=LOAD_MODULE,
                  help="Experiment module to load upon startup (see modules). Can also be a .cfg file of a study (see studies and --studypath).")
parser.add_option("-s","--studypath", dest="studypath", default=STUDYPATH,
                  help="The directory in which to look for .cfg files, media, .prc files etc. for a particular study.")
parser.add_option("-a", "--autolaunch", dest="autolaunch", default=AUTO_LAUNCH, 
                  help="Whether to automatically launch the selected module.")
parser.add_option("-d","--developer", dest="developer", default=DEVELOPER_MODE,
                  help="Whether to launch in developer mode; if true, allows to load,start, and cancel experiment modules via keyboard shortcuts.")
parser.add_option("-e","--engineconfig", dest="engineconfig", default=ENGINE_CONFIG,
                  help="A configuration file for the Panda3d engine (allows to change many engine-level settings, such as the renderer; note that the format is dictated by Panda3d).")
parser.add_option("-f","--fullscreen", dest="fullscreen", default=FULLSCREEN,
                  help="Whether to go fullscreen (default: according to current engine config).")
parser.add_option("-w","--windowsize", dest="windowsize", default=WINDOWSIZE,
                  help="Window size, formatted as in --windowsize 1024x768 to select the main window size in pixels (default: accoding to current engine config).")
parser.add_option("-o","--windoworigin", dest="windoworigin", default=WINDOWORIGIN,
                  help="Window origin, formatted as in --windoworigin 50/50 to select the main window origin, i.e. left upper corner in pixes (default: accoding to current engine config).")
parser.add_option("-b","--noborder", dest="noborder", default=NOBORDER,
                  help="Disable window borders (default: accoding to current engine config).")
parser.add_option("-c","--nomousecursor", dest="nomousecursor", default=NOMOUSECURSOR,
                  help="Disable mouse cursor (default: accoding to current engine config).")
parser.add_option("-r","--datariver", dest="datariver", default=DATA_RIVER,
                  help="Whether to enable DataRiver support in the launcher.")
parser.add_option("-l","--labstreaming", dest="labstreaming", default=LAB_STREAMING,
                  help="Whether to enable lab streaming layer (LSL) support in the launcher.")
parser.add_option("-p","--serverport", dest="serverport", default=SERVER_PORT,
                  help="The port on which the launcher listens for remote control commands (e.g. loading a module).")
parser.add_option("-t","--timecompensation", dest="timecompensation", default=COMPENSATE_LOST_TIME,
                  help="Compensate time lost to processing or jitter by making the successive sleep() call shorter by a corresponding amount of time (good for real time, can be a hindrance during debugging).")
parser.add_option("--comport", dest="comport", default=COM_PORT,
                  help="The COM port over which to send markers, or 0 if disabled.")
(opts,args) = parser.parse_args()

# --- Pre-engine initialization ---

print 'Performing pre-engine initialization...'
from framework.eventmarkers.eventmarkers import send_marker, init_markers, shutdown_markers
init_markers(opts.labstreaming,True,opts.datariver,int(opts.comport))

# --- Engine initialization ---

print 'Loading the Panda3d engine...',
# panda3d support
from direct.showbase.ShowBase import ShowBase
from direct.task.Task import Task
from pandac.PandaModules import WindowProperties
from panda3d.core import loadPrcFile, loadPrcFileData, Filename, DSearchPath, VBase4 
# thread coordination
import framework.tickmodule
import threading
# network support
import Queue
import SocketServer
print "done."

print "Applying the engine configuration file/settings..."

# load the selected engine configuration (studypath takes precedence over the SNAP root path)
config_searchpath = DSearchPath()
config_searchpath.appendDirectory(Filename.fromOsSpecific(opts.studypath))
config_searchpath.appendDirectory(Filename.fromOsSpecific('.'))
loadPrcFile(config_searchpath.findFile(Filename.fromOsSpecific(opts.engineconfig)))

# add a few more media search paths (in particular, media can be in the media directory, or in the studypath)
loadPrcFileData('', 'model-path ' + opts.studypath + '/media')
loadPrcFileData('', 'model-path ' + opts.studypath)
loadPrcFileData('', 'model-path media')

# override engine settings according to the command line arguments, if specified
if opts.fullscreen is not None:
    loadPrcFileData('', 'fullscreen ' + opts.fullscreen)
if opts.windowsize is not None:
    loadPrcFileData('', 'win-size ' + opts.windowsize.replace('x',' '))
if opts.windoworigin is not None:
    loadPrcFileData('', 'win-origin ' + opts.windoworigin.replace('/',' '))
if opts.noborder is not None:
    loadPrcFileData('', 'undecorated ' + opts.noborder)
if opts.nomousecursor is not None:
    loadPrcFileData('', 'nomousecursor ' + opts.nomousecursor)

global is_running
is_running = True

# -----------------------------------
# --- Main application definition ---
# -----------------------------------

class MainApp(ShowBase):    
    """The Main SNAP application."""
    
    def __init__(self,opts):
        ShowBase.__init__(self)

        self._module = None              # the currently loaded module
        self._instance = None            # instance of the module's Main class
        self._executing = False          # whether we are executing the module
        self._remote_commands = Queue.Queue() # a message queue filled by the TCP server
        self._opts = opts                # the configuration options
        self._console = None             # graphical console, if any
        
        # send an initial start marker
        send_marker(999)

        # preload some data and init some settings
        self.set_defaults()

        # register the main loop
        self._main_task = self.taskMgr.add(self._main_loop_tick,"main_loop_tick")
        
        # register global keys if desired
        if opts.developer:
            self.accept("escape",self.terminate)
            self.accept("f1",self._remote_commands.put,['start'])
            self.accept("f2",self._remote_commands.put,['cancel'])
            self.accept("f5",self._remote_commands.put,['prune'])
            self.accept("f12",self._init_console)
                
        # load the initial module or config if desired
        if opts.module is not None:
            if opts.module.endswith(".cfg"):
                self.load_config(opts.module)
            else:
                self.load_module(opts.module)
                
        # start the module if desired
        if (opts.autolaunch == True) or (opts.autolaunch=='1'):
            self.start_module()

        # start the TCP server for remote control
        self._init_server(opts.serverport)

        
    def set_defaults(self):
        """Sets some environment defaults that might be overridden by the modules."""
        font = loader.loadFont('arial.ttf',textureMargin=5)
        font.setPixelsPerUnit(128)
        base.win.setClearColorActive(True)
        base.win.setClearColor((0.3, 0.3, 0.3, 1))
        winprops = WindowProperties() 
        winprops.setTitle('SNAP') 
        base.win.requestProperties(winprops) 
        
        
    def load_module(self,name):
        """Try to load the given module, if any. The module can be in any folder under modules."""
        if name is not None and len(name) > 0:
            print 'Importing experiment module "' + name + '"...',            
            # find it under modules...
            locations = []
            for root, dirnames, filenames in os.walk('modules'):
                for filename in fnmatch.filter(filenames, name+'.py'):
                    locations.append(root)
            if len(locations) == 1:
                if self._instance is not None:
                    self.prune_module()
                self.set_defaults()
                if locations[0] not in sys.path:
                    sys.path.insert(0, locations[0])
                try:
                    # import it
                    self._module = __import__(name)
                    print 'done.'
                    # instantiate the main class 
                    print "Instantiating the module's Main class...",
                    self._instance = self._module.Main()
                    self._instance._make_up_for_lost_time = self._opts.timecompensation
                    print 'done.'
                except ImportError,e:
                    print "The experiment module '"+ name + "' could not be imported correctly. Make sure that its own imports are properly found by Python; reason:"
                    print e
                    traceback.print_exc()
                    
            elif len(locations) == 0:
                print "The module named '" + name + "' was not found in the modules folder or any of its sub-folders."                    
            else:
                print "The module named '" + name + "' was found in multiple sub-folders of the modules folder; make sure that you are not using a duplicate name."                    


    def load_config(self,name):
        """Try to load a study config file (see studies directory)."""
        print 'Attempting to load config "'+ name+ '"...'
        file = os.path.join(self._opts.studypath,name)
        try:
            if not os.path.exists(file):
                print 'file "' + file + '" not found.'
            else:
                with open(file,'r') as f:
                    self.load_module(f.readline().strip())
                    print 'Now setting variables...',
                    for line in f.readlines():
                        exec line in self._instance.__dict__
                    print 'done; config is loaded.'
        except Exception,e:
            print 'Error while loading the study config file "' + file + '".'
            print e
            traceback.print_exc()
            
    # start executing the currently loaded module
    def start_module(self):        
        if self._instance is not None:
            self.cancel_module()
            print 'Starting module execution...',
            self._instance.start()
            print 'done.'
            self._executing = True


    # cancel executing the currently loaded module (may be started again later)
    def cancel_module(self):
        if (self._instance is not None) and self._executing:
            print 'Canceling module execution...',
            self._instance.cancel()
            print 'done.'
        self._executing = False

             
    # prune a currently loaded module's resources
    def prune_module(self):
        if (self._instance is not None):
            print "Pruning current module's resources...",
            try:
                self._instance.prune()
            except Exception as inst:
                print "Exception during prune:"
                print inst
            print 'done.'

            
    # --- internal ---

    def _init_server(self,port):
        """Initialize the remote control server."""
        destination = self._remote_commands 
        class ThreadedTCPRequestHandler(SocketServer.StreamRequestHandler):
            def handle(self):
                try:
                    print "Client connection opened."
                    while True:
                        data = self.rfile.readline().strip()
                        if len(data)==0:
                            break                        
                        destination.put(data)
                except:
                    print "Connection closed by client."

        class ThreadedTCPServer(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
            pass

        print "Bringing up remote-control server on port", port, "...",
        try:
            server = ThreadedTCPServer(("", port),ThreadedTCPRequestHandler)
            server_thread = threading.Thread(target=server.serve_forever)
            server_thread.setDaemon(True)
            server_thread.start()
            print "done."
        except:
            print "failed; the port is already taken (probably the previous process is still around)."
    
  
    # init a console that is scoped to the current module
    def _init_console(self):
        """Initialize a pull-down console. Note that this console is a bit glitchy -- use at your own risk."""
        if self._console is None:
            try:
                print "Initializing console...",
                from framework.console.interactiveConsole import pandaConsole, INPUT_CONSOLE, INPUT_GUI, OUTPUT_PYTHON
                self._console = pandaConsole(INPUT_CONSOLE|INPUT_GUI|OUTPUT_PYTHON, self._instance.__dict__)
                print "done."
            except Exception as inst:
                print "failed:"
                print inst


    # main loop step, ticked every frame
    def _main_loop_tick(self,task):
        #framework.tickmodule.engine_lock.release()
        framework.tickmodule.shared_lock.release()

        # process any queued-up remote control messages
        try:
            while True:
                cmd = str(self._remote_commands.get_nowait()).strip()            
                if cmd == "start":
                    self.start_module()
                elif (cmd == "cancel") or (cmd == "stop"):
                    self.cancel_module()
                elif cmd == "prune":
                    self.prune_module()
                elif cmd.startswith("load "):
                    self.load_module(cmd[5:])
                elif cmd.startswith("setup "):
                    try:
                        exec cmd[6:] in self._instance.__dict__
                    except:
                        pass
                elif cmd.startswith("config "):
                    if not cmd.endswith(".cfg"):
                        self.load_config(cmd[7:]+".cfg")
                    else:
                        self.load_config(cmd[7:])
        except Queue.Empty:
            pass

        # tick the current module
        if (self._instance is not None) and self._executing:
            self._instance.tick()

        framework.tickmodule.shared_lock.acquire()
        #framework.tickmodule.engine_lock.acquire()
        return Task.cont

    def terminate(self):
        global is_running
        is_running = False


# ----------------------
# --- SNAP Main Loop ---
# ----------------------

try:
    app = MainApp(opts)
    while is_running:
        framework.tickmodule.shared_lock.acquire()
        #framework.tickmodule.engine_lock.acquire()
        app.taskMgr.step()
        #framework.tickmodule.engine_lock.release()
        framework.tickmodule.shared_lock.release()
except Exception,e:
    print 'Error in main loop: ', e
    traceback.print_exc()



# --------------------------------
# --- Finalization and cleanup ---
# --------------------------------

print 'Terminating launcher...'
shutdown_markers()