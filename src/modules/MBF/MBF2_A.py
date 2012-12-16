#
# 
#
#
from framework.deprecated.controllers import CommScheduler, CheckpointDriving, VisualSearchTask

from framework.latentmodule import LatentModule
from framework.convenience import ConvenienceFunctions
from framework.ui_elements.EventWatcher import EventWatcher
from framework.ui_elements.ScrollPresenter import ScrollPresenter
from framework.ui_elements.AudioPresenter import AudioPresenter
from framework.ui_elements.TextPresenter import TextPresenter
from panda3d.core import TextProperties,TextPropertiesManager
from direct.gui.DirectGui import *
import framework.speech
import random
import time
import copy


class SimpleRewardLogic(ConvenienceFunctions):
    """
    This class does all the reward things (counts the score and plays sounds when the score is to be updated).
    See bottom of this file for the marker table.
    """
    def __init__(self,
                 initial_score=10,                    # the initial score
                 sound_params = {'direction':0.0},    # properties of the score response sound
                 gain_file = 'ding.wav',              # sound file per point
                 loss_file = 'xBuzz01.wav',           # sound file for losses
                 none_file = 'click.wav',             # file to play if no reward
                 ding_interval = 0.2,                 # interval at which successive gain sounds are played... (if score is > 1)
                 buzz_volume = 0.1,                   # volume of the buzz (multiplied by the amount of loss)
                 gain_volume = 0.5,                   # volume of the gain sound
                 ):
        ConvenienceFunctions.__init__(self)
        self.score = initial_score
        self.params = sound_params
        self.gain_file = gain_file
        self.loss_file = loss_file
        self.none_file = none_file
        self.ding_interval = ding_interval
        self.buzz_volume = buzz_volume
        self.gain_volume = gain_volume

    def score_event(self,delta,nosound=False):
        """Handle a score update."""
        self.marker(150+delta)
        self.score = self.score+delta
        if not nosound:
            if delta>0:
                self.sound(self.gain_file,volume=self.gain_volume,**self.params)
                self.marker(1)
                while delta >= 1:
                    taskMgr.doMethodLater(delta*self.ding_interval,self.play_gain,'Score sound')
                    delta -= 1
            elif delta<0:
                # the buzz sounds is just played once, regardless of the loss amount
                self.sound(self.loss_file,volume=-self.buzz_volume*delta,**self.params)
                self.marker(2)
            else:
                # the buzz sounds is just played once, regardless of the loss amount
                self.sound(self.none_file,volume=self.buzz_volume,**self.params)

    def play_gain(self,task):
        self.sound(self.gain_file,volume=self.gain_volume,**self.params)
        self.marker(1)
        return task.done
 

class WarningLight(LatentModule):
    """
    The red/green/blue warning lights (SYSMONV).
    """
    def __init__(self,
                 # general properties
                 rewardlogic,                                   # reward handling logic
                 watcher = None,                                # optional event watcher
                 focused = True,                               # whether this task is currently focused
                 markerbase = 1,                                # markers markerbase..markerbase+6 are used                       
                 event_interval=lambda: random.uniform(45,85),  # interval between two successive events

                 # cueing control
                 cueobj = None,                                 # an object that might have .iscued set to true

                 # graphics parameters
                 pic_off='light_off.png',                       # picture to display for the disabled light
                 pic_on='light_on.png',                         # picture to display for the enabled light
                 screen_offset=0,                               # offset to position this icon on one of the three screens
                 pic_params={'pos':[0,0],'scale':0.15},          # parameters for the picture() command
                 snd_params={'volume':0.3,'direction':0.0},     # parameters for the sound() command
                 
                 # response handling
                 snd_hit='click2s.wav',                        # sound when the user correctly detected the warning state
                 snd_wrongcue='xBuzz01.wav',                    # the sound that is overlaid with the buzzer when the response was wrong due to incorrect cueing
                 response_key='sysmonv-check',                            # key to press in case of an event
                 timeout=2.5,                                   # response timeout for the user
                 hit_reward=0,                                  # reward if hit
                 miss_penalty=-20,                              # penalty if missed
                 false_penalty=-5,                              # penalty for false positives

                 # ticking support
                 pic_tick_off=None,                             # optional blinking in off status
                 pic_tick_on=None,                              # optional blinking in on status
                 tick_rate = None,                              # tick rate (duration in non-tick status, duration in tick status)
                 ):
        
        LatentModule.__init__(self)
        self.rewardlogic = rewardlogic
        self.focused = focused
        self.markerbase = markerbase
        self.event_interval = event_interval
        self.pic_off = pic_off
        self.pic_on = pic_on
        self.pic_params = copy.deepcopy(pic_params)
        self.snd_wrongcue = snd_wrongcue
        self.snd_params = snd_params
        self.snd_hit = snd_hit
        self.response_key = response_key
        self.timeout = timeout
        self.hit_reward = hit_reward
        self.miss_penalty = miss_penalty
        self.false_penalty = false_penalty
        self.screen_offset = screen_offset
        self.cueobj = cueobj
        self.control = False
        self.pic_tick_off = pic_tick_off 
        self.pic_tick_on = pic_tick_on
        if self.pic_tick_on is None:
            self.pic_tick_on = self.pic_on
        if self.pic_tick_off is None:
            self.pic_tick_off = self.pic_off
        self.tick_rate = tick_rate
        self.watcher = watcher

    def run(self):
        self.pic_params['pos'][0] += self.screen_offset
        # pre-cache the media files...
        self.precache_picture(self.pic_on)
        self.precache_picture(self.pic_off)
        self.precache_picture(self.pic_tick_on)
        self.precache_picture(self.pic_tick_off)
        self.precache_sound(self.snd_wrongcue)
        self.precache_sound(self.snd_hit)
        self.accept('control',self.oncontrol,[True])
        self.accept('control-up',self.oncontrol,[False])
        
        # set up an event watcher (taking care of timeouts and inappropriate responses)
        if self.watcher is None:
            self.watcher = EventWatcher(eventtype=self.response_key,
                                        handleduration=self.timeout,
                                        defaulthandler=self.false_detection)

        while True:
            # show the "off" picture for the inter-event interval
            if self.tick_rate is not None:
                t_end = time.time()+self.event_interval()
                while time.time() < t_end:
                    self.marker(self.markerbase+10)
                    # show the off/tic pic
                    self.picture(self.pic_tick_off, self.tick_rate[1], **self.pic_params)
                    # show the off pic
                    self.picture(self.pic_off, self.tick_rate[0], **self.pic_params)
            else:
                # just show the off pick
                self.picture(self.pic_off, self.event_interval(), **self.pic_params)

            # start watching for a response
            self.watcher.watch_for(self.correct, self.timeout, self.missed)
            self.marker(self.markerbase if self.focused else (self.markerbase+1))
            if self.tick_rate is not None:
                t_end = time.time()+self.timeout
                while time.time() < t_end:
                    self.marker(self.markerbase+11)
                    # show the on/tic pic
                    self.picture(self.pic_tick_on, self.tick_rate[1], **self.pic_params)
                    # show the off pic
                    self.picture(self.pic_on, self.tick_rate[0], **self.pic_params)
            else:
                # just show the "on" picture
                self.picture(self.pic_on, self.timeout, **self.pic_params)
            self.marker(self.markerbase+2)
            # reset the cue status
            if self.cueobj is not None:
                self.cueobj.iscued = False

    def oncontrol(self,status):
        self.control = status

    def missed(self):
        if self.focused:
            self.marker(self.markerbase+3)
            self.rewardlogic.score_event(self.miss_penalty)

    def false_detection(self):
        self.marker(self.markerbase+4)
        self.rewardlogic.score_event(self.false_penalty)
        
    def correct(self):        
        if self.focused:
            if ((self.cueobj is not None) and self.cueobj.iscued):
                self.marker(self.markerbase+5 if self.control else self.markerbase+6)
            else:
                self.marker(self.markerbase+7 if self.control else self.markerbase+8)
            if self.control == ((self.cueobj is not None) and self.cueobj.iscued):
                # the user correctly spots the warning event            
                self.sound(self.snd_hit,**self.snd_params)
                self.rewardlogic.score_event(self.hit_reward)
            else:
                # the user spotted it, but didn't get the cue right
                self.sound(self.snd_wrongcue,**self.snd_params)
                self.rewardlogic.score_event(self.false_penalty)
        else:
            self.marker(self.markerbase+9)
            # the user spotted it, but was not tasked to do so... 
            self.rewardlogic.score_event(self.false_penalty) 

    def flash(self,status,duration=1):
        self.picture(self.pic_on if status else self.pic_off,duration=duration, **self.pic_params)


