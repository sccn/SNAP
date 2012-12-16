# -*- coding:utf-8 -*-
from MessagePresenter import MessagePresenter
from direct.showbase import Audio3DManager
import time
try:
	import win32com.client
except:
	pass
import threading
import math

class AudioPresenter(MessagePresenter):
    """
    A spatialized auditory display on which audio messages
    (e.g. spoken messages or beeps & boops) can be presented. It has fixed 
    display properties such as direction and volume.
    
    As a special feature, any submitted message (i.e. any update of the contents)
    may lock the presenter for a specific amount of time, during which other 
    submissions will be rejected (the sender learns about the failure of its submission
    and may deal with it appropriately), which allows to control the rate at 
    which conflicting stimuli may appear.
    
    It is a valid target for a variety of stimulus streams (e.g. DistractorStream).
    """
    
    def __init__(self,
                 direction=0.0,         # horizontal sound direction (-1..+1 is left to right panned)
                 volume=0.3,              # sound source volume
                 playrate=1.0,          # the playrate of the sound (changes pitch and time)
                 timeoffset=0.0,        # time offset into the file
                 looping=False,         # whether the sound should be looping; can be turned off by calling .stop() on the return value of this function
                 loopcount=None,        # optionally the number of repeats if looping                 
                 surround=True,         # if True, the direction will go from -Pi/2 to Pi/2
                 *args,**kwargs
                 ):             
        """Construct a new AudioPresenter."""
        MessagePresenter.__init__(self,*args,**kwargs) 
        self.direction = direction
        self.volume = volume
        self.playrate = playrate
        self.timeoffset = timeoffset
        self.looping = looping
        self.loopcount = loopcount
        self.surround = surround
        self.speak = None
        self.audio3d = None      

    def _present(self,message):
        if message[-4] == '.':
            # sound file name 
            if self.surround:            
                if self.audio3d is None:
                    self.audio3d = Audio3DManager.Audio3DManager(base.sfxManagerList[0], camera)
                mysound = self.audio3d.loadSfx(message)
                mysound.set3dAttributes(1*math.sin(self.direction),1*math.cos(self.direction),0.0,0.0,0.0,0.0)
                mysound.setVolume(self.volume)
            else:
                mysound = loader.loadSfx(message)
                mysound.setVolume(self.volume)
                mysound.setBalance(self.direction)
            if self.looping:
                mysound.setLoop(True)
            if self.loopcount is not None:
                mysound.setLoopCount(self.loopcount)
            if self.timeoffset > 0.0:
                mysound.setTime(self.timeoffset)
            mysound.setPlayRate(self.playrate)
            mysound.play()
            self.marker(221)
        else:
            # actual text (note: no directionality supported yet)
            try:
                if self.speak is None:
                    self.speak = win32com.client.Dispatch('Sapi.SpVoice')
                    self.speak.Volume = self.volume*100.0
                    self.speak.Rate = -1
                threading.Thread(target=self.do_speak,args=[message]).start()
                self.marker(221)
            except:
                print "Error initializing speech output."

    def do_speak(self,message):
        try:
            self.speak.Speak(message)
        except:
            print "Error during speech production."

    def precache(self,message):
        if message[-4] == '.':
            loader.loadSfx(message)

    def destroy(self):
        try:
            if self.speak is not None:
                self.speak.Volume = 0
        except:
            pass
