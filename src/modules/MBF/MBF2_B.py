from framework.deprecated.controllers import AdvCommScheduler, CheckpointDriving, MathScheduler, AudioRewardLogic, VisualSearchTask
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


# =======================
# === Subtask classes ===
# =======================


class WarningLightTask(LatentModule):
    """
    A Warning light class (red/blue/green) that sporadically turns on/off and demands a
    response that can be configured (press a button when turning on / turning off / stopping to blink). 
    Has some support for a cue status object/task which is currently unused here (was for MBF2A).
    """
    def __init__(self,
                 # general properties
                 rewardlogic,                                   # reward handling logic
                 watcher = None,                                # optional event watcher
                 focused = True,                                # whether this task is currently focused
                 markerbase = 1,                                # markers markerbase..markerbase+6 are used                       
                 event_interval=lambda: random.uniform(45,85),  # interval between two successive events

                 # cueing control
                 cueobj = None,                                 # an object that might have .iscued set to true

                 # graphics parameters
                 pic_off='light_off.png',                       # picture to display for the disabled light
                 pic_on='light_on.png',                         # picture to display for the enabled light
                 screen_offset=0,                               # offset to position this icon on one of the three screens
                 pic_params={'pos':[0,0],'scale':0.15},         # parameters for the picture() command
                 snd_params={'volume':0.3,'direction':0.0},     # parameters for the sound() command
                 
                 # response handling
                 snd_hit='click2s.wav',                         # sound when the user correctly detected the warning state
                 snd_wrongcue='xBuzz01.wav',                    # the sound that is overlaid with the buzzer when the response was wrong due to incorrect cueing
                 response_key='sysmonv-check',                  # key to press in case of an event
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



class WarningSoundTask(LatentModule):
    """
    A warning sound class that turns on sporadically. Demands that the subject responds in some way
    when the sound goes on / off or stops "ticking" (if a tick sound).
    Has some support for a cue status object/task which is currently unused here (was for MBF2A).
    """
    def __init__(self,
                 # general properties
                 rewardlogic,                                   # reward handling logic
                 watcher = None,                                # response event watcher
                 focused = True,                                # whether this task is currently focused
                 markerbase = 1,                                # markers markerbase..markerbase+6 are used                       
                 event_interval=lambda: random.uniform(45,85),  # interval between two successive events

                 # cueing control
                 cueobj = None,                                 # an object that might have .iscued set to true

                 # audio parameters
                 screen_offset=0,                               # offset to position this source on one of the three screens
                 snd_on='xHyprBlip.wav',                        # sound to play in case of an event
                 snd_params={'volume':0.25,'direction':0.0},    # parameters for the sound() command
                 
                 # response handling
                 snd_hit='click2s.wav',                         # sound when the user correctly detected the warning state
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



# ============================
# === Main task definition ===
# ============================


class Main(LatentModule):    
    
    def __init__(self):
        LatentModule.__init__(self)


        # ===============================
        # === block design parameters ===
        # ===============================        
        self.randseed = 11463       # some initial randseed for the experiment; note that this should be different for each subject (None = random)
        self.uiblocks = 24          # number of blocks with different UI permutation: should be a multiple of 6
        self.focus_per_layout = 8   # number of focus conditions within a UI layout block
        self.rest_every = 3         # insert a rest period every k UI blocks
        self.focus_duration = lambda: random.uniform(30,50) # duration of a focus block (was: 30-50)
        self.initial_rest_time = 5 # initial rest time at the beginning of a new UI layout block

        self.tasknames = {'sysmonv':'visual system monitoring','sysmona':'auditory system monitoring','comma':'auditory communciations','commv':'text communications','math':'mathematics','satmap':'satellite map','drive':'driving task'}
                
        self.conditions = ['sysmonv-sysmona','math-satmap','math-drive','sysmona-drive','sysmona-satmap','sysmonv','sysmona','satmap','drive','math']
        self.bottom_up_probability = 0.5 # probability that the switch stimulus is bottom-up

        # (this is the full set of conditions that we're not using any more)        
        # self.conditions = ['sysmonv-sysmona','commv-comma','math-satmap','math-drive','comma-satmap','comma-drive','comma-sysmona','sysmona-drive','sysmona-satmap','sysmonv','sysmona','commv','comma','satmap','drive','math']
        
        # ==============================
        # === score logic parameters ===
        # ==============================
        self.score_params = {'initial_score':0,                 # the initial score
                             'sound_params':{'direction':-0.7}, # properties of the score response sound
                             'gain_file':'ding.wav',            # sound file per point
                             'loss_file':'xBuzz01-rev.wav',     # sound file for losses
                             'none_file':'click.wav',           # file to play if no reward
                             'buzz_volume':0.4,                 # volume of the buzz (multiplied by the amount of loss)
                             'gain_volume':0.5,                 # volume of the gain sound                             
                             'ding_interval':0.1,               # interval at which successive gain sounds are played... (if score is > 1)
                             'scorefile':'C:\\Studies\\DAS\scoretable.txt'} # this is where the scores are logged        
        self.false_response_penalty = -1    # penalty due to false response in visual/auditory system monitoring

        # ===========================================
        # === visual system monitoring parameters === 
        # ===========================================
        self.sysmonv_rect = [-0.4,0.4,0.55,0.9]
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
                                'pic_params':{'pos':[self.light_x-2*self.light_offset,0.8],'scale':self.light_scale}, # parameters for the picture() command
                                'response_key':'sysmonv-check',                  # key to press in case of an event
                                'timeout':2.5,                                   # response timeout for the user
                                'hit_reward':4,                                  # reward if hit
                                'miss_penalty':-2,                               # penalty if missed
                                'false_penalty':-1,                              # penalty for false positives
                                }
        self.greenlight_params = {'markerbase':20,                               # markers markerbase..markerbase+6 are used                       
                                  'event_interval':lambda: random.uniform(21,41),# interval between two successive events
                                  'focused':False,
                                  'pic_off':'buzzer.png',                        # picture to display for the disabled light
                                  'pic_on':'buzzer-grey.png',                    # picture to display for the enabled light
                                  'snd_hit':'xClick01.wav',                      # sound when the user correctly detected the warning state
                                  'pic_params':{'pos':[self.light_x-1*self.light_offset,0.8],'scale':self.light_scale}, # parameters for the picture() command
                                  'response_key':'sysmonv-check',                # key to press in case of an event
                                  'timeout':2.5,                                 # response timeout for the user
                                  'hit_reward':4,                                # reward if hit
                                  'miss_penalty':-2,                             # penalty if missed
                                  'false_penalty':-1,                            # penalty for false positives
                                  }
        self.bluelight_params =   {'markerbase':40,                              # markers markerbase..markerbase+6 are used                       
                                   'event_interval':lambda: random.uniform(19,44),# interval between two successive events
                                   'focused':False,
                                   'pic_off':'buzzer-grey.png',                  # picture to display for the disabled light
                                   'pic_on':'buzzer-grey.png',                   # picture to display for the enabled light
                                   'snd_hit':'xClick01.wav',                     # sound when the user correctly detected the warning state
                                   'pic_params':{'pos':[self.light_x+0*self.light_offset,0.8],'scale':self.light_scale}, # parameters for the picture() command
                                   'response_key':'sysmonv-check',                            # key to press in case of an event
                                   'timeout':2.75,                               # response timeout for the user
                                   'hit_reward':4,                               # reward if hit
                                   'miss_penalty':-2,                            # penalty if missed
                                   'false_penalty':-1,                           # penalty for false positives
                                   'pic_tick_off':'buzzer-blue.png',             # picture to display for the disabled light
                                   'tick_rate':[1.2,0.1],
                                   }
        self.yellowlight_params = {'markerbase':60,                              # markers markerbase..markerbase+6 are used                       
                                   'event_interval':lambda: random.uniform(40,70),# interval between two successive events
                                   'focused':False,
                                   'pic_off':'buzzer-grey.png',                  # picture to display for the disabled light
                                   'pic_on':'buzzer-yellow.png',                 # picture to display for the enabled light
                                   'snd_hit':'xClick01.wav',                     # sound when the user correctly detected the warning state
                                   'pic_params':{'pos':[self.light_x+1*self.light_offset,0.8],'scale':self.light_scale}, # parameters for the picture() command
                                   'response_key':'sysmonv-check',               # key to press in case of an event
                                   'timeout':2.5,                                # response timeout for the user
                                   'hit_reward':4,                               # reward if hit
                                   'miss_penalty':-2,                            # penalty if missed
                                   'false_penalty':-1                            # penalty for false positives
                                   }
                
        self.button_sysmonv_par = {'frameSize':(-4.5,4.5,-0.45,0.95),'text':"Check",'scale':.075,'text_font':loader.loadFont('arial.ttf')}
        self.button_sysmonv_pos = [0,0.63]
        
        # =============================================
        # === auditory system monitoring parameters ===
        # =============================================
        self.sysmona_timeout = 3
        self.sysmona_rect = [0.1,0.4,-0.34,-0.64]
        self.warnsound_params = {'markerbase':80,                                 # markers markerbase..markerbase+6 are used                       
                                 'event_interval':lambda: random.uniform(15,35),  # interval between two successive events
                                 'focused':False,
                                 'snd_on':'buzzz.wav',                            # picture to display for the enabled light
                                 'response_key':'sysmona-check',                  # key to press in case of an event
                                 'timeout':5.5,                                   # response timeout for the user
                                 'hit_reward':4,                                  # reward if hit
                                 'miss_penalty':-2,                               # penalty if missed
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
                                 'hit_reward':6,                                  # reward if hit
                                 'miss_penalty':-2,                               # penalty if missed
                                 'false_penalty':-1,                              # penalty for false positives
                                 'tick_rate':[0.7,0.1],                           # rate of the ticking...
                                 }
        self.button_sysmona_par = {'frameSize':(-2,2,-0.5,1),'text':'"Check"','scale':.075,'text_font':loader.loadFont('arial.ttf')}
        self.button_sysmona_pos = [0.25,-0.34]

        # ==============================
        # === auditory comm elements ===
        # ==============================
        self.voice_params = {'direction':0,'volume':1}
        self.commaud_params = {'markerbase':400,                                # base marker offset
                               'message_interval': lambda: random.uniform(7,8), # interval between message presentations
                               'response_timeout':6,                            # response timeout...
                               'lull_time': lambda: random.uniform(30,90),      # duration of lulls, in seconds (drawn per lull)
                               'situation_time': lambda: random.uniform(25,45), # duration of developing situations, in seconds (drawn per situation)
                               'clearafter': 5,                                 # clear the presenter after this many messages                                 
                               'message_interval': lambda: random.uniform(5,8), # message interval, in s (drawn per message)
                               'other_callsign_fraction': lambda: random.uniform(0.3,0.5),      # fraction of messages that are for other callsigns (out of all messages presented) (drawn per situation)
                               'no_callsign_fraction': lambda: random.uniform(0.25,0.35),        # fraction, out of the messages for "other callsigns", of messages that have no callsign (drawn per situation)
                               'time_fraction_until_questions': lambda: random.uniform(0.1,0.2), # the fraction of time into the situation until the first question comes up (drawn per situation)
                                                                                                 # in the tutorial mode, this should probably be close to zero
                               'questioned_fraction': lambda: random.uniform(0.6,0.8),           # fraction of targeted messages that incur questions
                               }
        
        self.button_comma_par = {'frameSize':(-2,2,-0.5,1),'text':'"Roger"','scale':.075,'text_font':loader.loadFont('arial.ttf')}
        self.button_comma_pos = [-0.25,-0.34]

        # ============================
        # === visual comm elements ===
        # ============================
        self.scroll_pos = [-0.475,-0.4,-0.18]
        self.scroll_params = {'width':28,'scale':0.035,'numlines':4,'height':4}
        self.commvis_params = {'markerbase':300,                                # base marker offset
                               'clearafter': 5,                                 # clear the presenter after this many messages                                 
                               'message_interval': lambda: random.uniform(5,8), # message interval, in s (drawn per message)
                               'response_timeout':5,                            # response timeout...
                               'lull_time': lambda: random.uniform(30,90),      # duration of lulls, in seconds (drawn per lull)
                               'situation_time': lambda: random.uniform(25,45), # duration of developing situations, in seconds (drawn per situation)
                               'message_interval': lambda: random.uniform(4,6), # message interval, in s (drawn per message)
                               'other_callsign_fraction': lambda: random.uniform(0.3,0.5),      # fraction of messages that are for other callsigns (out of all messages presented) (drawn per situation)
                               'no_callsign_fraction': lambda: random.uniform(0.25,0.35),        # fraction, out of the messages for "other callsigns", of messages that have no callsign (drawn per situation)
                               'time_fraction_until_questions': lambda: random.uniform(0.1,0.2), # the fraction of time into the situation until the first question comes up (drawn per situation)
                                                                                                 # in the tutorial mode, this should probably be close to zero
                               'questioned_fraction': lambda: random.uniform(0.6,0.8),           # fraction of targeted messages that incur questions
                               }
        self.button_commv_par_y = {'frameSize':(-1.2,1.2,-0.35,0.85),'text':"Yes",'scale':.075,'text_font':loader.loadFont('arial.ttf')}
        self.button_commv_par_n = {'frameSize':(-1,1,-0.35,0.85),'text':"No",'scale':.075,'text_font':loader.loadFont('arial.ttf')}
        self.button_commv_par_s = {'frameSize':(-1.65,1.65,-0.35,0.85),'text':"Skip",'scale':.075,'text_font':loader.loadFont('arial.ttf')}
        self.button_commv_pos_y = [-0.05,-0.44,-0.22]
        self.button_commv_pos_n = [0.15,-0.44,-0.22]
        self.button_commv_pos_s = [0.375,-0.44,-0.22]

        # =======================
        # === math task setup ===
        # =======================        
        self.numpad_topleft = [-0.4,0.7]                            # top-left corner of the numpad
        self.math_rect = [-0.52,0.52,0.9,0.15]
        self.math_params = {'difficulty': 2,                        # difficulty level of the problems (determines the size of involved numbers)
                            'focused':True,
                            'problem_interval': lambda: random.uniform(3,12), # delay before a new problem appears after the previous one has been solved
                            'response_timeout': 10.0,               # time within which the subject may respond to a problem
                            'gain_correct':5,                     
                            'loss_incorrect':-2,
                            'numpad_gridspacing': [0.16,-0.16],     # spacing of the button grid
                            'numpad_buttonsize': [0.75,0.75],              # size of the buttons
                            'numpad_textscale': 0.15                 # scale of the text
                            }        
        self.math_display_par = {'scale':0.04, 'textcolor':[1,1,1,1],'framecolor':[0,0,0,1],'width':9,'height':10}
        self.math_display_pos = [0.12,0.67]
        
        # ================================
        # === satellite map task setup ===
        # ================================
        self.satmap_frame = [0.35,0.65,0.57,0.925]                           # the display region in which to draw everything
        self.satmap_rect = [-0.54,0.54,0.9,0.12]                              # the display region in which to draw everything
        self.satmap_params = {'background':'satellite_baseline.png',         # background image to use 
                              'frame_boundary':0.2,                          # (invisible) zone around the display region in which things can move around and spawn
                              'focused':False,

                              # parameters of the target/non-target item processes
                              'clutter_params':{'pixelated':True,
                                                'num_items':30},           # parameters for the clutter process
                              'target_params':{'pixelated':True,
                                               'num_items':1,
                                               'item_speed':lambda: random.uniform(0.1,0.25),
                                               'item_spiral':lambda: [random.uniform(0,3.14),random.uniform(0.0075,0.0095),random.uniform(0.06,0.07)],  # perform a spiraling motion with the given radius and angular velocity
                                               }, # parameters for the target process
                              'intro_text':'Find the spiraling object!',     # the text that should be displayed before the script starts                                                   
                                 
                              # situational control
                              'target_probability':0.5,                      # probability of a new situation being a target situation (vs. non-target situation) 
                              'target_duration':lambda: random.uniform(3,6), # duration of a target situation
                              'nontarget_duration':lambda: random.uniform(5,15),# duration of a non-target situation
                                 
                              # end conditions
                              'end_trials':1000000,                          # number of situations to produce (note: this is not the number of targets)
                              'end_timeout':1000000,                         # lifetime of this stream, in seconds (the stream ends if the trials are exhausted)
                                 
                              # response control
                              'response_event':'satmap-target',              # the event that is generated when the user presses the response button
                              'loss_misstarget':0,                           # the loss incurred by missing a target                 
                              'loss_nontarget':-1,                           # the loss incurred by a false detection
                              'gain_target':4,                               # the gain incurred by correctly spotting a target 
                              }                
        # this button is drawn into the satmap and can currently not be clicked 
        self.button_satmap_par = {'pos':(0.31,0,0.4),'frameSize':(-2.4,2.4,-0.6,1.1),'sortOrder':10,'text':"Target",'scale':.075,'text_font':loader.loadFont('arial.ttf'),'command':messenger.send,'extraArgs':['satmap-target'],'rolloverSound':None,'clickSound':None}
        self.button_satmap_pos = [0,0]
        # this button is in 3-screen space and can be clicked; it is behind the other button
        self.button_satmap2_par = {'frameSize':(-2.5,2.5,-0.4,0.9),'text':"",'scale':.075,'text_font':loader.loadFont('arial.ttf'),'command':messenger.send,'extraArgs':['satmap-target'],'rolloverSound':None,'clickSound':None}
        self.button_satmap2_pos = [0.31,0.77]

        # ===============================
        # === city driving task setup ===
        # ===============================
        self.drive_frame = [0.35,0.65,0.2,0.55]
        self.drive_rect = [-0.54,0.54,0.12,-0.65]
        self.drive_params = {'focused':False,
                             'show_checkpoints':False,

                             # media                  
                             'envmodel':'big\\citty.egg',   # the environment model to use
                             'trucksound':"Diesel_Truck_idle2.wav",# loopable truck sound....
                             'trucksound_volume':0.25,      # volume of the sound
                             'trucksound_direction':0,      # direction relative to listener
                               
                             'target_model':"moneybag-rev.egg", # model of the target object
                             'target_scale':0.01,               # scale of the target model
                             'target_offset':0.2,               # y offset for the target object 

                             # checkpoint logic 
                             'points':[[-248.91,-380.77,4.812],[0,0,0]], # the sequence of nav targets...
                             'radius':10,                   # proximity to checkpoint at which it is considered reached... (meters)
                             # end conditions
                             'end_timeout':100000,          # end the task after this time
                             # movement parameters
                             'acceleration':0.5,            # acceleration during manual driving
                             'friction':0.95,               # friction coefficient
                             'torque':1,                    # actually angular velocity during turning
                             'height':0.7}        
        self.button_drive_par = {'frameSize':(-2.5,2.5,-0.4,0.9),'text':"Report",'scale':.075,'text_font':loader.loadFont('arial.ttf')}
        self.button_drive_pos = [0.31,0.025]


        # ============================
        # === main task parameters ===
        # ============================
        
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
        
        # bci control
        self.notification_cutoff = 0.2                              # if the probability that a message was noticed is smaller than this, fire off a message
        self.notice_probability = 0.5                               # this is the bci variable
        self.notice_probability_cumulant = 0.5                      # this is a smoothed version of the bci variabe
        self.notice_probability_history_mixin = 0.6                 # this is an update factor that mixes in previous notice-probability estimates (from earlier messages) to get a smoothed update for the current one
        self.notification_snd = 'xBleep.wav'

        # inter-block pauses
        self.pause_duration = lambda: random.uniform(40,60)
        
        # ambience sound setup
        self.ambience_sound = 'media\\ambience\\nyc_amb2.wav'
        self.ambience_volume = 0.1

        self.frames = []
        
    def run(self):
        try:
            # init the randseed
            if self.randseed is not None:
                print "WARNING: Randomization of the experiment is currently bypassed."
                random.seed(self.randseed)
                self.marker(30000+self.randseed)
                
            # =================================
            # === Block schedule generation ===
            # =================================
            
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
            
    
            # ================
            # === Tutorial ===
            # ================
            
            if not self.developer:
                self.write('Welcome to the MBF2 experiment B.')
                self.write('Press the space bar when you are ready.','space')


                    
            # ===============================
            # === One-time initialization ===
            # ===============================
            
            # set up the reward logic
            self.rewardlogic = AudioRewardLogic(**self.score_params)

            # load callsign table            
            self.callsigns = []
            with open('media\\'+self.callsign_file,'r') as f:
                for line in f:
                    self.callsigns.append(line.strip())
            self.callsigns = self.callsigns[:self.numcallsigns]

            # start some ambience sound loop
            self.ambience = self.sound(self.ambience_sound,looping=True,volume=self.ambience_volume,direction=0)

            # init speech control            
            if self.allow_speech:
                try:
                    framework.speech.listenfor(['roger','check','yes','no','skip'],self.onspeech)
                except:
                    print "Could not initialiate speech control; falling back to touch screen only."
            
            # initialize question counters
            self.num_question_uv = [0]
            self.num_question_lv = [0]
            self.num_question_au = [0]
            
            # =======================
            # === block main loop ===
            # =======================
                        
            # for each UI layout block...        
            for k in range(len(layouts)):
                if (k+1) % self.rest_every == 0:
                    # insert pause
                    self.marker(1701)

                    self.write("You may now rest for a while...",3,scale=0.04,pos=[0,0.4])
                    self.show_score()

                    # main rest block: just sleep and let the center task do the rest
                    duration = self.pause_duration()
                    if self.waitfor('f9', duration):
                        self.rewardlogic.paused = True
                        self.marker(900)
                        self.write("Pausing now. Please press f9 again to continue.",10,scale=0.04,pos=[0,0.4],block=False)
                        self.waitfor('f9', 10000)
                        self.rewardlogic.paused = False

                    self.marker(19)
                    self.sound('nice_bell.wav')
                    self.write("The rest block has now ended.",2,scale=0.04,pos=[0,0.4])

                
                # =======================================
                # === New layout block initialization ===
                # =======================================
                
                if not self.developer:
                    for i in [3,2,1]:
                        self.write('New block begins in '+str(i))
                self.marker(400+k)
                layout = layouts[k]
                
                # WARNING -- these are abstract & subject to layout permutation (names referring to some reference unpermuted layout)                
                left = self.screen_offsets[layout[0]]
                center = self.screen_offsets[layout[1]]
                right = self.screen_offsets[layout[2]]
                
                # instantiate the center drive task
                frameofs = center/3.35
                drive_frame = [self.drive_frame[0] + frameofs,self.drive_frame[1] + frameofs,self.drive_frame[2],self.drive_frame[3]]
                drive_rect = [self.drive_rect[0] + center,self.drive_rect[1] + center,self.drive_rect[2],self.drive_rect[3]]
                self.drive = self.launch(CheckpointDriving(frame=drive_frame,text_pos=[center,-0.55],**self.drive_params))
                self.button_drive = DirectButton(command=messenger.send,extraArgs=['drive-report'],rolloverSound=None,clickSound=None,
                                                pos=(self.button_drive_pos[0]+center,0,self.button_drive_pos[1]),**self.button_drive_par)

                # instantiate the satmap task
                frameofs = center/3.35
                satmap_frame = [self.satmap_frame[0] + frameofs,self.satmap_frame[1] + frameofs,self.satmap_frame[2],self.satmap_frame[3]]
                satmap_rect = [self.satmap_rect[0] + center,self.satmap_rect[1] + center,self.satmap_rect[2],self.satmap_rect[3]]
                self.satmap = self.launch(VisualSearchTask(self.rewardlogic,
                                                           frame=satmap_frame,
                                                           button_params=self.button_satmap_par,**self.satmap_params))
                self.button_satmap2 = DirectButton(pos=(self.button_satmap2_pos[0]+center,0,self.button_satmap2_pos[1]),**self.button_satmap2_par)
                
                # instantiate visual monitoring task
                sysmonv_rect = [self.sysmonv_rect[0] + right,self.sysmonv_rect[1] + right,self.sysmonv_rect[2],self.sysmonv_rect[3]]
                self.vismonwatcher = EventWatcher(eventtype='sysmonv-check',
                                                  handleduration=self.sysmonv_timeout,
                                                  defaulthandler=self.sysmonv_false_detection)
                self.redlight = self.launch(WarningLightTask(self.rewardlogic,screen_offset=right,watcher=self.vismonwatcher,**self.redlight_params))
                self.greenlight = self.launch(WarningLightTask(self.rewardlogic,screen_offset=right,watcher=self.vismonwatcher,**self.greenlight_params))
                self.bluelight = self.launch(WarningLightTask(self.rewardlogic,screen_offset=right,watcher=self.vismonwatcher,**self.bluelight_params))
                self.yellowlight = self.launch(WarningLightTask(self.rewardlogic,screen_offset=right,**self.yellowlight_params))
                self.button_sysmonv = DirectButton(command=messenger.send,extraArgs=['sysmonv-check'],rolloverSound=None,clickSound=None,
                                                   pos=(self.button_sysmonv_pos[0]+right,0,self.button_sysmonv_pos[1]),**self.button_sysmonv_par)
                
                # instantiate the auditory monitoring task
                sysmona_rect = [self.sysmona_rect[0] + right,self.sysmona_rect[1] + right,self.sysmona_rect[2],self.sysmona_rect[3]]
                self.audmonwatcher = EventWatcher(eventtype='sysmona-check',
                                                  handleduration=self.sysmona_timeout,
                                                  defaulthandler=self.sysmona_false_detection)
                self.warnsound = self.launch(WarningSoundTask(self.rewardlogic,screen_offset=right,watcher=self.audmonwatcher,**self.warnsound_params))
                self.ticksound = self.launch(WarningSoundTask(self.rewardlogic,screen_offset=right,watcher=self.audmonwatcher,**self.ticksound_params))
                self.icon_sysmona = self.picture('sysmon-speaker.png',100000,block=False,pos=[self.button_sysmona_pos[0]+right,self.button_sysmona_pos[1]-0.15],scale=0.1)

                # determine callsign
                targetsignidx = random.choice(xrange(len(self.callsigns)))
                self.marker(600+targetsignidx)
                targetsign = self.callsigns[targetsignidx]
                # and display it
                self.csign = self.write('Callsign: '+targetsign,10000,block=False,pos=[self.scroll_pos[0]+self.screen_offsets[layout[0]],self.scroll_pos[2]+0.06],scale=0.04,align='left',fg=[1,1,1,1])
                
                # instantiate the vis comm task
                self.commbox1 = ScrollPresenter(pos=[self.scroll_pos[0]+self.screen_offsets[layout[0]],self.scroll_pos[1]],**self.scroll_params)                
                self.commvis1 = self.launch(AdvCommScheduler(self.commbox1,self.rewardlogic,targetsign=targetsign,numcallsigns=self.numcallsigns,callsigns=self.callsign_file,commands='sentences_with_answers1.txt',events=['v1_y','v1_n','v1_s'],callback_func=lambda: self.check_bci("lower visual"),num_question=self.num_question_lv,**self.commvis_params))
                self.button_commv1_y = DirectButton(command=messenger.send,extraArgs=['v1_y'],rolloverSound=None,clickSound=None,
                                                    pos=(self.button_commv_pos_y[0]+left,0,self.button_commv_pos_y[1]),**self.button_commv_par_y)
                self.button_commv1_n = DirectButton(command=messenger.send,extraArgs=['v1_n'],rolloverSound=None,clickSound=None,
                                                    pos=(self.button_commv_pos_n[0]+left,0,self.button_commv_pos_n[1]),**self.button_commv_par_n)
                self.button_commv1_s = DirectButton(command=messenger.send,extraArgs=['v1_s'],rolloverSound=None,clickSound=None,
                                                    pos=(self.button_commv_pos_s[0]+left,0,self.button_commv_pos_s[1]),**self.button_commv_par_s)

                self.commbox2 = ScrollPresenter(pos=[self.scroll_pos[0]+self.screen_offsets[layout[0]],self.scroll_pos[2]],**self.scroll_params)                
                self.commvis2 = self.launch(AdvCommScheduler(self.commbox2,self.rewardlogic,targetsign=targetsign,numcallsigns=self.numcallsigns,callsigns=self.callsign_file,commands='sentences_with_answers2.txt',events=['v2_y','v2_n','v2_s'],callback_func=lambda: self.check_bci("upper visual"),num_question=self.num_question_uv,**self.commvis_params))
                self.button_commv2_y = DirectButton(command=messenger.send,extraArgs=['v2_y'],rolloverSound=None,clickSound=None,
                                                    pos=(self.button_commv_pos_y[0]+left,0,self.button_commv_pos_y[2]),**self.button_commv_par_y)
                self.button_commv2_n = DirectButton(command=messenger.send,extraArgs=['v2_n'],rolloverSound=None,clickSound=None,
                                                    pos=(self.button_commv_pos_n[0]+left,0,self.button_commv_pos_n[2]),**self.button_commv_par_n)
                self.button_commv2_s = DirectButton(command=messenger.send,extraArgs=['v2_s'],rolloverSound=None,clickSound=None,
                                                    pos=(self.button_commv_pos_s[0]+left,0,self.button_commv_pos_s[2]),**self.button_commv_par_s)
                
                # instantiate the aud comm task
                self.commsnd = AudioPresenter(**self.voice_params)
                self.commaud = self.launch(AdvCommScheduler(self.commsnd,self.rewardlogic,targetsign=targetsign,numcallsigns=self.numcallsigns,callsigns=self.callsign_file,commands='sentences_with_answers3.txt',callback_func=lambda: self.check_bci("audio"),num_question=self.num_question_au,**self.commaud_params))
                self.icon_comma = self.picture('comma-speaker.png',100000,block=False,pos=[self.button_comma_pos[0]+right,self.button_comma_pos[1]-0.15],scale=0.1)
                
                # instantiate the math task
                math_rect = [self.math_rect[0] + left,self.math_rect[1] + left,self.math_rect[2],self.math_rect[3]]
                self.mathdisplay = TextPresenter(pos=[self.math_display_pos[0]+left,self.math_display_pos[1]],**self.math_display_par)
                self.math = self.launch(MathScheduler(self.rewardlogic,self.mathdisplay,
                                                      numpad_topleft=[self.numpad_topleft[0] + self.screen_offsets[layout[0]],self.numpad_topleft[1]],**self.math_params))                

                # wait until the layout has sunken in...
                self.sleep(self.initial_layout_time)                


                # for each focus condition
                prevfocus = ''
                for focus in focus_conditions[k]:
                    
                    # =======================
                    # === New focus block ===
                    # =======================
                    
                    # reconfigure focused state for each object
                    self.drive.focused = focus.find('drive')>=0
                    self.satmap.focused = focus.find('satmap')>=0
                    self.redlight.focused = focus.find('sysmonv')>=0
                    self.greenlight.focused = focus.find('sysmonv')>=0
                    self.bluelight.focused = focus.find('sysmonv')>=0
                    self.yellowlight.focused = focus.find('sysmonv')>=0
                    self.warnsound.focused = focus.find('sysmona')>=0
                    self.ticksound.focused = focus.find('sysmona')>=0
                    self.math.focused = focus.find('math')>=0
                    
                    # present a switch stimulus
                    if prevfocus is None or prevfocus == '' or random.random() < self.bottom_up_probability:
                        # bottom-up stimulus
                        if focus.find('drive')>=0:
                            self.picture(block=False,pos=[center,-0.1],**self.bu_drive_img)
                        if focus.find('satmap')>=0:
                            self.picture(block=False,pos=[0,0],parent=self.satmap.renderviewport,**self.bu_satmap_img)
                        if focus.find('commv')>=0:
                            self.commbox1.submit_wait("\1highlight\1ATTENTION ATTENTION ATTENTION\2", self)
                            self.commbox2.submit_wait("\1highlight\1ATTENTION ATTENTION ATTENTION\2", self)
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
                            self.commbox1.submit_wait(instruction,self,3,3)
                            self.commbox2.submit_wait(instruction,self,3,3)
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


                    # ================================================
                    # === wait for the duration of the focus block ===
                    # ================================================
                    
                    duration = self.focus_duration()
                    # smoothly fade frames in around the hot spots
                    # not the finest way to do it, but gets the job done for now
                    self.sleep(3)                    
                    if True:
                        for k in [j/10.0 for j in range(1,11)]:
                            if focus.find('drive') >= 0:
                                self.frame(drive_rect,duration=duration-8,block=False,color=[1,1,1,k])
                            if focus.find('satmap') >= 0:                        
                                self.frame(satmap_rect,duration=duration-8,block=False,color=[1,1,1,k])
                            if focus.find('math') >= 0:
                                self.frame(math_rect,duration=duration-8,block=False,color=[1,1,1,k])
                            if focus.find('sysmonv') >= 0:
                                self.frame(sysmonv_rect,duration=duration-8,block=False,color=[1,1,1,k])
                            if focus.find('sysmona') >= 0:
                                self.frame(sysmona_rect,duration=duration-8,block=False,color=[1,1,1,k])
                            self.sleep(0.1)
                    self.sleep(duration-5-3)
                    prevfocus = focus
                
                
                # ======================================
                # === end of the screen layout block ===
                # ======================================
                
                self.redlight.cancel()
                self.greenlight.cancel()
                self.bluelight.cancel()
                self.yellowlight.cancel()
                self.warnsound.cancel()
                self.ticksound.cancel()
                self.commvis1.cancel()
                self.commvis2.cancel()
                self.commaud.cancel()
                self.math.cancel()
                self.satmap.cancel()
                self.drive.cancel()
                self.sleep(0.1)
                # and clear display objects
                self.clear_objects()
        finally:
            # ==========================
            # === main task shutdown ===
            # ==========================
            try:
                self.clear_objects()
            except:
                pass

            
    def sysmonv_false_detection(self):
        """ Event handler for false system-monitoring responses (if not focused). """
        self.marker(701)
        self.rewardlogic.score_event(self.false_response_penalty)

    def sysmona_false_detection(self):
        """ Event handler for false system-monitoring responses (if not focused). """
        self.marker(702)
        self.rewardlogic.score_event(self.false_response_penalty)
        
    def onspeech(self,phrase,listener):
        """Dispatch speech commands into regular messages."""
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
        if phrase.lower() == 'skip':
            self.send_message('s')
            
    def reset_comma(self,task):
        """Part of a graphical gimmick."""
        if time.time() >= self.icon_comma_reset_scale_at-0.1:                                
            self.icon_comma.setScale(0.1)
        return task.done 

    def reset_sysmona(self,task):
        """Part of a graphical gimmick."""
        if time.time() >= self.icon_sysmona_reset_scale_at-0.1:                                
            self.icon_sysmona.setScale(0.1)
        return task.done 

    def clear_objects(self):
        """ Destroy on-screen objects for shutdown / reset. """
        # remove event watchers
        self.vismonwatcher.destroy()
        self.audmonwatcher.destroy()
        # remove buttons
        self.icon_sysmona.destroy()
        self.icon_comma.destroy()
        self.button_commv1_y.destroy()
        self.button_commv1_n.destroy()
        self.button_commv1_s.destroy()
        self.button_commv2_y.destroy()
        self.button_commv2_n.destroy()
        self.button_commv2_s.destroy()
        self.button_sysmonv.destroy()
        self.button_satmap2.destroy()
        self.button_drive.destroy()
        # remove presenters
        self.mathdisplay.destroy()
        self.commbox1.destroy()
        self.commbox2.destroy()
        self.commsnd.destroy()
        self.csign.destroy()

    def check_bci(self,which):
        """ Query the BCI to determine whether the subject noticed the message. """
        self.notice_probability_cumulant = self.notice_probability_cumulant*self.notice_probability_history_mixin + self.notice_probability * (1-self.notice_probability_history_mixin)          
        if self.notice_probability_cumulant < self.notification_cutoff:
            self.write("Please don't forget to pay attention to your " +which+ " messages.", 1, False, [0,-0.75])
            self.sound(self.notification_snd, False, 0.5, 0)
            
    def show_score(self):
        """ Display the score to the subject & log it."""
        self.write("Your score is: " + str(self.rewardlogic.score*10),5,scale=0.1,pos=[0,0.8])
        self.rewardlogic.log_score()
                    