class CueLight(LatentModule):
    """
    The yellow cue light (SYSMONV).
    """
    def __init__(self,
                 rewardlogic,
                 focused = True,                               # whether this task is currently focused
                 markerbase = 1,                                # markers markerbase..markerbase+6 are used                       
                 event_interval=lambda: random.uniform(45,85),  # interval between two successive events
                 pic_off='light_off.png',                       # picture to display for the disabled light
                 pic_on='light_on.png',                         # picture to display for the enabled light
                 screen_offset=0,                               # offset to position this icon on one of the three screens
                 pic_params={'pos':[0,0],'scale':0.15},         # parameters for the picture() command
                 duration = 1.5,                                # duration for which the cue light stays on 
                 ):
        
        LatentModule.__init__(self)
        self.rewardlogic = rewardlogic
        self.focused = focused
        self.markerbase = markerbase
        self.event_interval = event_interval
        self.pic_off = pic_off
        self.pic_on = pic_on
        self.pic_params = pic_params
        self.screen_offset = screen_offset
        self.duration = duration
        self.pic_params = copy.deepcopy(pic_params)
        self.iscued = False

    def run(self):
        self.pic_params['pos'][0] += self.screen_offset
        # pre-cache the media files...
        self.precache_picture(self.pic_on)
        self.precache_picture(self.pic_off)
        while True:
            if not self.focused:
                self.iscued = False
            # show the "off" picture for the inter-event interval
            self.picture(self.pic_off, self.event_interval(), **self.pic_params)
            # show the "on" picture and cue the other items
            self.marker(self.markerbase+1)
            if self.focused:
                self.iscued = True            
            self.picture(self.pic_on, self.duration, **self.pic_params)

    def flash(self,status,duration=1):
        self.picture(self.pic_on if status else self.pic_off,duration=duration, **self.pic_params)


class WarningSound(LatentModule):
    """
    The warning sounds (SYSMONA).
    """
    def __init__(self,
                 # general properties
                 rewardlogic,                                   # reward handling logic
                 watcher = None,                                # response event watcher
                 focused = True,                               # whether this task is currently focused
                 markerbase = 1,                                # markers markerbase..markerbase+6 are used                       
                 event_interval=lambda: random.uniform(45,85),  # interval between two successive events

                 # cueing control
                 cueobj = None,                                 # an object that might have .iscued set to true

                 # audio parameters
                 screen_offset=0,                               # offset to position this source on one of the three screens
                 snd_on='xHyprBlip.wav',                            # sound to play in case of an event
                 snd_params={'volume':0.25,'direction':0.0},     # parameters for the sound() command
                 
                 # response handling
                 snd_hit='click2s.wav',                        # sound when the user correctly detected the warning state
                 snd_wrongcue='xBuzz01.wav',                    # the sound that is overlaid with the buzzer when the response was wrong due to incorrect cueing
                 response_key='sysmona-check',                  # key to press in case of an event
                 timeout=5.5,                                   # response timeout for the user
                 hit_reward=0,                                  # reward if hit
                 miss_penalty=-20,                              # penalty if missed
                 false_penalty=-5,                              # penalty for false positives

                 # ticking support
                 snd_tick_off=None,                             # optional ticking in off status
                 snd_tick_on=None,                              # optional ticking in on status
                 tick_rate = None,                              # tick rate (duration in non-tick status, duration in tick status)
                 ):
        
        LatentModule.__init__(self)
        self.rewardlogic = rewardlogic
        self.focused = focused
        self.markerbase = markerbase
        self.event_interval = event_interval
        self.snd_on = snd_on
        self.snd_params = snd_params
        self.snd_wrongcue = snd_wrongcue
        self.snd_hit = snd_hit
        self.response_key = response_key
        self.timeout = timeout
        self.hit_reward = hit_reward
        self.miss_penalty = miss_penalty
        self.false_penalty = false_penalty
        self.screen_offset = screen_offset
        self.snd_params = copy.deepcopy(snd_params)
        self.cueobj = cueobj
        self.control = False
        self.snd_tick_off = snd_tick_off 
        self.snd_tick_on = snd_tick_on
        self.tick_rate = tick_rate
        self.watcher = watcher

    def run(self):
        self.snd_params['direction'] += self.screen_offset
        # pre-cache the media files...
        self.precache_sound(self.snd_on)
        self.precache_sound(self.snd_tick_on)
        self.precache_sound(self.snd_tick_off)
        self.precache_sound(self.snd_wrongcue)
        self.precache_sound(self.snd_hit)
        self.accept('control',self.oncontrol,[True])
        self.accept('control-up',self.oncontrol,[False])
        
        # set up an event watcher (taking care of timeouts and inappropriate responses)
        if self.watcher is None:
            self.watcher = EventWatcher(eventtype=self.response_key,
                                        handleduration=self.timeout,
                                        defaulthandler=self.false_detection)
        while True:
            # off status
            if self.tick_rate is not None:
                t_end = time.time()+self.event_interval()
                while time.time() < t_end:
                    self.marker(self.markerbase+10)
                    # play the off/tic snd                    
                    self.sound(self.snd_tick_off, **self.snd_params)
                    self.sleep(self.tick_rate[1])
                    # wait
                    self.sleep(self.tick_rate[0])
            else:
                # wait
                self.sleep(self.event_interval())

            # start watching for a response
            self.watcher.watch_for(self.correct, self.timeout, self.missed)
            self.marker(self.markerbase if self.focused else (self.markerbase+1))
            if self.tick_rate is not None:
                t_end = time.time()+self.timeout
                while time.time() < t_end:
                    self.marker(self.markerbase+11)
                    # play the on/tic sound
                    if self.snd_tick_on is not None:
                        self.sound(self.snd_tick_on,**self.snd_params)
                    self.sleep(self.tick_rate[1])
                    # wait
                    self.sleep(self.tick_rate[0])
            else:
                # just play the "on" sound
                if self.snd_on is not None:
                    self.sound(self.snd_on, **self.snd_params)
                self.sleep(self.timeout)
            self.marker(self.markerbase+2)
            # reset the cue status
            if self.cueobj is not None:
                self.cueobj.iscued = False

    def oncontrol(self,status):
        self.control = status

    def missed(self):
        if self.focused:
            self.marker(self.markerbase+3)
            self.rewardlogic.score_event(self.miss_penalty)

    def false_detection(self):
        self.marker(self.markerbase+4)
        self.rewardlogic.score_event(self.false_penalty)
        
    def correct(self):        
        if self.focused:
            if ((self.cueobj is not None) and self.cueobj.iscued):
                self.marker(self.markerbase+5 if self.control else self.markerbase+6)
            else:
                self.marker(self.markerbase+7 if self.control else self.markerbase+8)
            if self.control == ((self.cueobj is not None) and self.cueobj.iscued):
                # the user correctly spots the warning event            
                self.sound(self.snd_hit,**self.snd_params)
                self.rewardlogic.score_event(self.hit_reward)
            else:
                # the user spotted it, but didn't get the cue right
                self.sound(self.snd_wrongcue,**self.snd_params)
                self.rewardlogic.score_event(self.false_penalty)
        else:
            self.marker(self.markerbase+9)
            # the user spotted it, but was not tasked to do so... 
            self.rewardlogic.score_event(self.false_penalty) 

    def flash(self,filename):
        self.sound(filename, **self.snd_params)        


