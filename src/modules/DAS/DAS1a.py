from framework.deprecated.controllers import VisualRewardLogic, TargetScheduler, MathScheduler
from framework.deprecated.subtasks import StimulusStream
from framework.latentmodule import LatentModule
from framework.ui_elements.ImagePresenter import ImagePresenter
from framework.ui_elements.AudioPresenter import AudioPresenter
from framework.ui_elements.ScrollPresenter import ScrollPresenter
from framework.ui_elements.TextPresenter import TextPresenter
from framework.ui_elements.EventWatcher import EventWatcher
from framework.ui_elements.RandomPresenter import RandomPresenter
from framework.deprecated.subtasks.VisualSearchTask import VisualSearchTask
from direct.gui.DirectGui import *
from panda3d.core import *
import framework.speech
import itertools
import random
import time


class Main(StimulusStream):
    """
    DAS1a: First version of the DAS experiment #1.
    """
    
    def __init__(self):
        LatentModule.__init__(self)
    
        # === settings for the visual stimulus presenters ===
        
        # a center presenter (always an image)
        self.img_center_params = {'pos':[0,0,0.3],'clearafter':1.5,'scale':0.1}
        # two different left presenters - either an image or a text box, depending on block
        self.img_left_params = {'pos':[-1.25,0,0.3],'clearafter':1,'color':[1, 1, 1, 0.1],'scale':0.1}
        self.txt_left_params = {'pos':[-1.25,0.3],'clearafter':2,'framecolor':[0, 0, 0, 0],'scale':0.1}
        # two different right presenters - either an image or a text box, depending on block
        self.img_right_params = {'pos':[1.25,0,0.3],'clearafter':1,'color':[1, 1, 1, 0.1],'scale':0.1}
        self.txt_right_params = {'pos':[1.25,0.3],'clearafter':2,'framecolor':[0, 0, 0, 0],'scale':0.1}        
        
        # === settings for the auditory stimulus presenters ===
        
        # there is a left, a right, and a center location
        self.aud_left_params = {'direction':-1}
        self.aud_right_params = {'direction':1}
        self.aud_center_params = {'direction':0}
        
        # === settings for the block design ===
        
        # parameters of the block configuration
        self.num_blocks = 42                # total number of blocks of the following types
        self.fraction_avstrong = 12         # audio/visual, strong separation of target probability/reward
        self.fraction_avweak = 12           # audio/visual, weak separation of target probability/reward
        self.fraction_avruminate = 12       # audio/visual with added rumination (here: math) tasks
        self.fraction_rest = 3              # rest block
        self.fraction_restmath = 3          # rest block with math tasks

        # === settings for the A/V switching design ===
        
        # switch layout for audio/visual blocks
        self.switches_per_block = lambda: int(random.uniform(3,3)) # number of switches per a/v block (random draw), was: 7,13
        self.switches_withinmodality = 1./3                     # probability of a within-modality switch stimulus
        self.switches_outofmodality = 1./3                      # probability of a (salient) out-of-modality switch stimulus
        self.switches_bimodally = 1./3                          # probability of a bimodally delivered switch stimulus
        self.av_switch_interval = lambda: random.uniform(25,35) # inter-switch interval for the audio/visual condition, was: 25,35
        self.switch_time = 1                                    # duration for which the switch instruction is being displayed        

        # === settings for the stimulus material ===

        # this is formatted as follows:
        # {'type of block1 ':{'type of presenter 1': [['targets if focused',...],['nontargets if focused',...],['optional targets if not focused'],['optional nontargets if not focused']]
        #                     'type of presenter 2': [['targets if focused',...],['nontargets if focused',...],['optional targets if not focused'],['optional nontargets if not focused']]},        
        #  'type of block 2':{'type of presenter 1': [['targets if focused',...],['nontargets if focused',...],['optional targets if not focused'],['optional nontargets if not focused']]
        #                     'type of presenter 2': [['targets if focused',...],['nontargets if focused',...],['optional targets if not focused'],['optional nontargets if not focused']]}}
        self.stim_material = {'avstrong': {'center_aud':[['Target.'],['nothing special','blah blah','monkey','nothing to report'],['TARGET!']],
                                           'center_vis':[['warning.png'],['onerust.png','tworust.png','threerust.png'],['salient_warning.png']],
                                           'side_img':[['rebel.png'],['onerust.png','tworust.png','threerust.png']],
                                           'side_txt':[['Target'],['Frankfurt','Berlin','Calgary','Barcelona']],
                                           'side_spc':[['Target'],['Frankfurt','Berlin','Calgary','Barcelona']],
                                           'side_snd':[['xHyprBlip.wav'],['xClick01.wav']]},
                              'avweak': {'center_aud':[['Target.'],['nothing special','blah blah','monkey','nothing to report']],
                                           'center_vis':[['warning.png'],['onerust.png','tworust.png','threerust.png']],
                                           'side_img':[['rebel.png'],['onerust.png','tworust.png','threerust.png']],
                                           'side_txt':[['Target'],['Frankfurt','Berlin','Calgary','Barcelona']],
                                           'side_spc':[['Target'],['Frankfurt','Berlin','Calgary','Barcelona']],
                                           'side_snd':[['xHyprBlip.wav'],['xClick01.wav']]}
                              }
                
        # probability distribution over locations, if a target should be presented
        self.target_probabilities = {'avstrong': {'center_aud':[0.4,0.1], # this is [probability-if-focused, probability-if-unfocused] 
                                                  'center_vis':[0.4,0.1], 
                                                  'side_img':[0.25,0.0],   # note that there are 2 locations with side_* (left/right) and that usually only one set of these is active at a given time
                                                  'side_txt':[0.25,0.0],   # also note that all the focused numbers one modality plus the unfocused numbers of the other modality should add up to 1.0
                                                  'side_spc':[0.25,0.0],   # (however, they will be automatically renormalized if necessary)
                                                  'side_snd':[0.25,0.0]},
                                     'avweak': {'center_aud':[0.4,0.2], 
                                                'center_vis':[0.4,0.2], 
                                                'side_img':[0.2,0.0],
                                                'side_txt':[0.2,0.0],
                                                'side_spc':[0.2,0.0],
                                                'side_snd':[0.2,0.0]}}
        
        # probability distribution over locations, if a non-target should be presented
        self.nontarget_probabilities = {'avstrong': {'center_aud':[0.3,0.3], 
                                                  'center_vis':[0.3,0.3], 
                                                  'side_img':[0.2,0.0],
                                                  'side_txt':[0.2,0.0],
                                                  'side_spc':[0.2,0.0],
                                                  'side_snd':[0.2,0.0]},
                                     'avweak': {'center_aud':[0.3,0.1], 
                                                'center_vis':[0.3,0.1], 
                                                'side_img':[0.2,0.1],
                                                'side_txt':[0.2,0.1],
                                                'side_spc':[0.2,0.1],
                                                'side_snd':[0.2,0.1]}}
        
        # rewards and penalities for target hits/misses
        self.rewards_penalties = {'avstrong': {'center_aud':['high-gain','high-loss','low-gain','low-loss'], # this is [score-if-focused-and-hit,score-if-focused-and-missed,score-if-nonfocused-and-hit,score-if-nonfocused-and-missed] 
                                               'center_vis':['high-gain','high-loss','low-gain','low-loss'], 
                                               'side_img':['low-gain','low-loss','low-gain','low-loss'],
                                               'side_txt':['low-gain','low-loss','low-gain','low-loss'],
                                               'side_spc':['low-gain','low-loss','low-gain','low-loss'],
                                               'side_snd':['low-gain','low-loss','low-gain','low-loss']},
                                     'avweak': {'center_aud':['high-gain','high-loss','high-gain','low-loss'], 
                                                'center_vis':['high-gain','high-loss','low-gain','low-loss'], 
                                                'side_img':['low-gain','low-loss','low-gain','low-loss'],
                                                'side_txt':['low-gain','low-loss','low-gain','low-loss'],
                                                'side_spc':['low-gain','low-loss','low-gain','low-loss'],
                                                'side_snd':['low-gain','low-loss','low-gain','low-loss']}}
        
        # auditory and visual switch stimuli, in and out of modality 
        self.vis_switch_inmodality = 'switch.png'
        self.vis_switch_outmodality = 'switch-target.png'
        self.aud_switch_inmodality = 'Switch'
        self.aud_switch_outmodality = 'Hey, Switch NOW!'

        # === settings for the stimulus appearance ===
        
        # target layout for audio/visual blocks
        self.target_probability = 0.2                           # overall probability of an event being a target in the a/v condition        
        self.target_focus_prob_strong = 0.9                     # probability of a given target appearing in the focused modality, if strong separation
                                                                # (1 - this number) for a target appearing in the non-focused modality 
        self.target_focus_prob_weak = 0.6                       # probability of a given target appearing in the focused modality, if weak separation
                                                                # (1 - this number) for a target appearing in the non-focused modality
        self.prob_salient = 0.2                                 # probability that a target appears at the salient location (center)
        self.prob_side1 = 0.5                                   # probability that a target appears at the first side location (side locations may be swapped from block to block)
        self.prob_side2 = 0.3                                   # probability that a target appears a the second side location
        
        # stimulus layout for audio/visual blocks
        self.av_stimulus_interval = lambda: random.uniform(0.5,4) # inter-stimulus interval for the audio/visual condition        

        # === settings for the rest & math tasks ===
        
        self.rest_duration = lambda: random.uniform(45,75)      # the duration of the rest condition
        self.math_params = {'difficulty': 1,                    # difficulty level of the problems (determines the size of involved numbers)
                            'problem_interval': lambda: random.uniform(3,12), # delay before a new problem appears after the previous one has been solved
                            'response_timeout': 10.0,           # time within which the subject may respond to a problem           
                            'numpad_topleft': [1.1,-0.3],        # top-left corner of the numpad
                            'numpad_gridspacing': [0.21,-0.21],   # spacing of the button grid
                            'numpad_buttonsize': [1,1]          # size of the buttons
                            }

        # === settings for scoring ===

        # scoring parameters
        self.scoring_params = {'initial_score': 250,                                                    # the initial score at the beginning of the experiment
                               'score_image_params': {'scale':0.12,'pos':[-1.25,0.5,0.5],'clearafter':2},   # properties of the score image
                               'score_sound_params': {'direction':-0.7,'volume':0.3},                     # properties of the score sound source
                               'score_responses': {'high-gain':[25,'happy_star.png','xDingLing.wav'],   # [points, image, soundfile] for each of the ...
                                                   'low-gain':[5,'star.png','ding.wav'],                # ... possible scoring conditions
                                                   'low-loss':[-5,'worried_smiley.png','xBuzz01.wav'],
                                                   'high-loss':[-25,'sad_smiley.png','slap.wav']}}

        # === settings for miscellaneous parameters ===
        
        # response control
        self.response_window = 3                                # response time window in seconds
        self.response_event = 'target-response'                 # response event/message type 
        self.button_params = {'frameSize':(-3,3,-0.5,1),'pos':(-1.25,0,-0.92),'text':"Target",'scale':.1,'text_font':loader.loadFont('arial.ttf')}     # parameters of the target button
        self.voiceindicator_params = {'pos':(0,0,-0.925),'scale':0.1,'color':[1, 1, 1, 1]}                               # parameters of the voice indicator image
        self.allow_speech = False

        # misc parameters
        self.randseed = 34214                                       # initial randseed for the experiment (NOTE: should be random!)
        self.scroller_params = {'pos':[-1.8,-0.5],'width':22,'clearafter':4}   # a text box for debugging, output, etc
        self.movers_params = {'frame':[0.35,0.65,0.1,0.5],           # parameters of the moving-items process
                              'trials':500,
                              'target_probability':0}
        
        self.developer = True                                   # if true, some time-consuming instructions are skipped
        
    def run(self):
        # init the randseed
        if self.randseed is not None:
            print "WARNING: Randomization of the experiment is currently bypassed."
            random.seed(self.randseed)        

        # === preprocess the stim material ===
        
        # if no out-of-modality (non-focused) stimuli are given, replicate the within-modality (focused) stimuli for them
        # for each block type...
        for bt in self.stim_material.iterkeys():
            # for each material set
            for ms in self.stim_material[bt].iterkeys():
                if len(self.stim_material[bt][ms]) < 2:
                    raise Exception("The collection of stimuli for a presenter type must include at least targets and non-targets.")
                if len(self.stim_material[bt][ms]) < 3:
                    self.stim_material[bt][ms].append(self.stim_material[bt][ms][0])
                if len(self.stim_material[bt][ms]) < 4:
                    self.stim_material[bt][ms].append(self.stim_material[bt][ms][1])

        # === init input/output setup that stays for the entire experiment ===

        # set up target response modalities (keyboard, button, speech)
        self.accept('control',messenger.send,['target-keyboard'])
        target_button = DirectButton(command=messenger.send,extraArgs=['target-touchscreen'],rolloverSound=None,clickSound=None,**self.button_params)
        if self.allow_speech:
            try:
                framework.speech.listenfor(['ack'],lambda phrase,listener: self.send_message('target-spoken'))
                self.accept('target-spoken',self.highlight_mic)
                speech_operational = True
            except:
                speech_operational = False
                print "Could not initialiate speech control; falling back to touch screen only."
        else:
            speech_operational = False                    

        if not self.developer: 
            self.write('Welcome to the DAS experiment.')
            self.write('Your task in the following is to respond to the target stimuli\n by either pressing the on-screen target button,\n or, if a microphone icon is displayed at the bottom of the screen,\n by speaking "Target" into the tabletop microphone.',5,scale=0.04)
            self.write('If you see a keypad on a side screen, expect to occasionally receive\n short math problems, which you solve by dialing the solution \n into the keypad and pressing the NEXT button.\n Keep in mind that your time to solve a given math problem is limited.',5,scale=0.04)
        
        # add an indicator image to display whether we have voice control
        self.voiceimage = ImagePresenter(**self.voiceindicator_params)

        # make a text output box
        textbox = ScrollPresenter(**self.scroller_params)
        
        # init the reward logic
        rewardlogic = VisualRewardLogic(**self.scoring_params)

        # make a passive center task (visual movers)
        # TODO: later, this will be chosen differently run of blocks (between rest conditions)
        self.launch(VisualSearchTask(textbox,**self.movers_params));

        # create the center presenter
        vis_center = ImagePresenter(**self.img_center_params)

        # create the three auditory stimulus presenters
        aud_left = AudioPresenter(**self.aud_left_params)
        aud_right = AudioPresenter(**self.aud_right_params)
        aud_center = AudioPresenter(**self.aud_center_params)

        # === generate the overall block design ===
         
        # first renormalize the fractions
        fraction_norm = 1.0 / (self.fraction_avstrong + self.fraction_avweak + self.fraction_avruminate + self.fraction_rest + self.fraction_restmath)
        self.fraction_avstrong *= fraction_norm
        self.fraction_avweak *= fraction_norm
        self.fraction_avruminate *= fraction_norm
        self.fraction_rest *= fraction_norm
        self.fraction_restmath *= fraction_norm

        # generate the list of A/V switching blocks (we have one with strong importance bias/separation, one with weak separation, and one strong-separation block with interspersed math problems
        self.blocks = ['avstrong']*int(self.fraction_avstrong*self.num_blocks) + ['avweak']*int(self.fraction_avweak*self.num_blocks) + ['avruminate']*int(self.fraction_avruminate*self.num_blocks)
        random.shuffle(self.blocks)        

        # TODO: optionally try to improve the ordering (e.g., make sure that blocks of a particular type are *not* concentrated in only one part of the experiment)

        # generate the list of resting blocks (some are pure resting, the others are resting + math)
        self.resting = ['rest']*int(self.fraction_rest*self.num_blocks) + ['restmath']*int(self.fraction_restmath*self.num_blocks)
        random.shuffle(self.resting)
        
        # merge them into one sequence of blocks
        indices = [k*len(self.blocks)/(len(self.resting)+1) for k in range(1,len(self.resting)+1)]
        indices.reverse()
        for k in range(len(indices)):
            self.blocks.insert(indices[k],self.resting[k])

        # generate the set of audio/visual display layouts for each type of A/V block (there are 12 combined layouts)
        # we have 4 screen layouts: img/img, img/txt, txt/img, txt/txt (txt=text, img=image)
        # and 3 audio layouts: spc/snd, spc/spc and snd/spc  (spc=speech, snd=sound)
        layouts = [e[0]+'-'+e[1] for e in itertools.product(['img/img','img/txt','txt/img','txt/txt'],['spc/snd','spc/spc','snd/spc'])]

        # for each block type, append a random permutation of the layouts to the block description strings  
        for blocktype in ['avstrong','avweak','avruminate']:
            # get the number of blocks of this type            
            blks = self.blocks.count(blocktype)
            if blks < len(layouts):
                print "Warning: the number of blocks in the ", blocktype, " condition is smaller than the number of display layouts; this will yield incomplete permutations."
            if blks % len(layouts) != 0:
                print "Warning: the number of blocks in the ", blocktype, " condition is not a multiple of the number of display layouts; this will yield incomplete permutations."

            # replicate the layouts for the number of blocks of this type
            lays = layouts * (blks/len(layouts) + (blks%len(layouts)>0))
            # shuffle them randomly
            random.shuffle(lays)
            
            # also generate a shuffled list of response layouts
            resp = ['verbal','manual']*(blks/2 + blks%2)
            random.shuffle(resp)
            
            # find the blocks which we want to annotate
            indices = [i for i in range(len(self.blocks)) if self.blocks[i]==blocktype]
            for k in range(len(indices)):
                # and for each of them, pick an entry from the permutation and append it
                self.blocks[indices[k]] += '-' + lays[k] + '-' + resp[k]


        # === execute the block design ===
        
        # for each block...
        prev = None
        for block in self.blocks:
            if block[0:2] == 'av':
                # one of the AV blocks
                self.marker(10)

                # update the GUI so that it indicates the current control type                
                if block.find('verbal') and speech_operational:
                    controltype = 'target-spoken'
                    target_button['state'] = DGG.DISABLED
                    self.voiceimage.submit('microphone_red.png')
                else:
                    target_button['state'] = DGG.NORMAL
                    controltype = 'target-touchscreen'
                    self.voiceimage.clear()
                    
                # set up and event watcher depending on the block's control type
                eventwatcher = EventWatcher(eventtype=controltype,
                                            handleduration=self.response_window,
                                            defaulthandler=lambda: rewardlogic.score_event('low-loss'))
                
                # determine whether we have strong focality of targets in the focused modality or not 
                if block.find('avstrong'):                
                    focality = 'avstrong'
                elif block.find('avweak'):
                    focality = 'avweak'
                elif block.find('avruminate'):
                    # note: ruminate blocks automatically have weak focality, because currently
                    #       the rumination instructions and responses are strongly visually coupled
                    focality = 'avweak'
                
                # determine the initial focused modality
                focus_modality = random.choice(['aud','vis'])
                
                # display AV block lead-in sequence
                if not self.developer:
                    modality = 'auditory' if focus_modality == 'aud' else 'visual'
                    self.write('Initially, you should direct your attention to the \n'+modality+' material until you encounter a switch instruction or symbol.',3,pos=(0,0.1),scale=0.04)
                    self.sleep(3)
                
                # - later generate the appropriate center task here... (if the prev was either none or a rest task...)
                
                # set up the appropriate display configuration for this block
                vis_left = ImagePresenter(**self.img_left_params) if block.find("img/")>=0 else TextPresenter(**self.txt_left_params)  
                vis_right = ImagePresenter(**self.img_right_params) if block.find("/img")>=0 else TextPresenter(**self.txt_right_params)  
   
                if block.find('avruminate'):
                    # if we're in the rumination condtion, also schedule a math task...
                    mathtask = self.launch(MathScheduler(presenter=textbox,rewardhandler=rewardlogic,**self.math_params))

                # determine the number of switch blocks to be done for this block
                # a switch block consits of a series of stimuli (targets/non-targets) followed by a switch cue (except for the last switch block)
                switchblocks = int(self.switches_per_block()+1)
                # ... and execute them
                for switchblock in range(switchblocks):
                    self.marker(11)
                    
                    # determine the duration of the current switch block
                    duration = self.av_switch_interval()
                    
                    print "Now in ", focus_modality, " condition for the next ",duration," seconds."
                
                    # and pre-load the aud/vis left/right/center RandomPresenters with the appropriate stimulus material
                    # for this, determine the offsets into the self.stim_material arrays to select between within-modality and out-of-modality material 
                    vis_focused = 0 if focus_modality == 'vis' else 2
                    aud_focused = 0 if focus_modality == 'aud' else 2
                    # also determine the type of stimulus material for left/right audio/visual, depending on block type
                    left_vis_material = 'side_img' if block.find("img/")>=0 else 'side_txt'
                    right_vis_material = 'side_img' if block.find("/img")>=0 else 'side_txt'                    
                    left_aud_material = 'side_spc' if block.find("spc/")>=0 else 'side_snd'
                    right_aud_material = 'side_spc' if block.find("/spc")>=0 else 'side_snd'
                    
                    # set up visual stimulus material depending on block configuration
                    out_vis_center = RandomPresenter(wrappresenter=vis_center,
                                                     messages={'target':self.stim_material[focality]['center_vis'][0+vis_focused],
                                                               'nontarget':self.stim_material[focality]['center_vis'][1+vis_focused]})
                    out_vis_left = RandomPresenter(wrappresenter=vis_left,
                                                   messages={'target':self.stim_material[focality][left_vis_material][0+vis_focused],
                                                             'nontarget':self.stim_material[focality][left_vis_material][1+vis_focused]})
                    out_vis_right = RandomPresenter(wrappresenter=vis_right,
                                                    messages={'target':self.stim_material[focality][right_vis_material][0+vis_focused],
                                                              'nontarget':self.stim_material[focality][right_vis_material][1+vis_focused]})
                    out_aud_center = RandomPresenter(wrappresenter=aud_center,
                                                     messages={'target':self.stim_material[focality]['center_aud'][0+aud_focused],
                                                               'nontarget':self.stim_material[focality]['center_aud'][1+aud_focused]})
                    out_aud_left = RandomPresenter(wrappresenter=aud_left,
                                                   messages={'target':self.stim_material[focality][left_aud_material][0+aud_focused],
                                                            'nontarget':self.stim_material[focality][left_aud_material][1+aud_focused]})
                    out_aud_right = RandomPresenter(wrappresenter=aud_right,
                                                    messages={'target':self.stim_material[focality][right_aud_material][0+aud_focused],
                                                             'nontarget':self.stim_material[focality][right_aud_material][1+aud_focused]})
                    
                    # generate probability distributions & score value setup for the 6 locations
                    d = self.target_probabilities[focality]
                    target_distribution = [d[left_vis_material][vis_focused>0],d['center_vis'][vis_focused>0],d[right_vis_material][vis_focused>0],
                                           d[left_aud_material][aud_focused>0],d['center_aud'][aud_focused>0],d[right_aud_material][aud_focused>0]]
                    d = self.nontarget_probabilities[focality]
                    nontarget_distribution = [d[left_vis_material][vis_focused>0],d['center_vis'][vis_focused>0],d[right_vis_material][vis_focused>0],
                                              d[left_aud_material][aud_focused>0],d['center_aud'][aud_focused>0],d[right_aud_material][aud_focused>0]]
                    d = self.rewards_penalties[focality]
                    hit_values = [d[left_vis_material][vis_focused],d['center_vis'][vis_focused],d[right_vis_material][vis_focused],
                                  d[left_aud_material][aud_focused],d['center_aud'][aud_focused],d[right_aud_material][aud_focused]]
                    miss_values = [d[left_vis_material][1+vis_focused],d['center_vis'][1+vis_focused],d[right_vis_material][1+vis_focused],
                                   d[left_aud_material][1+aud_focused],d['center_aud'][1+aud_focused],d[right_aud_material][1+aud_focused]]
                
                    print "DAS1: launching TargetScheduler..."
                
                    # schedule targets for the switch block
                    targets = self.launch(TargetScheduler(eventwatcher=eventwatcher,
                                              rewardhandler=rewardlogic,
                                              presenters=[out_vis_left,out_vis_center,out_vis_right,out_aud_left,out_aud_center,out_aud_right],
                                              end_timeout = duration,
                                              stimulus_interval = self.av_stimulus_interval,
                                              target_probability = self.target_probability,
                                              target_distribution=target_distribution,
                                              nontarget_distribution=nontarget_distribution,
                                              responsetime = self.response_window,
                                              hit_values=hit_values,
                                              miss_values=miss_values))
                
                    # ... and wait until they are done
                    # TODO: we better use a version of targets.join() here... 
                    self.sleep(duration+1)
                
                    # now present the switch cue, if applicable
                    if switchblock < switchblocks-1:
                        print "DAS1: resuming with switch..."
                        # not the last switch block: generate a switch cue
                        
                        # determine the modality in which it should show up
                        r = random.random()
                        if r < self.switches_withinmodality:
                            # within-modality switch instruction                            
                            if focus_modality == 'vis':                                
                                vis_center.submit_wait(self.vis_switch_inmodality,self,clearafter=self.switch_time)
                            else:
                                aud_center.submit_wait(self.aud_switch_inmodality,self,clearafter=self.switch_time)                            
                        elif r < self.switches_withinmodality + self.switches_bimodally:
                            # bi-modal switch instruction
                            # note: we are using here the within-modality stimuli for both modalities 
                            vis_center.submit_wait(self.vis_switch_inmodality,self,clearafter=self.switch_time)
                            aud_center.submit_wait(self.aud_switch_inmodality,self,clearafter=self.switch_time)
                        else:
                            # out-of-modality delivery; this is presented like a salient target
                            if focus_modality == 'vis':
                                aud_center.submit_wait(self.aud_switch_outmodality,self,clearafter=self.switch_time)                            
                            else:
                                vis_center.submit_wait(self.vis_switch_outmodality,self,clearafter=self.switch_time)

                        # wait for the lifetime of the switch announcement
                        self.sleep(self.switch_time)
                        # and flip the modality
                        focus_modality = 'vis' if focus_modality == 'aud' else 'aud'
                
                if block.find('avruminate'):
                    mathtask.cancel()
                
                self.write('You have successfully completed the block.\nYour current score is ' + str(rewardlogic.score),5,pos=(0,0.1),scale=0.04)

            elif block[0:3] == 'rest':
                duration = self.rest_duration()                
                # one of the rest blocks
                if block.find('math'):
                    self.write('Please take your time to solve the following math problems. A bell sound will remind your when this block is over.',3,pos=(0,0.1))
                    mathtask = self.launch(MathScheduler(presenter=textbox,rewardhandler=rewardlogic,end_timeout=duration,**self.math_params))
                    self.sleep(duration+5)
                else:
                    self.write('You may now rest until you hear a bell sound.',3,pos=(0,0.1))
                    self.sleep(duration)
                
                # play the bell sound
                self.sound('nice_bell.wav')
                    
            # destroy the old event watcher
            eventwatcher.destroy()
            prev = block
            
        # display any final material
        self.write('Congratulations! The experiment is now finished.',10,pos=(0,0.1))        


    def highlight_mic(self):
        self.voiceimage.icon.setScale(self.voiceimage.scale*1.3)
        self.voiceimage.reset_scale_at = time.time() + 0.75
        taskMgr.doMethodLater(0.75, self.reset_mic, 'DAS1.reset_mic()')
    
    def reset_mic(self,task):
        """Task to reset the mic image to normal size."""
        if time.time() >= self.voiceimage.reset_scale_at-0.1: # we don't reset if the schedule has been overridden in the meantime...                                
            self.voiceimage.icon.setScale(self.voiceimage.scale)
        return task.done 
          