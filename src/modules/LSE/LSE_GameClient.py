from framework.latentmodule import LatentModule
import threading
import rpyc, rpyc.core, rpyc.utils.classic, rpyc.utils.server  
from pandac.PandaModules import *
from direct.task import Task
import pygame,time
import framework.ui_elements.ScrollPresenter, framework.ui_elements.TextPresenter, framework.ui_elements.ImagePresenter, framework.ui_elements.AudioPresenter, framework.ui_elements.WorldspaceGizmos
import direct.gui.OnscreenImage
try:
    import framework.speech_io.speech
except Exception as e:
    print "Could not import speech IO: ", e

#
# This is the client component of the LSE experiment implementation.
# This module is executed on the subjects' PCs. It awaits commands from the master.
#

client_version = '0.03' # this is just for the experimenter's interest



class Main(LatentModule):
    def __init__(self):
        LatentModule.__init__(self)
        self.client_port = 3663                 # port where this client waits for connections from the master
        self.client_id = 0                      # 0 for the first client, 1 for the second
        
        self.keydown_mastercallback = None
        self.keyup_mastercallback = None
        self.joymove_mastercallback = None
        self.speech_mastercallback = None
        self.callbacks_connected = False
        self.localtesting = False                # if both clients run on one machine -- then they need to use different input peripherals 
        self.allow_speech = (self.client_id == 0) if self.localtesting else True # this is for debugging
        
        self.joystick = None
        self.last_x = 0
        self.last_y = 0
        self.last_u = 0
        self.last_v = 0
        self.last_buttons = ()
        
    def run(self):
        moduleself = self
        
        class MainService(rpyc.core.SlaveService):
            """            
            An rpyc service that exposes some features of this module:
            * allows the master to hook up callbacks to inform him of keystrokes
            * grants remote access to the Panda3d engine (and any other module for that matter) 
            """
            def exposed_mastercallbacks(self,keydown_cbf,keyup_cbf,joymove_cbf,speech_cbf):
                moduleself.keydown_mastercallback = rpyc.async(keydown_cbf)
                moduleself.keyup_mastercallback = rpyc.async(keyup_cbf)
                moduleself.joymove_mastercallback = rpyc.async(joymove_cbf)
                moduleself.speech_mastercallback = rpyc.async(speech_cbf)
                moduleself.callbacks_connected = True
                
            def exposed_stimpresenter(self):
                return moduleself

        # set up window title
        winprops = WindowProperties() 
        winprops.setTitle('LSE GameClient '+client_version + ' @' + str(self.client_port)) 
        base.win.requestProperties(winprops)

        # hook up key events
        base.buttonThrowers[0].node().setButtonDownEvent('buttonDown') 
        base.buttonThrowers[0].node().setButtonUpEvent('buttonUp') 
        self.accept('buttonDown', self.on_keydown) 
        self.accept('buttonUp', self.on_keyup)

        # init joystick control
        pygame.init()
        try:
            self.joystick = pygame.joystick.Joystick(self.client_id if self.localtesting else 0) 
            self.joystick.init()
            taskMgr.add(self.update_joystick,'update_joystick')
            print "Initialized joystick."
        except:
            print "Warning: no joystick found!"

        # init speech control
        if self.allow_speech:
            try:
                framework.speech_io.speech.listenfor(['yes','no','skip','report','red','green','blue','yellow','north','south','east','west','front','back','left','right','alpha move here','bravo move here','alpha move in front of me','bravo move in front of me','alpha move to truck','bravo move to truck','alpha move behind me','bravo move behind me','alpha move to my left','bravo move to my left','alpha move to my right','bravo move to my right','suspicious object'],self.on_speech)
            except:
                print "Could not initialiate speech control; falling back to touch screen only."
            
        # initiate a server thread that listens for remote commands
        self.remote_server = rpyc.utils.server.ThreadedServer(MainService,port=self.client_port)
        self.remote_thread = threading.Thread(target=self.remote_server.start)
        self.remote_thread.setDaemon(True)
        self.remote_thread.start()

        # sleep forever, keeping the engine running in the background
        self.sleep(100000)
                
    def on_tick(self,dt):
        time.sleep(0.025)
        
    def on_keydown(self, keyname):
        if self.callbacks_connected:
            self.keydown_mastercallback(keyname)

    def on_keyup(self, keyname):
        if self.callbacks_connected:
            self.keyup_mastercallback(keyname)

    def on_speech(self,phrase,listener):
        self.speech_mastercallback(phrase)
    
    def update_joystick(self,task):
        if self.callbacks_connected and self.joystick is not None:
            for e in pygame.event.get(): pass
            x = self.joystick.get_axis(1)
            y = self.joystick.get_axis(0)
            if self.joystick.get_numaxes() >= 5:
                u = self.joystick.get_axis(3)
                v = self.joystick.get_axis(4)
            else:
                u = 0
                v = 0
            buttons = (self.joystick.get_button(0),self.joystick.get_button(1),self.joystick.get_button(2),self.joystick.get_button(3))
            if not (self.last_x == x and self.last_y == y and self.last_u == u and self.last_v == v  and self.last_buttons == buttons): 
                self.joymove_mastercallback(x,y,u,v,buttons)
                self.last_x = x
                self.last_y = y
                self.last_u = u
                self.last_v = v
                self.last_buttons = buttons
        return Task.cont
    