class CueSound(LatentModule):
    """
    The cue sound (SYSMONVA).
    """
    def __init__(self,
                 rewardlogic,
                 focused = True,                               # whether this task is currently focused
                 markerbase = 1,                                # markers markerbase..markerbase+6 are used                       
                 event_interval=lambda: random.uniform(45,85),  # interval between two successive events
                 snd_on='xBleep.wav',                           # picture to display for the enabled light
                 screen_offset=0,                               # offset to position this icon on one of the three screens
                 snd_params={'volume':0.3,'direction':0.0},     # parameters for the sound() command
                 ):
        
        LatentModule.__init__(self)
        self.rewardlogic = rewardlogic
        self.focused = focused
        self.markerbase = markerbase
        self.event_interval = event_interval
        self.snd_on = snd_on
        self.snd_params = snd_params
        self.screen_offset = screen_offset
        self.snd_params = copy.deepcopy(self.snd_params)
        self.iscued = False

    def run(self):
        self.snd_params['direction'] += self.screen_offset
        # pre-cache the media files...
        self.precache_sound(self.snd_on)
        while True:
            self.sleep(self.event_interval())
            # play the "on" sound and cue the other items
            self.iscued = self.focused
            self.sound(self.snd_on, **self.snd_params)

class MathScheduler(LatentModule):
    """
    A class that presents random math problems to a presenter and processes user input.
    Optionally, the math problems can be just a type of distractor stream. 
    """
    def __init__(self,
                 # facilities used by this object
                 rewardhandler=None,            # a RewardLogic instance that manages the processing of generated rewards/penalties 
                 presenter=None,                # the presenter on which to output the math problems
                 presenter_params={'pos':lambda:[random.uniform(-0.5,0.5),random.uniform(-0.5,0)],      # parameters of a textpresenter, if no presenter is given
                                   'clearafter':3,'framecolor':[0,0,0,0],'scale':0.1,'align':'center'},
                 focused = True,                # whether this task is currently focused

                 # end conditions
                 end_timeout=None,              # end presentation after the timeout has passed
                 end_numproblems=None,          # end presentation after this number of problems have been presented
                 
                 # stimulus presentation statistics
                 difficulty=1,                  # difficulty level of the problems
                 problem_interval = lambda: random.uniform(3,12), # delay before a new problem appears after the previous one has been solved
                 
                 # response timing
                 response_timeout=10.0,         # time within which the subject may respond to a problem
                 gain_correct=3,                # gain if problem solved correctly
                 loss_incorrect=-2,             # loss if problem solved incorrectly                 
                 loss_nonfocused=-1,            # loss if problem 
                 
                 # parameters for the numpad
                 numpad_topleft=[1.4,-0.15],    # top-left corner of the numpad
                 numpad_gridspacing=[0.21,-0.21], # spacing of the button grid
                 numpad_buttonsize=[1,1],       # size of the buttons
                 numpad_textscale=0.2,       # size of the buttons
                 ):
                
        LatentModule.__init__(self)
        
        self.rewardhandler = rewardhandler
        self.presenter = presenter
        self.presenter_params = presenter_params
        self.end_timeout = end_timeout
        self.end_numproblems = end_numproblems
        
        self.difficulty = difficulty
        self.problem_interval = problem_interval
        self.response_timeout = response_timeout
        self.gain_correct = gain_correct
        self.loss_incorrect = loss_incorrect
        self.loss_nonfocused = loss_nonfocused

        self.numpad_topleft = numpad_topleft
        self.numpad_gridspacing = numpad_gridspacing
        self.numpad_buttonsize = numpad_buttonsize
        self.numpad_textscale = numpad_textscale
        self.focused = focused
        self.input = ''
        
    def run(self):
        try:
            if self.presenter is None:
                self.presenter = TextPresenter(**self.presenter_params)
            
            font = loader.loadFont('arial.ttf')
            xoff = 0.0
            yoff = 0.35
            size = 0.5
            # create the numpad
            self.buttons = []
            for k in range(10):
                if k==9:
                    x,y,n = 0,3,0
                else:
                    x,y,n = k%3,k/3,k+1
                self.buttons.append(DirectButton(frameSize=(-size+xoff,size+xoff,-size+yoff,size+yoff),
                                                 pos=(self.numpad_topleft[0] + x*self.numpad_gridspacing[0],0,self.numpad_topleft[1] + y*self.numpad_gridspacing[1]),
                                                 text_font=font, text=str(n), scale=self.numpad_textscale, command=messenger.send, extraArgs=['num-' + str(n)],
                                                 rolloverSound=None, clickSound=None))
            # and add the "next" button
            self.buttons.append(DirectButton(frameSize=(-(size+0.013)*2/0.13*0.2,(size+0.013)*2/0.13*0.2, -0.45,1.07 ),
                                             pos=(self.numpad_topleft[0] + 1.5*self.numpad_gridspacing[0],0,self.numpad_topleft[1] + 3*self.numpad_gridspacing[1]+self.numpad_textscale*0.15),
                                             text_font=font, text="NEXT", scale=0.65*self.numpad_textscale, command=messenger.send, extraArgs=['num-next'],
                                             rolloverSound=None, clickSound=None))

            # begin record-keeping...
            problems = 0
            starttime = time.time()

            for d in range(10):
                self.accept('num-'+str(d),self.on_digit,[d])
            self.accept('num-next',self.on_next)
            
            # for each problem...
            while True:
                # wait for the inter-problem interval
                self.sleep(self.problem_interval())
            
                # generate a new problem            
                op = random.choice(['+','*']) if self.difficulty > 3 else '+'
                A = int(random.uniform(7,7+self.difficulty*10))
                B = int(random.uniform(7,7+self.difficulty*10))            
            
                # present it
                self.presenter.submit_wait(str(A) + " " + op + " " + str(B) + " = ",self)
                
                # record the pressed digits (and resume() once next is pressed)
                self.input = ''
                self.sleep(self.response_timeout)
                    
                # convert them into a number and check if the typed-in answer is correct
                if self.focused:
                    input = int(self.input) if self.input != '' else 0
                    if input == (A+B if op=='+' else A*B):
                        self.rewardhandler.score_event(self.gain_correct)
                    else:
                        self.rewardhandler.score_event(self.loss_incorrect)
                self.presenter.clear()
                            
                # check end conditions
                problems += 1
                if self.end_numproblems is not None and problems > self.end_numnumproblems:
                    break
                if self.end_timeout is not None and time.time() > starttime + self.end_timeout:
                    break
            
        finally:
            self.ignoreAll()
            for b in self.buttons:
                b.destroy()

    def on_digit(self,d):
        self.input += str(d)

    def on_next(self):
        if self.focused:
            self.resume()
        else:
            self.rewardhandler.score_event(self.loss_nonfocused)
            self.presenter.clear()
            self.presenter.submit_wait('not focused!',self)

