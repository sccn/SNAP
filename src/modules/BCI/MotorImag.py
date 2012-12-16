from framework.latentmodule import LatentModule
import random

class Main(LatentModule):
    def __init__(self):
        LatentModule.__init__(self)
        
        # set defaults for some configurable parameters:
        self.training_trials = 10           # number of trial in training block
        self.trials_per_block = 30          # number of trials in each block
        self.blocks = 3                     # number of blocks to present
        self.pause_duration = 45            # duration of the pause between blocks
        self.fixation_duration = 1          # duation for which the fixation cross is displayed
        self.letter_duration = 3            # duration for which the letter is shown
        self.wait_duration = 1              # wait duration at the end of each trial (nothing displayed)

        self.letter_scale = 0.3
        self.stimulus_set = ['L','R','O']   # the set of stimuli to present
        
    def run(self):
        self.marker(10)  # emit an event marker to indicate the beginning of the experiment
        self.write('In this experiment you will be asked to imagine either a left-hand or a right-hand movement through a succession of trials. Each trial will begin with a fixation cross, followed either by the letter L (for left hand movement) or the letter R (for right hand movement), or O (for nothing -- relax). Please begin imagining the respective movement when the letter appears and keep going until the letter disappears (after about 3 seconds). If an O appears, please do nothing. When you are ready for a practice run, please press the space bar.',[1,'space'],wordwrap=30,pos=[0,0.3])

        self.markeroffset = 30  # in the training block we will record different marker numbers
        self.run_block(self.training_trials)
        self.markeroffset = 0

        self.write('Please press the space bar when you are ready for the main experiment.',[1,'space'],wordwrap=30)
        for b in range(self.blocks):
            self.run_block(self.trials_per_block)
            self.write('Pause. We will continue after the gong.',self.pause_duration)
            self.sound('nice_bell.wav')
            self.sleep(3)

        self.write('You successfully completed the experiment.')
        
    def run_block(self,numtrials):
        self.marker(1+self.markeroffset)       
        for k in range(numtrials):
            # show a fixation cross
            self.marker(2+self.markeroffset)
            self.crosshair(self.fixation_duration)
            # display one of the tree stimuli
            stimulus = random.choice([0,1,2])
            self.marker(stimulus+3+self.markeroffset)
            self.write(self.stimulus_set[stimulus],self.letter_duration,scale=self.letter_scale)
            # wait for a few more seconds
            self.marker(stimulus+10)
            self.sleep(self.wait_duration)
            