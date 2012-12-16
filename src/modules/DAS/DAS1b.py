from framework.convenience import ConvenienceFunctions
from framework.deprecated.controllers import VideoScheduler, CheckpointDriving, MathScheduler, AudioRewardLogic, VisualSearchTask
from framework.latentmodule import LatentModule
from framework.ui_elements.ImagePresenter import ImagePresenter
from framework.ui_elements.TextPresenter import TextPresenter
from framework.ui_elements.AudioPresenter import AudioPresenter
from framework.ui_elements.RandomPresenter import RandomPresenter
from framework.ui_elements.EventWatcher import EventWatcher
from direct.gui.DirectGui import DirectButton
from panda3d.core import *
import random
import time
import pickle


# exp structure:
#  - the main run consists of numavbouts A/V bouts (60)
#  - every rest_every A/V bouts, a pause is inserted (3)
#    - the pause takes rest_duration seconds (45..75) 
#  - each A/V bout contains 6 focus periods (lv,rv,la,ra,lvla,rvra) in some admissible order and balanced in pairs of bouts
#    - each focus period contains focus_numstims stimuli (15..40), a fraction being targets (1/3)
#    - each stimulus is displayed for stim_duration seconds (0.9s)
#    - at the beginning of each focus block there is an extra pull stimulus (0.9s)

# assuming 90 minutes experiment
# Total duration of main block: ~93 minutes on average (with some randomness)
# Total # of stims: 5400
# Total # of targets: 1800
# Targets per modality: 450 (~dual/single)
# Total # of switches: 180
# Switches across modalities: ca. 100
# Switches A->V: ca. 50
# Switches V->A: ca. 50
#
class WarningTask(LatentModule):
    """
    A press-when-the-warning-goes-off task that runs in parallel to the rest of the experiment.
    """
    def __init__(self,
                 rewardlogic,
                 event_interval=lambda: random.uniform(45,85),  # interval between two successive events
                 snd_probability=0.5,                           # probability that an event is indicated by a sound (instead of a pic)
                 pic_off='light_off.png',                       # picture to display for the disabled light
                 pic_on='light_on.png',                         # picture to display for the enabled light
                 snd_on='alert.wav',                            # sound to play in case of an event
                 snd_hit='xClick01.wav',                        # sound when the user correctly detected the warning state
                 pic_params={'pos':[0,0],'scale':0.2},          # parameters for the picture() command
                 snd_params={'volume':0.15,'direction':0.0},     # parameters for the sound() command
                 response_key='space',                          # key to press in case of an event
                 timeout=1.5,                                   # response timeout for the user
                 hit_reward=0,                                  # reward if hit
                 miss_penalty=-10,                              # penalty if missed
                 false_penalty=-5,                              # penalty for false positives
                 ):
        
        LatentModule.__init__(self)
        self.rewardlogic = rewardlogic
        self.event_interval = event_interval
        self.snd_probability = snd_probability
        self.pic_off = pic_off
        self.pic_on = pic_on
        self.snd_on = snd_on
        self.snd_hit = snd_hit
        self.pic_params = pic_params
        self.snd_params = snd_params
        self.response_key = response_key
        self.timeout = timeout
        self.hit_reward = hit_reward
        self.miss_penalty = miss_penalty
        self.false_penalty = false_penalty

    def run(self):
        # pre-cache the media files...
        self.precache_picture(self.pic_on)
        self.precache_picture(self.pic_off)
        self.precache_sound(self.snd_on)
        
        # set up an event watcher (taking care of timeouts and inappropriate responses)
        watcher = EventWatcher(eventtype=self.response_key,
                               handleduration=self.timeout,
                               defaulthandler=lambda: self.rewardlogic.score_event(self.false_penalty))
        while True:
            # show the "off" picture for the inter-event interval
            self.picture(self.pic_off, self.event_interval(), **self.pic_params)
            
            # start watching for a response
            watcher.watch_for(self.correct, self.timeout, lambda: self.rewardlogic.score_event(self.miss_penalty))
            if random.random() < self.snd_probability:
                # play a sound and continue with the off picture 
                self.sound(self.snd_on, **self.snd_params)
                self.marker(3)
                self.picture(self.pic_off, self.timeout, **self.pic_params)
            else:
                # show the "on" picture
                self.marker(4)
                self.picture(self.pic_on, self.timeout, **self.pic_params)
            self.marker(5)

    def correct(self):
        # called when the user correctly spots the warning event
        self.sound(self.snd_hit,**self.snd_params)
        self.rewardlogic.score_event(self.hit_reward)


class HoldTask(LatentModule):
    """
    A task that requires pressing and holding one of two buttons for extended periods of time.
    """
    def __init__(self,
                 rewardlogic,
                 left_button='z',
                 right_button='3',
                 nohold_duration=lambda: random.uniform(45,85), # duration of a no-hold period
                 hold_duration=lambda: random.uniform(30,45),   # duration of a hold period
                 pic='hold.png',                                # picture to indicate that a button should be held
                 snd='hold.wav',                                # sound to indicate that a button should be held
                 left_pos=[-0.5,-0.92],                         # position if left
                 right_pos=[0.5,-0.92],                         # position if right
                 pic_params={'scale':0.2},                      # parameters for the picture() command
                 snd_params={'volume':0.1},                     # parameters for the sound() command                 
                 scoredrain_snd='xTick.wav',                    # sound to play when the score is trained...
                 left_dir=-1,                                   # direction of the left "hold" sound 
                 right_dir=+1,                                  # direction of the right "hold" sound
                 loss_amount=-0.25,                             # amount of score lost if not held
                 loss_interval=0.5,                             # interval at which score is subtracted
                 ):
        
        LatentModule.__init__(self)
        self.rewardlogic = rewardlogic
        self.left_button = left_button
        self.right_button = right_button
        self.nohold_duration = nohold_duration
        self.hold_duration = hold_duration
        self.pic = pic
        self.snd = snd
        self.left_pos = left_pos
        self.right_pos = right_pos
        self.pic_params = pic_params
        self.snd_params = snd_params
        self.scoredrain_snd = scoredrain_snd
        self.left_dir = left_dir
        self.right_dir = right_dir
        self.loss_amount = loss_amount
        self.loss_interval = loss_interval
        self.should_hold = False
        self.left_down = False
        self.right_down = False
    
    def run(self):
        # set up checks for the appropriate keys
        self.accept(self.left_button,self.update_key_status,['left-down'])
        self.accept(self.left_button + '-up',self.update_key_status,['left-up'])
        self.accept(self.right_button,self.update_key_status,['right-down'])
        self.accept(self.right_button + '-up',self.update_key_status,['right-up'])
        
        # start a timer that checks if the appropriate button is down       
        taskMgr.doMethodLater(self.loss_interval,self.score_drain,'Score drain')

        while True:
            # no-hold condition: wait for the nohold duration 
            self.should_hold = False
            self.sleep(self.nohold_duration())
            
            # select a side to hold at
            if random.choice(['left','right']) == 'left':
                self.button = 'left'
                pos = self.left_pos
                dir = self.left_dir
                self.marker(6)
            else:
                self.button = 'right'
                pos = self.right_pos
                dir = self.right_dir
                self.marker(7)

            # hold condition: display the hold picture & play the hold indicator sound...
            self.should_hold = True
            self.sound(self.snd,direction=dir,**self.snd_params)
            self.picture(self.pic,self.hold_duration(),pos=pos,**self.pic_params)   
            self.marker(8)
    
    def score_drain(self,task):
        """Called periodically to check whether the subject is holding the correct button."""
        if self.should_hold:
            # subject should hold down a particular button
            if self.button == 'left' and (self.right_down or not self.left_down):
                self.rewardlogic.score_event(self.loss_amount,nosound=True)
                self.marker(9)
                self.sound(self.scoredrain_snd)
            if self.button == 'right' and (self.left_down or not self.right_down):            
                self.rewardlogic.score_event(self.loss_amount,nosound=True)
                self.marker(10)
                self.sound(self.scoredrain_snd)
        elif self.left_down or self.right_down:
            # subject should hold neither the left nor the right button...
            self.rewardlogic.score_event(self.loss_amount,nosound=True)
            self.marker(11)
            self.sound(self.scoredrain_snd)
        return task.again
  
    def update_key_status(self,evt):
        """Called whenever the status of the left or right key changes."""
        if evt=='left-up':
            self.left_down = False
        elif evt=='left-down':
            self.left_down = True
        if evt=='right-up':
            self.right_down = False
        elif evt=='right-down':
            self.right_down = True
        

