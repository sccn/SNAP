from framework.latentmodule import LatentModule
from panda3d.core import TextProperties, TextPropertiesManager
import random
import time

class Main(LatentModule):
    def __init__(self):
        LatentModule.__init__(self)
        
        self.tasks = ['overt', 'covert', 'control']
        with open('studies/speech/stimuli.txt', 'r') as f:
            self.stimuli = f.readlines()
        self.conditions = ['visual', 'auditory']
        self.n_blocks = 4
        self.pause = 0.5
        
    def run(self):
        self.implicit_markers = False
        base.win.setClearColor((0, 0, 0, 1))
        
        self.marker(0)  # Send one event to trigger the whole event sending process
        
        # Precache sounds
        self.file_list = ['studies/speech/stimuli/' + k.strip() + '_f.wav' for k in self.stimuli]
        for f in self.file_list:
            self.precache_sound(f)
        
        # Define text properties
        tp_gray = TextProperties()
        tp_gray.setTextColor(0.5, 0.5, 0.5, 1)
        tpMgr = TextPropertiesManager.getGlobalPtr()
        tpMgr.setProperties("gray", tp_gray)
        
        # Show instructions (only in training run)
        if self.training:
            self.n_blocks = 1
            self.write('This is a speech perception/production\nexperiment. You will complete\nseveral trials in each block.\n\n' + 
                       '\1gray\1[Press Space to continue]\2', duration='space', align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))
            self.write('The experiment consists of three conditions.\nIn each trial, ' + 
                       'you will be prompted to perform\none of these three tasks:\n' +
                       '(1) speak a word,\n' + 
                       '(2) imagine speaking a word,\n' + 
                       '(3) press the space bar.\n\n\1gray\1[Press Space to continue]\2', duration='space', align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))
            self.write('In each trial, you will see or hear a word.\n\nYou will also see ' + 
                       'a visual cue\nto indicate which task to perform:\n\n\1gray\1[Press Space to continue]\2', duration='space', align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))
            txt = self.write('(1) Speak a word\nwhen you see a speech bubble.\n\n\1gray\1[Press Space to continue]\2', duration=10000, block=False, align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))
            pic = self.picture('studies/speech/overt.png', duration=10000, block=False, scale=0.25, pos=(0, 0.5))
            self.waitfor('space')
            txt.destroy()
            pic.destroy()
            txt = self.write('(2) Imagine speaking a word\nwhen you see a thought bubble.\n\n\1gray\1[Press Space to continue]\2', duration=10000, block=False, align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))
            pic = self.picture('studies/speech/covert.png', duration=10000, block=False, scale=0.25, pos=(0, 0.5))
            self.waitfor('space')
            txt.destroy()
            pic.destroy()
            txt = self.write('(3) Press the space bar\nwhen you see a rectangle.\n\n\1gray\1[Press Space to continue]\2', duration=10000, block=False, align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))
            pic = self.picture('studies/speech/control.png', duration=10000, block=False, scale=(0.25, 1, 0.1), pos=(0, 0.5))
            self.waitfor('space')
            txt.destroy()
            pic.destroy()
            
        self.write('When you are ready,\npress the space bar to begin.' + 
                   '\n\n\1gray\1[Press Space to continue]\2', duration='space', align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))    
        
        # Create log file
        t = time.localtime()
        t_str = '-'.join([str(k) for k in [t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec]])
        f = open('studies/speech/log/' + t_str + '.txt', 'w')
        
        self.sleep(4)

        for block in range(self.n_blocks):
            # Create randomized stimulus presentation sequence
            items = []
            for i1 in range(len(self.stimuli)):   # Stimulus
                for i2 in range(len(self.tasks)):   # Task (overt, covert, control)
                    for i3 in range(len(self.conditions)):  # Condition (visual, auditory)
                        items.append([i1, i2, i3])
            random.shuffle(items)
            
            if self.training:
                items = items[:32]  # Use only the first 16 items for the training block
            
            counter = 0
            for trial in items:
                if not self.training and counter == len(items)/2:  # Break in the middle of each run
                    self.write('Time for a short break.\n\n' + 
                          '\1gray\1[Press Space to continue]\2', fg=(1, 1, 1, 1), duration='space', align='left', pos=(-0.5, 0), scale=0.05)
                    self.sleep(4)
                counter += 1    
                f.write(self.stimuli[trial[0]].strip() + '\t' + self.tasks[trial[1]] + '\t' + self.conditions[trial[2]] + '\t')
                if self.tasks[trial[1]] == 'overt':
                    self.picture('studies/speech/overt.png',
                                 duration=self.isi-self.pause, block=False, scale=0.5, pos=(0, -0.05))
                elif self.tasks[trial[1]] == 'covert':
                    self.picture('studies/speech/covert.png',
                                 duration=self.isi-self.pause, block=False, scale=0.5, pos=(0, -0.05))
                else:
                    self.picture('studies/speech/control.png',
                                 duration=self.isi-self.pause, block=False, scale=(0.5, 1, 0.2))
                
                # Format: 1zyxx, xx: stimulus (0-35), y: task (0, 1, 2), z: condition (0, 1)
                self.marker(trial[0] + trial[1] * 100 + trial[2] * 1000 + 10000)

                if self.conditions[trial[2]] == 'visual':
                    self.write(self.stimuli[trial[0]], duration=self.isi-self.pause, block=False, scale=0.15, fg=(1, 1, 1, 1))
                else:
                    self.sound(self.file_list[trial[0]], volume=0.5)
                    self.write('+', duration=self.isi-self.pause, block=False, scale=0.15, fg=(1, 1, 1, 1))
                
                if self.watchfor('space', self.isi):
                    f.write('space\n')  # Space bar was pressed
                else:
                    f.write('-\n')  # Space bar was not pressed
            if block < self.n_blocks - 1:  # If it's not the last block
                self.write('Time for a short break.\n\n' + 
                          '\1gray\1[Press Space to continue]\2', fg=(1, 1, 1, 1), duration='space', align='left', pos=(-0.5, 0), scale=0.05)
                self.sleep(4)
            
        f.close()
        if not self.training:    
            self.write('You successfully completed\none run of the experiment.\n\nThank you!', duration=5, align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))
    