class Main(LatentModule):    
    
    def __init__(self):
        LatentModule.__init__(self)

        self.randseed = 11463       # some initial randseed for the experiment; note that this should be different for each subject (None = random)

        # block design        
        self.uiblocks = 24          # number of blocks with different UI permutation: should be a multiple of 6
        self.focus_per_layout = 8   # number of focus conditions within a UI layout block
        self.rest_every = 3         # insert a rest period every k UI blocks
        self.focus_duration = lambda: random.uniform(30,50) # duration of a focus block (was: 30-50)
        self.initial_rest_time = 10 # initial rest time at the beginning of a new UI layout block

        self.tasknames = {'sysmonv':'visual system monitoring','sysmona':'auditory system monitoring','comma':'auditory communciations','commv':'text communications','math':'mathematics','satmap':'satellite map','drive':'driving task'}        
        # TODO: make this more complete
        self.conditions = ['sysmonv-sysmona','commv-comma','math-satmap','math-drive','comma-satmap','comma-drive','comma-sysmona','sysmona-drive','sysmona-satmap','sysmonv','sysmona','commv','comma','satmap','drive','math']
        self.bottom_up_probability = 0.5 # probability that the switch stimulus is bottom-up
        
        
        # === score logic setup (parameters to SimpleRewardLogic) ===
        self.score_params = {'initial_score':10,                # the initial score
                             'sound_params':{'direction':-0.7}, # properties of the score response sound
                             'gain_file':'ding.wav',            # sound file per point
                             'loss_file':'xBuzz01-rev.wav',     # sound file for losses
                             'none_file':'click.wav',           # file to play if no reward
                             'buzz_volume':0.4,                 # volume of the buzz (multiplied by the amount of loss)
                             'gain_volume':0.5,                 # volume of the gain sound                             
                             'ding_interval':0.15}              # interval at which successive gain sounds are played... (if score is > 1)
        
        self.false_response_penalty = -1    # penalty due to false response in visual/auditory system monitoring

        # === visual system monitoring elements === 
        self.sysmonv_timeout = 3
        self.light_scale = 0.1
        self.light_offset = 0.175
        self.light_x = 0.09
        self.redlight_params = {'markerbase':1,                                  # markers markerbase..markerbase+6 are used                       
                                'event_interval':lambda: random.uniform(15,35),  # interval between two successive events
                                'focused':False,
                                'pic_off':'buzzer-grey.png',                     # picture to display for the disabled light
                                'pic_on':'buzzer-red-real.png',                  # picture to display for the enabled light
                                'snd_hit':'xClick01.wav',                        # sound when the user correctly detected the warning state
                                'pic_params':{'pos':[self.light_x-2*self.light_offset,0.8],'scale':self.light_scale},          # parameters for the picture() command
                                'response_key':'sysmonv-check',                            # key to press in case of an event
                                'timeout':2.5,                                   # response timeout for the user
                                'hit_reward':1,                                  # reward if hit
                                'miss_penalty':-1,                              # penalty if missed
                                'false_penalty':-1,                              # penalty for false positives
                                }
        self.greenlight_params = {'markerbase':20,                                  # markers markerbase..markerbase+6 are used                       
                                  'event_interval':lambda: random.uniform(21,41),  # interval between two successive events
                                  'focused':False,
                                  'pic_off':'buzzer.png',                          # picture to display for the disabled light
                                  'pic_on':'buzzer-grey.png',                      # picture to display for the enabled light
                                  'snd_hit':'xClick01.wav',                        # sound when the user correctly detected the warning state
                                  'pic_params':{'pos':[self.light_x-1*self.light_offset,0.8],'scale':self.light_scale},        # parameters for the picture() command
                                  'response_key':'sysmonv-check',                            # key to press in case of an event
                                  'timeout':2.5,                                   # response timeout for the user
                                  'hit_reward':1,                                  # reward if hit
                                  'miss_penalty':-1,                              # penalty if missed
                                  'false_penalty':-1,                              # penalty for false positives
                                  }
        self.bluelight_params =   {'markerbase':40,                                  # markers markerbase..markerbase+6 are used                       
                                   'event_interval':lambda: random.uniform(19,44),  # interval between two successive events
                                   'focused':False,
                                   'pic_off':'buzzer-grey.png',                          # picture to display for the disabled light
                                   'pic_on':'buzzer-grey.png',                      # picture to display for the enabled light
                                   'snd_hit':'xClick01.wav',                        # sound when the user correctly detected the warning state
                                   'pic_params':{'pos':[self.light_x+0*self.light_offset,0.8],'scale':self.light_scale},        # parameters for the picture() command
                                   'response_key':'sysmonv-check',                            # key to press in case of an event
                                   'timeout':2.75,                                   # response timeout for the user
                                   'hit_reward':2,                                  # reward if hit
                                   'miss_penalty':-1,                              # penalty if missed
                                   'false_penalty':-1,                              # penalty for false positives
                                   'pic_tick_off':'buzzer-blue.png',                          # picture to display for the disabled light
                                   'tick_rate':[1.2,0.1],
                                   }
        self.yellowlight_params = {'markerbase':60,                                  # markers markerbase..markerbase+6 are used                       
                                   'event_interval':lambda: random.uniform(40,70),  # interval between two successive events
                                   'focused':False,
                                   'pic_off':'buzzer-grey.png',                          # picture to display for the disabled light
                                   'pic_on':'buzzer-yellow.png',                      # picture to display for the enabled light
                                   'pic_params':{'pos':[self.light_x+1*self.light_offset,0.8],'scale':self.light_scale},        # parameters for the picture() command
                                   'duration':1.5,                                  # duration for which the cue light stays on
                                   }
        self.button_sysmonv_par = {'frameSize':(-4.5,4.5,-0.45,0.95),'text':"Check",'scale':.075,'text_font':loader.loadFont('arial.ttf')}
        self.button_sysmonv_pos = [0,0.63]
        
        # === auditory system monitoring tasks ===
        self.sysmona_timeout = 3
        self.warnsound_params = {'markerbase':80,                                  # markers markerbase..markerbase+6 are used                       
                                 'event_interval':lambda: random.uniform(15,35),  # interval between two successive events
                                 'focused':False,
                                 'snd_on':'buzzz.wav',                        # picture to display for the enabled light
                                 'response_key':'sysmona-check',                            # key to press in case of an event
                                 'timeout':5.5,                                   # response timeout for the user
                                 'hit_reward':1,                                  # reward if hit
                                 'miss_penalty':-3,                              # penalty if missed
                                 'false_penalty':-1,                              # penalty for false positives
                                 }
        self.ticksound_params = {'markerbase':100,                                # markers markerbase..markerbase+6 are used                       
                                 'event_interval':lambda: random.uniform(19,40),  # interval between two successive events
                                 'snd_params':{'volume':0.2,'direction':0.0},     # parameters for the sound() command
                                 'focused':False,
                                 'snd_on':None,
                                 'snd_tick_off':'xTick.wav',                      # picture to display for the enabled light
                                 'response_key':'sysmona-check',                            # key to press in case of an event
                                 'timeout':6.5,                                   # response timeout for the user
                                 'hit_reward':2,                                  # reward if hit
                                 'miss_penalty':-3,                              # penalty if missed
                                 'false_penalty':-1,                              # penalty for false positives
                                 'tick_rate':[0.7,0.1],                             # rate of the ticking...
                                 }
        self.cuesound_params = {'markerbase':120,                                  # markers markerbase..markerbase+6 are used                       
                                'focused':False,
                                'event_interval':lambda: random.uniform(40,70),  # interval between two successive events
                                'snd_on':'xDeadRing.wav',                      # picture to display for the enabled light
                                'snd_params':{'volume':0.5,'direction':0.0},
                                }
        self.button_sysmona_par = {'frameSize':(-2,2,-0.5,1),'text':'"Check"','scale':.075,'text_font':loader.loadFont('arial.ttf')}
        self.button_sysmona_pos = [0.25,-0.34]

        # === auditory comm setup ===
        self.voice_params = {'direction':0,'volume':1}
        self.commaud_params = {'markerbase':400,                            # base marker offset
                               'focused':False,
                               'commands':'Commands.txt',                   # source file containing a list of commands
                               'distractors':'Filler.txt',                  # source file containing a list of distractor sentences
                               'cue_probability':0.1,                       # probability that a cue message is selected
                               'distractor_probability':0.35,                # probability that a distractor message is selected
                               'nontarget_probability':0.3,                 # probability that a non-target callsign message is selected
                               'target_probability':0.25,                    # probability that a target callsign message is selected                 
                               'isi':lambda: random.uniform(7,13),           # message interval
                               'end_trials':100000,                         # number of trials to produce
                               'end_timeout':100000,                        # lifetime of this stream, in seconds
                               'response_event':'comma-roger',                        # response button to use
                               'timeout':6,                                 # response timeout...                    
                               'loss_nontarget':-1,                         # amount of loss incurred when pressing for a non-target or if not focused
                               'loss_missed':-1,                            # amount of loss incurred when missing a target
                               'gain_target':2,                 
                               }
        self.button_comma_par = {'frameSize':(-2,2,-0.5,1),'text':'"Roger"','scale':.075,'text_font':loader.loadFont('arial.ttf')}
        self.button_comma_pos = [-0.25,-0.34]

        # === visual comm setup ===
        self.scroll_pos = [-0.475,-0.4]
        self.scroll_params = {'width':28,'scale':0.035}
        self.commvis_params = {'markerbase':300,                            # base marker offset
                               'focused':False,
                               'commands':'Commands.txt',                   # source file containing a list of commands
                               'distractors':'Filler.txt',                  # source file containing a list of distractor sentences
                               'cue_probability':0.1,                       # probability that a cue message is selected
                               'distractor_probability':0.4,                # probability that a distractor message is selected
                               'nontarget_probability':0.3,                 # probability that a non-target callsign message is selected
                               'target_probability':0.2,                    # probability that a target callsign message is selected                 
                               'isi':lambda: random.uniform(6,10),           # message interval
                               'end_trials':100000,                         # number of trials to produce
                               'end_timeout':100000,                        # lifetime of this stream, in seconds
                               'response_event':'commv-roger',                        # response button to use
                               'timeout':5,                                 # response timeout...                    
                               'loss_nontarget':-1,                         # amount of loss incurred when pressing for a non-target or if not focused
                               'loss_missed':-1,                            # amount of loss incurred when missing a target
                               'gain_target':2,                 
                               }
        
        self.button_commv_par = {'frameSize':(-1.8,1.8,-0.35,0.85),'text':"Roger",'scale':.075,'text_font':loader.loadFont('arial.ttf')}
        self.button_commv_pos = [0.375,-0.44]

        # === math task setup ===
        self.numpad_topleft = [-0.4,0.7]                            # top-left corner of the numpad
        self.math_params = {'difficulty': 2,                        # difficulty level of the problems (determines the size of involved numbers)
                            'focused':False,                            
                            'problem_interval': lambda: random.uniform(5,17), # delay before a new problem appears after the previous one has been solved
                            'response_timeout': 15.0,               # time within which the subject may respond to a problem           
                            'numpad_gridspacing': [0.16,-0.16],     # spacing of the button grid
                            'numpad_buttonsize': [0.75,0.75],              # size of the buttons
                            'numpad_textscale': 0.15                 # scale of the text
                            }
        self.math_display_par = {'scale':0.04, 'textcolor':[1,1,1,1],'framecolor':[0,0,0,1],'width':9,'height':10}
        self.math_display_pos = [0.12,0.67]
        
        # === satmap task setup ===
        self.satmap_frame = [0.35,0.65,0.57,0.925]                              # the display region in which to draw everything
        self.satmap_params = {'background':'satellite_baseline.png',         # background image to use 
                              'frame_boundary':0.2,                          # (invisible) zone around the display region in which things can move around and spawn
                              'focused':False,
            
                              # parameters of the target/non-target item processes
                              'clutter_params':{'pixelated':True,
                                                'num_items':50,
                                                'item_speed': lambda: random.uniform(0,0.05),             # overall item movement speed; may be callable 
                                                'item_diffusion': lambda: random.normalvariate(0,0.005),  # item Brownian perturbation process (applied at each frame); may be callable                                                
                                                },           # parameters for the clutter process
                              'target_params':{'pixelated':True,
                                               'num_items':1,
                                               'item_speed':lambda: random.uniform(0.01,0.05),
                                               'item_diffusion': lambda: random.normalvariate(0,0.005),  # item Brownian perturbation process (applied at each frame); may be callable
                                               'item_spiral':lambda: [random.uniform(0,3.14),random.uniform(0.005,0.0075),random.uniform(0.015,0.02)],
                                               }, # parameters for the target process
                              'intro_text':'',     # the text that should be displayed before the script starts                                                                                 
                             
                              # situational control
                              'target_probability':0.5,                      # probability of a new situation being a target situation (vs. non-target situation) 
                              'target_duration':lambda: random.uniform(3,6), # duration of a target situation
                              'nontarget_duration':lambda: random.uniform(5,15),# duration of a non-target situation
                             
                              # end conditions
                              'end_trials':1000000,                          # number of situations to produce (note: this is not the number of targets)
                              'end_timeout':1000000,                         # lifetime of this stream, in seconds (the stream ends if the trials are exhausted)
                             

                              # response control
                              'response_event':'satmap-target',              # the event that is generated when the user presses the response button
                              'loss_misstarget':-1,                           # the loss incurred by missing a target                 
                              'loss_nontarget':-1,                           # the loss incurred by a false detection
                              'gain_target':2,                               # the gain incurred by correctly spotting a target 
                              }       
        # this button is drawn into the satmap and can currently not be clicked 
        self.button_satmap_par = {'pos':(0.31,0,0.4),'frameSize':(-2.4,2.4,-0.6,1.1),'sortOrder':10,'text':"Target",'scale':.075,'text_font':loader.loadFont('arial.ttf'),'command':messenger.send,'extraArgs':['satmap-target'],'rolloverSound':None,'clickSound':None}
        self.button_satmap_pos = [0,0]
        # this button is in 3-screen space and can be clicked; it is behind the other button
        self.button_satmap2_par = {'frameSize':(-2.5,2.5,-0.4,0.9),'text':"",'scale':.075,'text_font':loader.loadFont('arial.ttf'),'command':messenger.send,'extraArgs':['satmap-target'],'rolloverSound':None,'clickSound':None}
        self.button_satmap2_pos = [0.31,0.77]


        # === drive task setup ===
        self.drive_frame = [0.35,0.65,0.2,0.55]
        self.drive_params = {'focused':False,
                             
                             # media                  
                             'envmodel':'big\\citty.egg',       # the environment model to use
                             'trucksound':"diesel_loop.wav",    # loopable truck sound....
                             'target_model':"moneybag-rev.egg", # model of the target object
                             'target_scale':0.01,               # scale of the target model
                             'target_offset':0.2,               # y offset for the target object 

                             # checkpoint logic 
                             'points':[[-248.91,-380.77,4.812],[0,0,0]], # the sequence of nav targets...
                             'radius':20,                   # proximity to checkpoint at which it is considered reached... (meters)

                             # end conditions
                             'end_timeout':100000,          # end the task after this time
                             'show_checkpoints':False,      # whether to show when a checkpoint is reached
                             
                             # movement parameters
                             'acceleration':0.5,            # acceleration during manual driving
                             'friction':0.95,               # friction coefficient
                             'torque':1,                    # actually angular velocity during turning
                             'height':0.7}
        self.button_drive_par = {'frameSize':(-2.5,2.5,-0.4,0.9),'text':"Report",'scale':.075,'text_font':loader.loadFont('arial.ttf')}
        self.button_drive_pos = [0.31,0.025]

        # focus stimuli
        self.bu_drive_img = {'image':'salient_warning.png',         # bottom-up driving task
                             'scale':0.25}
        self.bu_satmap_img = {'image':'salient_warning.png',        # bottom-up satmap task
                              'scale':0.25}
        self.bu_math_img = {'image':'salient_warning.png',          # bottom-up math task
                            'scale':0.15}
        self.bu_sysv_img = {'image':'salient_warning.png',          # bottom-up sysmonv task
                            'scale':0.15}
        self.bu_sysmona_img = {'image':'salient_warning.png',       # bottom-up sysmona task
                               'scale':0.15}
        self.bu_comma_img = {'image':'salient_warning.png',         # bottom-up comma task
                             'scale':0.15}

        self.initial_layout_time = 5                                # initial time after layout switch
        
        # callsign setup
        self.callsign_file = 'callsigns.txt'
        self.numcallsigns = 6        

        # misc parameters
        self.screen_offsets = [-1.13,0,1.13]   # the three screen offsets for UI permutation...
        self.developer = True
        
        # voice control
        self.voice_icon_enlarge_duration = 0.5
        self.voice_icon_enlarge_size = 0.12
        self.allow_speech = True
        
        # set up some global text highlighting functionality
        tpHighlight = TextProperties()
        tpHighlight.setTextColor(1, 0, 0, 1)
        tpHighlight.setSlant(0.3)        
        tpMgr = TextPropertiesManager.getGlobalPtr()
        tpMgr.setProperties("highlight", tpHighlight)
                
    def run(self):
        try:
            # init the randseed
            if self.randseed is not None:
                print "WARNING: Randomization of the experiment is currently bypassed."
                random.seed(self.randseed)
                self.marker(30000+self.randseed)
    
            if not self.developer:
                self.write('Welcome to the MBF2 experiment A.')
            
            # generate the UI block schedule
            layouts = [[0,1,2],[0,2,1],[1,0,2],[1,2,0],[2,0,1],[2,1,0]]
            if self.uiblocks % len(layouts) > 0:
                raise Exception('The # of UI blocks should be a multiple of 6')
            layouts = layouts*(self.uiblocks/len(layouts))
            random.shuffle(layouts)
    
            # determine the sequence of focus conditions for each layout block
            conditions = self.conditions*(1+self.uiblocks*self.focus_per_layout/len(self.conditions))
            conditions = conditions[:self.uiblocks*self.focus_per_layout]
            random.shuffle(conditions)
            
            # re-group them by layout
            focus_conditions = []
            for k in range(len(layouts)):
                focus_conditions.append(conditions[k*self.focus_per_layout : (1+k)*self.focus_per_layout])
                if (k+1) % self.rest_every == 0:
                    focus_conditions[k].append('') # append resting...        
            # pre-pend rest to the first block
            focus_conditions[0].insert(0,'')
            
            if not self.developer:
                self.write('Press the space bar when you are ready.','space')
    
            # set up the reward logic
            self.rewardlogic = SimpleRewardLogic(**self.score_params)

            # load callsign table            
            self.callsigns = []
            with open('media\\'+self.callsign_file,'r') as f:
                for line in f:
                    self.callsigns.append(line.strip())
            self.callsigns = self.callsigns[:self.numcallsigns]

            # init speech control            
            if self.allow_speech:
                try:
                    framework.speech.listenfor(['roger','check','yes','no'],self.onspeech)
                except:
                    print "Could not initialiate speech control; falling back to touch screen only."
            
            # self.write('Prepare yourself for the task.',5,pos=[0,0.9],block=False)
            # for each UI layout block...        
            for k in range(len(layouts)):
                for i in [3,2,1]:
                    self.write('New block begins in '+str(i))
                self.marker(400+k)
                layout = layouts[k]
                
                # WARNING -- these are subject to layout permutation (names referring to some reference unpermuted layout)                
                left = self.screen_offsets[layout[0]]
                center = self.screen_offsets[layout[1]]
                right = self.screen_offsets[layout[2]]
                
                # instantiate the center drive task
                frameofs = center/3.35
                frame = [self.drive_frame[0] + frameofs,self.drive_frame[1] + frameofs,self.drive_frame[2],self.drive_frame[3]]
                self.drive = self.launch(CheckpointDriving(frame=frame,text_pos=[center,-0.55],**self.drive_params))
                self.button_drive = DirectButton(command=messenger.send,extraArgs=['drive-report'],rolloverSound=None,clickSound=None,
                                                pos=(self.button_drive_pos[0]+center,0,self.button_drive_pos[1]),**self.button_drive_par)

                # instantiate the satmap task
                frameofs = center/3.35
                frame = [self.satmap_frame[0] + frameofs,self.satmap_frame[1] + frameofs,self.satmap_frame[2],self.satmap_frame[3]]
                self.satmap = self.launch(VisualSearchTask(self.rewardlogic,
                                                           frame=frame,
                                                           button_params=self.button_satmap_par,**self.satmap_params))
                self.button_satmap2 = DirectButton(pos=(self.button_satmap2_pos[0]+center,0,self.button_satmap2_pos[1]),**self.button_satmap2_par)
                
                # instantiate visual monitoring task
                self.vismonwatcher = EventWatcher(eventtype='sysmonv-check',
                                                  handleduration=self.sysmonv_timeout,
                                                  defaulthandler=self.sysmonv_false_detection)
                self.yellowlight = self.launch(CueLight(self.rewardlogic,screen_offset=right,**self.yellowlight_params))
                self.redlight = self.launch(WarningLight(self.rewardlogic,cueobj=self.yellowlight,screen_offset=right,watcher=self.vismonwatcher,**self.redlight_params))
                self.greenlight = self.launch(WarningLight(self.rewardlogic,cueobj=self.yellowlight,screen_offset=right,watcher=self.vismonwatcher,**self.greenlight_params))
                self.bluelight = self.launch(WarningLight(self.rewardlogic,screen_offset=right,watcher=self.vismonwatcher,**self.bluelight_params))
                self.button_sysmonv = DirectButton(command=messenger.send,extraArgs=['sysmonv-check'],rolloverSound=None,clickSound=None,
                                                   pos=(self.button_sysmonv_pos[0]+right,0,self.button_sysmonv_pos[1]),**self.button_sysmonv_par)
                
                # instantiate the auditory monitoring task
                self.audmonwatcher = EventWatcher(eventtype='sysmona-check',
                                                  handleduration=self.sysmona_timeout,
                                                  defaulthandler=self.sysmona_false_detection)
                self.cuesound = self.launch(CueSound(self.rewardlogic,screen_offset=right,**self.cuesound_params))
                self.warnsound = self.launch(WarningSound(self.rewardlogic,cueobj=self.cuesound,screen_offset=right,watcher=self.audmonwatcher,**self.warnsound_params))
                self.ticksound = self.launch(WarningSound(self.rewardlogic,cueobj=self.cuesound,screen_offset=right,watcher=self.audmonwatcher,**self.ticksound_params))
                self.button_sysmona = DirectButton(command=messenger.send,extraArgs=['sysmona-check'],rolloverSound=None,clickSound=None,
                                                   pos=(self.button_sysmona_pos[0]+right,0,self.button_sysmona_pos[1]),**self.button_sysmona_par)
                self.icon_sysmona = self.picture('sysmon-speaker.png',100000,block=False,pos=[self.button_sysmona_pos[0]+right,self.button_sysmona_pos[1]-0.15],scale=0.1)

                # --- comm setup ---
                # determine callsign
                targetsignidx = random.choice(xrange(len(self.callsigns)))
                self.marker(600+targetsignidx)
                targetsign = self.callsigns[targetsignidx]
                # and display it
                self.csign = self.write('Callsign: '+targetsign,10000,block=False,pos=[self.scroll_pos[0]+self.screen_offsets[layout[0]],self.scroll_pos[1]+0.06],scale=0.04,align='left',fg=[1,1,1,1])
                
                # instantiate the vis comm task
                self.commbox = ScrollPresenter(pos=[self.scroll_pos[0]+self.screen_offsets[layout[0]],self.scroll_pos[1]],**self.scroll_params)                
                self.commvis = self.launch(CommScheduler(self.commbox,self.rewardlogic,targetsign=targetsign,numcallsigns=self.numcallsigns,callsigns=self.callsign_file,**self.commvis_params))
                self.button_commv = DirectButton(command=messenger.send,extraArgs=['commv-roger'],rolloverSound=None,clickSound=None,
                                                 pos=(self.button_commv_pos[0]+left,0,self.button_commv_pos[1]),**self.button_commv_par)
                
                # instantiate the aud comm task
                self.commsnd = AudioPresenter(**self.voice_params)
                self.commaud = self.launch(CommScheduler(self.commsnd,self.rewardlogic,targetsign=targetsign,numcallsigns=self.numcallsigns,callsigns=self.callsign_file,**self.commaud_params))
                self.button_comma = DirectButton(command=messenger.send,extraArgs=['comma-roger'],rolloverSound=None,clickSound=None,
                                                 pos=(self.button_comma_pos[0]+right,0,self.button_comma_pos[1]),**self.button_comma_par)
                self.icon_comma = self.picture('comma-speaker.png',100000,block=False,pos=[self.button_comma_pos[0]+right,self.button_comma_pos[1]-0.15],scale=0.1)
                
                # instantiate the math task
                self.mathdisplay = TextPresenter(pos=[self.math_display_pos[0]+left,self.math_display_pos[1]],**self.math_display_par)
                self.math = self.launch(MathScheduler(self.rewardlogic,self.mathdisplay,
                                                      numpad_topleft=[self.numpad_topleft[0] + self.screen_offsets[layout[0]],self.numpad_topleft[1]],**self.math_params))                

                # wait until the layout has sunken in...
                self.sleep(self.initial_layout_time)                

                # for each focus condition
                prevfocus = ''
                for focus in focus_conditions[k]:
                    # reconfigure focused state for each object
                    self.drive.focused = focus.find('drive')>=0
                    self.satmap.focused = focus.find('satmap')>=0
                    self.redlight.focused = focus.find('sysmonv')>=0
                    self.greenlight.focused = focus.find('sysmonv')>=0
                    self.bluelight.focused = focus.find('sysmonv')>=0
                    self.yellowlight.focused = focus.find('sysmonv')>=0
                    self.warnsound.focused = focus.find('sysmona')>=0
                    self.ticksound.focused = focus.find('sysmona')>=0
                    self.cuesound.focused = focus.find('sysmona')>=0
                    self.commvis.focused = focus.find('commv')>=0
                    self.commaud.focused = focus.find('comma')>=0                    
                    self.math.focused = focus.find('math')>=0
                    
                    # present a switch stimulus
                    if prevfocus is None or prevfocus == '' or random.random() < self.bottom_up_probability:
                        # bottom-up stimulus
                        if focus.find('drive')>=0:
                            self.picture(block=False,pos=[center,-0.1],**self.bu_drive_img)
                        if focus.find('satmap')>=0:
                            self.picture(block=False,pos=[0,0],parent=self.satmap.renderviewport,**self.bu_satmap_img)
                        if focus.find('commv')>=0:
                            self.commbox.submit_wait("\1highlight\1ATTENTION ATTENTION ATTENTION\2", self)
                        if focus.find('math')>=0:
                            self.picture(block=False,pos=[left,0.6],**self.bu_math_img)
                        if focus.find('sysmonv')>=0:
                            self.picture(block=False,pos=[right,0.65],**self.bu_sysv_img)
                        if focus.find('sysmona')>=0:
                            self.sound('xHyprBlip.wav',volume=0.3)
                            self.picture(block=False,pos=[self.button_sysmona_pos[0]+right,self.button_sysmona_pos[1]-0.15],**self.bu_sysmona_img)
                        if focus.find('comma')>=0:
                            self.picture(block=False,pos=[self.button_comma_pos[0]+right,self.button_comma_pos[1]-0.15],**self.bu_comma_img)
                            self.commsnd.submit_wait("ATTENTION COMMUNICATIONS\2", self)
                    else:
                        # top-down stimulus; build a text instruction
                        instruction = "Please continue with"
                        spl = focus.split('-')
                        if len(spl) == 1:
                            articles = [' the ']
                        elif len(spl) == 2:
                            articles = [' the ',' and the ']
                        elif len(spl) == 3:
                            articles = [' the ',', the ', ' and the ']
                        for k in xrange(len(spl)):
                            instruction += articles[k] + self.tasknames[spl[k]]
                        instruction += '.'
                        # ... and insert it on the respective displays
                        if prevfocus.find('math')>=0:
                            self.write(instruction,5,block=False,pos=[left,0.9],scale=0.04,wordwrap=25) 
                        if prevfocus.find('commv')>=0:
                            self.commbox.submit_wait(instruction,self,3,3)
                        if prevfocus.find('comma')>=0:
                            self.commsnd.submit_wait(instruction,self,6,6)
                        if prevfocus.find('sysmona')>=0:
                            self.commsnd.submit_wait(instruction,self,6,6)
                        if prevfocus.find('sysmonv')>=0:
                            self.write(instruction,5,block=False,pos=[right,0.95],scale=0.04,wordwrap=25)
                        if prevfocus.find('drive')>=0:
                            self.write(instruction,5,block=False,pos=[center,-0.25],scale=0.04,wordwrap=25)
                        if prevfocus.find('satmap')>=0:
                            self.write(instruction,5,block=False,pos=[center,0.35],scale=0.04,wordwrap=25)                        

                    # wait for the duration of the focus block
                    duration = self.focus_duration()
                    self.sleep(duration)
                    prevfocus = focus
                
                # cancel subtasks
                self.redlight.cancel()
                self.greenlight.cancel()
                self.bluelight.cancel()
                self.yellowlight.cancel()
                self.warnsound.cancel()
                self.ticksound.cancel()
                self.cuesound.cancel()
                self.commvis.cancel()
                self.commaud.cancel()
                self.math.cancel()
                self.satmap.cancel()
                self.drive.cancel()
                self.sleep(0.1)
                # and clear display objects
                self.clear_objects()
        finally:
            try:
                self.clear_objects()
            except:
                pass
            
    def onspeech(self,phrase,listener):
        if phrase.lower() == 'roger':
            self.send_message('comma-roger')
            self.icon_comma.setScale(self.voice_icon_enlarge_size)
            self.icon_comma_reset_scale_at = time.time() + self.voice_icon_enlarge_duration
            taskMgr.doMethodLater(self.voice_icon_enlarge_duration, self.reset_comma, 'reset_comma()')
            
        if phrase.lower() == 'check':
            self.send_message('sysmona-check')
            self.icon_sysmona.setScale(self.voice_icon_enlarge_size)
            self.icon_sysmona_reset_scale_at = time.time() + self.voice_icon_enlarge_duration
            taskMgr.doMethodLater(self.voice_icon_enlarge_duration, self.reset_sysmona, 'reset_sysmona()')

        if phrase.lower() == 'yes':
            self.send_message('y')
        
        if phrase.lower() == 'no':
            self.send_message('n')
            
    def reset_comma(self,task):
        if time.time() >= self.icon_comma_reset_scale_at-0.1:                                
            self.icon_comma.setScale(0.1)
        return task.done 

    def reset_sysmona(self,task):
        if time.time() >= self.icon_sysmona_reset_scale_at-0.1:                                
            self.icon_sysmona.setScale(0.1)
        return task.done 

    def clear_objects(self):
        # remove event watchers
        self.vismonwatcher.destroy()
        self.audmonwatcher.destroy()
        # remove buttons
        self.icon_sysmona.destroy()
        self.icon_comma.destroy()
        self.button_comma.destroy()
        self.button_commv.destroy()
        self.button_sysmona.destroy()
        self.button_sysmonv.destroy()
        self.button_satmap2.destroy()
        self.button_drive.destroy()
        # remove presenters
        self.mathdisplay.destroy()
        self.commbox.destroy()
        self.commsnd.destroy()
        self.csign.destroy()

    def sysmonv_false_detection(self):
        self.marker(701)
        self.rewardlogic.score_event(self.false_response_penalty)

    def sysmona_false_detection(self):
        self.marker(702)
        self.rewardlogic.score_event(self.false_response_penalty)
 