class Main(LatentModule):
    """
    DAS1b: Second version of the DAS experiment #1.
    """
    
    def __init__(self):
        LatentModule.__init__(self)
        
        # --- default parameters (may also be changed in the study config) ---
        
        # block design
        self.randseed = 11115       # some initial randseed for the experiment; note that this should be different for each subject (None = random)
        self.numavbouts = 30        # number of A/V bouts in the experiment (x3 is approx. duration in minutes)
        self.fraction_words = 0.5   # words versus icons balance
        self.rest_every = 3         # number of A/V bouts until a rest block is inserted 
        self.resttypes = ['rest-movers-vis','rest-movers-mov','rest-math','rest-videos','rest-drive']    # these are the different flavors of the rest condition
        self.resttypes_avcompat = ['rest-movers-vis','rest-movers-mov','rest-videos','rest-drive']       # a subset of rest center tasks that may run in parallel to the a/v bouts 
        # self.fraction_withinmodality_switches = [0.2,0.4] # fraction of within-modality switches (range) -- note: only a few distinct numbers are actually possible here: currently disabled 
        
        # keys (for the key labels see http://www.panda3d.org/manual/index.php/Keyboard_Support)
        self.lefttarget = 'lcontrol'       # left-side target button
        self.righttarget = 'rcontrol'      # right-side target button
        self.lefthold = 'lalt'             # left hold button
        self.righthold = 'ralt'            # right hold button (keypad enter)
        self.max_successive_keypresses = 5 # maximum number of successive kbd presses until penalty kicks in 
        self.max_successive_touches = 5    # maximum number of successive touch presses until penalty kicks in
        self.max_successive_sound = 'slap.wav'  # this is the right penalty sound!

        # score logic setup (parameters to SimpleRewardLogic)
        self.score_params = {'initial_score':0,                 # the initial score
                             'sound_params':{'direction':-0.7}, # properties of the score response sound
                             'gain_file':'ding.wav',            # sound file per point
                             'loss_file':'xBuzz01-rev.wav',     # sound file for losses
                             'none_file':'click.wav',           # file to play if no reward
                             'buzz_volume':0.4,                 # volume of the buzz (multiplied by the amount of loss)
                             'gain_volume':0.5,                 # volume of the gain sound                             
                             'ding_interval':0.1,               # interval at which successive gain sounds are played... (if score is > 1)
                             'scorefile':'C:\\Studies\\DAS\scoretable.txt'} # this is where the scores are logged              
        
        self.loss_nontarget_press = -1  # loss if pressed outside a particular target response window
        self.loss_target_miss = -1      # loss if a target was missed
        self.gain_target_fav = 1        # gain if a favored target was hit (ck: fav scoring disabled)
        self.gain_target_nofav = 1      # gain if a non-favored target was hit (in a dual-modality setup)
        self.gain_hiexpense_plus = 1    # additional gain if the high-expense button was used to hit a target
        self.gain_cued_plus = 1         # additional gain if the double-pressing was correctly performed in response to a cued target 

        # screen button layout (parameters to DirectButton)
        self.button_left = {'frameSize':(-3.5,3.5,-0.6,1.1),'pos':(-1.1,0,-0.85),'text':"Target",'scale':.075,'text_font':loader.loadFont('arial.ttf')}     # parameters of the left target button
        self.button_right = {'frameSize':(-3.5,3.5,-0.6,1.1),'pos':(1.1,0,-0.85),'text':"Target",'scale':.075,'text_font':loader.loadFont('arial.ttf')}     # parameters of the right target button
        self.button_center = {'frameSize':(-3,3,-0.5,1),'pos':(0,0,-0.92),'text':"Warn Off",'scale':.075,'text_font':loader.loadFont('arial.ttf')}     # parameters of the center "warning off" button

        # visual presenter location layout (parameters to ImagePresenter and TextPresenter, respectively)
        self.img_center_params = {'pos':[0,0,0.3],'clearafter':1.5,'scale':0.1}
        self.img_left_params = {'pos':[-0.8,0,0.3],'clearafter':0.3,'color':[1, 1, 1, 1],'scale':0.1,'rotation': (lambda: [0,0,random.random()*360])}
        self.img_right_params = {'pos':[0.8,0,0.3],'clearafter':0.3,'color':[1, 1, 1, 1],'scale':0.1,'rotation': (lambda: [0,0,random.random()*360])}
        self.txt_left_params = {'pos':[-0.8,0.3],'clearafter':0.4,'framecolor':[0, 0, 0, 0],'scale':0.1,'align':'center'}
        self.txt_right_params = {'pos':[0.8,0.3],'clearafter':0.4,'framecolor':[0, 0, 0, 0],'scale':0.1,'align':'center'}        
        
        # auditory presenter location layout (parameters to AudioPresenter)
        self.aud_center_params = {'direction':0.0,'volume':0.5}
        self.aud_left_params = {'direction':-2,'volume':0.5}
        self.aud_right_params = {'direction':2,'volume':0.5}

        # design of the focus blocks (which are scheduled in bouts of length 6):
        self.pull_probability = 1   # chance that a pull cue is presented in case of a left/right switch (ck: disabled the no-pull condition)
        self.pull_duration = 0.9    # duration for which the pull cue is presented (in s)
        self.push_duration = 0.9    # duration for which the push cue is presented (in s)
        self.pull_volume = 2        # pull stimuli have a different volume from others (more salient)
        self.push_volume = 1        # push stimuli may have a different volume
        self.focus_numstims = lambda: random.uniform(15,40) # number of stimuli in a single focus block (for now: 20-40, approx. 10 seconds @ 3Hz)
        
        self.target_probability = 1.0/3 # probability that a given stimulus is a target (rather than a non-target)
        self.cue_probability = 0.0      # probability that a given target stimulus is turned into a cue (if there is no outstanding cue at this time)  
        self.cue_duration = 0.75         # duration of a cue stimulus
        self.stim_duration = 0.75        # duration (inter-stimulus interval) for a target/nontarget stimulus
        self.target_free_time = 0.75    # duration, after a target, during which no other target may appear 
        self.speech_offset = 0.2        # time offset for the animate/inanimate speech cues
        
        # response timing
        self.response_duration_words = 2.5  # timeout for response in the words condition
        self.response_duration_icons = 2.5  # timeout for response in the icons/beeps condition
        self.response_dp_duration = 0.25  # time window within which the second press of a double-press action has to occur
        
        # stimulus material
        self.animate_words = 'media\\animate.txt'       # text file containing a list of animate (target) words
        self.inanimate_words = 'media\\inanimate.txt'   # text file containing a list of inanimate (non-target) words
        self.target_beeps = ['t_t.wav']                 # list of target stimuli in the icons/beeps condition
        self.nontarget_beeps = ['nt_t.wav']             # list of non-target stimuli in the icons/beeps condition
        self.target_pics = ['disc-4-green.png']         # list of target pictures in the icons/beeps condition
        self.nontarget_pics = ['disc-3-green.png']      # list of non-target pictures in the icons/beeps condition
        self.pull_icon = 'disc-0-red-salient.png'       # pull stimulus as icon (red circle)
        self.pull_word = '\1salient\1RED!\1salient\1'  # pull stimulus as word
        self.pull_tone = 'red_t-rev2.wav'                    # pull stimulus as tone
        self.pull_speech_f = 'red_f-rev2.wav'            # pull stimulus spoken by a female
        self.pull_speech_m = 'red_m-rev2.wav'            # pull stimulus spoken by a male
        self.cue_icon = 'disc-0-yellow.png'             # cue stimulus as icon (yellow circle)
        self.cue_word = 'cue'                           # cue stimulus as word
        self.cue_tone = 'cue_t.wav'                     # cue stimulus as tone
        self.cue_speech_f = 'cue_f-rev.wav'             # cue stimulus spoken by a female
        self.cue_speech_m = 'cue_m-rev.wav'             # cue stimulus spoken by a male        
        
        # configuration of the warning task
        self.warning_params = {'event_interval':lambda: random.uniform(45,85),  # interval between two successive events
                               'snd_probability':0.5,                           # probability that an event is indicated by a sound (instead of a pic)
                               'pic_off':'buzzer-grey.png',                     # picture to display for the disabled light
                               'pic_on':'buzzer-red-real.png',                  # picture to display for the enabled light
                               'snd_on':'xHyprBlip.wav',                        # sound to play in case of an event
                               'snd_hit':'xClick01.wav',                        # sound when the user correctly detected the warning state
                               'pic_params':{'pos':[0,0.6],'scale':0.1},        # parameters for the picture() command
                               'snd_params':{'volume':0.1,'direction':0.0},     # parameters for the sound() command
                               'response_key':'enter',                          # key to press in case of an event
                               'timeout':3,                                     # response timeout for the user
                               'hit_reward':0,                                  # reward if hit
                               'miss_penalty':-10,                              # penalty if missed
                               'false_penalty':-5                               # penalty for false positives
                               }

        # configuration of the hold task
        self.hold_params = {'left_button':'z',                                  # the left button to hold
                            'right_button':'3',                                 # the right button to hold
                            'nohold_duration':lambda: random.uniform(45,85),    # duration of a no-hold period
                            'hold_duration':lambda: random.uniform(25,35),      # duration of a hold period
                            'pic':'hold_down.png',                              # picture to indicate that a button should be held
                            'snd':'xBleep.wav',                                 # sound to indicate that a button should be held
                            'left_pos':[-0.7,-0.9],                             # position if left
                            'right_pos':[0.7,-0.9],                             # position if right
                            'pic_params':{'scale':0.1},                         # parameters for the picture() command
                            'snd_params':{'volume':0.1},                        # parameters for the sound() command
                            'scoredrain_snd':'xTick-rev.wav',                   # sound to play when the score is trained...
                            'left_dir':-1,                                      # direction of the left "hold" sound 
                            'right_dir':+1,                                     # direction of the right "hold" sound
                            'loss_amount':0.25,                                 # amount of score lost if not held
                            'loss_interval':0.5,                                # interval at which score is subtracted
                            }

        # configuration of the rest block
        self.rest_duration = lambda: random.uniform(45,75)                      # duration of a rest block (was: 45-75)

        # center tasks
        self.movers_vis_params = {'background':'satellite_baseline.png',         # background image to use 
                                  'frame':[0.35,0.65,0.2,0.6],                   # the display region in which to draw everything
                                  'frame_boundary':0.2,                          # (invisible) zone around the display region in which things can move around and spawn
                                  'focused':True,
                
                                  # parameters of the target/non-target item processes
                                  'clutter_params':{'pixelated':True,
                                                    'num_items':140,
                                                    'item_speed': lambda: random.uniform(0,0.05),             # overall item movement speed; may be callable 
                                                    'item_diffusion': lambda: random.normalvariate(0,0.005),  # item Brownian perturbation process (applied at each frame); may be callable                                                
                                                    },           # parameters for the clutter process
                                  'target_params':{'pixelated':True,
                                                   'num_items':1,
                                                   'item_speed': lambda: random.uniform(0,0.05),             # overall item movement speed; may be callable 
                                                   'item_diffusion': lambda: random.normalvariate(0,0.005),  # item Brownian perturbation process (applied at each frame); may be callable                                                                                                   
                                                   'item_graphics':['tactical\\unit15.png','tactical\\unit15.png','tactical\\unit17.png']}, # parameters for the target process
                                  'intro_text':'Find the helicopter!',           # the text that should be displayed before the script starts
                                 
                                  # situational control
                                  'target_probability':0.5,                      # probability of a new situation being a target situation (vs. non-target situation) 
                                  'target_duration':lambda: random.uniform(3,6), # duration of a target situation
                                  'nontarget_duration':lambda: random.uniform(10,20),# duration of a non-target situation
                                 
                                  # end conditions
                                  'end_trials':1000000,                          # number of situations to produce (note: this is not the number of targets)
                                  'end_timeout':1000000,                         # lifetime of this stream, in seconds (the stream ends if the trials are exhausted)
                                 
                                  # response control
                                  'response_event':'space',                      # the event that is generated when the user presses the response button
                                  'loss_misstarget':0,                           # the loss incurred by missing a target                 
                                  'loss_nontarget':-2,                           # the loss incurred by a false detection
                                  'gain_target':4,                               # the gain incurred by correctly spotting a target 
                                  }

        self.movers_mov_params = {'background':'satellite_baseline.png',         # background image to use 
                                  'frame':[0.35,0.65,0.2,0.6],                  # the display region in which to draw everything
                                  'frame_boundary':0.2,                          # (invisible) zone around the display region in which things can move around and spawn
                                  'focused':True,
                
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
                                  'response_event':'space',                      # the event that is generated when the user presses the response button
                                  'loss_misstarget':0,                           # the loss incurred by missing a target                 
                                  'loss_nontarget':-2,                           # the loss incurred by a false detection
                                  'gain_target':2,                               # the gain incurred by correctly spotting a target 
                                  }
        
        self.math_params = {'difficulty': 2,                        # difficulty level of the problems (determines the size of involved numbers)
                            'focused':True,
                            'problem_interval': lambda: random.uniform(3,12), # delay before a new problem appears after the previous one has been solved
                            'response_timeout': 10.0,               # time within which the subject may respond to a problem
                            'gain_correct':5,                     
                            'loss_incorrect':-3,
                            'numpad_topleft': [0.9,-0.3],           # top-left corner of the numpad
                            'numpad_gridspacing': [0.21,-0.21],     # spacing of the button grid
                            'numpad_buttonsize': [1,1]              # size of the buttons
                            }
                
        self.video_params = {'files':['big\\forest.mp4'],           # the files to play (randomly)
                             'movie_params': {'pos':[0,-0.2],       # misc parameters to the movie() command
                                              'scale':[0.5,0.3],
                                              'aspect':1.12,
                                              'looping':True,                                              
                                              'volume':0.3}}

        self.driving_params = {'frame':[0.35,0.65,0.2,0.6],   # the display region in which to draw everything                 
                               'focused':True,
                               'show_checkpoints':False,

                               # media                  
                               'envmodel':'big\\citty.egg',        # the environment model to use
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

        # ambience sound setup
        self.ambience_sound = 'media\\ambience\\nyc_amb2.wav'
        self.ambience_volume = 0.1

        # misc parameters            
        self.developer = False,       # if true, some time-consuming instructions are skipped
        self.disable_center = False
        self.show_tutorial = False      # whether to show the tutorial
        self.run_main = True            # whether to run through the main game
    
    def run(self):
        try:
            self.marker(12)
    
            # define the "salient" text property (should actually have a card behind this...)
            tp_salient = TextProperties()
            tp_salient.setTextColor(1, 0.3, 0.3, 1)
            tp_salient.setTextScale(1.8)
            tpMgr = TextPropertiesManager.getGlobalPtr()
            tpMgr.setProperties("salient", tp_salient)
            
            # --- init the block design ---
            
            # init the randseed
            if self.randseed is not None:
                print "WARNING: Randomization of the experiment is currently bypassed."
                random.seed(self.randseed)
                self.marker(30000+self.randseed)
            if self.numavbouts % 2 != 0:
                raise Exception('Number of A/V bouts must be even.')
    
            # init the a/v bout order (lfem stands for "left female voice", rfem for "right female voice") 
            bouts  = ['av-words-lfem']*int(self.fraction_words*self.numavbouts/2) + ['av-words-rfem']*int(self.fraction_words*self.numavbouts/2) + ['av-icons']*int((1-self.fraction_words)*self.numavbouts)
            random.shuffle(bouts)
            
            # check if we have previously cached the focus order on disk (as it takes a while to compute it)
            cache_file = 'media\\focus_order_' + str(self.randseed) + '_new.dat'
            if False: # os.path.exists(cache_file):
                focus_order = pickle.load(open(cache_file))
            else:
                self.write('Calculating the experiment sequence.',0.1,scale=0.04)
    
                # generate the focus transitions for each pair of bouts
                valid = {'lv': ['rv','la','lvla'], # set of valid neighbors for each focus condition (symmetric) 
                         'rv': ['lv','ra','rvra'],
                         'la': ['lv','ra','lvla'],
                         'ra': ['la','rv','rvra'],
                         'lvra': ['lv','ra'],
                         'rvla': ['rv','la'],
                         'lvla': ['lv','la'],
                         'rvra': ['rv','ra']}
                focus_order = []  # list of focus conditions, per bout
                prev = None       # end point of the previous bout (before b)
                # for each pair of bouts...
                for b in range(0,len(bouts),2):
                    while True:
                        # generate a radom ordering of the mono conditions (balanced within each bout)
                        mono1 = ['lv','rv','la','ra']; random.shuffle(mono1)
                        mono2 = ['lv','rv','la','ra']; random.shuffle(mono2)
                        order = mono1 + mono2
                        # generate a random order of dual conditions (balanced within each pair of bouts)
                        dual = ['lvla','rvra','lvla','rvra']; random.shuffle(dual)
                        # and a list of insert positions in the first & second half (we only retain the first 2 indices in each after shuffling)
                        pos1 = [1,2,3,4]; random.shuffle(pos1)
                        pos2 = [5,6,7,8]; random.shuffle(pos2)
                        # the following instead allows split-attention modes to appear at the beginning of blocks
                        #  # and a list of insert positions in the first half
                        #  pos1 =  [1,2,3,4] if prev is None or len(prev)==4 else [0,1,2,3,4]; random.shuffle(pos1)
                        #  # and a list of insert positions in the second half
                        #  pos2 = [5,6,7,8] if pos1[0]==4 or pos1[1]==4 else [4,5,6,7,8]; random.shuffle(pos2)
                        # now insert at the respective positions (in reverse order to not mix up insert indices)
                        order.insert(pos2[1],dual[3])
                        order.insert(pos2[0],dual[2])
                        order.insert(pos1[1],dual[1])
                        order.insert(pos1[0],dual[0])
                        # now check sequence admissibility (accounting for the previous block if any)
                        check = order if prev is None else [prev] + order
                        admissible = True 
                        for c in range(len(check)-1):
                            if check[c+1] not in valid[check[c]]:
                                # found an invalid transition
                                admissible = False
                                break
                        # and check the fraction of within-modality switches
                        #if admissible:
                        #    num_withinmodality = 0
                        #    for c in range(len(check)-1):
                        #        if check[c][0] != check[c+1][0]:
                        #            num_withinmodality += 1                                 
                        #    if (1.0 * num_withinmodality / len(check)) < self.fraction_withinmodality_switches[0] or (1.0 * num_withinmodality / len(check)) > self.fraction_withinmodality_switches[1]:
                        #        admissible = False
                        if admissible:
                            break
                    # append two bouts to the focus_order array
                    focus_order.append(order[:6])
                    focus_order.append(order[6:])
                    # and remember the end point of what we just appended
                    prev = order[-1]
                pickle.dump(focus_order,open(cache_file,'w'))
            
            
            # insert the rest periods into bouts and focus_order..
            insert_pos = range(len(bouts)-2,1,-self.rest_every)
                    
            # generate the rest conditions
            rests = self.resttypes*(1+len(bouts)/(self.rest_every*len(self.resttypes)))
            rests = rests[:len(insert_pos)]
            random.shuffle(rests)
            
            # now insert
            for k in range(len(insert_pos)): 
                bouts.insert(insert_pos[k],rests[k])
                focus_order.insert(insert_pos[k],[])
            
            # determine the schedule of center task
            center_tasks = [None]*len(bouts)
            compatible_tasks_needed = 1 # the number of specifically a/v compatible center tasks that will be needed during a/v bout
            # a/v bouts after the last rest will need an a/v compatible center task
            cur_task = 0
            # go backwards and assign the current center task to each of the bouts...
            for k in range(len(bouts)-1,-1,-1):
                # until we find a rest block, which changes the center task
                if bouts[k].find('rest-') >= 0:
                    cur_task = bouts[k]
                else:
                    # if the center task is incompatible with a/v bouts, ...
                    if not cur_task in self.resttypes_avcompat and type(cur_task) != int:
                        # .. we take note that we need another a/v compatible task
                        cur_task = compatible_tasks_needed
                        compatible_tasks_needed += 1 
                center_tasks[k] = cur_task
            # now generate a balanced & randomized list of a/v compatible tasks
            avcompat = self.resttypes_avcompat * (1+compatible_tasks_needed/(len(self.resttypes_avcompat)))
            avcompat = avcompat[:compatible_tasks_needed]
            random.shuffle(avcompat)
            # ... and use them in the center tasks where needed
            for k in range(len(center_tasks)):
                if type(center_tasks[k]) == int:
                    center_tasks[k] = avcompat[center_tasks[k]]
            
            self.marker(13)
            
            # --- pre-load the media files ---
            
            self.sleep(0.5)
            
            # pre-load the target/non-target words (and corresponding sound files)
            animate_txt = []
            animate_snd_m = []
            animate_snd_f = []
            with open(self.animate_words) as f:
                for line in f:
                    word = line.strip(); animate_txt.append(word)
                    file = 'sounds\\' + word + '_m.wav'; animate_snd_m.append(file)                 
                    self.precache_sound(file)
                    file = 'sounds\\' +word + '_f.wav'; animate_snd_f.append(file)                 
                    self.precache_sound(file)
            inanimate_txt = []
            inanimate_snd_m = []
            inanimate_snd_f = []
            with open(self.inanimate_words) as f:
                for line in f:
                    word = line.strip(); inanimate_txt.append(word)
                    file = 'sounds\\' +word + '_m.wav'; inanimate_snd_m.append(file)                 
                    self.precache_sound(file)
                    file = 'sounds\\' +word + '_f.wav'; inanimate_snd_f.append(file)                 
                    self.precache_sound(file)
    
            # pre-load the target/non-target beeps
            for p in self.target_beeps:
                self.precache_sound(p)
            for p in self.nontarget_beeps:
                self.precache_sound(p)
                    
            # pre-load the target/non-target pictures
            for p in self.target_pics:
                self.precache_picture(p)
            for p in self.nontarget_pics:
                self.precache_picture(p)
    
            self.marker(14)
    
            # initially the target buttons are turned off 
            btarget_left = None
            btarget_right = None 
    
            # --- present introductory material ---
                
            while self.show_tutorial:
                self.marker(15)
                self.write('Welcome to the DAS experiment. Press the space bar to skip ahead.',[1,'space'],wordwrap=23,scale=0.04)
                
                self.write('In this experiment you will be presented a series of stimuli, some of which are "targets", and some of which are "non-targets". In the following, we will go through the various types of target and non-target stimuli.',[1,'space'],wordwrap=23,scale=0.04)
                self.write('There are in total 4 kinds of stimuli: spoken words, written words, icons, and tones.',[1,'space'],wordwrap=23,scale=0.04)
                
                self.write('Among the words, you only need to respond to animal words and should ignore the non-animal words.',[1,'space'],wordwrap=23,scale=0.04)        
                self.write('Here is an example spoken animal (i.e., target) word:',[1,'space'],wordwrap=23,scale=0.04)
                self.sound('sounds\\cat_f.wav',volume=1, direction=-1, surround=True,block=True)
                self.write('And here is an example spoken non-animal (i.e., non-target) word:',[1,'space'],wordwrap=23,scale=0.04)
                self.sound('sounds\\block_f.wav',volume=1, direction=-1, surround=True,block=True)
                self.sleep(1)
                self.write('Here are the same two words spoken by the male speaker.',[1,'space'],wordwrap=23,scale=0.04)
                self.sound('sounds\\cat_m.wav',volume=1, direction=1, surround=True,block=True)
                self.sleep(1)
                self.sound('sounds\\block_m.wav',volume=1, direction=1, surround=True,block=True)
                self.sleep(1)

                tmp_left = DirectButton(command=None,rolloverSound=None,clickSound=None,**self.button_left)
                tmp_right = DirectButton(command=None,rolloverSound=None,clickSound=None,**self.button_right)                    

                self.write('You respond to these stimuli by either pressing the left (for left stimuli) or right (for right stimuli) Ctrl button on your keyboard, OR the big left/right buttons on the touch screen. You should not use the same button too many times in a row but alternate between the keyboard and the touch screen (there will be a penalty for using only one type of button many times in a row).',[1,'space'],wordwrap=23,scale=0.04)

                tmp_left.destroy()
                tmp_right.destroy()
                
                self.write('The next type of stimulus is in the form of written words; again, animal words are targets and non-animal words are non-targets. Note that these will only light up for a short period of time.',[1,'space'],wordwrap=23,scale=0.04)
                self.write('cat',0.3,pos=[-0.8,0,0.3],fg=[1, 1, 1, 1],scale=0.1,align='center')
                self.sleep(1)
                self.write('block',0.3,pos=[-0.8,0,0.3],fg=[1, 1, 1, 1],scale=0.1,align='center')
                self.sleep(1)
                
                self.write('The other type of visual stimulus are icons. These are small disks (randomly rotated) with a different number of spines. The number of spines determines if the icon is a target or not. There are only two different shapes.',[1,'space'],wordwrap=23,scale=0.04)
                self.write('Here is a target.',[1,'space'],wordwrap=23,scale=0.04)
                self.picture(self.target_pics[0], 3, pos=[0.8,0,0.3], scale=0.1, color=[1,1,1,1],hpr=[0,0,random.random()*360])
                self.write('And here is a non-target.',[1,'space'],wordwrap=23,scale=0.04)
                self.picture(self.nontarget_pics[0], 3, pos=[0.8,0,0.3], scale=0.1, color=[1,1,1,1],hpr=[0,0,random.random()*360])
                self.write('The actual speed at which they show up is as follows.',[1,'space'],wordwrap=23,scale=0.04)
                self.picture(self.target_pics[0], 0.3, pos=[0.8,0,0.3], scale=0.1, color=[1,1,1,1],hpr=[0,0,random.random()*360])
                self.sleep(0.3)
                self.picture(self.nontarget_pics[0], 0.3, pos=[0.8,0,0.3], scale=0.1, color=[1,1,1,1],hpr=[0,0,random.random()*360])
                self.sleep(2)
        
                self.write('Finally, the last type of stimulus are tones; these need to be memoized precisely.',[1,'space'],wordwrap=23,scale=0.04)
                self.write('Here is a target.',[1,'space'],wordwrap=23,scale=0.04)
                self.sound(self.target_beeps[0],volume=1, direction=1, surround=True,block=True)
                self.sleep(1)
                self.write('And here is a non-target.',[1,'space'],wordwrap=23,scale=0.04)
                self.sound(self.nontarget_beeps[0],volume=1, direction=1, surround=True,block=True)
                self.sleep(1)
                self.write('Target and non-target will be played again for memoization. You will hear many more non-targets than targets, so listen carefully for their relative difference.',[1,'space'],wordwrap=23,scale=0.04)
                self.sound(self.target_beeps[0],volume=1, direction=1, surround=True,block=True)
                self.sleep(1)
                self.sound(self.nontarget_beeps[0],volume=1, direction=1, surround=True,block=True)
                self.sleep(1)
                
                self.write('Finally, and most importantly, there is a special and very noticable "cue event" that may appear among those stimuli.',[1,'space'],wordwrap=23,scale=0.04)
                self.write('It tells you to which side (left or right) AND to which modality (auditory or visual) you should attend by responding to targets that occur in that modality and side.',[1,'space'],wordwrap=23,scale=0.04)
                self.write('There are four versions of it -- one for each form of stimulus -- which will be played as follows. We will go through the sequence twice.',[1,'space'],wordwrap=23,scale=0.04)
                
                for k in range(2):
                    self.write('In written word form:',[1,'space'],wordwrap=23,scale=0.04)
                    self.write(self.pull_word,0.3,pos=[0.8,0,0.3],fg=[1, 1, 1, 1],scale=0.1,align='center')
                    self.sleep(1)
                    self.write('In spoken word form:',[1,'space'],wordwrap=23,scale=0.04)
                    self.sound(self.pull_speech_m,volume=2, direction=1, surround=True,block=True)
                    self.sleep(1)
                    self.write('In icon form:',[1,'space'],wordwrap=23,scale=0.04)
                    self.picture(self.pull_icon, 0.3, pos=[0.8,0,0.3], scale=0.1, color=[1,1,1,1],hpr=[0,0,random.random()*360])
                    self.sleep(1)
                    self.write('And in tone form:',[1,'space'],wordwrap=23,scale=0.04)
                    self.sound(self.pull_tone,volume=2, direction=1, surround=True,block=True)
                    self.sleep(1)
                    self.write('Note for comparison the non-target sound:',[1,'space'],wordwrap=23,scale=0.04)
                    self.sound(self.nontarget_beeps[0],volume=1, direction=1, surround=True,block=True)
                    self.sleep(3)

                self.write('In other words, if you HEAR a cue on the left side (the very high-pitched tone or the girl/man saying "red"), you respond to AUDITORY targets on the LEFT side and ignore the other targets (that is left visual targets, right visual targets, and right auditory targets).',[1,'space'],wordwrap=23,scale=0.04)
                self.write('Or if you SEE a cue on that side (the bright circle or the word "RED!"), you respond to VISUAL targets on that side and ignore all other targets (left auditory, right auditory, right visual).',[1,'space'],wordwrap=23,scale=0.04)
                self.sleep(1)
                self.write('In a fraction of cases, you will BOTH see a cue and hear a cue at the same time on one of the sides (e.g., right). This indicates that you need to respond to both visual AND auditory targets on that side and ignore targets on the other side. The only constellation in which this may happen is either both left visual and auditory, or both right visual and auditory cues.',[1,'space'],wordwrap=23,scale=0.04)
                self.write('Consequently, these cues are guiding you around across the two speakers and the two side screens and determine what targets you should subsequently respond to. Responding to targets in the wrong location (or modality) will subtract some score. Note that the cues themselves do not demand a button response.',[1,'space'],wordwrap=23,scale=0.04)
                self.write('Therefore - while these cues are quite noticable - you don''t want to miss them too frequently, as you not know what to respond to. Except if you figure it out by trial and error...',[1,'space'],wordwrap=23,scale=0.04)                
                self.sleep(1)                
                self.write('Whenever you hear a "Ding" sound, you will know that you earned 10 points. It sounds as follows:',[1,'space'],wordwrap=23,scale=0.04)
                self.sound(self.score_params["gain_file"],volume=0.5, direction=-0.7, surround=True,block=True)
                self.write('And whenever you hear a "Buzz" sound, you will know that you lost 10 points. It sounds as follows:',[1,'space'],wordwrap=23,scale=0.04)
                self.sound(self.score_params["loss_file"],volume=0.4, direction=-0.7, surround=True,block=True)
                self.write('It some cases you instead hear a "Click" sound in response to your key presses, which tells you that you neither gained nor lost points. It sounds as follows:',[1,'space'],wordwrap=23,scale=0.04)
                self.sound(self.score_params["none_file"],volume=0.5, direction=-0.7, surround=True,block=True)
                self.write('This may happen when the positive score for a key press (spotted a target) is canceled out by a negative score at the same time (e.g. by coincidence there was also a target in the other modality that you should not respond to). This is quite rare and not your fault, don''t think about it.',[1,'space'],wordwrap=23,scale=0.04)
                
                self.write('This completes the discussion of the main task of the experiment. We will now go through a series of additional challenges that come up at random times throughout the experiment.',[1,'space'],wordwrap=23,scale=0.04)
                                
                # self.write('Also, sometimes you will be asked to hold down a left or right button on your keyboard, and keep holding it until the indicator disappears. This is indicated by the following type of picture.',[1,'space'],wordwrap=23,scale=0.04)
                self.write('First and foremost, an event that will occasionally (but rarely) appear is a RED WARNING LIGHT in the upper center of the sceen, or a noticable ALARM SOUND. You must confirm that you noticed this type of event using the "ALARM" key on your keyboard. If you miss it, you lose a lot of score.',[1,'space'],wordwrap=23,scale=0.04)                
                
                #self.sleep(1)
                #self.sound(self.hold_params['snd'],direction=self.hold_params['left_dir'],**self.hold_params['snd_params'])
                #self.picture(self.hold_params['pic'],3,pos=self.hold_params['left_pos'],**self.hold_params['pic_params'])   
                
                self.sleep(2)
                
                self.write('And secondly, there is always some action going on in the center of the screen that you may engage in to gain extra score. There will be a message at the beginning of each block which tells you how to interact with it. Most of the time, this is a search task in which you are asked to watch for and spot a relatively rare object, and confirm that you saw it via the "SATELLITE MAP" bar in the middle of the keyboard.',[1,'space'],wordwrap=23,scale=0.04)
                self.write('If you miss any of these objects, you will not lose score, so you may disregard them if the main task demands too much attention. However, you can drastically increase your score by trying to accomplish the center-screen task whenever possible.',[1,'space'],wordwrap=23,scale=0.04)
                self.write('In some blocks the center task will be relatively dull and does not require any response from you, or in another case you are asked to count the occurrences of an object which you report later to the experimenter.',[1,'space'],wordwrap=23,scale=0.04)
                
                self.sleep(2)
                
                self.write('By the way, there will be occasional resting blocks in which you may relax for a while (or earn some extra score if bored).',[1,'space'],wordwrap=23,scale=0.04)
                self.write('After the tutorial the experimenter will ask you to play a training session of the experiment, so that you can familiarize yourself with the routines and ask questions about the experiment logic.',[1,'space'],wordwrap=23,scale=0.04)

                self.write('Do you want to see the tutorial again? (y/n).',1.5,wordwrap=23,scale=0.04)
                if self.waitfor_multiple(['y','n'])[0] == 'n':
                    break;
                
                break

            if not self.run_main:
                self.write('Tutorial finished.\nPlease let the experimenter know when you are ready for the training session.',5,wordwrap=23,scale=0.04)
                return
               
            # --- set up persistent entities that stay during the whole experiment ---
    
            # init the reward logic
            self.rewardlogic = AudioRewardLogic(**self.score_params)
    
            # init the keyboard shortcuts
            self.accept(self.lefttarget,self.response_key,['target-keyboard','l'])
            self.accept(self.righttarget,self.response_key,['target-keyboard','r'])
            self.accept(self.lefthold,messenger.send,['left-hold'])
            self.accept(self.righthold,messenger.send,['right-hold'])        
    
            # --- experiment block playback ---
    
            self.marker(16)
    
            no_target_before = time.time()      # don't present a target before this time
            self.init_response_parameters()        
    
            self.write('Press the space bar to start.','space',wordwrap=25,scale=0.04)
            self.write('Prepare for the experiment.',3,wordwrap=25,scale=0.04)
            for k in [3,2,1]:
                self.write(str(k),scale=0.1)
    
            # start some ambience sound loop
            self.ambience = self.sound(self.ambience_sound,looping=True,volume=self.ambience_volume,direction=0)
    
            # add a central button that acts as an additional space bar
            center_button = DirectButton(command=messenger.send,extraArgs=['space'],rolloverSound=None,clickSound=None,**self.button_center)
            # start the warning task
            self.warningtask = self.launch(WarningTask(self.rewardlogic,**self.warning_params))
            # start the hold task (ck: disabled) 
            # self.holdtask = self.launch(HoldTask(self.rewardlogic,**self.hold_params))
            
            # for each bout...
            prevbout = None                     # previous bout type
            prevcenter = None                   # previous center task type
            self.center = None                  # center task handle
            for k in range(len(bouts)):
                # schedule the center task
                if not self.disable_center and center_tasks[k] != prevcenter:
                    # terminate the old center task
                    if self.center is not None:
                        self.center.cancel()
                    # launch a new center task                
                    if center_tasks[k] == 'rest-movers-vis':
                        self.center = self.launch(VisualSearchTask(rewardlogic=self.rewardlogic,**self.movers_vis_params))
                    elif center_tasks[k] == 'rest-movers-mov':
                        self.center = self.launch(VisualSearchTask(rewardlogic=self.rewardlogic,**self.movers_mov_params))
                    elif center_tasks[k] == 'rest-math':
                        self.center = self.launch(MathScheduler(rewardhandler=self.rewardlogic,**self.math_params))
                    elif center_tasks[k] == 'rest-videos':
                        self.center = self.launch(VideoScheduler(**self.video_params))
                    elif center_tasks[k] == 'rest-drive':
                        self.write('Count the number of bags!',10,block=False,scale=0.04,wordwrap=25,pos=[0,0])
                        self.center = self.launch(CheckpointDriving(**self.driving_params))
                    else:
                        print "Unsupported center task; skipping"
                    prevcenter = center_tasks[k]
                
                if bouts[k][0:3] == 'av-':
                    # --- got an A/V bout ---
                    self.marker(17)
    
                    # create buttons if necessary
                    if btarget_left is None:
                        btarget_left = DirectButton(command=self.response_key,extraArgs=['target-touchscreen','l'],rolloverSound=None,clickSound=None,**self.button_left)
                    if btarget_right is None:
                        btarget_right = DirectButton(command=self.response_key,extraArgs=['target-touchscreen','r'],rolloverSound=None,clickSound=None,**self.button_right)                    
                    
                    # init visual presenters
                    words = bouts[k].find('words') >= 0
                    fem_left = bouts[k].find('lfem') >= 0
                    self.marker(23 if fem_left else 24)
                    if words:
                        self.marker(21)
                        vis_left = TextPresenter(**self.txt_left_params)
                        vis_right = TextPresenter(**self.txt_right_params)
                        vis_left_rnd = RandomPresenter(vis_left,{'target':animate_txt,'nontarget':inanimate_txt})
                        vis_right_rnd = RandomPresenter(vis_right,{'target':animate_txt,'nontarget':inanimate_txt})
                    else:
                        self.marker(22)
                        vis_left = ImagePresenter(**self.img_left_params)
                        vis_right = ImagePresenter(**self.img_right_params)
                        vis_left_rnd = RandomPresenter(vis_left,{'target':self.target_pics,'nontarget':self.nontarget_pics})
                        vis_right_rnd = RandomPresenter(vis_right,{'target':self.target_pics,'nontarget':self.nontarget_pics})                
                        
                    # init the audio presenters
                    aud_left = AudioPresenter(**self.aud_left_params)
                    aud_right = AudioPresenter(**self.aud_right_params)
                    if words:                    
                        aud_left_rnd = RandomPresenter(aud_left,{'target':animate_snd_f if fem_left else animate_snd_m,'nontarget':inanimate_snd_f if fem_left else inanimate_snd_m})
                        aud_right_rnd = RandomPresenter(aud_right,{'target':animate_snd_m if fem_left else animate_snd_f,'nontarget':inanimate_snd_m if fem_left else inanimate_snd_f})
                    else:
                        aud_left_rnd = RandomPresenter(aud_left,{'target':self.target_beeps,'nontarget':self.nontarget_beeps})
                        aud_right_rnd = RandomPresenter(aud_right,{'target':self.target_beeps,'nontarget':self.nontarget_beeps})
                    
                    # make a list of all current presenters to choose from when displaying targets/non-targets
                    presenters = {'lv':vis_left_rnd, 'rv':vis_right_rnd, 'la':aud_left_rnd, 'ra':aud_right_rnd}
    
                    # determine response timeout for this block
                    response_duration = self.response_duration_words if words else self.response_duration_icons 
    
                    prev_focus = None                
                    outstanding_cue = None
                    focus_blocks = focus_order[k]
                    # for each focus block...
                    for f in range(len(focus_blocks)):
                        
                        # determine the focus condition
                        focus = focus_blocks[f]
                        print 'Focus is now: ',focus
                        focusmap = {'lv':25,'rv':26,'la':27,'ra':28,'lvla':29,'lvra':30,'rvla':31,'rvra':32}                    
                        self.marker(focusmap[focus])
                        
                        # reset the slap-penalty counters if switching sides
                        # (these penalize too many successive presses of the same button in a row)
                        if prev_focus is not None and focus[0] != prev_focus[0]: 
                            self.reset_slap_counters()                        
                        
                        # determine the favored position (gives 2 points, the other one gives 1 point)
                        if len(focus) == 4:
                            favored_pos = focus[:2] if random.choice([False,True]) else focus[2:]
                            favormap = {'lv':33,'rv':34,'la':35,'ra':36}                    
                            self.marker(favormap[favored_pos])
                        else:
                            favored_pos = focus
    
                        # if there is an outstanding pre-cue from the previous focus block, and 
                        # the type of pre-cued modality is not contained in the current focus block:
                        if outstanding_cue is not None and focus.find(outstanding_cue) < 0:
                            self.marker(37)
                            # forget about it
                            outstanding_cue = None
                        
                        # determine if we should present a "pull" cue:
                        if prev_focus is not None and len(prev_focus)==2 and len(focus)==2 and prev_focus[1]==focus[1]:
                            # we do that only in a pure left/right switch, and if we are not at the beginning of a new bout
                            dopull = random.random() < self.pull_probability
                        else:
                            # always give a pull cue 
                            dopull = True
    
                        if dopull:
                            self.marker(38)
                            # present pull cue & wait for the pull duration
                            if focus.find('lv') >= 0:
                                vis_left.submit_wait(self.pull_word if words else self.pull_icon, self)
                                self.marker(39)
                            if focus.find('rv') >= 0:
                                vis_right.submit_wait(self.pull_word if words else self.pull_icon, self)
                                self.marker(40)
                            if focus.find('la') >= 0:
                                aud_left.submit_wait((self.pull_speech_f if fem_left else self.pull_speech_m) if words else self.pull_tone, self)
                                self.marker(41)
                            if focus.find('ra') >= 0:
                                aud_right.submit_wait((self.pull_speech_m if fem_left else self.pull_speech_f) if words else self.pull_tone, self)
                                self.marker(42)
                            self.sleep(self.pull_duration)
                            self.marker(43)
                        else:
                            pass
                            ## present push cue & wait (TODO: use other marker #'s)
                            #self.marker(338)
                            ## present push cue & wait for the duration
                            #if prev_focus.find('lv') >= 0:
                            #    vis_left.submit_wait(self.pull_word if words else self.pull_icon, self)
                            #    self.marker(339)
                            #if prev_focus.find('rv') >= 0:
                            #    vis_right.submit_wait(self.pull_word if words else self.pull_icon, self)
                            #    self.marker(340)
                            #if prev_focus.find('la') >= 0:
                            #    # hack: temporarily change the volume of the audio presenters for the pull cue
                            #    aud_left.submit_wait((self.pull_speech_f if fem_left else self.pull_speech_m) if words else self.pull_tone, self)
                            #    self.marker(341)
                            #if prev_focus.find('ra') >= 0:
                            #    # hack: temporarily change the volume of the audio presenters for the pull cue
                            #    aud_right.submit_wait((self.pull_speech_m if fem_left else self.pull_speech_f) if words else self.pull_tone, self)
                            #    self.marker(342)
                            #self.sleep(self.push_duration)
                            #self.marker(343)                                                        
    
                        # for each stimulus in this focus block...
                        numstims = int(self.focus_numstims())
                        for s in range(numstims):
                            
                            # show a target or a non-target?
                            istarget = time.time() > no_target_before and random.random() < self.target_probability
                            if istarget:
                                no_target_before = time.time() + self.target_free_time
                            
                            # turn the target into a cue?
                            iscue = outstanding_cue is None and random.random() < self.cue_probability
                            
                            if iscue:
                                self.marker(44)
                                # determine where to present the cue (note: we only do that in any of the current focus modalities)
                                if len(focus) == 4:
                                    # dual focus modality: choose one of the two
                                    outstanding_cue = focus[:2] if random.choice([False,True]) else focus[2:]  
                                else:
                                    outstanding_cue = focus
                                    
                                # display it...
                                if outstanding_cue == 'lv':                                
                                    vis_left.submit_wait(self.cue_word if words else self.cue_icon, self)
                                    self.marker(45)
                                elif outstanding_cue == 'rv':
                                    vis_right.submit_wait(self.cue_word if words else self.cue_icon, self)
                                    self.marker(46)
                                elif outstanding_cue == 'la':
                                    aud_left.submit_wait((self.cue_speech_f if fem_left else self.cue_speech_m) if words else self.cue_tone, self)
                                    self.marker(47)
                                elif outstanding_cue == 'ra':
                                    aud_right.submit_wait((self.cue_speech_m if fem_left else self.cue_speech_f) if words else self.cue_tone, self)
                                    self.marker(48)
                                # and2 wait...
                                self.sleep(self.cue_duration)
                                self.marker(49)
                                
                            elif istarget:
                                # present a target stimulus
                                self.marker(50)
                                pos = random.choice(['lv','rv','la','ra'])
                                presenters[pos].submit_wait("target",self)
                                targetmap = {'lv':51,'rv':52,'la':53,'ra':54}
                                self.marker(targetmap[pos])
                                
                                # set up response handling
                                if pos == favored_pos:
                                    reward = self.gain_target_fav
                                    self.marker(55)
                                elif focus.find(pos) >= 0:
                                    reward = self.gain_target_nofav
                                    self.marker(56)
                                else:
                                    reward = self.loss_nontarget_press
                                    self.marker(57)
                                self.expect_response(reward=reward, timeout=response_duration, wascued=(outstanding_cue==pos), side=pos[0])
                            else:
                                # present a non-target stimulus
                                self.marker(58)
                                pos = random.choice(['lv','rv','la','ra'])
                                presenters[pos].submit_wait("nontarget",self)
                                nontargetmap = {'lv':59,'rv':60,'la':61,'ra':62}
                                self.marker(nontargetmap[pos])
                                
                            # and wait for the inter-stimulus interval...
                            self.sleep(self.stim_duration)
                            self.marker(63)
                        
                        # focus block completed
                        prev_focus = focus
    
                    # bout completed
                    self.marker(64)
    
                    # destroy presenters...
                    vis_left.destroy()
                    vis_right.destroy()
                    aud_left.destroy()
                    aud_right.destroy()
                    
                    pass
                elif bouts[k][0:5] == 'rest-':
                    self.marker(18)
    
                    # delete buttons if necessary
                    if btarget_left is not None:
                        btarget_left.destroy()
                        btarget_left = None
                    if btarget_right is not None:
                        btarget_right.destroy()
                        btarget_right = None                    
                    

                    self.write("You may now rest for a while...",3,scale=0.04,pos=[0,0.4])
                    self.show_score()

                    # main rest block: just sleep and let the center task do the rest
                    duration = self.rest_duration()
                    if self.waitfor('f9', duration):
                        self.rewardlogic.paused = True
                        self.marker(400)
                        self.write("Pausing now. Please press f9 again to continue.",10,scale=0.04,pos=[0,0.4],block=False)
                        self.waitfor('f9', 10000)
                        self.rewardlogic.paused = False

                    self.marker(19)
                    self.sound('nice_bell.wav')
                    self.write("The rest block has now ended.",2,scale=0.04,pos=[0,0.4])
                    pass
                else:
                    print "unsupported bout type"
                prevbout = bouts[k]
                
            self.write('Experiment finished.\nYou may relax now...',5,pos=[0,0.4],scale=0.04)
            self.show_score()
            
            if self.center is not None:
                self.center.cancel()
            self.warningtask.cancel()
            self.holdtask.cancel()
        finally:
            try:
                if btarget_left is not None:
                    btarget_left.destroy()
                if btarget_right is not None:
                    btarget_right.destroy()
                center_button.destroy()
            except:
                pass            
            self.marker(20)    


    def show_score(self):
        """ Display the score to the subject & log it."""
        self.write("Your score is: " + str(self.rewardlogic.score*10),5,scale=0.1,pos=[0,0.8])
        self.rewardlogic.log_score()
        
    def init_response_parameters(self):
        """Initialize data structures to keep track of user responses."""
        self.response_outstanding = {'l':False,'r':False}
        self.response_window = {'l':None,'r':None}
        self.response_reward = {'l':None,'r':None}
        self.response_wascued = {'l':None,'r':None}
        self.response_dp_window = {'l':None,'r':None}
        self.response_dp_was_hiexpense = {'l':None,'r':None}
        self.response_dp_reward = {'l':None,'r':None}
        self.reset_slap_counters()
    
    def reset_slap_counters(self):
        """Reset the # of same-button presses in a row."""
        self.response_numkbd = {'l':0,'r':0}
        self.response_numtouch = {'l':0,'r':0}
    
    def expect_response(self,reward,timeout,wascued,side):
        """Set up an expected response for a particular duration (overrides previous expected responses)."""
        if self.response_outstanding[side] and self.response_dp_window[side] is not None:
            # a previous response was still outstanding: issue a miss penalty...
            if self.response_reward[side] > 0:
                self.marker(65)
                self.rewardlogic.score_event(self.loss_target_miss)
           
        # set up a new response window
        self.response_window[side] = time.time() + timeout
        self.response_outstanding[side] = True
        self.response_reward[side] = reward
        self.response_wascued[side] = wascued
        taskMgr.doMethodLater(timeout, self.response_timeout, 'EventWatcher.response_timeout()',extraArgs=[side])

    def response_key(self,keytype,side):
        """This function is called when the user presses a target button."""
        if keytype == 'target-touchscreen':
            # keep track of the # of successive presses of that button...
            self.response_numkbd[side] = 0
            self.response_numtouch[side] += 1
            self.marker(66 if side == 'l' else 67)
        else:
            # keep track of the # of successive presses of that button...
            self.response_numtouch[side] = 0
            self.response_numkbd[side] += 1
            self.marker(68 if side == 'l' else 69)
        
        # double-pressing is disabled for now (too complicated...)
        if self.response_dp_window[side] is not None:
            if time.time < self.response_dp_window[side]:                
                # called within a valid double-press situation: score!
                if keytype == 'target-touchscreen' and self.response_dp_was_hiexpense[side]:
                    self.marker(70)
                    # both key presses were hiexpense
                    self.response_dp_reward[side] += self.gain_hiexpense_plus
                else:
                    self.marker(71)
                # we add the cue gain
                self.response_dp_reward[side] += self.gain_cued_plus
                self.rewardlogic.score_event(self.response_dp_reward[side])
                self.response_dp_window[side] = None
                return
            else:
                self.marker(72)
                # called too late: treat it as a normal key-press  
                self.response_dp_window[side] = None
                
                
        if self.response_window[side] is None:
            # pressed outside a valid response window: baseline loss
            self.marker(73)
            self.rewardlogic.score_event(self.loss_nontarget_press)
        elif time.time() < self.response_window[side]:
            # within a valid response window            
            if not self.response_wascued[side]:
                
                # without a cue: normal response
                if keytype == 'target-touchscreen':
                    if self.response_numtouch[side] > self.max_successive_touches:
                        self.marker(83)
                        self.response_reward[side] = self.loss_nontarget_press
                        self.sound(self.max_successive_sound,volume=0.2)
                    else:                    
                        self.marker(74)
                        self.response_reward[side] += self.gain_hiexpense_plus
                else:
                    if self.response_numkbd[side] > self.max_successive_keypresses:
                        self.marker(84)
                        self.response_reward[side] = self.loss_nontarget_press
                        self.sound(self.max_successive_sound,volume=0.2)
                    else:
                        self.marker(75)
                self.rewardlogic.score_event(self.response_reward[side])
                
                
            else:
                self.marker(76)
                # with cue; requires special double-press logic
                self.response_dp_window[side] = time.time() + self.response_dp_duration
                self.response_dp_reward[side] = self.response_reward[side]
                self.response_dp_was_hiexpense[side] = (keytype=='target-touchscreen')
                taskMgr.doMethodLater(self.response_dp_window[side], self.doublepress_timeout, 'EventWatcher.doublepress_timeout()',extraArgs=[side])                    
            # no response outstanding --> dimantle the timeout
            self.response_outstanding[side] = False
            # also close the response window
            self.response_window[side] = None
           
    def response_timeout(self,side):
        """This function is called when a timeout on an expected response expires."""
        if not self.response_outstanding[side]:
            # no response outstanding anymore
            return
        elif time.time() < self.response_window[side]:
            # the timer was for a previous response window (which has been overridden since then)
            return
        else:
            # timeout expired!
            if self.response_reward[side] > 0:
                self.marker(77 if side=='l' else 78)
                self.rewardlogic.score_event(self.loss_target_miss)
            self.response_window[side] = None
            return 


    def doublepress_timeout(self,side):
        """This function is called when a timeout on the second press of a double-press situation expires."""
        if self.response_dp_window[side] is None:
            # the timeout was reset in the meantime
            return
        elif time.time() < self.response_dp_window[side]:
            # the timer was for a previous response window (which has been overridden since then)  
            return
        else:
            # the double-press opportunity timed out; count the normal score
            self.response_dp_window[side] = None
            if self.response_dp_was_hiexpense[side]:
                self.response_dp_reward[side] += self.gain_hiexpense_plus
                self.marker(79 if side == 'l' else 80)
            else:
                self.marker(81 if side == 'l' else 82)
            self.rewardlogic.score_event(self.response_dp_reward[side])
            
        
# === DAS Marker Table ===
#- 1: gain sound
#- 2: loss sound
#- 3: auditory warning on
#- 4: visual warning on
#- 5: warning off/expired
#- 6: hold left on 
#- 7: hold right on 
#- 8: hold off
#- 9: hold score drain tick (for left)
#- 10: hold score drain tick (for right)
#- 11: score drain tick (due to inappropriately held button)
#- 12: experiment launched
#- 13: experiment sequence generated
#- 14: media loaded
#- 15: tutorial started
#- 16: entering block loop
#- 17: a/v bout started
#- 18: rest bout started
#- 19: rest bout ended
#- 20: experiment ended
#- 21: entering words bout
#- 22: entering icons bout
#- 23: female on the left in subsequent bout
#- 24: male on the left in subsequent bout
#- 25: focus block for left visual spot
#- 26: focus block for right visual spot
#- 27: focus block for left auditory spot
#- 28: focus block for right auditory spot
#- 29: focus block for left visual and left auditory spot (dual condition)
#- 30: focus block for left visual and right auditory spot (dual condition)
#- 31: focus block for right visual and left auditory spot (dual condition)
#- 32: focus block for right visual and right auditory spot (dual condition)
#- 33: high-reward position in dual condition is left visual (low-reward is the other)
#- 34: high-reward position in dual condition is right visual (low-reward is the other)
#- 35: high-reward position in dual condition is left auditory (low-reward is the other)
#- 36: high-reward position in dual condition is right auditory (low-reward is the other)
#- 37: outstanding cue erased (due to focus switch to a constellation that does not include the 
#        cued position)
#- 38: preparing to present pull stimulus 
#- 39: pull stimulus on left visual spot
#- 40: pull stimulus on right visual spot
#- 41: pull stimulus on left auditory spot
#- 42: pull stimulus on right auditory spot
#- 43: pull duration expired (note: does not necessarily mean that the stim material was 
#        finished by then)
#- 44: preparing to present cue stimulus
#- 45: cue stimulus on left visual spot
#- 46: cue stimulus on right visual spot
#- 47: cue stimulus on left auditory spot
#- 48: cue stimulus on right auditory spot
#- 49: cue duration expired (note: dies not necessarily mean that the stim material was finished by 
#        then)
#- 50: preparing to present target stimulus
#- 51: target stimulus on left visual spot
#- 52: target stimulus on right visual spot
#- 53: target stimulus on left auditory spot
#- 54: target stimulus on right auditory spot
#- 55: high reward if target hit (favored position)
#- 56: low reward if target hit (non-favored position in dual condition)
#- 57: no reward if target hit (but also no loss; one of the unattended positions)
#- 58: preparing to present non-target stimulus
#- 59: non-target stimulus on left visual spot
#- 60: non-target stimulus on right visual spot
#- 61: non-target stimulus on left auditory spot
#- 62: non-target stimulus on right auditory spot
#- 63: inter-stimulus interval expired
#- 64: a/v bout ended
#- 65: target missed because next target is already being displayed on this side
#- 66: left touch screen button pressed
#- 67: right touch screen button pressed
#- 68: left keyboard target button pressed
#- 69: right keyboard target button pressed
#- 70: second press in an expected double-press/cued situation; high-expense button used in 
#        both cases (= extra reward)
#- 71: second press in an expected double-press/cued situation; no extra reward due to high 
#        expense (at most one of the two button presses was high-expense)
#- 72: pressed too late in a cued situation (may also be inadvertently)
#- 73: pressed outside a valid target reaction window (--> non-target press)
#- 74: pressed keyboard target within a valid target reaction window, but no cue given
#        (standard reward)
#- 75: pressed touchscreen target button within a valid target reaction window, but no cue given
#        (high-expense reward)
#- 76: first press in a double-press situation; reward deferred until second press comes in or 
#      timeout expires (after ~250ms in current settings)
#- 77: target response timeout expired on left side (target miss penalty)
#- 78: target response timeout expired on right side (target miss penalty)
#- 79: timeout for second press in a cued situation expired on left side, first press was a touch 
#        press; giving deferred high-expense reward
#- 80: timeout for second press in a cued situation expired on right side, first press was a touch 
#        press; giving deferred high-expense reward
#- 81: timeout for second press in a cued situation expired on left side, first press was a 
#        keyboard press; giving deferred standard reward
#- 82: timeout for second press in a cued situation expired on right side, first press was a
#        keyboard press; giving deferred standard reward
#- 83: touch press for too many successive times
#- 84: kbd press for too many successive times
#
#- 150 +/- 20 score update (offset = score delta)
#
#- 213: EventWatcher initialized
#- 214: EventWatcher watch_for() engaged
#- 215: EventWatcher watch_for() timeout reached, handler called
#- 216: EventWatcher watch_for() timeout reached, no handler called
#- 217: EventWatcher event registered in watch_for() window, event handler called
#- 218: EventWatcher event registered outside watch_for() window, defaulthandler in place
#- 219: EventWatcher event registered outside watch_for() window, no action
#- 220: output displayed on RandomPresenter
#- 221: output displayed on AudioPresenter
#- 222: output displayed on ImagePresenter
#- 223: output removed from ImagePresenter
#- 224: output displayed on ScrollPresenter
#- 225: output removed from ScrollPresenter
#- 226: output displayed on TextPresenter
#- 227: output removed from TextPresenter
#- 228: waiting for event to happen
#- 229: expected event registered (usually: keypress)
#- 230+k: k'th expected events registered (usually: keypress)
#- 244: timed movie displayed
#- 245: timed movie removed
#- 246: timed sound displayed
#- 247: timed sound removed
#- 248: timed picture displayed
#- 249: timed picture removed
#- 250: timed rectangle displayed
#- 251: timed rectangle removed
#- 252: timed crosshair displayed
#- 253: timed crosshair removed
#- 254: timed text displayed
#- 255: timed text removed
#
#- 10000+k k'th message selected on RandomPresenter
#- 20000+k k'th element randomly picked from message's pool in RandomPresenter
#- 30000+k: randseed
    
